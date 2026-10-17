"""Smoke: replace_statement — address one statement in a symbol body."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

from toolkit.backends import RootDirBackend  # noqa: E402
from toolkit.core import Policy, Session  # noqa: E402
from toolkit.formats import Format  # noqa: E402
from toolkit.tools import TOOL_MAP  # noqa: E402


def _check(label, ok):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return ok


def _run(root, patches):
    backend = RootDirBackend(root)
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP, policy=Policy()) as s:
        return s.apply_patches(patches)


SRC = '''\
def foo(x):
    a = 1
    b = 2
    return a + b + x
'''


def main():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        f = root / "m.py"
        f.write_text(SRC, encoding="utf-8")

        # 1. replace statement #2 (b = 2 -> b = 42)
        r = _run(root, [{"action": "replace_statement",
                         "arguments": {"file_path": "m.py",
                                       "qualname": "foo",
                                       "index": 2,
                                       "new_code": "b = 42"}}])[0]
        ok &= _check("replace #2 ok", r.status == "ok")
        text = f.read_text(encoding="utf-8")
        ok &= _check("b = 42", "b = 42" in text)
        ok &= _check("a = 1 preserved", "a = 1" in text)
        ok &= _check("return preserved", "return a + b + x" in text)
        ok &= _check("no b = 2", "b = 2\n" not in text)

        # 2. out of range
        r = _run(root, [{"action": "replace_statement",
                         "arguments": {"file_path": "m.py",
                                       "qualname": "foo",
                                       "index": 99,
                                       "new_code": "x = 1"}}])[0]
        ok &= _check("out of range error", r.status == "error")
        ok &= _check("error_code index_out_of_range",
                     r.error_code == "index_out_of_range")

        # 3. delete statement #1 (a = 1)
        r = _run(root, [{"action": "replace_statement",
                         "arguments": {"file_path": "m.py",
                                       "qualname": "foo",
                                       "index": 1}}])[0]
        ok &= _check("delete ok", r.status == "ok")
        text = f.read_text(encoding="utf-8")
        ok &= _check("a = 1 gone", "a = 1" not in text)
        ok &= _check("b = 42 kept", "b = 42" in text)

        # 4. replace with multi-line block
        r = _run(root, [{"action": "replace_statement",
                         "arguments": {"file_path": "m.py",
                                       "qualname": "foo",
                                       "index": 1,
                                       "new_code": "b = 42\nb += 1"}}])[0]
        ok &= _check("multi-line replace ok", r.status == "ok")
        text = f.read_text(encoding="utf-8")
        ok &= _check("b += 1 present", "b += 1" in text)

        # 5. bad index (0)
        r = _run(root, [{"action": "replace_statement",
                         "arguments": {"file_path": "m.py",
                                       "qualname": "foo",
                                       "index": 0,
                                       "new_code": "x = 1"}}])[0]
        ok &= _check("index=0 error", r.status == "error")

        # 6. not found qualname
        r = _run(root, [{"action": "replace_statement",
                         "arguments": {"file_path": "m.py",
                                       "qualname": "nope",
                                       "index": 1,
                                       "new_code": "x = 1"}}])[0]
        ok &= _check("not_found", r.status == "error")
        ok &= _check("error_code not_found", r.error_code == "not_found")

        # 7. empty body of one-statement function -> becomes pass
        (root / "n.py").write_text("def only():\n    return 1\n", encoding="utf-8")
        r = _run(root, [{"action": "replace_statement",
                         "arguments": {"file_path": "n.py",
                                       "qualname": "only",
                                       "index": 1}}])[0]
        ok &= _check("last stmt delete ok", r.status == "ok")
        text = (root / "n.py").read_text(encoding="utf-8")
        ok &= _check("replaced by pass", "pass" in text)
        ok &= _check("return 1 gone", "return 1" not in text)

        # 8. Lua file -> explicit not supported
        (root / "x.luau").write_text("local M = {}\nreturn M\n", encoding="utf-8")
        r = _run(root, [{"action": "replace_statement",
                         "arguments": {"file_path": "x.luau",
                                       "qualname": "M.x",
                                       "index": 1,
                                       "new_code": "return 1"}}])[0]
        ok &= _check("lua not supported", r.status == "error")
        ok &= _check("error_code lua_not_supported",
                     r.error_code == "lua_not_supported")

    print()
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
