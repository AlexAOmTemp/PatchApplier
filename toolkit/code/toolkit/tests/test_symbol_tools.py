"""Tests for new symbol tools: signature, delete, insert, vars, occurrence."""
from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import FilesystemBackend
from toolkit.core import Policy, Session
from toolkit.formats import Format
from toolkit.tools import TOOL_MAP


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


def _run(root, patches):
    backend = FilesystemBackend(root)
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP, policy=Policy()) as s:
        return s.apply_patches(patches)


SEED = '''\
"""Module doc."""

import os
from pathlib import Path

HOTKEY = "ctrl"
MAX_LEN: int = 100
counter = 0


def top(x: int) -> int:
    """Top doc."""
    return x + 1


def top(x: int) -> int:
    """Duplicate name."""
    return x - 1


class Widget:
    """A widget."""

    WIDTH = 10

    def render(self) -> str:
        return "w"

    async def fetch(self) -> bytes:
        return b""


def outer():
    def inner():
        return 42
    return inner
'''


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / "sample.py"

        # --- list_symbols include_vars ---
        print("== list_symbols include_vars=True ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, [
            {"action": "list_symbols",
             "arguments": {"file_path": "sample.py", "include_vars": True}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("HOTKEY as const", "HOTKEY [const]" in r.message, r.message)
        t.expect("MAX_LEN as const", "MAX_LEN [const]" in r.message)
        t.expect("counter as var", "counter [var]" in r.message)
        t.expect("Widget.WIDTH as const", "Widget.WIDTH [const]" in r.message)

        # --- list_symbols default (no vars) ---
        print()
        print("== list_symbols default (no vars) ==")
        r = _run(root, [
            {"action": "list_symbols",
             "arguments": {"file_path": "sample.py"}},
        ])[0]
        t.expect("ok", r.status == "ok")
        t.expect("no HOTKEY without flag", "HOTKEY" not in r.message)
        t.expect("has top", "top [function]" in r.message)
        t.expect("has Widget", "Widget [class]" in r.message)

        # --- read_symbol <module> ---
        print()
        print("== read_symbol <module> ==")
        r = _run(root, [
            {"action": "read_symbol",
             "arguments": {"file_path": "sample.py", "qualname": "<module>"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("has module docstring", "Module doc." in r.message)
        t.expect("has import os", "import os" in r.message)
        t.expect("has HOTKEY", "HOTKEY" in r.message)
        t.expect("stops before def top", "def top" not in r.message)

        # --- read_symbol occurrence ---
        print()
        print("== read_symbol occurrence ==")
        r = _run(root, [
            {"action": "read_symbol",
             "arguments": {"file_path": "sample.py", "qualname": "top"}},
        ])[0]
        t.expect("ambiguous error", r.status == "error")
        t.expect("error_code ambiguous_symbol", r.error_code == "ambiguous_symbol")

        r = _run(root, [
            {"action": "read_symbol",
             "arguments": {"file_path": "sample.py", "qualname": "top",
                           "occurrence": 2}},
        ])[0]
        t.expect("second occurrence ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("has Duplicate name", "Duplicate name" in r.message)

        # --- replace_symbol_signature ---
        print()
        print("== replace_symbol_signature: top (occurrence=1) ==")
        r = _run(root, [
            {"action": "replace_symbol_signature",
             "arguments": {"file_path": "sample.py", "qualname": "top",
                           "new_signature": "def top(x: int, y: int = 0) -> int:",
                           "occurrence": 1}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("new sig present", "def top(x: int, y: int = 0) -> int:" in content)
        t.expect("old body preserved", "return x + 1" in content)
        t.expect("second top intact", "return x - 1" in content)
        ast.parse(content)
        t.expect("result parses", True)

        # --- replace_symbol_signature for class ---
        print()
        print("== replace_symbol_signature: Widget ==")
        r = _run(root, [
            {"action": "replace_symbol_signature",
             "arguments": {"file_path": "sample.py", "qualname": "Widget",
                           "new_signature": "class Widget(Base):"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("new class sig", "class Widget(Base):" in content)
        t.expect("methods intact", "def render" in content)

        # --- replace_symbol_signature rejects var ---
        print()
        print("== replace_symbol_signature on var ==")
        r = _run(root, [
            {"action": "replace_symbol_signature",
             "arguments": {"file_path": "sample.py", "qualname": "HOTKEY",
                           "new_signature": "HOTKEY: str = 'x'"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code no_signature", r.error_code == "no_signature")

        # --- delete_symbol ---
        print()
        print("== delete_symbol: counter ==")
        r = _run(root, [
            {"action": "delete_symbol",
             "arguments": {"file_path": "sample.py", "qualname": "counter"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("counter removed", "counter" not in content)
        ast.parse(content)
        t.expect("result parses", True)

        # --- insert_symbol: module end ---
        print()
        print("== insert_symbol: end of module ==")
        r = _run(root, [
            {"action": "insert_symbol",
             "arguments": {"file_path": "sample.py",
                           "new_code": "def tail() -> None:\n    pass\n",
                           "position": "end"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("tail added", "def tail() -> None:" in content)
        ast.parse(content)
        t.expect("result parses", True)

        # --- insert_symbol: inside class ---
        print()
        print("== insert_symbol: end of Widget ==")
        r = _run(root, [
            {"action": "insert_symbol",
             "arguments": {"file_path": "sample.py",
                           "new_code": "def reset(self) -> None:\n    self.x = 0\n",
                           "container": "Widget",
                           "position": "end"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("reset added with indent", "    def reset(self) -> None:" in content)
        t.expect("reset body indented", "        self.x = 0" in content)
        ast.parse(content)
        t.expect("result parses", True)

        # --- insert_symbol: before anchor ---
        print()
        print("== insert_symbol: before Widget ==")
        r = _run(root, [
            {"action": "insert_symbol",
             "arguments": {"file_path": "sample.py",
                           "new_code": "def before_widget() -> None:\n    pass\n",
                           "position": "before",
                           "anchor": "Widget"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        idx_new = content.index("def before_widget")
        idx_widget = content.index("class Widget")
        t.expect("before_widget appears first", idx_new < idx_widget)
        ast.parse(content)
        t.expect("result parses", True)

        # --- insert_symbol: bad position ---
        print()
        print("== insert_symbol: bad position ==")
        r = _run(root, [
            {"action": "insert_symbol",
             "arguments": {"file_path": "sample.py",
                           "new_code": "def nope():\n    pass\n",
                           "position": "middle"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code bad_position", r.error_code == "bad_position")

        # --- insert_symbol: before without anchor ---
        print()
        print("== insert_symbol: before without anchor ==")
        r = _run(root, [
            {"action": "insert_symbol",
             "arguments": {"file_path": "sample.py",
                           "new_code": "def nope():\n    pass\n",
                           "position": "before"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code anchor_required", r.error_code == "anchor_required")

        # --- move_symbol: reorder within a file ---
        print()
        print("== move_symbol: top → end of module ==")
        p.write_text(SEED, encoding="utf-8")
        before = p.read_text(encoding="utf-8")
        r = _run(root, [
            {"action": "move_symbol",
             "arguments": {"file_path": "sample.py", "qualname": "top",
                           "occurrence": 1, "position": "end"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        ast.parse(content)
        t.expect("result parses", True)
        # Occurrence=1 is the one with "Top doc."; it moves to the end.
        idx_moved = content.index('"""Top doc."""')
        idx_widget = content.index("class Widget")
        t.expect("moved top now after Widget", idx_moved > idx_widget, content)
        # The other top ("Duplicate name.") stays before Widget.
        idx_other = content.index('"""Duplicate name."""')
        t.expect("other top still before Widget", idx_other < idx_widget)

        # --- move_symbol: move a function into a class ---
        print()
        print("== move_symbol: outer → Widget.end ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, [
            {"action": "move_symbol",
             "arguments": {"file_path": "sample.py", "qualname": "outer",
                           "container": "Widget", "position": "end"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        ast.parse(content)
        t.expect("result parses", True)
        t.expect("outer now indented as method",
                 "    def outer():" in content, content)

        # --- move_symbol: cross-file ---
        print()
        print("== move_symbol: outer → other.py ==")
        p.write_text(SEED, encoding="utf-8")
        (root / "other.py").write_text('"""Target."""\n', encoding="utf-8")
        r = _run(root, [
            {"action": "move_symbol",
             "arguments": {"file_path": "sample.py", "qualname": "outer",
                           "target_file": "other.py", "position": "end"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        src_content = p.read_text(encoding="utf-8")
        tgt_content = (root / "other.py").read_text(encoding="utf-8")
        ast.parse(src_content)
        ast.parse(tgt_content)
        t.expect("both parse", True)
        t.expect("outer gone from source", "def outer" not in src_content)
        t.expect("outer present in target", "def outer" in tgt_content)
        t.expect("nested inner preserved",
                 "def inner" in tgt_content)

        # --- move_symbol: bad position ---
        print()
        print("== move_symbol: bad position ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, [
            {"action": "move_symbol",
             "arguments": {"file_path": "sample.py", "qualname": "top",
                           "position": "middle"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code bad_position", r.error_code == "bad_position")

        # --- move_symbol: target missing ---
        print()
        print("== move_symbol: target missing ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, [
            {"action": "move_symbol",
             "arguments": {"file_path": "sample.py", "qualname": "outer",
                           "target_file": "nope.py"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code target_not_found", r.error_code == "target_not_found")

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
