"""list_files: non-recursive by default, shows dirs, hides dotdirs."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.tools.read import ListFilesTool
from toolkit.formats import Format

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()

res = []
def check(name, cond, msg=""):
    res.append((name, cond))
    print(f"[{'OK' if cond else 'FAIL'}] {name}" + (f"  {msg[:120]}" if not cond else ""))

try:
    def run(label, **kw):
        r = ListFilesTool().execute(backend=wb, fmt=Format.load("default"), **kw)
        print(f"\n--- {label} ---")
        for line in r.message.splitlines()[:15]:
            print(f"  {line}")
        return r

    # 1. non-recursive default: shows dirs + files, no .git, no nested
    r = run("non-recursive PatchApplier",
            directory="RimWorld/PatchApplier", show_size=False)
    check("1a: has CLAUDE.md", "CLAUDE.md" in r.message)
    check("1b: has DEV/", "DEV/" in r.message)
    check("1c: has RWoM-main/", "RWoM-main/" in r.message)
    check("1d: no .git", ".git" not in r.message)
    check("1e: no .patch_applier", ".patch_applier" not in r.message)
    check("1f: no nested (no build.py)", "build.py" not in r.message)
    check("1g: no recursive RWoM-main files", "RWoM-main/RimWorldOfMagic" not in r.message)

    # 2. show_hidden=True: .git appears
    r2 = run("show_hidden", directory="RimWorld/PatchApplier",
             show_size=False, show_hidden=True)
    check("2a: .git visible", ".git/" in r2.message)
    check("2b: .patch_applier visible", ".patch_applier/" in r2.message)

    # 3. recursive=True on a small dir: nested files appear
    r3 = run("recursive DEV", directory="RimWorld/PatchApplier/DEV",
             show_size=False, recursive=True)
    check("3a: recursive has build.py", "build.py" in r3.message)
    check("3b: recursive has NOTES.md", "NOTES.md" in r3.message)

    # 3c. recursive on huge dir: capped, no crash
    r3c = run("recursive PatchApplier (huge)",
              directory="RimWorld/PatchApplier", show_size=False, recursive=True)
    check("3c: huge dir returns cap message",
          "слишком много" in r3c.message)

    # 4. glob works with non-recursive (direct children only)
    r4 = run("non-recursive *.md", directory="RimWorld/PatchApplier",
             glob="*.md", show_size=False)
    check("4a: CLAUDE.md in *.md", "CLAUDE.md" in r4.message)
    # Subdirs shown if they contain a glob match (DEV/NOTES.md -> DEV/)
    check("4b: DEV/ shown (contains NOTES.md)", "DEV/" in r4.message)
    check("4c: no nested .md", "build.py" not in r4.message)
    check("4d: no .git (hidden)", ".git" not in r4.message)
finally:
    wb.close()

ok = sum(1 for _, c in res if c)
print(f"\n{ok}/{len(res)} passed")
sys.exit(0 if ok == len(res) else 1)
