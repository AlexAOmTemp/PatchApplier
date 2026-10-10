"""Smoke: import the GUI module to catch syntax/import errors.

Does NOT construct tk.Tk() — just imports app.py. A real GUI smoke is
the user's restart; this catches the common case (stale symbol, missing
import) at zero risk.
"""
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

try:
    from toolkit.runner.gui import app as _app
    print("[OK]   toolkit.runner.gui.app imported")
    # Sanity: attributes we expect to survive the refactor.
    for name in ("run", "_switch_project", "_menu_new_project",
                 "_menu_open_project", "_menu_project_settings"):
        if not hasattr(_app, name):
            print(f"[FAIL] missing attribute: {name}")
            sys.exit(1)
    print("[OK]   all expected attributes present")
    print("=== gui smoke OK ===")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"=== gui smoke FAILED: {type(e).__name__}: {e} ===")
    sys.exit(1)
