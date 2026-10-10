"""Tests for copy_unit: selectors, container handling, error codes."""
from __future__ import annotations

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


MD_SRC = (
    "# Src\n\n"
    "## 1. First\n\n"
    "<!-- summary: first -->\n\n"
    "Body one.\n\n"
    "## 2. Second\n\n"
    "<!-- summary: second -->\n\n"
    "Body two.\n"
)

PY_SRC = (
    '\"\"\"Src module.\"\"\"\n'
    "\n"
    "def hello():\n"
    '    return 1\n'
    "\n"
    "\n"
    "class Widget:\n"
    "    def render(self):\n"
    '        return "w"\n'
)

LUA_SRC = (
    "-- Sample Lua module\n"
    "local M = {}\n"
    "\n"
    "function M.hello(name)\n"
    '    return "hi " .. name\n'
    "end\n"
    "\n"
    "return M\n"
)


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # --- bad_selector: not a dict ---
        print("== selector not a dict ==")
        (root / "src.md").write_text(MD_SRC, encoding="utf-8")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.md", "target_file": "dst.md",
                           "selector": "nope"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code bad_selector", r.error_code == "bad_selector")

        # --- bad_selector: two keys ---
        print()
        print("== selector with two keys ==")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.md", "target_file": "dst.md",
                           "selector": {"section_number": "1",
                                        "section_title": "First"}}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code bad_selector", r.error_code == "bad_selector")

        # --- bad_selector: zero keys ---
        print()
        print("== selector with zero keys ==")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.md", "target_file": "dst.md",
                           "selector": {}}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code bad_selector", r.error_code == "bad_selector")

        # --- wrong_selector: .md + qualname ---
        print()
        print("== .md + qualname ==")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.md", "target_file": "dst.md",
                           "selector": {"qualname": "Foo.bar"}}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code wrong_selector", r.error_code == "wrong_selector")

        # --- wrong_selector: .py + section_number ---
        print()
        print("== .py + section_number ==")
        (root / "src.py").write_text(PY_SRC, encoding="utf-8")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.py", "target_file": "dst.py",
                           "selector": {"section_number": "1"}}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code wrong_selector", r.error_code == "wrong_selector")

        # --- unknown_unit: bad extension ---
        print()
        print("== .xyz source ==")
        (root / "src.xyz").write_text("whatever", encoding="utf-8")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.xyz", "target_file": "dst.xyz",
                           "selector": {"qualname": "foo"}}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code unknown_unit", r.error_code == "unknown_unit")

        # --- source_not_found ---
        print()
        print("== missing source ==")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "nope.md", "target_file": "dst.md",
                           "selector": {"section_number": "1"}}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code source_not_found", r.error_code == "source_not_found")

        # --- destination_exists: source == target ---
        print()
        print("== source == target ==")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.md", "target_file": "src.md",
                           "selector": {"section_number": "1"}}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code destination_exists", r.error_code == "destination_exists")

        # --- container on .md -> container_not_supported ---
        print()
        print("== .md + container ==")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.md", "target_file": "dst.md",
                           "selector": {"section_number": "1"},
                           "container": "Widget"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code container_not_supported",
                 r.error_code == "container_not_supported",
                 f"got {r.error_code!r}: {r.message}")

        # --- container on .lua -> container_not_supported (new fix) ---
        print()
        print("== .lua + container ==")
        (root / "src.lua").write_text(LUA_SRC, encoding="utf-8")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.lua", "target_file": "dst.lua",
                           "selector": {"qualname": "M.hello"},
                           "container": "Foo"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code container_not_supported",
                 r.error_code == "container_not_supported",
                 f"got {r.error_code!r}: {r.message}")

        # --- .lua without container -> ok ---
        print()
        print("== .lua without container ==")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.lua", "target_file": "dst.lua",
                           "selector": {"qualname": "M.hello"},
                           "position": "end"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.error_code} {r.message}")
        if r.status == "ok":
            tgt = (root / "dst.lua").read_text(encoding="utf-8")
            t.expect("hello copied", "function M.hello" in tgt, tgt)

        # --- .py without container -> ok ---
        print()
        print("== .py without container ==")
        (root / "dst.py").write_text('\"\"\"Target.\"\"\"\n', encoding="utf-8")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.py", "target_file": "dst.py",
                           "selector": {"qualname": "hello"},
                           "position": "end"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.error_code} {r.message}")
        if r.status == "ok":
            tgt = (root / "dst.py").read_text(encoding="utf-8")
            t.expect("hello copied", "def hello" in tgt, tgt)

        # --- .py + container (Widget exists in target) -> ok ---
        print()
        print("== .py + container ==")
        (root / "dst.py").write_text(
            '\"\"\"Target.\"\"\"\n\n\nclass Widget:\n    pass\n',
            encoding="utf-8",
        )
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.py", "target_file": "dst.py",
                           "selector": {"qualname": "hello"},
                           "container": "Widget", "position": "end"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.error_code} {r.message}")
        if r.status == "ok":
            tgt = (root / "dst.py").read_text(encoding="utf-8")
            t.expect("hello inside Widget",
                     "    def hello" in tgt, tgt)

        # --- .py duplicate in container: Widget.hello already exists ---
        print()
        print("== .py duplicate in container ==")
        (root / "src.py").write_text(PY_SRC, encoding="utf-8")
        (root / "dst.py").write_text(
            '\"\"\"Target.\"\"\"\n\n\nclass Widget:\n'
            "    def hello(self):\n"
            "        return 0\n",
            encoding="utf-8",
        )
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.py", "target_file": "dst.py",
                           "selector": {"qualname": "hello"},
                           "container": "Widget", "position": "end"}},
        ])[0]
        t.expect("error", r.status == "error",
                 f"{r.status}: {r.error_code} {r.message}")
        t.expect("error_code destination_exists",
                 r.error_code == "destination_exists",
                 f"got {r.error_code!r}: {r.message}")

        # --- .md happy path (regression) ---
        print()
        print("== .md happy path ==")
        (root / "dst.md").write_text("# Dst\n", encoding="utf-8")
        r = _run(root, [
            {"action": "copy_unit",
             "arguments": {"source_file": "src.md", "target_file": "dst.md",
                           "selector": {"section_number": "1"},
                           "position": "end"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.error_code} {r.message}")
        if r.status == "ok":
            tgt = (root / "dst.md").read_text(encoding="utf-8")
            t.expect("section 1 copied", "## 1. First" in tgt, tgt)

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
