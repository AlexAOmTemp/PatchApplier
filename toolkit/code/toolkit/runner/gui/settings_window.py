"""Project settings window: name, roots, visibility, sources.

Opened from File -> Project settings. Edits an in-memory Workspace and
an in-memory CONFIG dict; writes both on OK; Cancel discards.

Sections:
  - project name (Entry, right-click or Ctrl+C to copy)
  - Roots (LabelFrame): notebook with per-root PolicyTree,
    Add / Remove, Show hidden, short legend
  - Visibility rules (LabelFrame): editors for the two ignore files,
    labelled by what they hide rather than by filename
  - Sources (LabelFrame): Documentation, Python (+ Allow scripts),
    MCP, Lua on disk, Luau source radio

Invariants:
  - `exec.enabled` requires `index_python`. When Python indexing is off,
    the exec checkbox is forced off and disabled. Enforced again on save.
  - Luau source radio follows MCP / Lua-on-disk checkboxes:
      neither         -> radio disabled, no selection
      only MCP        -> forced to mcp, disabled
      only Lua-on-disk-> forced to rojo, disabled
      both            -> radio enabled, default rojo
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
    dlg.geometry("780x820")
    dlg.minsize(660, 700)

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

    # === Roots ========================================================
    roots_frame = tk.LabelFrame(main, text="Roots (project folders)",
                                padx=8, pady=8)
    roots_frame.pack(fill="both", expand=True, pady=(8, 0))

    nb = ttk.Notebook(roots_frame)
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

    tk.Button(roots_ctrl, text="Add root\u2026", command=_add_root).pack(side="left")
    tk.Button(roots_ctrl, text="Remove root", command=_remove_root).pack(
        side="left", padx=(6, 0))
    tk.Checkbutton(roots_ctrl, text="Show hidden", variable=show_hidden_var).pack(
        side="right")

    tk.Label(roots_frame, text=_LEGEND, anchor="w", justify="left",
             fg="#666", font=("Consolas", 8)).pack(fill="x", pady=(6, 0))

    # === Visibility rules ============================================
    vis = tk.LabelFrame(main, text="Visibility rules", padx=8, pady=8)
    vis.pack(fill="x", pady=(8, 0))

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
        _open_ignore_editor(dlg, pi_path, "Hide filesystem paths",
                            _pi.DEFAULT_PATCHIGNORE,
                            on_saved=lambda: (
                                pi_label_var.set(_count_label(pi_path)),
                                _on_show_hidden()))

    def _open_mi():
        _open_ignore_editor(dlg, mi_path, "Hide Roblox modules",
                            _mi.DEFAULT_MCPIGNORE,
                            on_saved=lambda: mi_label_var.set(_count_label(mi_path)))

    pi_row = tk.Frame(vis)
    pi_row.pack(fill="x", pady=(0, 4))
    tk.Button(pi_row, text="Hide filesystem paths\u2026",
              command=_open_pi, width=24, anchor="w").pack(side="left")
    tk.Label(pi_row, textvariable=pi_label_var, fg="#666").pack(
        side="left", padx=(8, 0))
    tk.Label(pi_row, text="(.patchignore: paths hidden from the LLM on disk)",
             fg="#999", font=("Consolas", 8)).pack(side="left", padx=(8, 0))

    mi_row = tk.Frame(vis)
    mi_row.pack(fill="x")
    mi_btn = tk.Button(mi_row, text="Hide Roblox modules\u2026",
                       command=_open_mi, width=24, anchor="w")
    mi_btn.pack(side="left")
    tk.Label(mi_row, textvariable=mi_label_var, fg="#666").pack(
        side="left", padx=(8, 0))
    tk.Label(mi_row, text="(.mcpignore: modules hidden from the LLM in DataModel)",
             fg="#999", font=("Consolas", 8)).pack(side="left", padx=(8, 0))

    # === Sources =====================================================
    src = tk.LabelFrame(main, text="Sources", padx=8, pady=8)
    src.pack(fill="x", pady=(8, 0))

    docs_var = tk.BooleanVar(value=bool(config.get("index_docs", True)))
    py_var = tk.BooleanVar(value=bool(config.get("index_python", True)))
    backend_now = (config.get("backend") or "composite")
    mcp_var = tk.BooleanVar(value=backend_now in ("mcp", "composite"))
    rojo_var = tk.BooleanVar(value=bool(config.get("index_lua", False)))
    luau_var = tk.StringVar(value=(config.get("luau_mode") or "mcp"))
    exec_var = tk.BooleanVar(value=bool((config.get("exec") or {}).get("enabled")))

    # Documentation
    tk.Checkbutton(src, text="Documentation (.md)", variable=docs_var,
                   anchor="w").pack(fill="x")

    # Python (with nested Allow scripts)
    tk.Checkbutton(src, text="Python (.py)", variable=py_var,
                   anchor="w").pack(fill="x")
    py_sub = tk.Frame(src)
    py_sub.pack(fill="x", padx=(22, 0))
    exec_cb = tk.Checkbutton(py_sub, text="Allow Python scripts (run_python)",
                             variable=exec_var, anchor="w")
    exec_cb.pack(side="left")
    exec_hint = tk.Label(py_sub, text="", fg="#888", font=("Consolas", 8))
    exec_hint.pack(side="left", padx=(8, 0))

    # MCP
    tk.Checkbutton(src, text="MCP (Roblox scene + code)", variable=mcp_var,
                   anchor="w").pack(fill="x")

    # Lua files on disk
    tk.Checkbutton(src, text="Lua files on disk (.luau)", variable=rojo_var,
                   anchor="w").pack(fill="x")

    # Luau source radio
    radio_row = tk.Frame(src)
    radio_row.pack(fill="x", pady=(4, 0), padx=(22, 0))
    tk.Label(radio_row, text="Luau source:").pack(side="left")
    luau_mcp_rb = tk.Radiobutton(radio_row, text="MCP", variable=luau_var,
                                 value="mcp")
    luau_rojo_rb = tk.Radiobutton(radio_row, text="Rojo", variable=luau_var,
                                  value="rojo")
    luau_mcp_rb.pack(side="left", padx=(8, 0))
    luau_rojo_rb.pack(side="left", padx=(8, 0))
    luau_hint = tk.Label(radio_row, text="", fg="#888", font=("Consolas", 8))
    luau_hint.pack(side="left", padx=(8, 0))

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
        # both: user chooses, default Rojo
        luau_mcp_rb.config(state="normal")
        luau_rojo_rb.config(state="normal")
        if luau_var.get() not in ("mcp", "rojo"):
            luau_var.set("rojo")
        luau_hint.config(text="")

    def _sync_mcp_btn():
        # .mcpignore is relevant only when MCP is on and Luau source is mcp.
        use_mcp_code = bool(mcp_var.get()) and luau_var.get() == "mcp"
        mi_btn.config(state=("normal" if use_mcp_code else "disabled"))

    py_var.trace_add("write", lambda *_: _sync_exec_state())
    mcp_var.trace_add("write", lambda *_: (_sync_luau_state(), _sync_mcp_btn()))
    rojo_var.trace_add("write", lambda *_: _sync_luau_state())
    luau_var.trace_add("write", lambda *_: _sync_mcp_btn())
    _sync_exec_state()
    _sync_luau_state()
    _sync_mcp_btn()

    # === buttons ======================================================
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
        # index_lua is on when any Luau source is enabled.
        config["index_lua"] = bool(mcp or rojo)

        # Luau mode from radio, but only meaningful when a source exists.
        if mcp and rojo:
            config["luau_mode"] = luau_var.get() or "rojo"
        elif mcp:
            config["luau_mode"] = "mcp"
        elif rojo:
            config["luau_mode"] = "rojo"
        else:
            config["luau_mode"] = (config.get("luau_mode") or "mcp")

        # Backend derived.
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
