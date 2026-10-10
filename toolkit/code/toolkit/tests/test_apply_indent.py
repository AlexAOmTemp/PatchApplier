"""Tests for _apply_indent normalization: idempotency, literals, blanks."""
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
from toolkit.tools.symbols._ast import _apply_indent


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


def _check_apply_indent(t):
    print("== _apply_indent: basic ==")
    out = _apply_indent("def f():\n    return 1", "    ")
    t.expect("no trailing blank", len(out) == 2, repr(out))
    t.expect("indent applied", out[0].startswith("    def"), repr(out))
    t.expect("nested kept relative", out[1] == "        return 1", repr(out))

    print()
    print("== _apply_indent: trailing newline does not become phantom ==")
    out_a = _apply_indent("def f():\n    return 1", "  ")
    out_b = _apply_indent("def f():\n    return 1\n", "  ")
    t.expect("same length", len(out_a) == len(out_b), f"{out_a} vs {out_b}")
    t.expect("same content", out_a == out_b)

    print()
    print("== _apply_indent: idempotent w.r.t. caller-supplied indent ==")
    body_flat = "def f():\n    return 1\n"
    body_indented = "    def f():\n        return 1\n"
    a = _apply_indent(body_flat, "  ")
    b = _apply_indent(body_indented, "  ")
    t.expect("identical results", a == b, f"{a} vs {b}")

    print()
    print("== _apply_indent: multiline string literal NOT corrupted ==")
    # Here the common indent is 0 (def at col 0), so dedent leaves everything
    # alone; the nested literal content with 8 spaces is preserved.
    code = (
        "def f():\n"
        '    s = """\n'
        "        <div>\n"
        '    """\n'
        "    return s"
    )
    out = _apply_indent(code, "    ")
    t.expect("literal preserved", any('        <div>' in ln for ln in out), repr(out))

    print()
    print("== _apply_indent: fully-indented block (all lines share indent) ==")
    # Common indent is 4, so dedent strips 4 from every line, then re-adds 4.
    # Net effect: unchanged, and internal relative indent preserved.
    code = (
        "    def f():\n"
        "        s = \"\"\"\n"
        "            <div>\n"
        "        \"\"\"\n"
        "        return s"
    )
    out = _apply_indent(code, "    ")
    t.expect("def at 4", out[0] == "    def f():", repr(out))
    t.expect("return at 8", out[4] == "        return s", repr(out))
    t.expect("literal content kept", any("            <div>" in ln for ln in out), repr(out))


def _check_tool_roundtrip(t, root):
    p = root / "m.py"

    print()
    print("== insert_symbol: flat vs pre-indented new_code are equivalent ==")
    seed = "class W:\n    pass\n"

    p.write_text(seed, encoding="utf-8")
    r = _run(root, [{"action": "insert_symbol",
                     "arguments": {"file_path": "m.py",
                                   "new_code": "def reset(self):\n    self.x = 0\n",
                                   "container": "W", "position": "end"}}])[0]
    t.expect("flat: ok", r.status == "ok", f"{r.status}: {r.message}")
    flat_result = p.read_text(encoding="utf-8")

    p.write_text(seed, encoding="utf-8")
    r = _run(root, [{"action": "insert_symbol",
                     "arguments": {"file_path": "m.py",
                                   "new_code": "    def reset(self):\n        self.x = 0\n",
                                   "container": "W", "position": "end"}}])[0]
    t.expect("indented: ok", r.status == "ok", f"{r.status}: {r.message}")
    indented_result = p.read_text(encoding="utf-8")

    t.expect("results identical", flat_result == indented_result,
             f"flat:\n{flat_result}\nindented:\n{indented_result}")

    print()
    print("== insert_symbol: no doubled blank after body ==")
    # Body ends with single \n; output must not have a doubled blank before
    # the next statement.
    t.expect("no double blank", "\n\n\n" not in flat_result, repr(flat_result))


def main():
    t = T()
    _check_apply_indent(t)
    with tempfile.TemporaryDirectory() as td:
        _check_tool_roundtrip(t, Path(td))

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
