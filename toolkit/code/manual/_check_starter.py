"""Check: does the current project's status show roots in the policy section?

Runs GetStatusTool with the current session's backend (if any) — but
since this is a standalone script, it constructs a fresh workspace from
`.patch_applier/workspace.json` and a MultiRootFsBackend, then calls
GetStatusTool with the right context. The output is compared against
expected shape: `## Policy Filesystem` + root basename + `[R W Id Ip Il]`.
"""
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

ROOT = HERE.parents[2]  # PatchApplier/
STATE = ROOT / ".patch_applier"

from toolkit.config import workspace as ws_mod
from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.formats import Format
from toolkit.tools.status import GetStatusTool


ws = load_workspace({"project_dir": str(ROOT), "state_dir": ".patch_applier"})
if ws is None:
    print("[FAIL] no workspace loaded")
    sys.exit(1)
print(f"[OK]   workspace loaded: {ws.name}  roots={ws.root_names()}")

wb = MultiRootFsBackend(ws, STATE)
wb.open()

try:
    GetStatusTool.set_context(
        project_name=ws.name,
        backend="composite",
        backends_enabled={"filesystem", "mcp"},
    )
    r = GetStatusTool().execute(backend=wb, fmt=Format.load("default"))
    print()
    print(r.message)
    print()
    if "## Policy Filesystem" in r.message:
        print("[OK]   has Policy Filesystem section")
    else:
        print("[FAIL] no Policy Filesystem section")
    for name in ws.root_names():
        if name in r.message:
            print(f"[OK]   root '{name}' mentioned")
        else:
            print(f"[FAIL] root '{name}' missing from policy")
    if "[R W Id Ip Il]" in r.message or "Id" in r.message:
        print("[OK]   five-flag display present")
    else:
        print("[FAIL] five-flag display missing")
finally:
    wb.close()
