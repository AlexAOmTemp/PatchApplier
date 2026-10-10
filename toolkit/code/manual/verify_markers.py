"""Smoke: module markers rendered in CODE_INDEX.md."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

from toolkit.backends import FilesystemBackend  # noqa: E402
from toolkit.indexers.code import build_code_index  # noqa: E402


def _check(label, ok):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return ok


MAIN = '''\
"""doc"""


if __name__ == "__main__":
    print(1)
'''

LIB = '''\
import a


def helper():
    return a.X
'''

A_MOD = '''\
X = 1
'''

TEST = '''\
from a import X


def test_it():
    assert X == 1
'''

BIG = "\n".join(f"x{i} = {i}" for i in range(400)) + "\n"

VENDOR = '''\
V = 1
'''

SUPPRESSED = '''\
# pa: users, large
X = 1
''' + "\n".join(f"y{i} = {i}" for i in range(400)) + "\n"


def main():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "main.py").write_text(MAIN, encoding="utf-8")
        (root / "lib.py").write_text(LIB, encoding="utf-8")
        (root / "a.py").write_text(A_MOD, encoding="utf-8")
        (root / "test_lib.py").write_text(TEST, encoding="utf-8")
        (root / "big.py").write_text(BIG, encoding="utf-8")
        (root / "vendor").mkdir()
        (root / "vendor" / "v.py").write_text(VENDOR, encoding="utf-8")
        (root / "suppressed.py").write_text(SUPPRESSED, encoding="utf-8")

        be = FilesystemBackend(root)
        r = build_code_index(be)
        text = r.text

        # find header lines
        headers = {}
        for line in text.splitlines():
            if line.startswith("## "):
                # path is between '## ' and '  ('
                tail = line[3:]
                path = tail.split("  (", 1)[0]
                headers[path] = line

        # main.py: ◉ present, no → 0 users
        h = headers["main.py"]
        ok &= _check("main.py has ◉", "◉" in h)
        ok &= _check("main.py no '→ 0 users'", "→ 0 users" not in h)
        ok &= _check("main.py no '← 0 imp'", "← 0 imp" not in h)

        # a.py: imported by lib and test -> → 2 users (1 tests)
        h = headers["a.py"]
        ok &= _check("a.py has → 2 users", "→ 2 users" in h)
        ok &= _check("a.py has (1 tests)", "(1 tests)" in h)
        ok &= _check("a.py no ◉", "◉" not in h)

        # lib.py: imports a -> ← 1 imp; no one imports lib -> no → users line
        h = headers["lib.py"]
        ok &= _check("lib.py ← 1 imp", "← 1 imp" in h)
        ok &= _check("lib.py no → users", "→" not in h)

        # test_lib.py: [tests/]
        h = headers["test_lib.py"]
        ok &= _check("test_lib.py [tests/]", "[tests/]" in h)

        # big.py: 400 lines -> ⚠ large
        h = headers["big.py"]
        ok &= _check("big.py ⚠ large", "⚠ large" in h)

        # vendor/v.py: [vendor/]
        h = headers["vendor/v.py"]
        ok &= _check("vendor/v.py [vendor/]", "[vendor/]" in h)

        # suppressed.py: has # pa: users, large -> no → users, no ⚠ large
        h = headers["suppressed.py"]
        ok &= _check("suppressed: no ⚠ large", "⚠ large" not in h)
        ok &= _check("suppressed: no → users", "→" not in h)

        # symbol-level ⚠ large: big_func has >100 lines
        big_func_src = '''\
def small():\n    return 1\n\n\ndef big_func():\n''' + ''.join(
            f"    x{i} = {i}\n" for i in range(150)) + '''\
    return 0\n'''
        (root / "sym_large.py").write_text(big_func_src, encoding="utf-8")

        # cycle: cyc_a <-> cyc_b
        (root / "cyc_a.py").write_text("import cyc_b\nX = 1\n", encoding="utf-8")
        (root / "cyc_b.py").write_text("import cyc_a\nY = 1\n", encoding="utf-8")

        be2 = FilesystemBackend(root)
        r2 = build_code_index(be2)
        headers2 = {}
        for line in r2.text.splitlines():
            if line.startswith("## "):
                tail = line[3:]
                path = tail.split("  (", 1)[0]
                headers2[path] = line

        ok &= _check("sym_large: small not marked",
                     "def small" not in r2.text or "- small [function]" in r2.text)
        # find the big_func line
        big_line = next((l for l in r2.text.splitlines()
                         if "- big_func [function]" in l), "")
        ok &= _check("big_func has ⚠ large", "⚠ large" in big_line)
        ok &= _check("cycle: cyc_a marked", "⚠ cycle" in headers2["cyc_a.py"])
        ok &= _check("cycle: cyc_b marked", "⚠ cycle" in headers2["cyc_b.py"])
        ok &= _check("main.py still no cycle", "⚠ cycle" not in headers2["main.py"])

    print()
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
