"""Tests for the unit model tools: read_unit, list_units, set_annotation,
replace_unit (with part / block), insert_block.

Covers Python, markdown, and Luau. Uses a temp project; exercises the
model end to end via Session.apply_patches so path policy applies as in
real use.
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


PY_SAMPLE = '''\
\"\"\"Module docstring.\"\"\"
import os

CONST = 1


def helper(x: int) -> int:
    \"\"\"Return x + 1.\"\"\"
    return x + 1


class Widget:
    \"\"\"A widget.\"\"\"

    def render(self) -> str:
        return "w"

    def fetch(self) -> int:
        a = 1
        b = 2
        return a + b
'''

MD_SAMPLE = '''\
# Index

## 1. First
<!-- summary: first section -->

Body one.

### 1.1 Sub
<!-- summary: sub -->

Sub body.

## 2. Second
<!-- summary: second section -->

Body two.
'''

LUA_SAMPLE = '''\
local M = {}

--- Adds.
function M.add(a, b)
    return a + b
end

return M
'''


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text(PY_SAMPLE, encoding="utf-8")
        (root / "doc.md").write_text(MD_SAMPLE, encoding="utf-8")
        (root / "m.lua").write_text(LUA_SAMPLE, encoding="utf-8")

        backend = FilesystemBackend(root)
        backend.open()
        fmt = Format.load("default")
        with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:

            def run(action: str, **args):
                return s.apply_patches([
                    {"action": action, "arguments": args},
                ])[0]

            # --- read_unit ---
            print("== read_unit: Python head ===")
            r = run("read_unit", file_path="a.py",
                    address={"qualname": "helper"}, part="head")
            t.expect("ok", r.status == "ok", r.message)
            t.expect("has def helper", "def helper" in r.message)
            t.expect("no body", "return x + 1" not in r.message)

            print("== read_unit: Python annotation ===")
            r = run("read_unit", file_path="a.py",
                    address={"qualname": "Widget"}, part="annotation")
            t.expect("ok", r.status == "ok")
            t.expect("docstring", "A widget" in r.message)

            print("== read_unit: block range ===")
            r = run("read_unit", file_path="a.py",
                    address={"qualname": "Widget.fetch"}, block="1-2")
            t.expect("ok", r.status == "ok")
            t.expect("block marker", "=== block 1 ===" in r.message)
            t.expect("has a=1", "a = 1" in r.message)
            t.expect("has b=2", "b = 2" in r.message)
            t.expect("no return", "return a + b" not in r.message)

            print("== read_unit: markdown section ===")
            r = run("read_unit", file_path="doc.md",
                    address={"section_number": "1"}, part="annotation")
            t.expect("ok", r.status == "ok")
            t.expect("summary", "first section" in r.message)

            print("== read_unit: Luau annotation ===")
            r = run("read_unit", file_path="m.lua",
                    address={"qualname": "M.add"}, part="annotation")
            t.expect("ok", r.status == "ok")
            t.expect("annotation", "Adds" in r.message)

            print("== read_unit: bad part ===")
            r = run("read_unit", file_path="a.py",
                    address={"qualname": "helper"}, part="nose")
            t.expect("error", r.status == "error")
            t.expect("bad_part", r.error_code == "bad_part", r.error_code)

            print("== read_unit: block out of range ===")
            r = run("read_unit", file_path="a.py",
                    address={"qualname": "helper"}, block="999")
            t.expect("error", r.status == "error")
            t.expect("block_out_of_range", r.error_code == "block_out_of_range", r.error_code)

            # --- list_units ---
            print("== list_units: Python ===")
            r = run("list_units", file_path="a.py")
            t.expect("ok", r.status == "ok")
            t.expect("has helper", "helper" in r.message)
            t.expect("has Widget.render", "Widget.render" in r.message)

            # --- set_annotation ---
            print("== set_annotation: replace Python docstring ===")
            r = run("set_annotation", file_path="a.py",
                    address={"qualname": "helper"},
                    text="NEW DOC")
            t.expect("ok", r.status == "ok", r.message)
            after = (root / "a.py").read_text(encoding="utf-8")
            t.expect("new doc in file", "NEW DOC" in after)
            t.expect("old doc gone", "Return x + 1" not in after)

            print("== set_annotation: no annotation fails ===")
            r = run("set_annotation", file_path="a.py",
                    address={"qualname": "Widget.render"},
                    text="x")
            t.expect("error", r.status == "error")
            t.expect("no_annotation", r.error_code == "no_annotation", r.error_code)

            print("== set_annotation: markdown summary ===")
            r = run("set_annotation", file_path="doc.md",
                    address={"section_number": "2"}, text="updated 2")
            t.expect("ok", r.status == "ok")
            md = (root / "doc.md").read_text(encoding="utf-8")
            t.expect("new summary", "updated 2" in md)

            # --- replace_block ---
            print("== replace_block: single ===")
            r = run("replace_unit", file_path="a.py",
                    address={"qualname": "Widget.fetch"},
                    block=3, new_text="return 42")
            t.expect("ok", r.status == "ok", r.message)
            after = (root / "a.py").read_text(encoding="utf-8")
            t.expect("new return", "return 42" in after)

            print("== replace_block: range deletes ===")
            r = run("replace_unit", file_path="a.py",
                    address={"qualname": "Widget.fetch"},
                    block="1-2", new_text="")
            t.expect("ok", r.status == "ok", r.message)
            after = (root / "a.py").read_text(encoding="utf-8")
            t.expect("a=1 gone", "a = 1" not in after)
            t.expect("b=2 gone", "b = 2" not in after)
            t.expect("return 42 kept", "return 42" in after)

            print("== replace_block: bad range ===")
            r = run("replace_unit", file_path="a.py",
                    address={"qualname": "Widget.fetch"},
                    block="1,3", new_text="x")
            t.expect("error", r.status == "error")
            t.expect("bad_block_range", r.error_code == "bad_block_range", r.error_code)

            # --- delete_block ---
            print("== delete_block ===")
            (root / "b.py").write_text(
                "def f():\n    a = 1\n    b = 2\n    return a + b\n",
                encoding="utf-8")
            r = run("replace_unit", file_path="b.py",
                    address={"qualname": "f"}, block=1, new_text="")
            t.expect("ok", r.status == "ok", r.message)
            after = (root / "b.py").read_text(encoding="utf-8")
            t.expect("a=1 gone", "a = 1" not in after)
            t.expect("b=2 kept", "b = 2" in after)

            # --- insert_block ---
            print("== insert_block: before anchor ===")
            (root / "c.py").write_text(
                "def f():\n    a = 1\n    return a\n",
                encoding="utf-8")
            r = run("insert_block", file_path="c.py",
                    address={"qualname": "f"},
                    new_text="first = True",
                    position="before", anchor=1)
            t.expect("ok", r.status == "ok", r.message)
            after = (root / "c.py").read_text(encoding="utf-8")
            t.expect("inserted", "first = True" in after)
            t.expect("order correct", after.index("first = True") < after.index("a = 1"))

            print("== insert_block: bad position ===")
            r = run("insert_block", file_path="c.py",
                    address={"qualname": "f"},
                    new_text="x", position="middle", anchor=1)
            t.expect("error", r.status == "error")
            t.expect("bad_position", r.error_code == "bad_position", r.error_code)

            print("== insert_block: anchor_required ===")
            r = run("insert_block", file_path="c.py",
                    address={"qualname": "f"},
                    new_text="x", position="before")
            t.expect("error", r.status == "error")
            t.expect("anchor_required", r.error_code == "anchor_required", r.error_code)

            # --- replace_unit ---
            print("== replace_unit: body only ===")
            (root / "d.py").write_text(
                "def f():\n    \"\"\"doc\"\"\"\n    old = 1\n",
                encoding="utf-8")
            r = run("replace_unit", file_path="d.py",
                    address={"qualname": "f"},
                    new_text="new = 2", part="body")
            t.expect("ok", r.status == "ok", r.message)
            after = (root / "d.py").read_text(encoding="utf-8")
            t.expect("new body", "new = 2" in after)
            t.expect("old gone", "old = 1" not in after)
            t.expect("docstring kept", '\"\"\"doc\"\"\"' in after)

            # --- lua: not_applicable for block ops ---
            print("== Luau: replace_block not_applicable ===")
            r = run("replace_unit", file_path="m.lua",
                    address={"qualname": "M.add"}, block=1, new_text="x")
            t.expect("error", r.status == "error")
            t.expect("not_applicable", r.error_code == "not_applicable", r.error_code)

            # --- syntax error recovery ---
            print("== replace_block: result_syntax_error ===")
            r = run("replace_unit", file_path="c.py",
                    address={"qualname": "f"}, block=1, new_text="def bad(:")
            t.expect("error", r.status == "error")
            t.expect("result_syntax_error",
                     r.error_code == "result_syntax_error", r.error_code)
            after = (root / "c.py").read_text(encoding="utf-8")
            t.expect("file unchanged", "def bad(:" not in after)

    print()
    print(f"=== {t.passed} ok, {t.failed} failed ===")
    return 0 if t.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
