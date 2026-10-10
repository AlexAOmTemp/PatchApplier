"""Smoke: Symbol.source_hash is populated and stable."""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

from toolkit.formats.code import parse_module  # noqa: E402

SRC = '''\
def greet(name: str) -> str:
    return f"hi {name}"


class Widget:
    def render(self):
        return 1
'''


def main():
    ok = True
    m = parse_module(SRC, path="m.py")
    for s in m.symbols:
        present = s.source_hash is not None
        print(f"  {'PASS' if present else 'FAIL'}  {s.qualname}: source_hash={s.source_hash}")
        ok &= present

    # same content -> same hash
    m2 = parse_module(SRC, path="m.py")
    same = all(a.source_hash == b.source_hash
               for a, b in zip(m.symbols, m2.symbols))
    print(f"  {'PASS' if same else 'FAIL'}  stable across parses")
    ok &= same

    # changed body -> changed hash for that symbol only
    SRC2 = SRC.replace("return 1", "return 2")
    m3 = parse_module(SRC2, path="m.py")
    by_qn = {s.qualname: s.source_hash for s in m3.symbols}
    greet_same = by_qn["greet"] == m.find("greet").source_hash
    render_diff = by_qn["Widget.render"] != m.find("Widget.render").source_hash
    print(f"  {'PASS' if greet_same else 'FAIL'}  unchanged symbol hash stable")
    print(f"  {'PASS' if render_diff else 'FAIL'}  changed symbol hash differs")
    ok &= greet_same and render_diff

    print()
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
