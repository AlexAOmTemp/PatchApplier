"""Test indent inference in Python symbol tools.

Tools infer indent from the AST (node.col_offset) and normalize whatever
`new_code` they receive — flush-left, already indented, or over-indented
all produce the same correctly-indented result. No `indent` parameter.

`qualname_lost` protects against silent corruption: if the result parses
but the target symbol vanished, the patch is rolled back.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from toolkit.backends import RootDirBackend
from toolkit.tools.symbols.python import ReplaceSymbolTool, ReplaceSymbolBodyTool


SOURCE = """\
class Foo:
    def a(self):
        return 1

    def b(self):
        return 2


def top():
    return 99
"""


class T:
    def __init__(self):
        self.ok = 0
        self.fail = 0

    def expect(self, name, cond, extra=""):
        if cond:
            print(f"  PASS  {name}")
            self.ok += 1
        else:
            print(f"  FAIL  {name}  {extra}")
            self.fail += 1


def _fresh(tmp: Path) -> RootDirBackend:
    (tmp / "m.py").write_text(SOURCE, encoding="utf-8")
    be = RootDirBackend(str(tmp))
    be.open()
    return be


def main():
    t = T()
    tmp = Path(__file__).resolve().parent / "_tmp_symbol_indent"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        # 1. Method, flush-left input -> tool adds 4 spaces
        be = _fresh(tmp)
        r = ReplaceSymbolTool().execute(
            backend=be, fmt=None, file_path="m.py",
            qualname="Foo.b",
            new_code="def b(self):\n    return 42",
        )
        text = (tmp / "m.py").read_text(encoding="utf-8")
        t.expect("method flush-left (ok)", r.status == "ok", r.message)
        t.expect("method flush-left (content)",
                 "    def b(self):\n        return 42" in text, repr(text))

        # 2. Method, pre-indented input (4 spaces) -> idempotent, no doubling
        be = _fresh(tmp)
        r = ReplaceSymbolTool().execute(
            backend=be, fmt=None, file_path="m.py",
            qualname="Foo.b",
            new_code="    def b(self):\n        return 42",
        )
        text = (tmp / "m.py").read_text(encoding="utf-8")
        t.expect("method pre-indented (ok)", r.status == "ok", r.message)
        t.expect("method pre-indented (content)",
                 "    def b(self):\n        return 42" in text, repr(text))
        t.expect("method pre-indented (no 8-space)",
                 "        def b(self):" not in text, repr(text))

        # 3. Method, over-indented input (8 spaces) -> normalized to 4
        be = _fresh(tmp)
        r = ReplaceSymbolTool().execute(
            backend=be, fmt=None, file_path="m.py",
            qualname="Foo.b",
            new_code="        def b(self):\n            return 42",
        )
        text = (tmp / "m.py").read_text(encoding="utf-8")
        t.expect("method over-indented (ok)", r.status == "ok", r.message)
        t.expect("method over-indented (content)",
                 "    def b(self):\n        return 42" in text, repr(text))

        # 4. Module-level function, flush-left
        be = _fresh(tmp)
        r = ReplaceSymbolTool().execute(
            backend=be, fmt=None, file_path="m.py",
            qualname="top",
            new_code="def top():\n    return 100",
        )
        text = (tmp / "m.py").read_text(encoding="utf-8")
        t.expect("module-level flush-left (ok)", r.status == "ok", r.message)
        t.expect("module-level flush-left (content)",
                 "def top():\n    return 100" in text, repr(text))

        # 5. Method body, flush-left -> col_offset + 4
        be = _fresh(tmp)
        r = ReplaceSymbolBodyTool().execute(
            backend=be, fmt=None, file_path="m.py",
            qualname="Foo.b",
            new_body="return 7",
        )
        text = (tmp / "m.py").read_text(encoding="utf-8")
        t.expect("body flush-left (ok)", r.status == "ok", r.message)
        t.expect("body flush-left (content)",
                 "    def b(self):\n        return 7" in text, repr(text))

        # 6. Empty input
        be = _fresh(tmp)
        r = ReplaceSymbolTool().execute(
            backend=be, fmt=None, file_path="m.py",
            qualname="Foo.b",
            new_code="",
        )
        t.expect("empty new_code -> empty_input",
                 r.error_code == "empty_input", f"got {r.error_code!r}")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n=== ИТОГ: ok={t.ok}, fail={t.fail} ===")
    sys.exit(0 if t.fail == 0 else 1)


if __name__ == "__main__":
    main()
