"""Smoke: `# pa: ...` suppression directives are parsed."""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

from toolkit.formats.code import parse_module  # noqa: E402


def _check(label, ok):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return ok


def main():
    ok = True

    # 1. no directive -> empty
    m = parse_module("x = 1\n", path="a.py")
    ok &= _check("no directive -> empty", m.suppress == frozenset())

    # 2. single marker
    m = parse_module("# pa: no-users\nx = 1\n", path="b.py")
    ok &= _check("single -> {'no-users'}", m.suppress == frozenset({"no-users"}))

    # 3. comma-separated
    m = parse_module("# pa: no-users, no-large\nx = 1\n", path="c.py")
    ok &= _check("comma -> two", m.suppress == frozenset({"no-users", "no-large"}))

    # 4. multiple lines merge
    src = "# pa: no-users\n# pa: no-imports\nx = 1\n"
    m = parse_module(src, path="d.py")
    ok &= _check("multi-line merge", m.suppress == frozenset({"no-users", "no-imports"}))

    # 5. after line 20 -> ignored
    src = "\n" * 25 + "# pa: no-users\nx = 1\n"
    m = parse_module(src, path="e.py")
    ok &= _check("past 20 lines -> ignored", m.suppress == frozenset())

    # 6. odd spacing
    m = parse_module("#  pa:   no-users  ,  no-large\nx = 1\n", path="f.py")
    ok &= _check("tolerant whitespace",
                 m.suppress == frozenset({"no-users", "no-large"}))

    print()
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
