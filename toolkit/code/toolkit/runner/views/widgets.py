"""Reusable Tk widgets for the runner GUI."""
from __future__ import annotations

import tkinter as tk


class StatusLog(tk.Frame):
    """Compact status log: newest on top, scrollable, colored by leading glyph.

    Exposes `.set(msg)` matching StringVar's interface so existing call sites
    stay unchanged. `.set_state(msg)` is the idempotent variant for state-like
    values (clipboard warnings, error line) that get refreshed on every poll.
    """

    MAX_LINES = 200
    _TAGS = {
        "\u2713": "#306030",  # success
        "\u2717": "#a02020",  # error
        "\u26a0": "#c07000",  # warning
        "\u2139": "#707070",  # info
        "\u23f3": "#b58900",  # in progress
        "\u23f9": "#707070",  # stopped
    }

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._last_state = None
        self._text = tk.Text(
            self, height=4, wrap="word", relief="flat", borderwidth=0,
            highlightthickness=0, font=("Segoe UI", 9),
            state="disabled", cursor="arrow", background="#ffffff",
        )
        self._scroll = tk.Scrollbar(self, command=self._text.yview, width=10)
        self._text.configure(yscrollcommand=self._scroll.set)
        self._text.pack(side="left", fill="both", expand=True)
        self._scroll.pack(side="right", fill="y")
        for glyph, color in self._TAGS.items():
            self._text.tag_configure(glyph, foreground=color)
        self._text.tag_configure("_default", foreground="#404040")

        # A `state="disabled"` Text allows mouse selection but ignores
        # keyboard events, so Ctrl+C does not copy. Bind by *physical*
        # key code, not by keysym: on a non-Latin layout (e.g. Russian)
        # the keysym is Cyrillic and a `<Control-c>` binding misses.
        # Windows virtual-key codes are layout-independent: 67 = C, 65 = A.
        self._text.bind("<Control-KeyPress>", self._on_ctrl_key)
        self._menu = tk.Menu(self._text, tearoff=0)
        self._menu.add_command(label="Копировать", command=self._copy_selection)
        self._menu.add_command(label="Выделить всё", command=self._select_all)
        self._text.bind("<Button-3>", self._show_context_menu)

    def _on_ctrl_key(self, event):
        """Layout-independent Ctrl+C / Ctrl+A for the log widget.

        Uses `event.keycode` — the physical key, stable across keyboard
        layouts — instead of `event.keysym`, which differs on Cyrillic
        layouts (`Cyrillic_es` instead of `c`).
        """
        if event.keycode == 67:      # physical 'C'
            return self._copy_selection(event)
        if event.keycode == 65:      # physical 'A'
            return self._select_all(event)
        return None

    def _copy_selection(self, _e=None):
        try:
            text = self._text.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self.clipboard_clear()
        self.clipboard_append(text)
        return "break"

    def _select_all(self, _e=None):
        self._text.tag_add("sel", "1.0", "end")
        return "break"

    def _show_context_menu(self, e):
        try:
            self._menu.tk_popup(e.x_root, e.y_root)
        finally:
            self._menu.grab_release()

    def set(self, msg):
        if msg is None:
            return
        msg = str(msg)
        if not msg:
            return
        head = msg.lstrip()[:1]
        tag = head if head in self._TAGS else "_default"
        self._text.configure(state="normal")
        self._text.insert("1.0", msg + "\n", tag)
        lines = int(self._text.index("end-1c").split(".")[0])
        if lines > self.MAX_LINES:
            self._text.delete(f"{self.MAX_LINES + 1}.0", "end")
        self._text.see("1.0")
        self._text.configure(state="disabled")

    def set_state(self, msg):
        if msg == self._last_state:
            return
        self._last_state = msg
        if msg:
            self.set(msg)

    def clear(self):
        self._last_state = None
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
