"""get_status показывае ## Scope при непустом llmscope."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.tools.status import GetStatusTool
from toolkit.tools.scope import SetScopeTool, ClearScopeTool
from toolkit.formats import Format

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()

GetStatusTool.set_context(project_name=ws.name, backend="composite",
                          backends_enabled={"filesystem"})

def run(label, **kw):
    r = GetStatusTool().execute(backend=wb, fmt=Format.load("default"), **kw)
    has = "## Scope" in r.message
    print(f"[{label}] {r.status}  has_scope_section={has}")
    return r, has

try:
    ClearScopeTool().execute(backend=wb)
    print("== empty scope ==")
    _, has = run("default")
    assert not has, "scope section must be absent when file is empty"

    SetScopeTool().execute(backend=wb, text=(
        "Source  # engine, not our mod\n"
        "tests   # not for review\n"
    ))
    print("\n== non-empty scope ==")
    r, has = run("default")
    assert has, r.message
    # Always-on even with sections='session'
    _, has2 = run("sections=session", sections="session")
    assert has2, "scope must be shown even with explicit sections"
    print("  rendered:")
    for line in r.message.split("## Scope", 1)[1].split("##", 1)[0].splitlines()[:5]:
        print("    " + line)

    print("\n[OK] get_status ## Scope works")
finally:
    ClearScopeTool().execute(backend=wb)
    wb.close()
