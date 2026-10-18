"""End-to-end: tree with scope.

Semantics: tree always has `path=`; rules matching that path (or its
children) are exempt, finer rules on subdirs remain active.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.tools.tree import TreeTool
from toolkit.tools.scope import SetScopeTool, ClearScopeTool
from toolkit.formats import Format

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()

TOOLKIT = "PatchAppliers/PatchApplier/toolkit/code/toolkit"

def run(label, **kw):
    r = TreeTool().execute(backend=wb, fmt=Format.load("default"), **kw)
    head = r.message.split("\n", 1)[0]
    print(f"[{label}] {r.status}  {head}")
    return r

def body_of(msg: str) -> str:
    """Drop footer lines ("[...hidden by scope...]") and header."""
    lines = msg.splitlines()
    return "\n".join(l for l in lines if not l.startswith("["))

try:
    ClearScopeTool().execute(backend=wb)
    print("== no scope ==")
    r0 = run("toolkit, scoped=true", path=TOOLKIT, max_dirs=100)

    # Hide tests, but allow specific subdir via named path
    SetScopeTool().execute(backend=wb, text=(
        "tests  # not for review\n"
        "tests/slow  # too slow\n"
    ))
    print("\n== scope: tests, tests/slow ==")
    r1 = run("toolkit, scoped=true", path=TOOLKIT, max_dirs=100)
    assert "hidden" in r1.message, r1.message[-300:]
    body = body_of(r1.message)
    assert "/tests" not in body, body[:500]
    r2 = run("toolkit, scoped=false", path=TOOLKIT, max_dirs=100, scoped=False)
    assert "/tests" in body_of(r2.message), r2.message[:500]

    # Named path=tests: shows tests, but tests/slow should remain hidden
    r3 = run("toolkit/tests, scoped=true", path=f"{TOOLKIT}/tests", max_dirs=100)
    body3 = body_of(r3.message)
    print("  body:")
    for line in body3.splitlines()[:6]:
        print("    " + line)
    # tests/slow must be hidden even under explicit path=tests
    assert "/slow" not in body3, body3[:500]

    print("\n[OK] tree scope integration works")
finally:
    ClearScopeTool().execute(backend=wb)
    wb.close()
