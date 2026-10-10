"""Project settings window: name, root tabs, per-path policy.

Opened from File -> Project settings. Replaces the placeholder dialog and
the old `open_settings_dialog` (removed in an earlier step). The window
edits an in-memory Workspace and writes on OK; Cancel discards.

What is here now:
  - project name (Entry)
  - one tab per root, each containing a PolicyTree widget
  - Add root / Remove root
  - show hidden checkbox
  - OK / Cancel

What is deferred (see docs/GUI_PROJECT_SETTINGS.md):
  - .patchignore / .mcpignore editors
  - index / MCP / exec toggles
  - per-path overrides beyond what PolicyTree handles
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from ...config import patchignore as _pi
from ...config.loader import scan_subdirs
from ...config import workspace as ws_mod
from ..projects import load_workspace, save_workspace
from .tree_view import PolicyTree


_MAX_DEPTH = 3


def open_project_settings(parent, project_dir: Path,
                          state_subdir: str,
                          on_save=None) -> None:
    """Open the modal settings window.

    Raises `projects.NotAProject` if the folder has no workspace.json.
    `on_save` is called after a successful save with the new name (or
    None if unchanged) — the caller restarts the session there.
    """
    w = load_workspace(project_dir, state_subdir)
    state_dir = project_dir / state_subdir

    dlg = tk.Toplevel(parent)
    dlg.title("Project settings")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.geometry("860x580")
    dlg.minsize(720, 480)

    main = tk.Frame(dlg, padx=12, pady=12)
    main.pack(fill="both", expand=True)

    # --- name ---------------------------------------------------------
    name_row = tk.Frame(main)
    name_row.pack(fill="x", pady=(0, 6))
    tk.Label(name_row, text="Project name:").pack(side="left")
    name_var = tk.StringVar(value=w.name)
    tk.Entry(name_row, textvariable=name_var).pack(
        side="left", fill="x", expand=True, padx=(8, 0))

    tk.Label(main, text=f"Folder: {project_dir}", anchor="w",
             fg="#666").pack(fill="x")

    # --- tabs ---------------------------------------------------------
    tk.Label(main, text="Roots:", anchor="w").pack(fill="x", pady=(10, 2))

    nb = ttk.Notebook(main)
    nb.pack(fill="both", expand=True)

    show_hidden_var = tk.BooleanVar(value=False)
    tree_widgets: dict[str, PolicyTree] = {}

    def _patterns():
        return _pi.read(state_dir)

    def _render_tab(name: str) -> None:
        pt = tree_widgets.get(name)
        root_obj = w.roots.get(name)
        if pt is None or root_obj is None:
            return
        try:
            dirs = scan_subdirs(
                Path(root_obj.path),
                max_depth=_MAX_DEPTH,
                patterns=_patterns(),
                show_hidden=bool(show_hidden_var.get()),
            )
        except Exception:
            dirs = []
        pt.render(dirs, show_hidden=bool(show_hidden_var.get()))

    def _rebuild_tabs() -> None:
        for tab_id in nb.tabs():
            nb.forget(tab_id)
        tree_widgets.clear()
        for name in w.root_names():
            root_obj = w.roots[name]
            tab = tk.Frame(nb)
            pt = PolicyTree(tab, root_obj)
            pt.pack(fill="both", expand=True)
            tree_widgets[name] = pt
            nb.add(tab, text=name)
        for name in w.root_names():
            _render_tab(name)

    def _on_show_hidden():
        for name in w.root_names():
            _render_tab(name)
    show_hidden_var.trace_add("write", lambda *_: _on_show_hidden())

    _rebuild_tabs()

    # --- controls row -------------------------------------------------
    ctrl = tk.Frame(main)
    ctrl.pack(fill="x", pady=(8, 0))

    def _add_root() -> None:
        folder = filedialog.askdirectory(title="Root folder", parent=dlg)
        if not folder:
            return
        try:
            ws_mod.add_root(w, folder)
        except ValueError as e:
            messagebox.showerror("Cannot add root", str(e), parent=dlg)
            return
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
        _rebuild_tabs()

    tk.Button(ctrl, text="Add root\u2026", command=_add_root).pack(side="left")
    tk.Button(ctrl, text="Remove root", command=_remove_root).pack(
        side="left", padx=(6, 0))
    tk.Checkbutton(ctrl, text="Show hidden", variable=show_hidden_var).pack(
        side="right")

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
        dlg.destroy()
        if on_save is not None:
            try:
                on_save(new_name or None)
            except Exception:
                pass

    tk.Button(btn_row, text="OK", command=_ok, width=10).pack(side="right")
    tk.Button(btn_row, text="Cancel", command=dlg.destroy, width=10).pack(
        side="right", padx=(0, 6))
