"""Tests for parse_code_index_text + diff_code_index."""
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.indexers.diff import parse_code_index_text, diff_code_index


PASS = "[OK]  "
FAIL = "[FAIL]"


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def expect(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"{PASS} {label}")
            self.passed += 1
        else:
            print(f"{FAIL} {label}" + (f" -- {detail}" if detail else ""))
            self.failed += 1


BASE = """# Code Index

## a.py  (10 стр., 1.0 KB)
Hash: 111  Len: 500
Imports: os
- foo [function] (L1\u2013L3)
- Bar [class] (L5\u2013L10)
  - Bar.method [method] (L6\u2013L9)

## b.py  (5 стр., 0.5 KB)
Hash: 222  Len: 300
- baz [function] (L1\u2013L5)
"""


def main():
    t = T()

    # --- parse ---
    print("== parse_code_index_text ==")
    mods = parse_code_index_text(BASE)
    t.expect("2 modules", len(mods) == 2, list(mods.keys()))
    t.expect("a.py present", "a.py" in mods)
    t.expect("a.py hash", mods["a.py"]["hash"] == 111, mods["a.py"]["hash"])
    t.expect("a.py len", mods["a.py"]["len"] == 500)
    t.expect("a.py lines", mods["a.py"]["lines"] == 10)
    t.expect("a.py has 3 symbols", len(mods["a.py"]["symbols"]) == 3,
             list(mods["a.py"]["symbols"].keys()))
    t.expect("a.py has foo", "foo" in mods["a.py"]["symbols"])
    t.expect("a.py has Bar.method", "Bar.method" in mods["a.py"]["symbols"])
    t.expect("Bar.method line_start == 6",
             mods["a.py"]["symbols"]["Bar.method"]["line_start"] == 6)

    # --- diff: no change ---
    print()
    print("== diff: no change ==")
    dr = diff_code_index(BASE, BASE)
    t.expect("no change marker", "без изменений" in dr.header, dr.header)

    # --- diff: created ---
    print()
    print("== diff: created ==")
    dr = diff_code_index("", BASE)
    t.expect("created marker", "создан" in dr.header, dr.header)

    # --- diff: module changed (hash) ---
    print()
    print("== diff: module hash changed ==")
    changed = BASE.replace("Hash: 111", "Hash: 999")
    dr = diff_code_index(BASE, changed)
    t.expect("changed marker (~)", "~1" in dr.header, dr.header)
    t.expect("a.py listed", "a.py" in dr.render())

    # --- diff: symbol added ---
    print()
    print("== diff: symbol added to a.py ==")
    added = BASE.replace(
        "  - Bar.method [method] (L6\u2013L9)",
        "  - Bar.method [method] (L6\u2013L9)\n- new_func [function] (L12\u2013L14)",
    ).replace("Hash: 111", "Hash: 999").replace("Len: 500", "Len: 560")
    dr = diff_code_index(BASE, added)
    rendered = dr.render()
    t.expect("changed marker", "~1" in dr.header, dr.header)
    t.expect("new_func listed with +", "+ a.py :: new_func" in rendered, rendered)

    # --- diff: module added ---
    print()
    print("== diff: module added ==")
    with_c = BASE + "\n## c.py  (3 стр., 0.3 KB)\nHash: 333  Len: 100\n- qux [function] (L1\u2013L3)\n"
    dr = diff_code_index(BASE, with_c)
    t.expect("+1 in header", "+1" in dr.header, dr.header)
    t.expect("c.py listed with +", "+ c.py" in dr.render())

    # --- diff: module removed ---
    print()
    print("== diff: module removed ==")
    dr = diff_code_index(BASE, BASE.replace("\n## b.py", "\n## _removed_b.py").replace("## _removed_b.py  (5 стр., 0.5 KB)\nHash: 222  Len: 300\n- baz [function] (L1\u2013L5)\n", ""))
    t.expect("-1 in header", "-1" in dr.header, dr.header)

    # --- diff: symbol line range shifted (same hash) ---
    print()
    print("== diff: same hash -> not changed ==")
    dr = diff_code_index(BASE, BASE)
    t.expect("identical text -> no change", "без изменений" in dr.header)

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
