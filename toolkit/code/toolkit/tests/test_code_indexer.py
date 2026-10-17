"""Tests for indexers.code — build_code_index + render."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import RootDirBackend
from toolkit.indexers.code import build_code_index


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


SAMPLE_A = '''\
"""Module A."""
import os


def helper():
    """Help."""
    return 1


class Widget:
    """A widget."""
    def render(self):
        pass
'''


SAMPLE_B = '''\
def top():
    pass
'''


BROKEN = '''\
def broken(:
    pass
'''


def main():
    t = T()
    backend = RootDirBackend(TOOLKIT_ROOT)
    backend.open()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text(SAMPLE_A, encoding="utf-8")
        (root / "b.py").write_text(SAMPLE_B, encoding="utf-8")
        (root / "broken.py").write_text(BROKEN, encoding="utf-8")
        (root / "nested").mkdir()
        (root / "nested" / "c.py").write_text(SAMPLE_B, encoding="utf-8")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "fake.py").write_text(SAMPLE_B, encoding="utf-8")

        # Use a backend rooted at tmp for this test.
        tmp_backend = RootDirBackend(root)
        tmp_backend.open()

        print("== build_code_index on tmp root ==")
        result = build_code_index(tmp_backend)

        # Sample A: helper, Widget, Widget.render = 3 symbols
        # Sample B: top = 1 symbol, in both b.py and nested/c.py
        # broken.py: dropped (SyntaxError)
        # __pycache__/fake.py: skipped by skip_dirs
        # Total: 3 + 1 + 1 = 5 symbols across 3 modules
        t.expect("modules_count == 3", result.modules_count == 3,
                 f"got {result.modules_count}: {[m.path for m in result.modules]}")
        t.expect("symbols_count == 5", result.symbols_count == 5,
                 f"got {result.symbols_count}")

        paths = [m.path for m in result.modules]
        t.expect("a.py in list", "a.py" in paths, paths)
        t.expect("b.py in list", "b.py" in paths, paths)
        t.expect("nested/c.py in list", "nested/c.py" in paths, paths)
        t.expect("broken.py NOT in list", "broken.py" not in paths, paths)
        t.expect("__pycache__ skipped",
                 all("__pycache__" not in p for p in paths), paths)

        # Text rendering checks
        text = result.text
        t.expect("CODE_PREAMBLE present", "# Code Index" in text)
        t.expect("module header a.py", "## a.py" in text)
        t.expect("helper symbol listed", "helper" in text)
        t.expect("Widget symbol listed", "Widget" in text)
        t.expect("Widget.render listed (dotted)", "Widget.render" in text)
        t.expect("nested indent for render",
                 "  - Widget.render" in text, text[:600])
        t.expect("hash line present", "Hash:" in text)
        t.expect("imports line for a.py", "Imports: os" in text)

        # Manifest checks
        manifest = json.loads(result.manifest_json)
        t.expect("manifest is list", isinstance(manifest, list))
        t.expect("manifest has 3 modules", len(manifest) == 3)
        a_entry = next((m for m in manifest if m["path"] == "a.py"), None)
        t.expect("a.py in manifest", a_entry is not None)
        if a_entry:
            qualnames = [s["qualname"] for s in a_entry["symbols"]]
            t.expect("manifest has helper", "helper" in qualnames, qualnames)
            t.expect("manifest has Widget.render",
                     "Widget.render" in qualnames, qualnames)
            t.expect("manifest has imports", "os" in a_entry["imports"])
            t.expect("manifest has hash", isinstance(a_entry["hash"], int))
            t.expect("manifest has len", isinstance(a_entry["len"], int))

        tmp_backend.close()

    backend.close()

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
