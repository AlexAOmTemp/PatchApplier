"""find_symbol / find_usages под scope."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.tools.find_symbol import FindSymbolTool
from toolkit.tools.find_usages import FindUsagesTool
from toolkit.tools.scope import ExcludeTool, ClearScopeTool
from toolkit.tools.index import install_index_paths
from toolkit.formats import Format

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
install_index_paths(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()

def run(label, tool, **kw):
    r = tool.execute(backend=wb, fmt=Format.load("default"), **kw)
    head = r.message.split("\n", 1)[0]
    print(f"[{label}] {r.status}  {head}")
    return r

try:
    ClearScopeTool().execute(backend=wb)
    print("== no scope ==")
    r0 = run("find_symbol 'Tool'", FindSymbolTool(), query="Tool", limit=5)

    ExcludeTool().execute(backend=wb, patterns=["tests"], reason="review")
    print("\n== scope: tests excluded ==")

    # Strong case: query that only matches inside tests. With scope on,
    # expect zero visible matches + footer with hidden count. With scope
    # off, expect actual matches.
    r1 = run("find_symbol 'test_' scoped", FindSymbolTool(), query="test_", limit=10)
    r2 = run("find_symbol 'test_' scoped=false", FindSymbolTool(), query="test_", limit=10, scoped=False)
    assert "hidden by scope" in r1.message, r1.message[:300]
    assert "hidden by scope" not in r2.message, r2.message[:300]

    # Explicit manifest should not apply scope.
    r3 = run("find_symbol explicit manifest", FindSymbolTool(), query="test_", limit=10,
            manifest_path=".patch_applier/CODE_INDEX.manifest.json")
    assert "hidden by scope" not in r3.message, r3.message[:300]

    r4 = run("find_usages scoped", FindUsagesTool(), query="core", limit=5)
    r5 = run("find_usages scoped=false", FindUsagesTool(), query="core", limit=5, scoped=False)
    assert "hidden by scope" not in r4.message, r4.message[:300]

    print("\n[OK] find_* scope integration works")
finally:
    ClearScopeTool().execute(backend=wb)
    wb.close()
