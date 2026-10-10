"""GUI package. Public entry point: `run()`.

Re-exports from .app once the package split is complete; during the
migration the modules here exist alongside the legacy monolithic
`runner/gui.py` (which cannot coexist with this package on disk, so the
legacy file is moved into `runner/gui_legacy.py` before this package
materializes).
"""
from __future__ import annotations

__all__ = ["run"]


def run():
    from .app import run as _run
    return _run()
