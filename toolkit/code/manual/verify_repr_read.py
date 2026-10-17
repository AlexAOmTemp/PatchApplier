"""Smoke: read_file raw=repr + replace_in_file search_repr.

Checks:
  1. read_file raw=repr returns quoted repr without line numbers.
  2. read_file raw=text returns raw text.
  3. read_file raw=numbered returns 'N: ...' per line.
  4. repr output, fed back into replace_in_file with search_repr=True,
     matches exactly (incl. tricky whitespace).
  5. CRLF file: read repr shows \\r\\n; replace_in_file round-trips CRLF.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # toolkit/code

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


TRICKY = 'def foo():   \n    pass\n\n# trailing spaces above\n'


def main():
    all_ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        f = root / "m.py"
        f.write_text(TRICKY, encoding="utf-8")

        # 1. repr
        r = _run(root, [{"action": "read_file",
                         "arguments": {"file_path": "m.py", "raw": "repr"}}])[0]
        all_ok &= _check("repr: ok", r.status == "ok")
        body = r.message.split("\n", 1)[1]
        all_ok &= _check("repr: starts with quote", body.startswith("'") or body.startswith('"'))
        all_ok &= _check("repr: has \\n escape", "\\n" in body)
        all_ok &= _check("repr: no '1: ' prefix", not body.startswith("1: "))
        print(f"    body: {body!r}")
        repr_body = body

        # 2. text
        r = _run(root, [{"action": "read_file",
                         "arguments": {"file_path": "m.py", "raw": "text"}}])[0]
        all_ok &= _check("text: ok", r.status == "ok")
        all_ok &= _check("text: raw (no quotes)", not r.message.split('\n',1)[1].startswith("'"))

        # 3. numbered
        r = _run(root, [{"action": "read_file",
                         "arguments": {"file_path": "m.py", "raw": "numbered"}}])[0]
        all_ok &= _check("numbered: ok", r.status == "ok")
        all_ok &= _check("numbered: has '1: '", "1: " in r.message)

        # 4. round-trip: repr -> replace_in_file
        r = _run(root, [{"action": "replace_in_file",
                         "arguments": {"file_path": "m.py",
                                       "search": repr_body,
                                       "replace": "'def foo():\\n    return 1\\n'",
                                       "search_repr": True}}])[0]
        all_ok &= _check("round-trip: ok", r.status == "ok")
        if r.status == "ok":
            text = f.read_text(encoding="utf-8")
            all_ok &= _check("round-trip: content applied", "return 1" in text)
            all_ok &= _check("round-trip: no trailing-space line left", "pass" not in text)

        # 5. CRLF
        f2 = root / "crlf.txt"
        f2.write_bytes(b"line one\r\nline two\r\nline three\r\n")
        r = _run(root, [{"action": "read_file",
                         "arguments": {"file_path": "crlf.txt", "raw": "repr"}}])[0]
        all_ok &= _check("crlf: repr shows \\r\\n", "\\r\\n" in r.message)
        r = _run(root, [{"action": "replace_in_file",
                         "arguments": {"file_path": "crlf.txt",
                                       "search": "'line two\\r\\n'",
                                       "replace": "'LINE TWO\\r\\n'",
                                       "search_repr": True}}])[0]
        all_ok &= _check("crlf: replace ok", r.status == "ok")
        raw = f2.read_bytes()
        all_ok &= _check("crlf: CRLF preserved", b"\r\n" in raw)
        all_ok &= _check("crlf: content changed", b"LINE TWO" in raw)

    print()
    print("ALL OK" if all_ok else "SOME FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
