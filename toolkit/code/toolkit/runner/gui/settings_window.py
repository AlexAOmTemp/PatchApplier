"""Project settings window: name, sources, roots, policy.

Opened from File -> Project settings. Edits an in-memory Workspace and
an in-memory CONFIG dict; writes both on OK; Cancel discards.

Section order follows the workflow: choose what you work with (Sources),
remove noise (visibility rules, inside Sources), then tune policy (Roots).

  - project name (Entry, right-click or Ctrl+C to copy)
  - Sources (LabelFrame):
      [x] Documentation (.md)                [Hide paths…] (N rules)
      [x] Python (.py)                       (toggle + nested exec)
          [x] Allow Python scripts
      [x] MCP (Roblox scene + code)          [Hide modules…] (N rules)
      [x] Lua files on disk (.luau)
          Luau source: ( ) MCP  ( ) Rojo
  - Roots (LabelFrame, hidden when no FS source is on):
      notebook with per-root PolicyTree, Add/Remove, Show hidden, legend
  - OK / Cancel

Visibility rules live next to the source they affect:
  - Hide paths (patchignore) applies to disk roots; disabled when neither
    Documentation nor Python is on.
  - Hide modules (mcpignore) applies to DataModel; disabled when MCP is
    off or Luau source is Rojo.

Column visibility in the policy tree is driven by Sources:
  - Id shown only when Documentation is on
  - Ip shown only when Python is on
  - Il shown only when Lua-on-disk is on (MCP-side index is not tuned
    here; it is always on when MCP runs and filtered via .mcpignore)

Invariants enforced here and on save:
  - exec.enabled requires index_python
  - luau_mode follows the radio; forced when only one source is on
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import pyperclip

from ...config import patchignore as _pi
from ...config import mcpignore as _mi
from ...config.loader import scan_subdirs_ex, DEFAULT_SCAN_MAX_ROWS as _SCAN_MAX_ROWS
from ...config import workspace as ws_mod
from ..projects import load_workspace, save_workspace
from .tree_view import PolicyTree


_MAX_DEPTH = 3


_LEGEND = (
    "R read   W write   Id index docs   Ip index py   Il index lua   "
    "\u00b7 inherit   + allow   \u2212 deny   (hidden rows: all \u2212)"
)


# --- entry with layout-independent Ctrl+C / Ctrl+A -----------------------


def _make_copyable_entry(entry: tk.Entry) -> None:
    menu = tk.Menu(entry, tearoff=0)
    menu.add_command(label="\u041a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c",
                     command=lambda: pyperclip.copy(entry.get()))

    def _show(event):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
    entry.bind("<Button-3>", _show)

    _COPY_KEYCODES = {67}
    _SELECT_ALL_KEYCODES = {65}
    _COPY_KEYSYMS = {"c", "cyrillic_es"}
    _SELECT_ALL_KEYSYMS = {"a", "cyrillic_ef"}

    def _ctrl(event):
        kc = getattr(event, "keycode", None)
        ks = (event.keysym or "").lower()
        if kc in _COPY_KEYCODES or ks in _COPY_KEYSYMS:
            try:
                entry.event_generate("<<Copy>>")
            except Exception:
                pyperclip.copy(entry.get())
            return "break"
        if kc in _SELECT_ALL_KEYCODES or ks in _SELECT_ALL_KEYSYMS:
            entry.select_range(0, "end")
            entry.icursor("end")
            return "break"
        return None

    entry.bind("<Control-KeyPress>", _ctrl, add="+")


# --- ignore editor --------------------------------------------------------


def _open_ignore_editor(parent, path: Path, title: str,
                        default_text: str, on_saved=None) -> None:
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.transient(parent)
    dlg.grab_set()
    dlg.geometry("560x460")
    dlg.minsize(420, 340)

    tk.Label(
        dlg, anchor="w", justify="left",
        text=("One line = one pattern (.gitignore-like).\n"
              "*, ?, [seq], ! — same as .gitignore."),
    ).pack(fill="x", padx=12, pady=(12, 4))

    body = tk.Frame(dlg)
    body.pack(fill="both", expand=True, padx=12, pady=(0, 6))
    lb = tk.Listbox(body, selectmode="extended", font=("Consolas", 9))
    sb = tk.Scrollbar(body, orient="vertical", command=lb.yview)
    lb.configure(yscrollcommand=sb.set)
    lb.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    try:
        raw = path.read_text(encoding="utf-8") if path.is_file() else default_text
    except Exception:
        raw = default_text
    for line in raw.splitlines():
        lb.insert("end", line)

    entry_row = tk.Frame(dlg)
    entry_row.pack(fill="x", padx=12, pady=(0, 6))
    entry = tk.Entry(entry_row, font=("Consolas", 9))
    entry.pack(side="left", fill="x", expand=True)

    def _add(*_a):
        v = entry.get()
        if v.strip():
            lb.insert("end", v)
        entry.delete(0, "end")

    def _remove(*_a):
        for i in reversed(lb.curselection()):
            lb.delete(i)

    def _reset():
        if not messagebox.askyesno(title, "Reset to default?", parent=dlg):
            return
        lb.delete(0, "end")
        for ln in default_text.splitlines():
            lb.insert("end", ln)

    def _open_all():
        if not messagebox.askyesno(title, "Remove all rules?", parent=dlg):
            return
        lb.delete(0, "end")

    entry.bind("<Return>", _add)
    tk.Button(entry_row, text="Add", command=_add, width=10).pack(
        side="left", padx=(6, 0))
    tk.Button(entry_row, text="Remove", command=_remove, width=10).pack(
        side="left", padx=(6, 0))

    tools_row = tk.Frame(dlg)
    tools_row.pack(fill="x", padx=12, pady=(0, 6))
    tk.Button(tools_row, text="Reset to default", command=_reset).pack(side="left")
    tk.Button(tools_row, text="Open all", command=_open_all).pack(
        side="left", padx=(6, 0))

    btn_row = tk.Frame(dlg)
    btn_row.pack(fill="x", padx=12, pady=(6, 12))

    def _ok():
        lines = [str(x) for x in lb.get(0, "end")]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=dlg)
            return
        dlg.destroy()
        if on_saved is not None:
            try:
                on_saved()
            except Exception:
                pass

    tk.Button(btn_row, text="OK", command=_ok, width=10).pack(side="right")
    tk.Button(btn_row, text="Cancel", command=dlg.destroy, width=10).pack(
        side="right", padx=(0, 6))


# --- main window ----------------------------------------------------------


def open_project_settings(parent, project_dir: Path, state_subdir: str,
                          config: dict, on_save=None) -> None:
    w = load_workspace(project_dir, state_subdir)
    state_dir = project_dir / state_subdir

    dlg = tk.Toplevel(parent)
    dlg.title("Project settings")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.geometry("820x820")
    dlg.minsize(700, 700)

    main = tk.Frame(dlg, padx=12, pady=12)
    main.pack(fill="both", expand=True)

    # --- name ---------------------------------------------------------
    name_row = tk.Frame(main)
    name_row.pack(fill="x", pady=(0, 4))
    tk.Label(name_row, text="Project name:").pack(side="left")
    name_var = tk.StringVar(value=w.name)
    name_entry = tk.Entry(name_row, textvariable=name_var)
    name_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
    _make_copyable_entry(name_entry)

    tk.Label(main, text=f"Folder: {project_dir}", anchor="w",
             fg="#666").pack(fill="x")

    # --- state --------------------------------------------------------
    docs_var = tk.BooleanVar(value=bool(config.get("index_docs", True)))
    py_var = tk.BooleanVar(value=bool(config.get("index_python", True)))
    backend_now = (config.get("backend") or "composite")
    mcp_var = tk.BooleanVar(value=backend_now in ("mcp", "composite"))
    rojo_var = tk.BooleanVar(value=bool(config.get("index_lua", False)))
    luau_var = tk.StringVar(value=(config.get("luau_mode") or "mcp"))
    exec_var = tk.BooleanVar(value=bool((config.get("exec") or {}).get("enabled")))

    pi_path = state_dir / _pi.PATCHIGNORE_NAME
    mi_path = state_dir / _mi.MCPIGNORE_NAME

    def _count_label(path: Path) -> str:
        if not path.is_file():
            return "(no rules)"
        try:
            n = len(_pi.parse(path.read_text(encoding="utf-8")))
            return f"{n} rule{'s' if n != 1 else ''}"
        except Exception:
            return "(unreadable)"

    pi_label_var = tk.StringVar(value=_count_label(pi_path))
    mi_label_var = tk.StringVar(value=_count_label(mi_path))

    # --- Sources ------------------------------------------------------
    src = tk.LabelFrame(main, text="Sources", padx=8, pady=8)
    src.pack(fill="x", pady=(8, 0))

    # Row 1: Documentation + Hide paths button (right-aligned)
    r_docs = tk.Frame(src)
    r_docs.pack(fill="x")
    tk.Checkbutton(r_docs, text="Documentation (.md)", variable=docs_var,
                   anchor="w").pack(side="left")
    pi_btn = tk.Button(r_docs, text="Hide paths\u2026",
                       command=lambda: _open_pi(), width=14)
    pi_btn.pack(side="right")
    tk.Label(r_docs, textvariable=pi_label_var, fg="#888",
             font=("Consolas", 8)).pack(side="right", padx=(0, 6))

    # Row 2: Python + Allow scripts (nested visual)
    r_py = tk.Frame(src)
    r_py.pack(fill="x")
    tk.Checkbutton(r_py, text="Python (.py)", variable=py_var,
                   anchor="w").pack(side="left")

    r_py_sub = tk.Frame(src)
    r_py_sub.pack(fill="x", padx=(22, 0))
    exec_cb = tk.Checkbutton(r_py_sub, text="Allow Python scripts (run_python)",
                             variable=exec_var, anchor="w")
    exec_cb.pack(side="left")
    exec_hint = tk.Label(r_py_sub, text="", fg="#c07000",
                         font=("Consolas", 8))
    exec_hint.pack(side="left", padx=(8, 0))

    # Row 3: MCP + Hide modules button (right-aligned)
    # Label adapts to Luau source: when code comes from disk (Rojo), the
    # bridge is only used for the scene; when code goes through .Source,
    # it carries both. Neutral fallback while both are off.
    mcp_label_var = tk.StringVar(value="MCP (Roblox bridge)")
    r_mcp = tk.Frame(src)
    r_mcp.pack(fill="x", pady=(4, 0))
    tk.Checkbutton(r_mcp, textvariable=mcp_label_var, variable=mcp_var,
                   anchor="w").pack(side="left")
    mi_btn = tk.Button(r_mcp, text="Hide modules\u2026",
                       command=lambda: _open_mi(), width=14)
    mi_btn.pack(side="right")
    tk.Label(r_mcp, textvariable=mi_label_var, fg="#888",
             font=("Consolas", 8)).pack(side="right", padx=(0, 6))

    # Row 4: Lua files on disk
    r_rojo = tk.Frame(src)
    r_rojo.pack(fill="x")
    tk.Checkbutton(r_rojo, text="Lua files on disk (.luau)", variable=rojo_var,
                   anchor="w").pack(side="left")

    # Row 5: Luau source radio
    radio_row = tk.Frame(src)
    radio_row.pack(fill="x", padx=(22, 0), pady=(2, 0))
    tk.Label(radio_row, text="Luau source:").pack(side="left")
    luau_mcp_rb = tk.Radiobutton(radio_row, text="MCP", variable=luau_var,
                                 value="mcp")
    luau_rojo_rb = tk.Radiobutton(radio_row, text="Rojo", variable=luau_var,
                                  value="rojo")
    luau_mcp_rb.pack(side="left", padx=(8, 0))
    luau_rojo_rb.pack(side="left", padx=(8, 0))
    luau_hint = tk.Label(radio_row, text="", fg="#888",
                         font=("Consolas", 8))
    luau_hint.pack(side="left", padx=(8, 0))

    # --- Roots --------------------------------------------------------
    roots_frame = tk.LabelFrame(main, text="Roots (project folders)",
                                padx=8, pady=8)
    roots_frame.pack(fill="both", expand=True, pady=(8, 0))

    nb = ttk.Notebook(roots_frame)
    nb.pack(fill="both", expand=True)

    show_hidden_var = tk.BooleanVar(value=False)
    tree_widgets: dict[str, PolicyTree] = {}
    # Lazy render bookkeeping: which root tabs still need a first render,
    # and the frozen column set from the last render. The column set only
    # changes when Documentation / Python / Lua-on-disk toggles; MCP and
    # Luau-mode toggles leave it alone, so they must not force a full
    # tree rebuild (which on RimWorld means thousands of Tk widgets).
    _dirty: set[str] = set()
    _last_columns: set[str] = set()
    # Directory scan cache. Keyed by (root_name, show_hidden); populated on
    # first render of a root and reused for every later render that does
    # not actually change which directories exist. Without this, switching
    # tabs or toggling a source re-reads the disk even though the tree is
    # the same — on a RimWorld root (~86 mods at depth 3) that is the
    # dominant cost of the dialog feeling slow. Invalidated explicitly by
    # _invalidate_scan() when .patchignore changes or a root is added or
    # removed; show_hidden flip is a natural cache miss (different key).
    # Scan cache: keyed by root_name only. The scan is always performed
    # with show_hidden=True (hidden dirs are terminal so the result is a
    # superset); filtering for the not-show-hidden view happens in memory.
    # That makes the show-hidden toggle zero-disk: no cache miss, no
    # re-walk — just a list comprehension and a re-render.
    _scan_cache: dict[str, tuple[list, int | None]] = {}

    def _patterns():
        return _pi.read(state_dir)

    def _active_flags() -> set[str]:
        flags = {"read", "write"}
        if docs_var.get():
            flags.add("index_docs")
        if py_var.get():
            flags.add("index_py")
        if rojo_var.get():
            flags.add("index_lua")
        return flags

    def _invalidate_scan(root_name: str | None = None) -> None:
        """Drop cached scan results so the next render re-reads the disk.

        Called after any change that can alter which directories exist or
        are hidden: .patchignore edits, root add/remove.
        """
        if root_name is None:
            _scan_cache.clear()
        else:
            _scan_cache.pop(root_name, None)

    def _scan_dirs(name: str, root_obj) -> tuple[list, int | None]:
        cached = _scan_cache.get(name)
        if cached is not None:
            return cached
        try:
            paths, truncated = scan_subdirs_ex(
                Path(root_obj.path),
                max_depth=_MAX_DEPTH,
                patterns=_patterns(),
                show_hidden=True,      # superset; filtered at render time
                max_rows=_SCAN_MAX_ROWS,
            )
        except Exception:
            paths, truncated = [], None
        _scan_cache[name] = (paths, truncated)
        return paths, truncated

    def _render_tab(name: str) -> None:
        pt = tree_widgets.get(name)
        root_obj = w.roots.get(name)
        if pt is None or root_obj is None:
            return
        pt.set_active_flags(_active_flags())
        full, truncated = _scan_dirs(name, root_obj)
        show_h = bool(show_hidden_var.get())
        paths = full if show_h else [p for p in full if not p[1]]
        pt.render(paths, show_hidden=show_h, truncated_at=truncated)

    def _rebuild_tabs() -> None:
        nonlocal _last_columns
        # Cache is keyed by (root_name, show_hidden) and remains valid
        # across tab rebuilds as long as the set of roots and their
        # contents did not change; only the set of roots being iterated
        # differs. Dropped only when we know content may have changed.
        for tab_id in nb.tabs():
            nb.forget(tab_id)
        tree_widgets.clear()
        _dirty.clear()
        for name in w.root_names():
            root_obj = w.roots[name]
            tab = tk.Frame(nb)
            pt = PolicyTree(tab, root_obj, active_flags=_active_flags())
            pt.pack(fill="both", expand=True)
            tree_widgets[name] = pt
            nb.add(tab, text=name)
            _dirty.add(name)
        # Render only the selected tab now; the rest render on first switch
        # (see _on_tab_changed). On a project with a large root this is the
        # difference between "wait 10s on open" and "wait under 1s":
        # policy rows are one Tk widget per cell, thousands of them at
        # depth 3, and the previous code rendered every root twice.
        try:
            idx = nb.index(nb.select())
            current = nb.tab(idx, "text")
        except Exception:
            current = None
        if current in tree_widgets:
            _render_tab(current)
            _dirty.discard(current)
        _last_columns = _active_flags()

    def _on_tab_changed(_event=None) -> None:
        try:
            idx = nb.index(nb.select())
            name = nb.tab(idx, "text")
        except Exception:
            return
        if name in _dirty:
            _render_tab(name)
            _dirty.discard(name)

    def _on_show_hidden():
        # Visibility of hidden rows changed: input to render() changes, so
        # bypass the signature cache. The scan cache is keyed by
        # show_hidden, so a flip is a natural cache miss — no explicit
        # invalidation needed.
        for pt in tree_widgets.values():
            pt.invalidate()
        _dirty.update(w.root_names())
        _on_tab_changed()
    show_hidden_var.trace_add(
        "write", lambda *_: dlg.after_idle(_on_show_hidden))

    _rebuild_tabs()
    nb.bind("<<NotebookTabChanged>>", _on_tab_changed)

    roots_ctrl = tk.Frame(roots_frame)
    roots_ctrl.pack(fill="x", pady=(6, 0))

    def _add_root() -> None:
        folder = filedialog.askdirectory(title="Root folder", parent=dlg)
        if not folder:
            return
        try:
            ws_mod.add_root(w, folder)
        except ValueError as e:
            messagebox.showerror("Cannot add root", str(e), parent=dlg)
            return
        # A newly added root has no cache entry yet, so no explicit
        # invalidation is required — its first render scans fresh.
        _rebuild_tabs()
        try:
            nb.select(len(nb.tabs()) - 1)
        except Exception:
            pass

    def _remove_root() -> None:
        try:
            idx = nb.index(nb.select())
        except Exception:
            return
        if idx < 0:
            return
        name = nb.tab(idx, "text")
        if not messagebox.askyesno(
                "Remove root",
                f"Remove root {name!r} from this project?\n"
                "Files on disk are not touched.",
                parent=dlg):
            return
        w.roots.pop(name, None)
        _invalidate_scan(name)
        _rebuild_tabs()

    add_btn = tk.Button(roots_ctrl, text="Add root\u2026", command=_add_root)
    add_btn.pack(side="left")
    rm_btn = tk.Button(roots_ctrl, text="Remove root", command=_remove_root)
    rm_btn.pack(side="left", padx=(6, 0))
    tk.Checkbutton(roots_ctrl, text="Show hidden", variable=show_hidden_var).pack(
        side="right")

    tk.Label(roots_frame, text=_LEGEND, anchor="w", justify="left",
             fg="#666", font=("Consolas", 8)).pack(fill="x", pady=(6, 0))

    # --- ignore editor openers (defined after paths)

    def _open_pi():
        def _after_edit():
            # .patchignore changed on disk: any cached scan for any root
            # is now potentially stale, because hidden paths may have
            # moved. Drop everything, then rebuild the visible tab.
            _invalidate_scan()
            pi_label_var.set(_count_label(pi_path))
            _on_show_hidden()
        _open_ignore_editor(dlg, pi_path, "Hide filesystem paths",
                            _pi.DEFAULT_PATCHIGNORE,
                            on_saved=_after_edit)

    def _on_scan_cache_dirty():
        """Called after any change that alters which dirs exist or are hidden.

        Invalidates the signature caches on every tree and rebuilds only
        the visible tab. Kept separate from _on_show_hidden because the
        two have different reasons but the same effect on trees.
        """
        for pt in tree_widgets.values():
            pt.invalidate()
        _dirty.update(w.root_names())
        _on_tab_changed()

    def _open_mi():
        _open_ignore_editor(dlg, mi_path, "Hide Roblox modules",
                            _mi.DEFAULT_MCPIGNORE,
                            on_saved=lambda: mi_label_var.set(_count_label(mi_path)))

    # --- reactive rules ----------------------------------------------

    def _sync_exec_state():
        if py_var.get():
            exec_cb.config(state="normal")
            exec_hint.config(text="")
        else:
            exec_var.set(False)
            exec_cb.config(state="disabled")
            exec_hint.config(text="(requires Python)")

    def _sync_luau_state():
        mcp = bool(mcp_var.get())
        rojo = bool(rojo_var.get())
        if not mcp and not rojo:
            luau_mcp_rb.config(state="disabled")
            luau_rojo_rb.config(state="disabled")
            luau_hint.config(text="(no Luau source enabled)")
            return
        if mcp and not rojo:
            luau_var.set("mcp")
            luau_mcp_rb.config(state="disabled")
            luau_rojo_rb.config(state="disabled")
            luau_hint.config(text="(only MCP)")
            return
        if not mcp and rojo:
            luau_var.set("rojo")
            luau_mcp_rb.config(state="disabled")
            luau_rojo_rb.config(state="disabled")
            luau_hint.config(text="(only Rojo)")
            return
        # both
        luau_mcp_rb.config(state="normal")
        luau_rojo_rb.config(state="normal")
        if luau_var.get() not in ("mcp", "rojo"):
            luau_var.set("rojo")
        luau_hint.config(text="")

    def _sync_visibility_buttons():
        fs_any = bool(docs_var.get() or py_var.get())
        pi_btn.config(state=("normal" if fs_any else "disabled"))
        # .mcpignore applies to DataModel code: needs MCP as source AND Luau
        # source being MCP (not Rojo).
        use_mcp_code = bool(mcp_var.get()) and luau_var.get() == "mcp"
        mi_btn.config(state=("normal" if use_mcp_code else "disabled"))

    def _sync_roots_visibility():
        fs_any = bool(docs_var.get() or py_var.get())
        if fs_any:
            if not roots_frame.winfo_ismapped():
                roots_frame.pack(fill="both", expand=True, pady=(8, 0))
                # after the Sources frame; main already contains src
                roots_frame.pack_configure(after=src)
        else:
            if roots_frame.winfo_ismapped():
                roots_frame.pack_forget()
        # Add/Remove also gated by fs_any
        st = "normal" if fs_any else "disabled"
        add_btn.config(state=st)
        rm_btn.config(state=st)

    def _sync_tree_columns():
        # Only re-render when the visible column set actually changed.
        # mcp_var and luau_var changes flow through _sync_all too, but they
        # do not affect columns — skipping them avoids a full tree rebuild
        # on every unrelated checkbox toggle.
        nonlocal _last_columns
        cur = _active_flags()
        if cur == _last_columns:
            return
        _last_columns = cur
        _dirty.update(w.root_names())
        _on_tab_changed()

    def _sync_mcp_label():
        mcp = bool(mcp_var.get())
        rojo = bool(rojo_var.get())
        if mcp and luau_var.get() == "mcp":
            mcp_label_var.set("MCP (Roblox bridge: scene + code)")
        elif mcp and luau_var.get() == "rojo":
            mcp_label_var.set("MCP (Roblox bridge: scene only)")
        elif mcp:
            mcp_label_var.set("MCP (Roblox bridge)")
        else:
            mcp_label_var.set("MCP (Roblox bridge)")

    def _sync_all():
        _sync_exec_state()
        _sync_luau_state()
        _sync_visibility_buttons()
        _sync_roots_visibility()
        _sync_tree_columns()
        _sync_mcp_label()

    def _defer(fn):
        """Run fn after the current event finishes.

        A trace_add callback runs inside Tk's variable-update path, before
        the checkbox has been redrawn. Rebuilding the policy tree there
        keeps the checkbox visually stuck mid-flip. after_idle defers the
        work until Tk has caught up on drawing, so the toggle visibly
        lands first.
        """
        try:
            dlg.after_idle(fn)
        except Exception:
            fn()

    docs_var.trace_add("write", lambda *_: _defer(_sync_all))
    py_var.trace_add("write", lambda *_: _defer(_sync_all))
    mcp_var.trace_add("write", lambda *_: _defer(_sync_all))
    rojo_var.trace_add("write", lambda *_: _defer(_sync_all))
    luau_var.trace_add("write", lambda *_: _defer(_sync_all))
    _sync_all()

    # --- buttons ------------------------------------------------------
    btn_row = tk.Frame(main)
    btn_row.pack(fill="x", pady=(12, 0))

    def _ok() -> None:
        new_name = name_var.get().strip()
        if new_name and new_name != w.name:
            w.name = new_name
        try:
            save_workspace(project_dir, w, state_subdir)
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=dlg)
            return

        docs = bool(docs_var.get())
        py = bool(py_var.get())
        mcp = bool(mcp_var.get())
        rojo = bool(rojo_var.get())

        config["index_docs"] = docs
        config["index_python"] = py
        config["index_lua"] = bool(mcp or rojo)

        if mcp and rojo:
            config["luau_mode"] = luau_var.get() or "rojo"
        elif mcp:
            config["luau_mode"] = "mcp"
        elif rojo:
            config["luau_mode"] = "rojo"
        else:
            config["luau_mode"] = (config.get("luau_mode") or "mcp")

        fs_on = docs or py
        if fs_on and mcp:
            config["backend"] = "composite"
        elif mcp:
            config["backend"] = "mcp"
        else:
            config["backend"] = "filesystem"

        ex = dict(config.get("exec") or {})
        ex["enabled"] = bool(exec_var.get()) and py
        config["exec"] = ex

        dlg.destroy()
        if on_save is not None:
            try:
                on_save(new_name or None)
            except Exception:
                pass

    tk.Button(btn_row, text="OK", command=_ok, width=10).pack(side="right")
    tk.Button(btn_row, text="Cancel", command=dlg.destroy, width=10).pack(
        side="right", padx=(0, 6))
