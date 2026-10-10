"""Launcher for the toolkit GUI.

Adds `toolkit/code` to sys.path so the inner `toolkit` package is importable,
then delegates to `toolkit.runner.gui.run()`. Lives at the toolkit root so
the entry point is discoverable without digging into code/.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = HERE / "code"
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

from toolkit.runner.gui import run


if __name__ == "__main__":
    run()
