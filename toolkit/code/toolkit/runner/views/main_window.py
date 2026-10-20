"""Main window construction.

Never imports from app.py. All external access comes through
`callbacks` (dict of Callable) and `config` (dict). The window owns Tk
widgets and the layout; it does not own application logic.
"""
from __future__ import annotations

import tkinter as tk

from .widgets import StatusLog, ReadyLight


class MainWindow:
    """Tk root + all top-level widgets.

    Public fields (app.py pulls these into its globals for callbacks):
      root, btn, repeat_btn, status_var, project_label,
      fs_status_var, fs_status_label, mcp_status_var, mcp_status_label,
      mcp_reconnect_btn, starter_include_roblox_var,
      recent_menu, right_panel, toggle_btn, lang_var.

    `toggle_right_panel` is the only non-trivial method: it toggles
    `right_visible` and adjusts geometry/text. Everything else is
    construction.
    """

    def __init__(
        self,
        *,
        config: dict,
        callbacks: dict,
        hotkey: str,
        langs: list[str],
        initial_lang: str,
        geometry_collapsed: str,
        geometry_expanded: str,
        width_left: int,
        width_toggle: int,
        width_right: int,
        window_h: int,
    ):
        self._config = config
        self._cb = callbacks
        self._hotkey = hotkey
        self._langs = langs
        self._initial_lang = initial_lang
        self._geom_collapsed = geometry_collapsed
        self._geom_expanded = geometry_expanded
        self._w_left = width_left
        self._w_toggle = width_toggle
        self._w_right = width_right
        self._w_h = window_h

        self.right_visible = False

        self.root = tk.Tk()
        self.root.title("Patch Applier")
        self.root.geometry(geometry_collapsed)
        self.root.resizable(False, False)

        self._build_menu()
        self._build_body()

    # -- menu ------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New project\u2026",
                              command=self._cb["on_new_project"])
        file_menu.add_command(label="Open project\u2026",
                              command=self._cb["on_open_project"])
        self.recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Recent", menu=self.recent_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Project settings\u2026",
                              command=self._cb["on_project_settings"])
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

    # -- body ------------------------------------------------------------

    def _build_body(self) -> None:
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill="both", expand=True)
        self._build_left(main_frame)
        self._build_toggle(main_frame)
        self._build_right(main_frame)

    def _build_left(self, parent) -> None:
        left_panel = tk.Frame(parent, width=self._w_left, height=self._w_h - 20)
        left_panel.pack_propagate(False)
        left_panel.pack(side="left", fill="y", padx=(10, 0), pady=10)

        patches_frame = tk.LabelFrame(left_panel, text="\u041f\u0430\u0442\u0447\u0438",
                                      padx=8, pady=6)
        patches_frame.pack(fill="x")

        self.btn = tk.Button(
            patches_frame,
            text=f"\u0412\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u044c ({self._hotkey})",
            command=self._cb["on_button_click"],
            font=("Arial", 12), height=2,
        )
        self.btn.pack(fill="x", pady=(0, 4))

        self.repeat_btn = tk.Button(
            patches_frame,
            text="\u21bb \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439 \u043f\u0430\u0442\u0447",
            command=self._cb["on_repeat_click"],
        )
        self.repeat_btn.pack(fill="x", pady=(0, 4))

        tk.Button(patches_frame,
                  text="\U0001F4CB \u041f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439 \u043f\u0430\u0442\u0447",
                  command=self._cb["on_get_last_patch"]).pack(fill="x", pady=(0, 4))
        tk.Button(patches_frame,
                  text="\U0001F4CB \u041f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442",
                  command=self._cb["on_get_last_output"]).pack(fill="x", pady=(0, 4))

        status_row = tk.Frame(left_panel)
        status_row.pack(fill="x", pady=(8, 0))

        self.ready_light = ReadyLight(status_row)
        self.ready_light.pack(side="left", padx=(0, 6))

        self.project_label = tk.Label(
            status_row,
            text="\u26a0 \u0443\u043a\u0430\u0436\u0438\u0442\u0435 \u043f\u0443\u0442\u044c \u043a \u043f\u0440\u043e\u0435\u043a\u0442\u0443",
            anchor="w", fg="#c07000", wraplength=self._w_left - 30,
            justify="left", cursor="hand2",
        )
        self.project_label.pack(side="left", fill="x", expand=True)
        self.project_label.bind("<Button-1>",
                                lambda _e: self._cb["on_copy_project_path"]())
        self._make_copyable(self.project_label)

        self.status_var = StatusLog(left_panel)
        self.status_var.pack(fill="both", expand=True, pady=(6, 0))

        backend_row = tk.Frame(left_panel)
        backend_row.pack(side="bottom", fill="x", pady=(6, 0))

        self.fs_status_var = tk.StringVar(value="")
        self.fs_status_label = tk.Label(
            backend_row, textvariable=self.fs_status_var,
            anchor="w", fg="#808080", font=("Consolas", 9))
        self.fs_status_label.pack(side="left")

        self.mcp_status_var = tk.StringVar(value="")
        self.mcp_status_label = tk.Label(
            backend_row, textvariable=self.mcp_status_var,
            anchor="w", fg="#808080", font=("Consolas", 9))
        self.mcp_status_label.pack(side="left", padx=(10, 0))

        self.mcp_reconnect_btn = tk.Button(
            backend_row, text="\u21bb", width=2,
            command=self._cb["on_mcp_reconnect"], state="disabled")
        self.mcp_reconnect_btn.pack(side="left", padx=(6, 0))

        self.lang_var = tk.StringVar(value=self._initial_lang)
        lang_btn = tk.Button(backend_row, textvariable=self.lang_var, width=5,
                             font=("Consolas", 9), command=self._on_lang_click)
        lang_btn.pack(side="right")

        clear_log_btn = tk.Button(backend_row, text="\u2715", width=2,
                                  font=("Consolas", 9),
                                  command=self.status_var.clear)
        clear_log_btn.pack(side="right", padx=(0, 4))

    def _on_lang_click(self) -> None:
        nxt = self._cb["next_language"](self.lang_var.get(), self._langs)
        self.lang_var.set(nxt)
        self._config["ui_language"] = nxt
        try:
            self._cb["save_config"](self._config)
        except Exception:
            pass

    def _make_copyable(self, label_widget) -> None:
        menu = tk.Menu(label_widget, tearoff=0)
        menu.add_command(label="\u041a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c",
                         command=lambda: self.root.clipboard_append(
                             label_widget.cget("text")))
        def _show(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
        label_widget.bind("<Button-3>", _show)

    def _build_toggle(self, parent) -> None:
        toggle_frame = tk.Frame(parent, width=self._w_toggle)
        toggle_frame.pack_propagate(False)
        toggle_frame.pack(side="left", fill="y", padx=(6, 6), pady=10)
        self.toggle_btn = tk.Button(toggle_frame, text="\u2192",
                                    command=self.toggle_right_panel, width=2)
        self.toggle_btn.pack(fill="both", expand=True)

    def _build_right(self, parent) -> None:
        self.right_panel = tk.Frame(parent, width=self._w_right)
        self.right_panel.pack_propagate(False)

        self.topmost_var = tk.BooleanVar(value=True)
        def _toggle_topmost():
            self.root.attributes("-topmost", self.topmost_var.get())
        tk.Checkbutton(self.right_panel, text="\u041f\u043e\u0432\u0435\u0440\u0445 \u0432\u0441\u0435\u0445 \u043e\u043a\u043e\u043d",
                       variable=self.topmost_var,
                       command=_toggle_topmost).pack(anchor="w", pady=(0, 8))

        self.auto_run_on_copy_var = tk.BooleanVar(
            value=bool(self._config.get("auto_run_on_copy", False)))

        def _toggle_auto_run() -> None:
            enabled = bool(self.auto_run_on_copy_var.get())
            self._config["auto_run_on_copy"] = enabled
            try:
                self._cb["save_config"](self._config)
            except Exception:
                pass
            try:
                self._cb["on_auto_run_toggle"](enabled)
            except Exception:
                pass

        tk.Checkbutton(
            self.right_panel,
            text="\u26a1 \u0410\u0432\u0442\u043e-\u0437\u0430\u043f\u0443\u0441\u043a (Ctrl+Alt + \u043a\u043e\u043f\u0438\u044f)",
            variable=self.auto_run_on_copy_var,
            command=_toggle_auto_run,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        tk.Button(self.right_panel,
                  text="\U0001F4CA \u041f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439 \u0434\u0438\u0444\u0444",
                  command=self._cb["on_get_last_diff"]).pack(fill="x", pady=(0, 8))

        session_frame = tk.LabelFrame(self.right_panel,
                                      text="\u0421\u0442\u0430\u0440\u0442 \u0441\u0435\u0441\u0441\u0438\u0438",
                                      padx=8, pady=6)
        session_frame.pack(fill="x", pady=(0, 8))

        tk.Button(session_frame,
                  text="\U0001F4C4 \u0421\u0442\u0430\u0440\u0442\u043e\u0432\u044b\u0439 \u0442\u0435\u043a\u0441\u0442 \u0434\u043b\u044f LLM",
                  command=self._cb["on_starter_text"]).pack(fill="x")

        self.starter_include_roblox_var = tk.BooleanVar(value=False)
        tk.Checkbutton(session_frame, text="+ RobloxCodeRules.md",
                       variable=self.starter_include_roblox_var,
                       justify="left").pack(anchor="w", pady=(4, 0))

        self.starter_include_xml_var = tk.BooleanVar(value=False)
        tk.Checkbutton(session_frame, text="+ XML_START.md",
                       variable=self.starter_include_xml_var,
                       justify="left").pack(anchor="w", pady=(0, 0))

    # -- toggle ----------------------------------------------------------

    def toggle_right_panel(self) -> None:
        self.right_visible = not self.right_visible
        if self.right_visible:
            self.right_panel.pack(side="right", fill="y", padx=(0, 10), pady=10)
            self.toggle_btn.config(text="\u2190")
            self.root.geometry(self._geom_expanded)
        else:
            self.right_panel.pack_forget()
            self.toggle_btn.config(text="\u2192")
            self.root.geometry(self._geom_collapsed)
