"""Verify: bad root gives helpful message with valid roots list."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()

try:
    # filter_check
    r = wb.filter_check("PatchApplier/DEV/NOTES.md", "read")
    print(f"filter_check: {r}")
    ok1 = r is not None and r[0] == "filter" and "valid" not in r[1] and "RimWorld" in r[1]
    print(f"  [{'OK' if ok1 else 'FAIL'}] lists valid roots")

    # existing root still works
    r2 = wb.filter_check("RimWorld/PatchApplier/DEV/NOTES.md", "read")
    print(f"valid root: {r2}")
    print(f"  [{'OK' if r2 is None else 'FAIL'}] valid root passes")

    # exists -> FileNotFoundError with valid roots
    try:
        wb.exists("PatchApplier/DEV/NOTES.md")
        print("  [FAIL] exists did not raise")
    except FileNotFoundError as e:
        msg = str(e)
        print(f"exists raises: {msg}")
        ok3 = "valid roots" in msg and "RimWorld" in msg
        print(f"  [{'OK' if ok3 else 'FAIL'}] exception lists valid roots")

    # state prefix still works
    try:
        r3 = wb.filter_check(".patch_applier/llmscope", "read")
        print(f"  [{'OK' if r3 is None else 'FAIL'}] state prefix bypasses")
    except Exception as e:
        print(f"  [FAIL] state raised: {e}")
finally:
    wb.close()
