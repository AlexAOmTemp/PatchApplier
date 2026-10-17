"""Tests for the `tree` tool: aggregates, max_dirs cap, dotdirs skip.

Note: `test_tree.py` (already present) covers the GUI tree_view module.
This file covers `toolkit/tools/tree.py` -- the LLM-facing tool.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import FilesystemBackend
from toolkit.core import Session
from toolkit.formats import Format
from toolkit.tools import TOOL_MAP


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


def _run(root: Path, patches: list[dict]):
    backend = FilesystemBackend(root)
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:
        return s.apply_patches(patches)


def _write(root: Path, rel: str, content: str = "x") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root, "a.py", "print(1)\n")
        _write(root, "b.md", "# b\n")
        _write(root, "sub/c.py", "print(2)\n")
        _write(root, "sub/d.xml", "<x/>\n")
        _write(root, "sub/deep/e.py", "print(3)\n")
        _write(root, ".hidden/h.py", "print(4)\n")
        _write(root, ".hidden/nested/k.py", "print(5)\n")

        print("== basic tree ==")
        r = _run(root, [{"action": "tree", "arguments": {"path": "."}}])[0]
        t.expect("ok", r.status == "ok", r.message)
        msg = r.message
        t.expect("header has tree:", "=== tree:" in msg)
        t.expect("shows sub", "sub  " in msg or "sub (" in msg, msg)
        t.expect("shows sub/deep", "sub/deep" in msg, msg)
        t.expect("hides .hidden", ".hidden" not in msg, msg)

        print("== types: .py before .xml ==")
        sub_line = next((ln for ln in msg.splitlines() if "sub  (" in ln), "")
        t.expect("sub line has .py", ".py" in sub_line, sub_line)
        t.expect("sub line has .xml", ".xml" in sub_line, sub_line)
        if ".py" in sub_line and ".xml" in sub_line:
            t.expect("sub: .py before .xml",
                     sub_line.index(".py") < sub_line.index(".xml"),
                     sub_line)

        print("== max_dirs=2 cap ==")
        r = _run(root, [{"action": "tree", "arguments": {
            "path": ".", "max_dirs": 2,
        }}])[0]
        t.expect("ok", r.status == "ok", r.message)
        msg = r.message
        t.expect("partial marker", "(partial)" in msg, msg)
        t.expect("frontier mentioned", "frontier_unexpanded=" in msg, msg)
        t.expect("deeper: >=", "deeper: >=" in msg, msg)

        print("== concrete subpath ==")
        r = _run(root, [{"action": "tree", "arguments": {
            "path": "sub",
        }}])[0]
        t.expect("ok", r.status == "ok", r.message)
        msg = r.message
        t.expect("header names sub", "tree: sub" in msg, msg)
        t.expect("shows sub/deep", "sub/deep" in msg, msg)

        print("== not_found ==")
        r = _run(root, [{"action": "tree", "arguments": {
            "path": "nonexistent",
        }}])[0]
        t.expect("error", r.status == "error")
        t.expect("not_found", r.error_code == "not_found", r.error_code)

        print("== empty path ==")
        r = _run(root, [{"action": "tree", "arguments": {}}])[0]
        t.expect("error", r.status == "error")
        t.expect("bad_input", r.error_code == "bad_input", r.error_code)

        print("== bad max_dirs=0 ==")
        r = _run(root, [{"action": "tree", "arguments": {
            "path": ".", "max_dirs": 0,
        }}])[0]
        t.expect("error", r.status == "error")
        t.expect("bad_options", r.error_code == "bad_options", r.error_code)

        print("== show_types=false ==")
        r = _run(root, [{"action": "tree", "arguments": {
            "path": ".", "show_types": False,
        }}])[0]
        t.expect("ok", r.status == "ok", r.message)
        msg = r.message
        rows = [ln for ln in msg.splitlines() if "(" in ln and "tree:" not in ln]
        t.expect("no type tokens in rows",
                 all(".py " not in ln for ln in rows), str(rows[:2]))

    print()
    print(f"=== {t.passed} ok, {t.failed} failed ===")
    return 0 if t.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
