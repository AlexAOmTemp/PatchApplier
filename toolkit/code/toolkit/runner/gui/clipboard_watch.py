"""Clipboard watcher for Ctrl+Alt auto-run.

Only active while the user holds Ctrl+Alt: that is the signal "I am
copying a patch, apply it". Outside those modifiers nothing is read
from the clipboard at all, so the poll loop costs two cheap
``is_pressed`` checks per tick and nothing more.

A change is reported only after the modifiers became held *and* the
clipboard content changed during that hold -- pasting with plain Ctrl+V
never triggers, and the same text copied twice does not re-fire until
the buffer changes again.
"""
from __future__ import annotations

import threading
import time

import keyboard
import pyperclip


POLL_INTERVAL = 0.15   # seconds between ticks
COOLDOWN = 1.0         # ignore triggers for N seconds after one fires


class ClipboardWatcher:
    """Background thread: fires ``on_trigger(text)`` when Ctrl+Alt is
    held and the clipboard changes during that hold.

    ``on_trigger`` runs on the *worker* thread; the callback must
    marshal itself onto the Tk thread (``root.after(0, ...)``).
    """

    def __init__(self, on_trigger, *, poll: float = POLL_INTERVAL,
                 cooldown: float = COOLDOWN):
        self._on_trigger = on_trigger
        self._poll = poll
        self._cooldown = cooldown
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._baseline = ""             # clipboard content when hold began
        self._last_fire = 0.0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=1.0)
        self._thread = None

    def _mods_held(self) -> bool:
        try:
            return keyboard.is_pressed("ctrl") and keyboard.is_pressed("alt")
        except Exception:
            return False

    def _read(self) -> str:
        try:
            return pyperclip.paste() or ""
        except Exception:
            return ""

    def _run(self) -> None:
        held = False
        while not self._stop.is_set():
            now_held = self._mods_held()
            if now_held and not held:
                # Fresh hold: snapshot the current clipboard so that
                # pasting something that was already there does not fire.
                self._baseline = self._read()
            elif now_held:
                current = self._read()
                if current and current != self._baseline:
                    now = time.time()
                    if now - self._last_fire >= self._cooldown:
                        self._last_fire = now
                        self._baseline = current
                        try:
                            self._on_trigger(current)
                        except Exception:
                            pass
                    else:
                        self._baseline = current
            held = now_held
            self._stop.wait(self._poll)
