"""Tests for tools.find_symbol."""
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
from toolkit.indexers.code import build_code_index
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


SAMPLE_A = '''\
"""Module A."""


def helper(x: int) -> int:
    """Help."""
    return x + 1


class Widget:
    """A widget."""

    def render(self) -> str:
        return "w"
'''


SAMPLE_B = '''\


def standalone():
    pass
'''


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "alpha.py").write_text(SAMPLE_A, encoding="utf-8")
        (root / "beta.py").write_text(SAMPLE_B, encoding="utf-8")

        backend = FilesystemBackend(root)
        backend.open()

        ci = build_code_index(backend)
        backend.write("CODE_INDEX.manifest.json", ci.manifest_json)

        fmt = Format.load("default")
        with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:
            print("== find_symbol: 'helper' ==")
            r = s.apply_patches([
                {"action": "find_symbol", "arguments": {"query": "helper"}},
            ])[0]
            t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
            t.expect("has alpha.py", "alpha.py" in r.message)
            t.expect("has helper", "helper" in r.message)
            t.expect("has line range", "L" in r.message)

            print()
            print("== find_symbol: 'Widget.render' ==")
            r = s.apply_patches([
                {"action": "find_symbol", "arguments": {"query": "Widget.render"}},
            ])[0]
            t.expect("ok", r.status == "ok")
            t.expect("has qualname", "Widget.render" in r.message)
            t.expect("kind method shown", "[method]" in r.message)

            print()
            print("== find_symbol: by module path 'beta' ==")
            r = s.apply_patches([
                {"action": "find_symbol", "arguments": {"query": "beta"}},
            ])[0]
            t.expect("ok", r.status == "ok")
            t.expect("has beta.py", "beta.py" in r.message)
            t.expect("has standalone", "standalone" in r.message)

            print()
            print("== find_symbol: no match ==")
            r = s.apply_patches([
                {"action": "find_symbol", "arguments": {"query": "xyz_nonexistent"}},
            ])[0]
            t.expect("ok (not error)", r.status == "ok")
            t.expect("no match message",
                     "\u0421\u043e\u0432\u043f\u0430\u0434\u0435\u043d\u0438\u0439 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e" in r.message,
                     r.message[:200])

            print()
            print("== find_symbol: empty query ==")
            r = s.apply_patches([
                {"action": "find_symbol", "arguments": {"query": ""}},
            ])[0]
            t.expect("error", r.status == "error")
            t.expect("error_code == empty_query", r.error_code == "empty_query")

            print()
            print("== find_symbol: missing manifest ==")
            r = s.apply_patches([
                {"action": "find_symbol",
                 "arguments": {"query": "x", "manifest_path": "nope.json"}},
            ])[0]
            t.expect("error", r.status == "error")
            t.expect("error_code == manifest_not_found",
                     r.error_code == "manifest_not_found")

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
