"""Smoke: replace_symbol `part` routing."""
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
def foo(x: int) -> int:
    """Doc."""
    return x + 1
'''


def main():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        f = root / "m.py"
        f.write_text(SRC, encoding="utf-8")

        # 1. part=body -> signature preserved, body changed
        r = _run(root, [{"action": "replace_symbol",
                         "arguments": {"file_path": "m.py", "qualname": "foo",
                                       "part": "body",
                                       "new_code": "return x + 99"}}])[0]
        ok &= _check("part=body ok", r.status == "ok")
        text = f.read_text(encoding="utf-8")
        ok &= _check("body: sig preserved", "def foo(x: int) -> int:" in text)
        ok &= _check("body: return x + 99", "return x + 99" in text)
        ok &= _check("body: old return gone", "return x + 1" not in text)

        # 2. part=signature -> body preserved
        r = _run(root, [{"action": "replace_symbol",
                         "arguments": {"file_path": "m.py", "qualname": "foo",
                                       "part": "signature",
                                       "new_code": "def foo(x: int, y: int = 0) -> int:"}}])[0]
        ok &= _check("part=signature ok", r.status == "ok")
        text = f.read_text(encoding="utf-8")
        ok &= _check("sig: new line", "def foo(x: int, y: int = 0) -> int:" in text)
        ok &= _check("sig: body kept", "return x + 99" in text)

        # 3. part=all -> whole replacement
        whole = "def foo(z: str) -> str:\n    return z.upper()\n"
        r = _run(root, [{"action": "replace_symbol",
                         "arguments": {"file_path": "m.py", "qualname": "foo",
                                       "part": "all",
                                       "new_code": whole}}])[0]
        ok &= _check("part=all ok", r.status == "ok")
        text = f.read_text(encoding="utf-8")
        ok &= _check("all: new def", "def foo(z: str) -> str:" in text)
        ok &= _check("all: old return gone", "return x + 99" not in text)

        # 4. default is part=all
        whole2 = "def foo() -> int:\n    return 0\n"
        r = _run(root, [{"action": "replace_symbol",
                         "arguments": {"file_path": "m.py", "qualname": "foo",
                                       "new_code": whole2}}])[0]
        ok &= _check("default=all ok", r.status == "ok")
        text = f.read_text(encoding="utf-8")
        ok &= _check("default: new def", "def foo() -> int:" in text)

        # 5. bad part
        r = _run(root, [{"action": "replace_symbol",
                         "arguments": {"file_path": "m.py", "qualname": "foo",
                                       "part": "middle",
                                       "new_code": "x"}}])[0]
        ok &= _check("bad part error", r.status == "error")
        ok &= _check("error_code bad_part", r.error_code == "bad_part")

    print()
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
