"""Shared GUI state and constants.

Everything here is process-global: Tk variables, config cache, session
handle, tiny inter-thread queue. Imported by presenters and views so they
read the same singletons. No Tk widgets are constructed here except the
StatusLog class (which is a widget, and belongs in views/ on the next
migration step — kept here for now so the split is incremental).
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path


# gui package lives at toolkit/runner/gui/__init__.py
HERE = Path(__file__).resolve().parent          # toolkit/runner/gui/
RUNNER_DIR = HERE.parent                        # toolkit/runner/


def _find_toolkit_root(start: Path) -> Path:
    """Locate the toolkit root by walking up from `start`.

    Two markers identify the root in a layout-independent way: the
    toolkit-wide `.patch_applier.json` file, and `docs/LLM_START.*.md`
    (the starter text). Either is enough. This makes the toolkit
    relocatable: move the whole directory anywhere, or reshape its
    internal structure, without touching this module.

    Falls back to `start.parents[3]` (the current layout) if neither
    marker is found — e.g. a partially installed toolkit.
    """
    p = start
    for _ in range(8):
        if (p / ".patch_applier.json").is_file():
            return p
        docs = p / "docs"
        if docs.is_dir() and any(docs.glob("LLM_START.*.md")):
            return p
        if p.parent == p:
            break
        p = p.parent
    return start.parents[3] if len(start.parents) >= 4 else start


TOOLKIT_ROOT = _find_toolkit_root(HERE)                # toolkit/
PROJECT_ROOT = TOOLKIT_ROOT.parent              # project root


# Persistent state kept next to the GUI (still in runner/, not in gui/,
# because the runner scripts read/write them).
LAST_PATCH = RUNNER_DIR / "last_patch.json"
LAST_OUTPUT = RUNNER_DIR / "last_output.txt"
LAST_DIFF = RUNNER_DIR / "last_diff.txt"

HOTKEY = "ctrl+alt+space"
BUTTON_STATE_REFRESH_MS = 1000

WIDTH_LEFT = 390
WIDTH_RIGHT = 240
WIDTH_TOGGLE = 30
WINDOW_H = 400
COLLAPSED_W = WIDTH_LEFT + WIDTH_TOGGLE + 22
EXPANDED_W = COLLAPSED_W + WIDTH_RIGHT + 10

MONO_FONT = ("Consolas", 10)



msg_queue: queue.Queue = queue.Queue()

last_applied_patch_norm = None
last_output_text = None
is_executing = False
_last_mcp_ready = False
_last_mcp_state: str = ""

CONFIG: dict = {}
PROJECT_OK = False

# Persistent Session for in-process patching.
_session = None
_session_lock = threading.Lock()
_session_backend_name = None

# Tk variables — created lazily by app.run() (they need a Tk root).
# Kept here as module-level names so presenters/handlers can reference them
# after run() populates them.
mcp_status_var = None
status_label = None
status_var = None
fs_status_var = None
mcp_status_var = None
fs_status_label = None
mcp_status_label = None
error_var = None
project_label = None
right_panel = None
toggle_btn = None
btn = None
repeat_btn = None
root = None
starter_include_roblox_var = None
starter_include_xml_var = None
mcp_reconnect_btn = None
