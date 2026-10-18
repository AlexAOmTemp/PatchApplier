"""Stale-patterns bug: `.patchignore` edited on disk, backend must see it.

Real scenario from user: `.git` was hidden, they unhid it, patch ran
again — still 'hidden' because patterns were cached at open().

After fix: filter_check stats .patchignore every call, reloads on mtime change.
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"
PI = STATE / ".patchignore"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)

orig = PI.read_text(encoding="utf-8")
res = []
def check(name, cond, msg=""):
    res.append((name, cond))
    print(f"[{'OK' if cond else 'FAIL'}] {name}" + (f"  {msg}" if not cond else ""))

# Use a path that exists and whose visibility depends on `.*`.
P = "RimWorld/PatchApplier/.git/HEAD"

# Ensure `.*` is disabled (@.* in orig? check)
no_dot = orig
if "@.*" not in no_dot:
    no_dot = no_dot + "@.*\n"

# --- state A: hidden (`.git` active) ---
hidden_state = no_dot.replace("@.*", ".*")
PI.write_text(hidden_state, encoding="utf-8")
time.sleep(0.01)

wb = MultiRootFsBackend(ws, STATE)
wb.open()
try:
    check("A1: .git hidden at open",
          wb.filter_check(P, "read") is not None, str(wb.filter_check(P, "read")))

    # --- user edits: unhide (restore @.*) ---
    PI.write_text(no_dot, encoding="utf-8")
    time.sleep(0.02)  # ensure mtime changes on coarse FS

    r = wb.filter_check(P, "read")
    check("A2: autoreload — now visible", r is None, str(r))

    # --- user re-hides ---
    PI.write_text(hidden_state, encoding="utf-8")
    time.sleep(0.02)
    r = wb.filter_check(P, "read")
    check("A3: autoreload — hidden again", r is not None, str(r))

    # --- state prefix still exempt ---
    check("A4: state prefix unaffected",
          wb.filter_check(".patch_applier/llmscope", "read") is None)
finally:
    wb.close()
    PI.write_text(orig, encoding="utf-8")

ok = sum(1 for _, c in res if c)
print(f"\n{ok}/{len(res)} passed")
sys.exit(0 if ok == len(res) else 1)
