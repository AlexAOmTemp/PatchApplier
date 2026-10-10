"""One-shot cleanup: remove stale toolkit/.patch_applier/ directory.

That directory was the state location when `project_dir` was
PatchApplier/toolkit/. Now `project_dir` is PatchApplier/ and state lives
in PatchApplier/.patch_applier/. The old one contains only INDEX.md and
its sidecar — leftover from a pre-workspace run. Safe to remove.
"""
from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
STALE = ROOT / "toolkit" / ".patch_applier"
KEEP = ROOT / ".patch_applier"


print(f"root:  {ROOT}")
print(f"stale: {STALE}  exists={STALE.exists()}")
print(f"keep:  {KEEP}  exists={KEEP.exists()}")

if STALE.exists() and STALE != KEEP:
    for f in STALE.iterdir():
        print(f"  removing {f.name}")
    shutil.rmtree(STALE)
    print(f"removed {STALE}")
else:
    print("nothing to remove")

print(f"stale exists after: {STALE.exists()}")
