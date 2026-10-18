"""list_files / survey_dir под scope."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.tools.read import ListFilesTool, SurveyDirTool
from toolkit.tools.scope import ExcludeTool, ClearScopeTool
from toolkit.formats import Format

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()

TOOLKIT = "PatchAppliers/PatchApplier/toolkit/code/toolkit"

def run(label, tool, **kw):
    r = tool.execute(backend=wb, fmt=Format.load("default"), **kw)
    head = r.message.split("\n", 1)[0]
    has_footer = "hidden by scope" in r.message.rsplit("\n", 1)[-1]
    print(f"[{label}] {r.status}  {head}  footer={has_footer}")
    return r

try:
    ClearScopeTool().execute(backend=wb)
    print("== no scope ==")
    run("list toolkit", ListFilesTool(), directory=TOOLKIT, glob="*.py")
    run("survey toolkit", SurveyDirTool(), path=TOOLKIT)

    ExcludeTool().execute(backend=wb, patterns=["tests"], reason="review")
    print("\n== scope: tests excluded ==")
    l1 = run("list toolkit scoped", ListFilesTool(), directory=TOOLKIT, glob="*.py")
    print(f"  body has '/tests/': {'/tests/' in l1.message.rsplit(chr(10), 1)[0]}")
    l2 = run("list toolkit scoped=false", ListFilesTool(), directory=TOOLKIT, glob="*.py", scoped=False)
    assert "/tests/" in l2.message

    s1 = run("survey toolkit scoped", SurveyDirTool(), path=TOOLKIT)
    print(f"  body has 'tests': {chr(10)+'tests' in s1.message.rsplit(chr(10), 2)[0] if chr(10) in s1.message else False}")
    s2 = run("survey toolkit scoped=false", SurveyDirTool(), path=TOOLKIT, scoped=False)

    # Named subdir exempts itself only
    l3 = run("list toolkit/tests scoped", ListFilesTool(), directory=f"{TOOLKIT}/tests", glob="*.py")
    assert "hidden by scope" not in l3.message, l3.message[-200:]

    print("\n[OK] list_files / survey_dir scope integration works")
finally:
    ClearScopeTool().execute(backend=wb)
    wb.close()
