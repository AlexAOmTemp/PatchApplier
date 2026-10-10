"""Tk widget: scrollable directory list with per-row policy cells.

A row = one directory. On the right: five possible cells, R / W / Id /
Ip / Il. Which cells are shown is controlled by `active_flags`:

    read        always visible
    write       always visible
    index_docs  visible only when Documentation is enabled
    index_py    visible only when Python indexing is enabled
    index_lua   visible only when Lua-on-disk (Rojo) is enabled

The MCP-side Lua index is not configured from here (it is always on
when MCP runs and is filtered only via .mcpignore), so index_lua here
is about disk files in Rojo mode.

Each cell cycles through three states:

    dot     no override at this path (inherit)
    +       override exists, this flag is True
    -       override exists, this flag is False

Click semantics:

    dot  ->  + or -   create override from effective, invert the clicked flag
    +    ->  -        flip to False (only this flag)
    -    ->  +        flip to True (only this flag)

Hidden rows are hard-denied: all cells show a fixed minus and clicks are
ignored. The topmost row is the virtual root, keyed "." in overrides.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path

from ...config.workspace import PathPolicy, Root
from .tree import build_tree, filter_hidden


FLAG_COLUMNS = (
    ("read",       "R"),
    ("write",      "W"),
    ("index_docs", "Id"),
    ("index_py",   "Ip"),
    ("index_lua",  "Il"),
)

_MONO = ("Consolas", 10)
_BG_HOVER = "#e6e6e6"
_HIDDEN_FG = "#a02020"
_ROOT_FG = "#404040"
_STATE_GLYPH = {None: "\u00b7", True: "+", False: "\u2212"}
_STATE_FG = {None: "#888888", True: "#307030", False: "#c03030"}

_TEE = "\u251c\u2500\u2500 "
_ELBOW = "\u2514\u2500\u2500 "
_PIPE = "\u2502   "
_SPACE = "    "


def _all_flags() -> set[str]:
    return {k for k, _ in FLAG_COLUMNS}


class PolicyTree(tk.Frame):
    """Scrollable canvas with a scrollbar and one row per directory."""

    def __init__(self, parent, root: Root,
                 active_flags: set[str] | None = None):
        super().__init__(parent)
        self._root = root
        self._overrides = root.overrides
        self._row_widgets: dict[str, dict] = {}
        self._hidden_paths: set[str] = set()
        self._root_label = Path(root.path).name or "[root]"
        self._active_flags = (set(active_flags) if active_flags is not None
                              else _all_flags())

        self._container = tk.Frame(self, bd=1, relief="sunken")
        self._container.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(self._container, highlightthickness=0)
        self._scrollbar = tk.Scrollbar(self._container, orient="vertical",
                                       command=self._canvas.yview)
        self._inner = tk.Frame(self._canvas)
        self._inner.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.create_window((0, 0), window=self._inner, anchor="nw",
                                   tags="inner")
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfigure("inner", width=e.width),
        )

    # --- public API ---------------------------------------------------

    def set_active_flags(self, flags: set[str]) -> None:
        """Change which cells are shown. Caller must re-render."""
        self._active_flags = set(flags)

    def render(self, paths: list[tuple[str, bool]],
               show_hidden: bool = False) -> None:
        """(Re)build the visual rows from a flat [(rel, hidden)] list."""
        for w in self._inner.winfo_children():
            w.destroy()
        self._row_widgets.clear()
        self._hidden_paths = {p for p, h in paths if h}

        tree = build_tree(paths)
        if not show_hidden:
            tree = filter_hidden(tree)

        active = [(k, l) for k, l in FLAG_COLUMNS if k in self._active_flags]
        self._make_header_row(active)
        self._make_row(".", display_text=f"[{self._root_label}]",
                       hidden=False, root_row=True, active_columns=active)
        self._render_children(tree, prefix="", path_prefix="",
                              active_columns=active)

    def overrides(self) -> dict[str, PathPolicy]:
        return self._overrides

    # --- rendering ----------------------------------------------------

    def _bg(self) -> str:
        try:
            return self._inner.cget("bg")
        except Exception:
            return "#f0f0f0"

    def _make_header_row(self, active_columns) -> None:
        row = tk.Frame(self._inner, bg=self._bg())
        row.pack(fill="x", anchor="w", pady=(0, 4))
        for _, label in active_columns:
            lbl = tk.Label(row, text=label, font=_MONO, width=2,
                           bg=self._bg(), fg="#306030")
            lbl.pack(side="left", padx=(0, 2))
        tk.Label(row, text="path", font=_MONO, bg=self._bg(), fg="#306030",
                 anchor="w").pack(side="left", fill="x", expand=True)

    def _render_children(self, nodes: list[dict], prefix: str,
                         path_prefix: str, active_columns) -> None:
        last = len(nodes) - 1
        for i, node in enumerate(nodes):
            is_last = (i == last)
            connector = _ELBOW if is_last else _TEE
            display = prefix + connector + node["name"]
            path = (f"{path_prefix}/{node['name']}"
                    if path_prefix else node["name"])
            self._make_row(path, display_text=display,
                           hidden=bool(node.get("hidden")),
                           active_columns=active_columns)
            if node.get("children"):
                cont = prefix + (_SPACE if is_last else _PIPE)
                self._render_children(node["children"], cont, path,
                                      active_columns)

    def _make_row(self, rel_path: str, display_text: str,
                  hidden: bool = False, root_row: bool = False,
                  active_columns=None) -> None:
        if active_columns is None:
            active_columns = [(k, l) for k, l in FLAG_COLUMNS
                              if k in self._active_flags]
        bg = self._bg()
        row = tk.Frame(self._inner, bg=bg)
        row.pack(fill="x", anchor="w")

        cells = {}
        for key, _label in active_columns:
            cell = tk.Label(row, text="\u00b7", font=_MONO, width=2,
                            bg=bg, fg="#888888",
                            cursor=("arrow" if hidden else "hand2"))
            cell.pack(side="left", padx=(0, 2))
            if not hidden:
                cell.bind("<Button-1>", self._cell_click(rel_path, key))
            cells[key] = cell

        fg = _HIDDEN_FG if hidden else (_ROOT_FG if root_row else "black")
        text_label = tk.Label(row, text=display_text, font=_MONO,
                              bg=bg, fg=fg, anchor="w", justify="left")
        text_label.pack(side="left", fill="x", expand=True)

        widgets = [row, text_label] + list(cells.values())
        row.bind("<Enter>", lambda e, ws=widgets: [w.config(bg=_BG_HOVER) for w in ws])
        row.bind("<Leave>", lambda e, ws=widgets, b=bg: [w.config(bg=b) for w in ws])

        self._row_widgets[rel_path] = {"text": text_label, **cells}
        self._refresh_row(rel_path)

    def _refresh_row(self, rel_path: str) -> None:
        widgets = self._row_widgets.get(rel_path)
        if not widgets:
            return
        for key, _label in FLAG_COLUMNS:
            if key not in widgets:
                continue
            state = self._flag_state(rel_path, key)
            try:
                widgets[key].config(text=_STATE_GLYPH[state],
                                    fg=_STATE_FG[state])
            except Exception:
                pass

    # --- state --------------------------------------------------------

    def _flag_state(self, rel_path: str, flag_key: str) -> bool | None:
        if rel_path in self._hidden_paths:
            return False
        pol = self._overrides.get(rel_path)
        if pol is None:
            return None
        return bool(getattr(pol, flag_key))

    def _effective(self, rel_path: str) -> PathPolicy:
        return self._root.policy_for(rel_path)

    def _cell_click(self, rel_path: str, flag_key: str):
        def handler(_event):
            self._cycle(rel_path, flag_key)
        return handler

    def _cycle(self, rel_path: str, flag_key: str) -> None:
        if rel_path in self._hidden_paths:
            return
        cur = self._overrides.get(rel_path)
        if cur is None:
            eff = self._effective(rel_path)
            new = eff.copy()
            setattr(new, flag_key, not bool(getattr(eff, flag_key)))
            self._overrides[rel_path] = new
        else:
            setattr(cur, flag_key, not bool(getattr(cur, flag_key)))
        self._refresh_row(rel_path)
