"""Double-click launcher for the toolkit GUI.

Ensures the toolkit parent directory is on sys.path, writes our PID to a
temp file (read by restart_gui.py), then calls `toolkit.runner.gui.run()`.
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.runner.gui import run


if __name__ == "__main__":
    pid_file = Path(tempfile.gettempdir()) / "patch_applier_gui.pid"
    try:
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    run()
