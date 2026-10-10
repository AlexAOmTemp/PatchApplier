"""Tests for symbol-aware tools: list_symbols, read_symbol,
replace_function, replace_function_body."""
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


def _run(root: Path, patches: list[dict], policy: Policy | None = None):
    backend = FilesystemBackend(root)
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:
        return s.apply_patches(patches)


SEED = '''\
"""Sample module."""


def top(x: int) -> int:
    """Top doc."""
    return x + 1


class Widget:
    """A widget."""

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
        p.write_text(SEED, encoding="utf-8")

        # --- list_symbols ---
        print("== list_symbols ==")
        r = _run(root, [
            {"action": "list_symbols", "arguments": {"file_path": "sample.py"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("has top", "top" in r.message)
        t.expect("has Widget", "Widget" in r.message)
        t.expect("has Widget.render", "Widget.render" in r.message)
        t.expect("has Widget.fetch", "Widget.fetch" in r.message)
        t.expect("has outer.inner", "outer.inner" in r.message)
        t.expect("class kind shown", "[class]" in r.message)
        t.expect("async kind shown", "[async_function]" in r.message)

        # --- read_symbol ---
        print()
        print("== read_symbol: Widget.render ==")
        r = _run(root, [
            {"action": "read_symbol",
             "arguments": {"file_path": "sample.py", "qualname": "Widget.render"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("header shows qualname", "Widget.render" in r.message)
        t.expect("body has 'def render'", "def render" in r.message)
        t.expect("body has return '", "return \"w\"" in r.message)
        # Should NOT include top function or class def
        t.expect("body has no 'def top'", "def top" not in r.message)
        t.expect("body has no 'class Widget'", "class Widget" not in r.message)

        print()
        print("== read_symbol: not found ==")
        r = _run(root, [
            {"action": "read_symbol",
             "arguments": {"file_path": "sample.py", "qualname": "nope"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == not_found", r.error_code == "not_found")

        # --- replace_function ---
        print()
        print("== replace_function: top ==")
        new_top = (
            "def top(x: int) -> int:\n"
            "    \"\"\"New top.\"\"\"\n"
            "    return x * 2\n"
        )
        r = _run(root, [
            {"action": "replace_function",
             "arguments": {"file_path": "sample.py", "qualname": "top",
                           "new_code": new_top}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("delta present", r.delta is not None)
        content = p.read_text(encoding="utf-8")
        t.expect("new body present", "return x * 2" in content)
        t.expect("old body gone", "return x + 1" not in content)
        t.expect("class still intact", "class Widget" in content)

        # Verify file parses
        import ast
        ast.parse(content)
        t.expect("result parses", True)

        # --- replace_function: method ---
        print()
        print("== replace_function: Widget.render (indent handling) ==")
        new_render = (
            "def render(self) -> str:\n"
            "    return \"RENDERED\"\n"
        )
        r = _run(root, [
            {"action": "replace_function",
             "arguments": {"file_path": "sample.py", "qualname": "Widget.render",
                           "new_code": new_render}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("new render body", "RENDERED" in content)
        # Check indent: def render should be at 4 spaces
        t.expect("method def has 4-space indent", "    def render" in content,
                 content)
        t.expect("body has 8-space indent", "        return \"RENDERED\"" in content,
                 content)
        ast.parse(content)
        t.expect("result parses", True)

        # --- replace_function_body ---
        print()
        print("== replace_function_body: Widget.fetch ==")
        r = _run(root, [
            {"action": "replace_function_body",
             "arguments": {"file_path": "sample.py", "qualname": "Widget.fetch",
                           "new_body": "return b\"XYZ\""}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("async def preserved",
                 "async def fetch(self) -> bytes:" in content, content)
        t.expect("new body present", "return b\"XYZ\"" in content)
        t.expect("old body gone", "return b\"\"" not in content)
        ast.parse(content)
        t.expect("result parses", True)

        # --- replace_function_body: nested function ---
        print()
        print("== replace_function_body: outer.inner ==")
        r = _run(root, [
            {"action": "replace_function_body",
             "arguments": {"file_path": "sample.py", "qualname": "outer.inner",
                           "new_body": "return 100"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("inner body updated", "return 100" in content)

        # --- syntax error rejection ---
        print()
        print("== syntax error in new_code is rejected ==")
        before = p.read_text(encoding="utf-8")
        r = _run(root, [
            {"action": "replace_function",
             "arguments": {"file_path": "sample.py", "qualname": "top",
                           "new_code": "def top(:\n    pass"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == result_syntax_error",
                 r.error_code == "result_syntax_error", r.error_code)
        after = p.read_text(encoding="utf-8")
        t.expect("file unchanged", before == after)

        # --- empty new_code ---
        print()
        print("== empty new_code rejected ==")
        r = _run(root, [
            {"action": "replace_function",
             "arguments": {"file_path": "sample.py", "qualname": "top",
                           "new_code": ""}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == empty_input", r.error_code == "empty_input")

        # --- filter blocks ---
        print()
        print("== filter blocks replace_function ==")
        policy = Policy.uniform(mode="white", paths=["sub"])
        r = _run(root, [
            {"action": "replace_function",
             "arguments": {"file_path": "sample.py", "qualname": "top",
                           "new_code": "def top():\n    pass"}},
        ], policy)[0]
        t.expect("blocked", r.status == "blocked", f"{r.status}: {r.message}")

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
