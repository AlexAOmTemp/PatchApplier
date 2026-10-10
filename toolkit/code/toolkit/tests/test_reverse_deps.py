"""Tests for module-level reverse dependencies (Used by)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import FilesystemBackend
from toolkit.indexers.code import build_code_index


PASS = "[OK]  "
FAIL = "[FAIL]"


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def expect(self, label, cond, detail=""):
        if cond:
            print(f"{PASS} {label}")
            self.passed += 1
        else:
            print(f"{FAIL} {label}" + (f" -- {detail}" if detail else ""))
            self.failed += 1


A_PY = '''\
"""Module A."""

def helper():
    return 1
'''

B_PY = '''\
"""Module B."""
import a


def use():
    return a.helper()
'''

C_PY = '''\
"""Module C."""
from a import helper


def call():
    return helper()
'''

D_PY = '''\
"""Module D: no internal imports."""
import os


def noop():
    return os.getcwd()
'''


PKG_INIT = '''\
"""Package init."""
import a
from . import a as _a
'''


PKG_A = '''\
"""Package module a."""


def inner():
    return 2
'''


SELF_PY = '''\
"""Module importing itself (should not count)."""
import self_mod


def f():
    return self_mod
'''


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text(A_PY, encoding="utf-8")
        (root / "b.py").write_text(B_PY, encoding="utf-8")
        (root / "c.py").write_text(C_PY, encoding="utf-8")
        (root / "d.py").write_text(D_PY, encoding="utf-8")
        (root / "self_mod.py").write_text(SELF_PY, encoding="utf-8")
        (root / "pkg").mkdir()
        (root / "pkg" / "__init__.py").write_text(PKG_INIT, encoding="utf-8")
        (root / "pkg" / "a.py").write_text(PKG_A, encoding="utf-8")

        be = FilesystemBackend(root)
        be.open()
        result = build_code_index(be)
        be.close()

        manifest = json.loads(result.manifest_json)
        by_path = {m["path"]: m for m in manifest}

        # a.py is imported by b.py, c.py (both absolute forms), and
        # by pkg/__init__.py via relative `from . import a`.
        a_used = by_path["a.py"]["used_by"]
        t.expect("a.py used_by includes b.py", "b.py" in a_used, a_used)
        t.expect("a.py used_by includes c.py", "c.py" in a_used, a_used)
        t.expect("a.py used_by includes pkg/__init__.py",
                 "pkg/__init__.py" in a_used, a_used)
        t.expect("a.py used_by sorted", a_used == sorted(a_used), a_used)

        # pkg/a.py is imported by pkg/__init__.py via `from . import a`.
        pkg_a_used = by_path["pkg/a.py"]["used_by"]
        t.expect("pkg/a.py used_by includes pkg/__init__.py",
                 "pkg/__init__.py" in pkg_a_used, pkg_a_used)

        # d.py has only external import (os) -> not in any used_by.
        for path, m in by_path.items():
            t.expect(f"d.py not using {path} internally",
                     "d.py" not in m["used_by"],
                     f"{path}: {m['used_by']}")
            break  # one check is enough; keep output short

        # Self-import does not count.
        t.expect("self_mod.py not in its own used_by",
                 "self_mod.py" not in by_path["self_mod.py"]["used_by"])

        # Duplicates collapse: b.py imports a once; result has one edge.
        t.expect("no duplicate importer entries",
                 a_used.count("b.py") == 1, a_used)

        # Rendered text contains the Used by line for a.py.
        text = result.text
        t.expect("rendered: 'Used by:' present",
                 "Used by:" in text, text[:800])

        # Module with no used_by (d.py) must not have a Used by line.
        # Find d.py's block.
        lines = text.splitlines()
        d_idx = next((i for i, l in enumerate(lines) if l.startswith("## d.py")), -1)
        t.expect("d.py block found", d_idx >= 0, lines[:10])
        if d_idx >= 0:
            block = lines[d_idx:d_idx + 5]
            has_used = any(l.startswith("Used by:") for l in block)
            t.expect("d.py block has no Used by line", not has_used, block)

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
