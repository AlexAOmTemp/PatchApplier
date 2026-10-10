"""Smoke: symbol-tools preserve CRLF in .py and .luau files."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

from toolkit.backends import FilesystemBackend  # noqa: E402
from toolkit.core import Policy, Session  # noqa: E402
from toolkit.formats import Format  # noqa: E402
from toolkit.tools import TOOL_MAP  # noqa: E402


def _check(label, ok):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return ok


def _run(root, patches):
    backend = FilesystemBackend(root)
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP, policy=Policy()) as s:
        return s.apply_patches(patches)


PY_CRLF = (
    b'"""doc"""\r\n'
    b'\r\n'
    b'def top(x: int) -> int:\r\n'
    b'    return x + 1\r\n'
    b'\r\n'
    b'class Foo:\r\n'
    b'    def bar(self):\r\n'
    b'        return 1\r\n'
)

LUA_CRLF = (
    b'local M = {}\r\n'
    b'\r\n'
    b'function M.hello()\r\n'
    b'    return 1\r\n'
    b'end\r\n'
    b'\r\n'
    b'return M\r\n'
)


def main():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # 1. Python: replace_symbol on CRLF file
        f = root / "m.py"
        f.write_bytes(PY_CRLF)
        r = _run(root, [{"action": "replace_symbol",
                         "arguments": {"file_path": "m.py", "qualname": "top",
                                       "new_code": "def top(x: int) -> int:\n    return x + 2\n"}}])[0]
        ok &= _check("py replace_symbol ok", r.status == "ok")
        data = f.read_bytes()
        ok &= _check("py CRLF preserved", b"\r\n" in data and b"\n" in data)
        ok &= _check("py no bare LF", b"\n" not in data.replace(b"\r\n", b""))
        ok &= _check("py edit applied", b"return x + 2" in data)

        # 2. Python: insert_symbol
        r = _run(root, [{"action": "insert_symbol",
                         "arguments": {"file_path": "m.py", "new_code": "def added():\n    return 42\n",
                                       "position": "end"}}])[0]
        ok &= _check("py insert ok", r.status == "ok")
        data = f.read_bytes()
        ok &= _check("py insert CRLF preserved",
                     b"\n" not in data.replace(b"\r\n", b""))
        ok &= _check("py insert applied", b"def added" in data)

        # 3. Lua: replace_symbol
        g = root / "x.luau"
        g.write_bytes(LUA_CRLF)
        r = _run(root, [{"action": "replace_symbol",
                         "arguments": {"file_path": "x.luau", "qualname": "M.hello",
                                       "new_code": "function M.hello()\n    return 2\nend\n"}}])[0]
        ok &= _check("lua replace_symbol ok", r.status == "ok")
        data = g.read_bytes()
        ok &= _check("lua CRLF preserved",
                     b"\n" not in data.replace(b"\r\n", b""))
        ok &= _check("lua edit applied", b"return 2" in data)

    print()
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
