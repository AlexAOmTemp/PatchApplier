"""Tests for Lua indent preservation (replace_symbol_body, insert, etc.)."""
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
    with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:
        return s.apply_patches(patches)


TAB_SEED = "local M = {}\n\nfunction M.f(x)\n\tlocal y = x + 1\n\treturn y\nend\n\nreturn M\n"
SPACE_SEED = "local M = {}\n\nfunction M.f(x)\n    local y = x + 1\n    return y\nend\n\nreturn M\n"


def _body_case(t, root, seed, label, expected_line):
    p = root / "mod.lua"
    p.write_text(seed, encoding="utf-8")
    r = _run(root, [{"action": "replace_symbol_body",
                     "arguments": {"file_path": "mod.lua",
                                   "qualname": "M.f",
                                   "new_body": "local y = x * 2\nreturn y"}}])[0]
    t.expect(f"{label}: ok", r.status == "ok", f"{r.status}: {r.message}")
    content = p.read_text(encoding="utf-8")
    t.expect(f"{label}: body indent", expected_line in content,
             repr(content))


def main():
    t = T()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        print("== replace_symbol_body: file uses tabs ==")
        _body_case(t, root, TAB_SEED, "tabs", "\tlocal y = x * 2")

        print()
        print("== replace_symbol_body: file uses 4 spaces ==")
        _body_case(t, root, SPACE_SEED, "spaces", "    local y = x * 2")

        print()
        print("== replace_symbol_body: file uses 2 spaces ==")
        two = "local M = {}\n\nfunction M.f(x)\n  local y = x + 1\n  return y\nend\n\nreturn M\n"
        _body_case(t, root, two, "2sp", "  local y = x * 2")

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
