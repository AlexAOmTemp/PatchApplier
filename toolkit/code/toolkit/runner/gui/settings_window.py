"""Project settings window: name, root tabs, policy, sources.

Opened from File -> Project settings. Edits an in-memory Workspace and
an in-memory CONFIG dict; writes both on OK; Cancel discards.

Sections:
  - project name (Entry, right-click or Ctrl+C to copy)
  - one tab per root, each with a PolicyTree
  - Add root / Remove root / Show hidden
  - .patchignore / .mcpignore editors (modal listbox)
  - sources: index docs/py/lua, MCP backend, luau mode, allow run_python
  - legend below the tabs
  - OK / Cancel

Rule: exec (run_python) requires Python indexing. If `index_python` is
off, the exec checkbox is forced off and disabled. The same invariant is
enforced again on save, so a stale config cannot turn exec on under a
disabled Python.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import pyperclip

from ...config import patchignore as _pi
from ...config import mcpignore as _mi
from ...config.loader import scan_subdirs
from ...config import workspace as ws_mod
from ..projects import load_workspace, save_workspace
from .tree_view import PolicyTree


_MAX_DEPTH = 3


_LEGEND = (
    "R = read (читать)   W = write (писать)   "
    "Id = index docs (.md)   Ip = index py (.py)   Il = index lua (.luau)\n"
    "\u00b7 inherit   + allow   \u2212 deny   "
    "Click cycles the cell; the topmost [root] row sets the root's default policy.\n"
    "Hidden rows are hard-denied: all five flags forced to \u2212, clicks ignored."
)


# --- entry with layout-independent Ctrl+C / Ctrl+A -----------------------


def _make_copyable_entry(entry: tk.Entry) -> None:
    """Right-click menu + layout-independent Ctrl+C / Ctrl+A on an Entry.

    Tk binds <<Copy>> to the keysym 'c' (Latin). On a Russian keyboard
    layout the physical C key produces Cyrillic 'с', so the default
    binding does not fire. We add an explicit handler on
    Control-KeyPress keyed on the physical keycode (layout-independent
    on Windows) and generate the virtual event ourselves.
    """
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
    """Modal listbox editor for a .patchignore / .mcpignore file."""
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
    """Open the modal settings window.

    `config` is the in-memory CONFIG dict (edited in place). `on_save`
    is called after both workspace.json and CONFIG are written; the
    caller saves CONFIG to disk and restarts the session there.
    """
    w = load_workspace(project_dir, state_subdir)
    state_dir = project_dir / state_subdir

    dlg = tk.Toplevel(parent)
    dlg.title("Project settings")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.geometry("720x680")
    dlg.minsize(620, 560)

    main = tk.Frame(dlg, padx=12, pady=12)
    main.pack(fill="both", expand=True)

    # --- name ---------------------------------------------------------
    name_row = tk.Frame(main)
    name_row.pack(fill="x", pady=(0, 6))
    tk.Label(name_row, text="Project name:").pack(side="left")
    name_var = tk.StringVar(value=w.name)
    name_entry = tk.Entry(name_row, textvariable=name_var)
    name_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
    _make_copyable_entry(name_entry)

    tk.Label(main, text=f"Folder: {project_dir}", anchor="w",
             fg="#666").pack(fill="x")

    # --- roots tabs ---------------------------------------------------
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

    # --- roots controls ----------------------------------------------
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

    # --- ignore editors ----------------------------------------------
    ignores = tk.LabelFrame(main, text="Ignore rules", padx=8, pady=6)
    ignores.pack(fill="x", pady=(8, 0))

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

    def _open_pi():
        _open_ignore_editor(dlg, pi_path, ".patchignore",
                            _pi.DEFAULT_PATCHIGNORE,
                            on_saved=lambda: (
                                pi_label_var.set(_count_label(pi_path)),
                                _on_show_hidden()))

    def _open_mi():
        _open_ignore_editor(dlg, mi_path, ".mcpignore",
                            _mi.DEFAULT_MCPIGNORE,
                            on_saved=lambda: mi_label_var.set(_count_label(mi_path)))

    pi_row = tk.Frame(ignores)
    pi_row.pack(fill="x", pady=(0, 2))
    tk.Button(pi_row, text="Edit .patchignore\u2026", command=_open_pi).pack(side="left")
    tk.Label(pi_row, textvariable=pi_label_var, fg="#666").pack(
        side="left", padx=(8, 0))

    mi_row = tk.Frame(ignores)
    mi_row.pack(fill="x")
    mi_btn = tk.Button(mi_row, text="Edit .mcpignore\u2026", command=_open_mi)
    mi_btn.pack(side="left")
    tk.Label(mi_row, textvariable=mi_label_var, fg="#666").pack(
        side="left", padx=(8, 0))

    # --- sources ------------------------------------------------------
    src = tk.LabelFrame(main, text="Sources", padx=8, pady=6)
    src.pack(fill="x", pady=(8, 0))

    docs_var = tk.BooleanVar(value=bool(config.get("index_docs", True)))
    py_var = tk.BooleanVar(value=bool(config.get("index_python", True)))
    lua_var = tk.BooleanVar(value=bool(config.get("index_lua", True)))

    backend_now = (config.get("backend") or "composite")
    mcp_var = tk.BooleanVar(value=backend_now in ("mcp", "composite"))
    luau_var = tk.StringVar(value=(config.get("luau_mode") or "mcp"))

    exec_var = tk.BooleanVar(value=bool((config.get("exec") or {}).get("enabled")))

    row1 = tk.Frame(src)
    row1.pack(fill="x")
    tk.Checkbutton(row1, text="Index docs (.md)", variable=docs_var).pack(side="left")
    tk.Checkbutton(row1, text="Index python (.py)", variable=py_var).pack(
        side="left", padx=(12, 0))
    tk.Checkbutton(row1, text="Index lua (.luau)", variable=lua_var).pack(
        side="left", padx=(12, 0))

    row2 = tk.Frame(src)
    row2.pack(fill="x", pady=(4, 0))
    tk.Checkbutton(row2, text="MCP backend", variable=mcp_var).pack(side="left")
    tk.Label(row2, text="  luau mode:").pack(side="left", padx=(12, 0))
    luau_mcp_rb = tk.Radiobutton(row2, text="mcp", variable=luau_var,
                                 value="mcp")
    luau_rojo_rb = tk.Radiobutton(row2, text="rojo", variable=luau_var,
                                  value="rojo")
    luau_mcp_rb.pack(side="left")
    luau_rojo_rb.pack(side="left", padx=(6, 0))

    row3 = tk.Frame(src)
    row3.pack(fill="x", pady=(4, 0))
    exec_cb = tk.Checkbutton(row3, text="Allow run_python", variable=exec_var)
    exec_cb.pack(side="left")
    exec_hint = tk.Label(row3, text="(requires Python indexing)", fg="#888")
    exec_hint.pack(side="left", padx=(6, 0))

    # --- reactive rules ----------------------------------------------

    def _sync_exec_state():
        """exec can only be on when index_python is on."""
        if py_var.get():
            exec_cb.config(state="normal")
            exec_hint.config(text="(requires Python indexing)", fg="#888")
        else:
            exec_var.set(False)
            exec_cb.config(state="disabled")
            exec_hint.config(text="(disabled: python indexing off)", fg="#c07000")

    def _sync_mcp_state():
        mcp_on = bool(mcp_var.get())
        st = "normal" if mcp_on else "disabled"
        luau_mcp_rb.config(state=st)
        luau_rojo_rb.config(state=st)
        # .mcpignore only relevant when MCP + luau=mcp; keep button state
        mcp_luau = mcp_on and luau_var.get() == "mcp"
        mi_btn.config(state=("normal" if mcp_luau else "disabled"))

    py_var.trace_add("write", lambda *_: _sync_exec_state())
    mcp_var.trace_add("write", lambda *_: _sync_mcp_state())
    luau_var.trace_add("write", lambda *_: _sync_mcp_state())
    _sync_exec_state()
    _sync_mcp_state()

    # --- legend -------------------------------------------------------
    legend = tk.Label(main, text=_LEGEND, anchor="w", justify="left",
                      fg="#666", font=("Consolas", 9))
    legend.pack(fill="x", pady=(8, 0))

    # --- buttons ------------------------------------------------------
    btn_row = tk.Frame(main)
    btn_row.pack(fill="x", pady=(10, 0))

    def _ok() -> None:
        new_name = name_var.get().strip()
        if new_name and new_name != w.name:
            w.name = new_name
        try:
            save_workspace(project_dir, w, state_subdir)
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=dlg)
            return

        # config
        config["index_docs"] = bool(docs_var.get())
        config["index_python"] = bool(py_var.get())
        config["index_lua"] = bool(lua_var.get())
        config["luau_mode"] = luau_var.get() or "mcp"

        mcp_on = bool(mcp_var.get())
        fs_on = docs_var.get() or py_var.get()
        if fs_on and mcp_on:
            config["backend"] = "composite"
        elif mcp_on:
            config["backend"] = "mcp"
        else:
            config["backend"] = "filesystem"

        ex = dict(config.get("exec") or {})
        # Enforce invariant on save too: exec requires Python.
        ex["enabled"] = bool(exec_var.get()) and bool(py_var.get())
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
