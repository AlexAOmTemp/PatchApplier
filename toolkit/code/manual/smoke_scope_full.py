"""Full scope smoke — 12 edge cases + end-to-end include/set_scope.

Saves current `.patch_applier/llmscope`, runs tests, restores.
"""
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
from toolkit.config import llmscope

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()

SCOPE_REL = ".patch_applier/llmscope"
TESTS_DIR = "PatchAppliers/PatchApplier/toolkit/code/toolkit/tests"
TEST_FILE = f"{TESTS_DIR}/test_get_index.py"
OTHER_FILE = f"{TESTS_DIR}/test_cli_config_isolation.py"

results = []
def check(name, cond, msg=""):
    status = "OK" if cond else "FAIL"
    results.append((name, status, msg))
    print(f"[{status}] {name}" + (f"  {msg[:120]}" if not cond else ""))

def save():
    try:
        if wb.exists(SCOPE_REL):
            return wb.read(SCOPE_REL)
    except Exception:
        pass
    return ""

def restore(text):
    try:
        if text:
            wb.write(SCOPE_REL, text)
        elif wb.exists(SCOPE_REL):
            wb.delete(SCOPE_REL)
    except Exception as e:
        print(f"RESTORE FAILED: {e}")

def load_scope():
    return llmscope.Scope(llmscope.parse(wb.read(SCOPE_REL)))

_original = save()
try:
    # 1. include end-to-end
    ClearScopeTool().execute(backend=wb)
    ExcludeTool().execute(backend=wb, patterns=[TESTS_DIR], reason="whole dir")
    IncludeTool().execute(backend=wb, patterns=[TEST_FILE], reason="one file")
    sc = load_scope()
    check("1a: included file visible", not sc.is_hidden(TEST_FILE))
    check("1b: other test hidden", sc.is_hidden(OTHER_FILE))

    # 2. set_scope end-to-end
    SetScopeTool().execute(backend=wb, text="a/b  # why1\nc/d  # why2")
    sc = load_scope()
    check("2: set_scope replaced", len(sc.rules) == 2 and sc.rules[0].glob == "a/b")

    # 3. `tests/**` pattern
    SetScopeTool().execute(backend=wb, text="tests/**  # glob")
    sc = load_scope()
    check("3a: tests/** deep", sc.is_hidden("p/tests/a/b/c.py"))
    check("3b: tests/** direct", sc.is_hidden("tests/x.py"))

    # 4. duplicate exclude
    ClearScopeTool().execute(backend=wb)
    ExcludeTool().execute(backend=wb, patterns=["foo"], reason="r1")
    ExcludeTool().execute(backend=wb, patterns=["foo"], reason="r2")
    sc = load_scope()
    check("4: duplicates allowed", len(sc.rules) == 2)
    check("4b: still hides", sc.is_hidden("foo/bar.py"))

    # 5. include without prior exclude = noop
    ClearScopeTool().execute(backend=wb)
    IncludeTool().execute(backend=wb, patterns=["nothing.py"], reason="noop")
    sc = load_scope()
    check("5: include alone is noop", not sc.is_hidden("nothing.py"))

    # 6. empty patterns
    ClearScopeTool().execute(backend=wb)
    r = ExcludeTool().execute(backend=wb, patterns=[], reason="x")
    check("6: empty patterns = error",
          r.status == "error" and r.error_code == "bad_options")

    # 7. set_scope(text="") = clear
    SetScopeTool().execute(backend=wb, text="old.py  # will be cleared")
    SetScopeTool().execute(backend=wb, text="")
    r = GetScopeTool().execute(backend=wb)
    check("7: empty text = clear", "empty" in r.message.lower())

    # 8. set_scope with only comments
    SetScopeTool().execute(backend=wb, text="# just a comment\n# another")
    r = GetScopeTool().execute(backend=wb)
    check("8: comments-only = empty", "empty" in r.message.lower())

    # 9. get_status always shows scope when non-empty
    from toolkit.tools.status import GetStatusTool
    GetStatusTool.set_context(project_name="smoke", backend="composite",
                              backends_enabled={"filesystem"})
    ExcludeTool().execute(backend=wb, patterns=["z"], reason="s")
    r = GetStatusTool().execute(backend=wb, sections=["session"])
    check("9: sections=session shows ## Scope", "## Scope" in r.message)

    # 10. broken llmscope surfaces error
    wb.write(SCOPE_REL, "this line has no reason\n")
    r = GetStatusTool().execute(backend=wb)
    check("10a: status shows scope ERR", "scope ERR" in r.message)
    from toolkit.tools.index import GetIndexTool, install_index_paths
    install_index_paths(cfg)
    r = GetIndexTool().execute(backend=wb, kind="code", limit=1)
    check("10b: get_index shows scope ERR", "scope ERR" in r.message)

    # 11. path= uses exemptions (already covered by smoke_scope_exempt),
    # verify integration here: exclude tests, path=tests should show all
    ClearScopeTool().execute(backend=wb)
    ExcludeTool().execute(backend=wb, patterns=[TESTS_DIR], reason="r")
    r = GetIndexTool().execute(backend=wb, kind="code", path=TESTS_DIR, limit=0)
    # path= exempts TESTS_DIR rule, so ALL tests visible
    check("11: path=tests exempts dir rule",
          "test_get_index.py" in r.message and "test_cli_config_isolation.py" in r.message,
          r.message[:200])
    # And without path=, they're hidden (in a full listing)
    r2 = GetIndexTool().execute(backend=wb, kind="code", limit=0)
    check("11b: default view hides tests",
          "test_cli_config_isolation.py" not in r2.message)

    # 12. backslash in pattern
    SetScopeTool().execute(backend=wb, text="a\\b\\c  # bs")
    sc = load_scope()
    check("12: backslash normalized", sc.is_hidden("x/a/b/c/d.py"))

finally:
    restore(_original)
    wb.close()

ok = sum(1 for _, s, _ in results if s == "OK")
fail = sum(1 for _, s, _ in results if s == "FAIL")
print(f"\n{ok} passed, {fail} failed")
sys.exit(0 if fail == 0 else 1)
