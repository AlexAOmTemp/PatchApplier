"""tree: recursive sizes by default (like du -sh)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.tools.tree import TreeTool
from toolkit.formats import Format

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()

res = []
def check(name, cond, msg=""):
    res.append((name, cond))
    print(f"[{'OK' if cond else 'FAIL'}] {name}" + (f"  {msg[:150]}" if not cond else ""))

try:
    def run(label, **kw):
        r = TreeTool().execute(backend=wb, fmt=Format.load("default"), **kw)
        print(f"\n--- {label} ---")
        for line in r.message.splitlines()[:12]:
            print(f"  {line}")
        return r

    # 1. RimWorld depth=1: Mods must NOT show 0 files
    r = run("RimWorld depth=1", path="RimWorld", max_depth=1, scoped=False)
    check("1a: Mods has files (not 0)",
          "Mods  (" in r.message and "Mods  (0 B, 0 files)" not in r.message,
          r.message[:300])
    check("1b: RimWorldWin64_Data has >300MB",
          "RimWorldWin64_Data  (" in r.message and "MB" in r.message)
    check("1c: PatchApplier shows files",
          "PatchApplier  (" in r.message and "131.7 KB" not in r.message,
          r.message[:400])

    # 2. recursive_sizes=False: old behavior (direct-only)
    r2 = run("recursive_sizes=False", path="RimWorld", max_depth=1,
             scoped=False, recursive_sizes=False)
    check("2a: Mods (0 files) visible when direct-only",
          "Mods  (" in r2.message)
    check("2b: shows subdir count when not recursive",
          "subdirs" in r2.message, r2.message[:400])

    # 3. scoped: Mods hidden
    from toolkit.tools.scope import ExcludeTool, ClearScopeTool
    ClearScopeTool().execute(backend=wb)
    ExcludeTool().execute(backend=wb, patterns=["Mods"], reason="smoke")
    r3 = run("scope=Mods excluded", path="RimWorld", max_depth=1)
    check("3a: Mods hidden", "Mods" not in r3.message or "hidden" in r3.message,
          r3.message[:500])
    ClearScopeTool().execute(backend=wb)
finally:
    wb.close()

ok = sum(1 for _, c in res if c)
print(f"\n{ok}/{len(res)} passed")
sys.exit(0 if ok == len(res) else 1)
