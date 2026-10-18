"""Smoke-test the new structure mode of get_index.

Checks: default limit=500, path filter, sort=size, limit=0 (unlimited).
"""
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.tools.index import GetIndexTool, install_index_paths
from toolkit.formats import Format


cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
install_index_paths(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()

try:
    def run(label, **kw):
        r = GetIndexTool().execute(backend=wb, fmt=Format.load("default"), **kw)
        msg = r.message
        head = msg.split("\n", 1)[0]
        print(f"[{label}] {r.status}  {head}")
        return r

    run("py default",   kind="code")
    run("py path",      kind="code", path="PatchAppliers/PatchApplier/toolkit/code/toolkit/core")
    run("py sort=size", kind="code", sort="size", limit=10)
    run("cs path",      kind="csharp", path="RimWorld/Mods/1123043922/1.6")
    run("cs limit=20",  kind="csharp", limit=20)
    run("docs snapshot",kind="docs")
    print()
    # Sanity: py default should show >limit=500? No — 218 modules < 500.
    r = run("py limit=5", kind="code", limit=5)
    assert "of " in r.message and "5 of " in r.message, r.message[:200]
    r = run("py limit=0", kind="code", limit=0)
    assert "of " in r.message, r.message[:200]
    print("[OK] header counts correct")
finally:
    wb.close()
