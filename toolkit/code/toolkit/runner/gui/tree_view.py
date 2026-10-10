"""Tk widget: scrollable directory list with five policy flags per row.

A row = one directory. Five cells on the right: R / W / Id / Ip / Il.
Each cell cycles through three states:

    dot     no override at this path (inherit)
    +       override exists, this flag is True
    -       override exists, this flag is False

Click semantics (see docs/GUI_PROJECT_SETTINGS.md section 2.2):

    dot  ->  + or -   create override from effective, invert the clicked flag
    +    ->  -        flip to False (only this flag)
    -    ->  +        flip to True (only this flag)

Returning a cell to dot (removing the whole override) is a separate
Ctrl+click gesture - not implemented in this pass.

The topmost row is the virtual root, keyed "." in overrides. It holds
the default policy for the whole root; children inherit from it.

Directory rows use tree connectors (├── └── │) so nesting is visible
without counting indents.
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

# Tree drawing pieces. For each child: connector (├── / └──),
# and continuation for descendants (│   or four spaces).
_TEE = "\u251c\u2500\u2500 "
_ELBOW = "\u2514\u2500\u2500 "
_PIPE = "\u2502   "
_SPACE = "    "


class PolicyTree(tk.Frame):
    """Scrollable canvas with a scrollbar and one row per directory."""

    def __init__(self, parent, root: Root):
        super().__init__(parent)
        self._root = root
        self._overrides = root.overrides  # mutate in place, same object
        self._row_widgets: dict[str, dict] = {}
        self._root_label = Path(root.path).name or "[root]"

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

    def render(self, paths: list[tuple[str, bool]],
               show_hidden: bool = False) -> None:
        """(Re)build the visual rows from a flat [(rel, hidden)] list."""
        for w in self._inner.winfo_children():
            w.destroy()
        self._row_widgets.clear()

        tree = build_tree(paths)
        if not show_hidden:
            tree = filter_hidden(tree)

        self._make_header_row()
        # Virtual root row: the whole root's default policy.
        self._make_row(".", display_text=f"[{self._root_label}]",
                       hidden=False, root_row=True)
        self._render_children(tree, prefix="", path_prefix="")

    def overrides(self) -> dict[str, PathPolicy]:
        """Return the live overrides dict (mutated in place)."""
        return self._overrides

    # --- rendering ----------------------------------------------------

    def _bg(self) -> str:
        try:
            return self._inner.cget("bg")
        except Exception:
            return "#f0f0f0"

    def _make_header_row(self) -> None:
        row = tk.Frame(self._inner, bg=self._bg())
        row.pack(fill="x", anchor="w", pady=(0, 4))
        for _, label in FLAG_COLUMNS:
            lbl = tk.Label(row, text=label, font=_MONO, width=2,
                           bg=self._bg(), fg="#306030")
            lbl.pack(side="left", padx=(0, 2))
        tk.Label(row, text="path", font=_MONO, bg=self._bg(), fg="#306030",
                 anchor="w").pack(side="left", fill="x", expand=True)

    def _render_children(self, nodes: list[dict],
                         prefix: str, path_prefix: str) -> None:
        """prefix: visible tree glyphs for this level.

        path_prefix: the logical rel-path prefix, joined with '/'.
        """
        last = len(nodes) - 1
        for i, node in enumerate(nodes):
            is_last = (i == last)
            connector = _ELBOW if is_last else _TEE
            display = prefix + connector + node["name"]
            path = f"{path_prefix}/{node['name']}" if path_prefix else node["name"]
            self._make_row(path, display_text=display,
                           hidden=bool(node.get("hidden")))
            if node.get("children"):
                cont = prefix + (_SPACE if is_last else _PIPE)
                self._render_children(node["children"], cont, path)

    def _make_row(self, rel_path: str, display_text: str,
                  hidden: bool = False, root_row: bool = False) -> None:
        bg = self._bg()
        row = tk.Frame(self._inner, bg=bg)
        row.pack(fill="x", anchor="w")

        cells = {}
        for key, _label in FLAG_COLUMNS:
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
            state = self._flag_state(rel_path, key)
            try:
                widgets[key].config(text=_STATE_GLYPH[state],
                                    fg=_STATE_FG[state])
            except Exception:
                pass

    # --- state --------------------------------------------------------

    def _flag_state(self, rel_path: str, flag_key: str) -> bool | None:
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
        cur = self._overrides.get(rel_path)
        if cur is None:
            # dot -> create override: start from effective, invert clicked flag
            eff = self._effective(rel_path)
            new = eff.copy()
            setattr(new, flag_key, not bool(getattr(eff, flag_key)))
            self._overrides[rel_path] = new
        else:
            # + <-> - : flip only this flag
            setattr(cur, flag_key, not bool(getattr(cur, flag_key)))
        self._refresh_row(rel_path)
