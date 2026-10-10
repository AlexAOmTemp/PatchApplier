"""Final session cleanup: gitignore + remove stray dir + git rm --cached."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

# 1. .patch_applier/.gitignore
_gitignore_state = (
    "# Toolkit state — generated files, not for version control.\n"
    "INDEX.md\n"
    "INDEX.md.version\n"
    "CODE_INDEX.md\n"
    "CODE_INDEX.md.version\n"
    "CODE_INDEX.manifest.json\n"
    "CODE_INDEX_LUA.md\n"
    "CODE_INDEX_LUA.md.version\n"
    "CODE_INDEX_LUA.manifest.json\n"
    ".index_meta.json\n"
    "bridge_log.jsonl\n"
    "outputs.json\n"
    "patch.json\n"
    "\n"
    "# Kept (config / policy): workspace.json, .patchignore, .mcpignore, config.json\n"
)
(ROOT / ".patch_applier" / ".gitignore").write_text(_gitignore_state,
                                                     encoding="utf-8")
print("wrote .patch_applier/.gitignore")

# 2. toolkit/.gitignore
_gitignore_toolkit = (
    "# Toolkit runtime — logs and toolkit-wide state.\n"
    "runtime/\n"
    "\n"
    "# Python cache.\n"
    "__pycache__/\n"
    "*.pyc\n"
)
(ROOT / "toolkit" / ".gitignore").write_text(_gitignore_toolkit,
                                               encoding="utf-8")
print("wrote toolkit/.gitignore")

# 3. Remove stray .patch_applier/.patch_applier/
stray = ROOT / ".patch_applier" / ".patch_applier"
if stray.exists():
    shutil.rmtree(stray)
    print(f"removed stray: {stray}")
else:
    print("no stray dir")

# 4. git rm --cached for already-tracked generated files
exe = shutil.which("git")
paths = [
    "toolkit/runtime",
    ".patch_applier/INDEX.md",
    ".patch_applier/INDEX.md.version",
    ".patch_applier/CODE_INDEX.md",
    ".patch_applier/CODE_INDEX.md.version",
    ".patch_applier/CODE_INDEX.manifest.json",
    ".patch_applier/CODE_INDEX_LUA.md",
    ".patch_applier/CODE_INDEX_LUA.md.version",
    ".patch_applier/CODE_INDEX_LUA.manifest.json",
    ".patch_applier/.index_meta.json",
    ".patch_applier/bridge_log.jsonl",
    ".patch_applier/outputs.json",
    ".patch_applier/patch.json",
]
p = subprocess.run(
    [exe, "rm", "-r", "--cached", "--ignore-unmatch"] + paths,
    cwd=str(ROOT), capture_output=True, text=True,
)
print(f"git rm rc={p.returncode}")
if p.stdout.strip(): print(p.stdout.rstrip())
if p.stderr.strip(): print("STDERR:", p.stderr.rstrip())

# 5. Rebuild state listing
print("\n=== .patch_applier/ after ===")
for c in sorted((ROOT / ".patch_applier").iterdir()):
    print(f"  {c.name}")
