"""End-to-end: grep with scoped=true/false, explicit paths, directory."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.tools.read import GrepTool
from toolkit.tools.scope import ExcludeTool, ClearScopeTool
from toolkit.formats import Format

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()

TOOLKIT = "PatchAppliers/PatchApplier/toolkit/code/toolkit"
PATTERN = "def execute"

def has_footer(msg: str) -> bool:
    """Footer is on the LAST line; grep results may contain the marker text."""
    last = msg.rstrip().rsplit("\n", 1)[-1]
    return "hidden by scope" in last and "scoped=false" in last

def run(label, **kw):
    r = GrepTool().execute(backend=wb, fmt=Format.load("default"),
                           pattern=PATTERN, **kw)
    head = r.message.split("\n", 1)[0]
    print(f"[{label}] {r.status}  {head}")
    if has_footer(r.message):
        print(f"  footer: {r.message.rstrip().rsplit(chr(10), 1)[-1]}")
    return r

try:
    ClearScopeTool().execute(backend=wb)
    print("== no scope ==")
    r0 = run("no scope", directory=TOOLKIT, max_results=50)

    ExcludeTool().execute(backend=wb, patterns=["tests"], reason="not for review")
    print("\n== scope: tests excluded ==")
    r1 = run("dir=toolkit, scoped=true", directory=TOOLKIT, max_results=50)
    assert has_footer(r1.message), r1.message[-300:]
    r2 = run("dir=toolkit, scoped=false", directory=TOOLKIT, max_results=50, scoped=False)
    assert not has_footer(r2.message), r2.message[-300:]

    # explicit paths bypass
    r3 = run("paths=[tests/...], scoped=true",
             paths=[f"{TOOLKIT}/tests/test_get_index.py"], max_results=5)
    assert not has_footer(r3.message), r3.message[-300:]

    # directory=exempt subtree
    r4 = run("dir=toolkit/tests, scoped=true",
             directory=f"{TOOLKIT}/tests", max_results=5)
    assert not has_footer(r4.message), r4.message[-300:]

    print("\n[OK] grep scope integration works")
finally:
    ClearScopeTool().execute(backend=wb)
    wb.close()
