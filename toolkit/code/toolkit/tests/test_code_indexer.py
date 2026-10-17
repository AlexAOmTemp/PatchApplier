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

    # --- incremental: reuse unchanged, re-parse the changed one ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'a.py').write_text('def helper():\n    return 1\n', encoding='utf-8')
        (root / 'b.py').write_text(
            'from a import helper\n\ndef use():\n    return helper()\n',
            encoding='utf-8')

        b = RootDirBackend(root)
        r1 = build_code_index(b)
        b.close()
        t.expect('incr: cold build', r1.modules_count == 2, r1.modules_count)

        prev = json.loads(r1.manifest_json)
        t.expect('incr: manifest stores raw_calls',
                 any(e.get('raw_calls') for e in prev),
                 [len(e.get('raw_calls') or []) for e in prev])
        t.expect('incr: manifest stores import_bindings',
                 any(e.get('import_bindings') for e in prev),
                 [len(e.get('import_bindings') or []) for e in prev])
        t.expect('incr: manifest stores imported_modules',
                 any(e.get('imported_modules') for e in prev),
                 [e.get('imported_modules') for e in prev])

        # No-op: identical output and manifest
        b = RootDirBackend(root)
        r2 = build_code_index(b, prev_manifest=prev)
        b.close()
        t.expect('incr: no-op text identical', r2.text == r1.text)
        t.expect('incr: no-op manifest identical',
                 r2.manifest_json == r1.manifest_json)

        # Change a.py only; drop its cache entry
        (root / 'a.py').write_text(
            'def helper():\n    return 1\n\ndef extra():\n    return 2\n',
            encoding='utf-8')
        prev2 = [e for e in prev if e['path'] != 'a.py']
        b = RootDirBackend(root)
        r3 = build_code_index(b, prev_manifest=prev2)
        b.close()
        t.expect('incr: changed file re-parsed',
                 'extra' in r3.text, r3.text[:200])
        t.expect('incr: unchanged file still cached',
                 any(e['path'] == 'b.py' for e in json.loads(r3.manifest_json)))
        # The import graph edge from b -> a must survive even though a was
        # re-parsed and b came from cache.
        t.expect('incr: used_by edge survives',
                 'b.py' in r3.text, r3.text[:400])

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
