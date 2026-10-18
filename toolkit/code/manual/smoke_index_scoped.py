"""End-to-end: get_index with scoped=true/false."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.tools.index import GetIndexTool, install_index_paths
from toolkit.tools.scope import ExcludeTool, ClearScopeTool
from toolkit.formats import Format

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
install_index_paths(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()

def run(label, **kw):
    r = GetIndexTool().execute(backend=wb, fmt=Format.load("default"), **kw)
    head = r.message.split("\n", 1)[0]
    tail = r.message.rsplit("\n", 1)[-1] if "hidden by scope" in r.message else ""
    print(f"[{label}] {r.status}")
    print(f"  head: {head}")
    if tail:
        print(f"  tail: {tail}")
    return r

try:
    ClearScopeTool().execute(backend=wb)
    print("== no scope ==")
    r = run("scoped default", kind="code", limit=5)
    assert "hidden" not in r.message, r.message[:200]

    ExcludeTool().execute(backend=wb, patterns=["tests"], reason="not for review")
    print("\n== scope: tests excluded ==")
    r = run("scoped=true", kind="code", limit=5)
    assert "hidden" in r.message, r.message[:300]
    assert "tests" in r.message, r.message[-200:]

    r = run("scoped=false", kind="code", limit=5, scoped=False)
    assert "hidden" not in r.message, r.message[:300]

    r = run("path=hidden, scoped=true", kind="code", limit=5,
            path="PatchAppliers/PatchApplier/toolkit/code/toolkit/tests")
    print(f"  -> {r.message.splitlines()[0]}")
    r = run("path=hidden, scoped=false", kind="code", limit=5,
            path="PatchAppliers/PatchApplier/toolkit/code/toolkit/tests",
            scoped=False)
    print(f"  -> {r.message.splitlines()[0]}")

    print("\n[OK] scoped flag works")
finally:
    ClearScopeTool().execute(backend=wb)
    wb.close()
