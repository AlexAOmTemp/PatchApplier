"""Smoke: read_file two axes (numbered, escape)."""
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


SRC = 'def foo():   \n    pass\n\n# comment\n'


def main():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "m.py").write_text(SRC, encoding="utf-8")

        # 1. default: numbered=true, escape=perline
        r = _run(root, [{"action": "read_file",
                         "arguments": {"file_path": "m.py"}}])[0]
        ok &= _check("default ok", r.status == "ok")
        body = r.message.split("\n", 1)[1]
        ok &= _check("default: line number present", body.startswith("1: "))
        ok &= _check("default: repr quotes present", "'" in body)
        ok &= _check("default: trailing spaces visible", "foo():   \\" in body)

        # 2. numbered=false, escape=perline
        r = _run(root, [{"action": "read_file",
                         "arguments": {"file_path": "m.py", "numbered": False}}])[0]
        body = r.message.split("\n", 1)[1]
        ok &= _check("n=false: no line number", not body.startswith("1: "))
        ok &= _check("n=false: still escaped", "'" in body)

        # 3. numbered=false, escape=blob
        r = _run(root, [{"action": "read_file",
                         "arguments": {"file_path": "m.py",
                                       "numbered": False, "escape": "blob"}}])[0]
        body = r.message.split("\n", 1)[1]
        ok &= _check("blob: single literal", body.count("'") == 2)
        ok &= _check("blob: \\n inside", "\\n" in body)

        # 4. numbered=true, escape=none
        r = _run(root, [{"action": "read_file",
                         "arguments": {"file_path": "m.py", "escape": "none"}}])[0]
        body = r.message.split("\n", 1)[1]
        ok &= _check("none: has line number", body.startswith("1: "))
        ok &= _check("none: no quote noise", body.count("'") == 0)

        # 5. numbered=true + escape=blob -> error
        r = _run(root, [{"action": "read_file",
                         "arguments": {"file_path": "m.py",
                                       "numbered": True, "escape": "blob"}}])[0]
        ok &= _check("blob+numbered: error", r.status == "error")
        ok &= _check("blob+numbered: bad_escape", r.error_code == "bad_escape")

        # 6. legacy raw=repr
        r = _run(root, [{"action": "read_file",
                         "arguments": {"file_path": "m.py", "raw": "repr"}}])[0]
        body = r.message.split("\n", 1)[1]
        ok &= _check("legacy repr: no line numbers", not body.startswith("1: "))
        ok &= _check("legacy repr: blob literal", body.count("'") == 2)

        # 7. range + perline
        r = _run(root, [{"action": "read_file",
                         "arguments": {"file_path": "m.py",
                                       "start_line": 1, "end_line": 2}}])[0]
        body = r.message.split("\n", 1)[1]
        ok &= _check("range: numbered", body.startswith("1: "))
        ok &= _check("range: two lines", body.count("'") == 4)

    print()
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
