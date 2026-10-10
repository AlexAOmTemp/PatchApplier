"""Tests for tools.symbol_graph."""
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


# Chain: entry.run -> mid.step -> leaf.finish
SAMPLE_ENTRY = '''\
"""Entry point."""
from mid import step


def run():
    step()
    return 42
'''

SAMPLE_MID = '''\
"""Middle layer."""
from leaf import finish


def step():
    finish()
    return 1
'''

SAMPLE_LEAF = '''\
"""Leaf."""


def finish():
    return 0
'''

# Self / class example
SAMPLE_CLASSES = '''\
"""Class methods."""


class Outer:
    def method_a(self):
        self.method_b()

    def method_b(self):
        print("b")
'''


# Builtins / variable-method noise
SAMPLE_NOISE = '''\
"""Noise cases."""


def noisy(items):
    if isinstance(items, list):
        items.append(1)
    print(len(items))
    x = items.count(1)
    return x
'''


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "entry.py").write_text(SAMPLE_ENTRY, encoding="utf-8")
        (root / "mid.py").write_text(SAMPLE_MID, encoding="utf-8")
        (root / "leaf.py").write_text(SAMPLE_LEAF, encoding="utf-8")
        (root / "classes.py").write_text(SAMPLE_CLASSES, encoding="utf-8")
        (root / "noise.py").write_text(SAMPLE_NOISE, encoding="utf-8")

        backend = FilesystemBackend(root)
        backend.open()

        ci = build_code_index(backend)
        backend.write("CODE_INDEX.manifest.json", ci.manifest_json)

        fmt = Format.load("default")
        with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:
            print("== depth=1: run -> step ==")
            r = s.apply_patches([
                {"action": "symbol_graph", "arguments": {"qualname": "run"}},
            ])[0]
            t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
            t.expect("has root", "entry.py::run" in r.message)
            t.expect("has step", "step" in r.message)
            t.expect("has mid.py::step", "mid.py::step" in r.message or "mid.py" in r.message)
            t.expect("called by none", "called by (0)" in r.message)

            print()
            print("== depth=2: run -> step -> finish ==")
            r = s.apply_patches([
                {"action": "symbol_graph",
                 "arguments": {"qualname": "run", "depth": 2}},
            ])[0]
            t.expect("ok", r.status == "ok")
            t.expect("has finish", "finish" in r.message)

            print()
            print("== callers: finish called by step ==")
            r = s.apply_patches([
                {"action": "symbol_graph", "arguments": {"qualname": "finish"}},
            ])[0]
            t.expect("ok", r.status == "ok")
            t.expect("has step as caller", "step" in r.message)
            t.expect("called by (1)", "called by (1)" in r.message)

            print()
            print("== callers: step called by run ==")
            r = s.apply_patches([
                {"action": "symbol_graph", "arguments": {"qualname": "step"}},
            ])[0]
            t.expect("ok", r.status == "ok")
            t.expect("has run as caller", "run" in r.message)

            print()
            print("== self.method resolution ==")
            r = s.apply_patches([
                {"action": "symbol_graph",
                 "arguments": {"qualname": "Outer.method_a"}},
            ])[0]
            t.expect("ok", r.status == "ok")
            t.expect("method_b resolved", "method_b" in r.message)
            t.expect("not unresolved", "unresolved" not in r.message.lower()
                     or "method_b" not in r.message.split("unresolved")[-1])

            print()
            print("== builtins and variable.method filtered ==")
            r = s.apply_patches([
                {"action": "symbol_graph", "arguments": {"qualname": "noisy"}},
            ])[0]
            t.expect("ok", r.status == "ok")
            t.expect("no isinstance", "isinstance" not in r.message)
            t.expect("no print", "print" not in r.message)
            t.expect("no len", " len" not in r.message and "len(" not in r.message)
            t.expect("no items.append", "items.append" not in r.message)
            t.expect("no items.count", "items.count" not in r.message)

            print()
            print("== not found ==")
            r = s.apply_patches([
                {"action": "symbol_graph",
                 "arguments": {"qualname": "xyz_nonexistent"}},
            ])[0]
            t.expect("ok (soft)", r.status == "ok")
            t.expect("has 'не найден'", "не найден" in r.message)

            print()
            print("== empty qualname ==")
            r = s.apply_patches([
                {"action": "symbol_graph", "arguments": {"qualname": ""}},
            ])[0]
            t.expect("error", r.status == "error")
            t.expect("error_code empty_query", r.error_code == "empty_query",
                     f"{r.error_code}")

            print()
            print("== ambiguous symbol ==")
            # Two files with a symbol of the same name.
            (root / "dup1.py").write_text(
                "def duplicate():\n    pass\n", encoding="utf-8")
            (root / "dup2.py").write_text(
                "def duplicate():\n    pass\n", encoding="utf-8")
            ci2 = build_code_index(backend)
            backend.write("CODE_INDEX.manifest.json", ci2.manifest_json)

            r = s.apply_patches([
                {"action": "symbol_graph",
                 "arguments": {"qualname": "duplicate"}},
            ])[0]
            t.expect("error", r.status == "error")
            t.expect("error_code ambiguous", r.error_code == "ambiguous_symbol",
                     f"{r.error_code}")

            r = s.apply_patches([
                {"action": "symbol_graph",
                 "arguments": {"qualname": "duplicate", "occurrence": 1}},
            ])[0]
            t.expect("ok with occurrence", r.status == "ok")
            t.expect("points at dup1", "dup1.py" in r.message)

            print()
            print("== max_nodes cap ==")
            r = s.apply_patches([
                {"action": "symbol_graph",
                 "arguments": {"qualname": "run", "depth": 5,
                               "max_nodes": 1}},
            ])[0]
            t.expect("ok", r.status == "ok")
            t.expect("has cap message", "+1 more" in r.message or "more" in r.message)

    print()
    print(f"=== {t.passed} passed, {t.failed} failed ===")
    return 0 if t.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
