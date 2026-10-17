"""Smoke: verify symbol-tool indent fixes.

Checks:
  1. replace_symbol_signature on a multi-line def keeps params, replaces head.
  2. replace_symbol with mixed-indent new_code fails with a clear
     result_syntax_error (tool must NOT auto-repair).
  3. replace_symbol with flat new_code succeeds (baseline).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # toolkit/code

from toolkit.backends import RootDirBackend  # noqa: E402
from toolkit.tools.symbols.python import (  # noqa: E402
    ReplaceSymbolSignatureTool,
    ReplaceSymbolTool,
)

SINGLE_SIG = '''\
def foo(a, b):
    return a + b
'''

MULTI_SIG = '''\
def foo(
    a: int,
    b: int,
) -> int:
    pass
'''

CLASS_SRC = '''\
class A:
    def m(self):
        pass
'''


def _check(label, ok):
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {label}")
    return ok


def main():
    all_ok = True
    tmp = Path(tempfile.mkdtemp())
    backend = RootDirBackend(str(tmp))
    backend.open()
    try:
        # 1. multi-line signature
        f1 = tmp / "m.py"
        f1.write_text(SINGLE_SIG, encoding="utf-8")
        r = ReplaceSymbolSignatureTool().execute(
            backend, None,
            file_path="m.py", qualname="foo", new_signature=MULTI_SIG,
        )
        all_ok &= _check("multi-line sig: ok", r.status == "ok")
        text = f1.read_text(encoding="utf-8")
        all_ok &= _check("params preserved (a: int)", "a: int" in text)
        all_ok &= _check("body preserved (return a + b)", "return a + b" in text)
        all_ok &= _check("no duplicate def", text.count("def foo") == 1)
        print("  --- file after ---")
        for ln in text.splitlines():
            print(f"  |{ln}")

        # 2. mixed indent -> must fail (no auto-repair)
        f2 = tmp / "n.py"
        f2.write_text(CLASS_SRC, encoding="utf-8")
        mixed = "@classmethod\n  def m(self):\n    pass\n"
        r2 = ReplaceSymbolTool().execute(
            backend, None,
            file_path="n.py", qualname="A.m", new_code=mixed,
        )
        all_ok &= _check("mixed indent: error", r2.status == "error")
        all_ok &= _check(
            "mixed indent: result_syntax_error",
            r2.error_code == "result_syntax_error",
        )
        print("  --- message ---")
        print(f"  {r2.message}")

        # 3. flat baseline should work
        flat = "def m(self):\n    return 1\n"
        r3 = ReplaceSymbolTool().execute(
            backend, None,
            file_path="n.py", qualname="A.m", new_code=flat,
        )
        all_ok &= _check("flat baseline: ok", r3.status == "ok")
    finally:
        backend.close()

    print()
    print("ALL OK" if all_ok else "SOME FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
