"""Tests for find_usages tool."""
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
from toolkit.tools.find_usages import FindUsagesTool


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


MANIFEST = [
    {
        "path": "toolkit/core/paths.py",
        "hash": 1, "len": 100,
        "imports": [],
        "used_by": ["toolkit/core/router.py", "toolkit/backends/composite.py"],
        "symbols": [],
    },
    {
        "path": "toolkit/core/router.py",
        "hash": 2, "len": 200,
        "imports": [".paths.is_mcp_path", ".models.Result"],
        "used_by": ["toolkit/runner/gui.py"],
        "symbols": [],
    },
    {
        "path": "toolkit/runner/gui.py",
        "hash": 3, "len": 300,
        "imports": ["..core.router.plan_rebuilds"],
        "used_by": [],
        "symbols": [],
    },
]


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "CODE_INDEX.manifest.json").write_text(
            json.dumps(MANIFEST, indent=2), encoding="utf-8")
        be = RootDirBackend(root)
        be.open()

        print("== exact path match ==")
        r = FindUsagesTool().execute(backend=be, fmt=None,
                                     query="toolkit/core/paths.py")
        t.expect("ok", r.status == "ok", r.status)
        t.expect("finds paths.py", "toolkit/core/paths.py" in r.message, r.message)
        t.expect("shows used by", "used by:" in r.message, r.message)
        t.expect("used by router", "toolkit/core/router.py" in r.message, r.message)
        t.expect("used by composite",
                 "toolkit/backends/composite.py" in r.message, r.message)
        t.expect("imports none", "imports:  (none)" in r.message, r.message)

        print()
        print("== substring match ==")
        r = FindUsagesTool().execute(backend=be, fmt=None, query="router")
        t.expect("ok", r.status == "ok", r.status)
        t.expect("finds router", "toolkit/core/router.py" in r.message, r.message)
        t.expect("shows imports", "imports:" in r.message, r.message)
        t.expect("shows is_mcp_path import",
                 ".paths.is_mcp_path" in r.message, r.message)

        print()
        print("== module with no used_by ==")
        r = FindUsagesTool().execute(backend=be, fmt=None, query="gui")
        t.expect("ok", r.status == "ok", r.status)
        t.expect("used by none", "used by:  (none)" in r.message, r.message)

        print()
        print("== no match ==")
        r = FindUsagesTool().execute(backend=be, fmt=None, query="nonexistent")
        t.expect("ok (no match)", r.status == "ok", r.status)
        t.expect("no match message", "Модулей не найдено" in r.message, r.message)

        print()
        print("== empty query ==")
        r = FindUsagesTool().execute(backend=be, fmt=None, query="")
        t.expect("error", r.status == "error", r.status)
        t.expect("error_code empty_query",
                 r.error_code == "empty_query", r.error_code)

        print()
        print("== missing manifest ==")
        r = FindUsagesTool().execute(backend=be, fmt=None, query="x",
                                     manifest_path="nope.json")
        t.expect("error", r.status == "error", r.status)
        t.expect("error_code manifest_not_found",
                 r.error_code == "manifest_not_found", r.error_code)

        be.close()

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
