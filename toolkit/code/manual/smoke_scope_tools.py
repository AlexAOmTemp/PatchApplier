"""End-to-end smoke for scope tools via a real backend."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.tools.scope import (
    GetScopeTool, ExcludeTool, IncludeTool, SetScopeTool, ClearScopeTool,
)

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()

def show(label, r):
    print(f"[{label}] {r.status}  {r.message}")
    return r

try:
    # Ensure clean state
    ClearScopeTool().execute(backend=wb)
    show("get empty", GetScopeTool().execute(backend=wb))

    show("exclude no reason", ExcludeTool().execute(backend=wb, patterns=["tests"]))

    r = ExcludeTool().execute(backend=wb, patterns=["tests", "manual"], reason="not for review")
    show("exclude", r)
    assert r.status == "ok", r

    r = GetScopeTool().execute(backend=wb)
    show("get after exclude", r)
    assert "tests" in r.message and "not for review" in r.message, r.message

    r = IncludeTool().execute(backend=wb, patterns=["tests/test_core.py"], reason="core test target")
    show("include", r)
    assert r.status == "ok", r

    r = GetScopeTool().execute(backend=wb)
    show("get after include", r)
    assert "!tests/test_core.py" in r.message, r.message

    r = SetScopeTool().execute(backend=wb, text="Mods/*  # other mods\n!Mods/target  # ours")
    show("set_scope", r)
    assert r.status == "ok" and r.message.endswith("2 rule(s)"), r

    r = SetScopeTool().execute(backend=wb, text="broken line without reason")
    show("set_scope bad", r)
    assert r.status == "error" and r.error_code == "scope_parse_error", r

    r = ClearScopeTool().execute(backend=wb)
    show("clear", r)
    r = GetScopeTool().execute(backend=wb)
    assert "empty" in r.message, r.message
    print("[OK] all scope tools behave")
finally:
    wb.close()
