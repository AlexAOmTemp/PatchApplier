"""Smoke-check: does app.py (and gui/*.py) compile?

Usage: run_python(script="toolkit/code/manual/verify_app_syntax.py")

Compiles without importing — so no Tk, no keyboard hook, no GUI side-effects.
"""
from __future__ import annotations
import py_compile
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUI_DIR = HERE.parent / "toolkit" / "runner" / "gui"

def main() -> int:
    targets = sorted(GUI_DIR.glob("*.py"))
    if not targets:
        print(f"no files under {GUI_DIR}", file=sys.stderr)
        return 1
    failed = []
    for p in targets:
        try:
            py_compile.compile(str(p), doraise=True)
            print(f"ok  {p.name}")
        except py_compile.PyCompileError as e:
            failed.append(p.name)
            print(f"FAIL {p.name}\n{e}", file=sys.stderr)
    if failed:
        print(f"\n{len(failed)} file(s) failed", file=sys.stderr)
        return 1
    print(f"\nall {len(targets)} file(s) compile")
    return 0

if __name__ == "__main__":
    sys.exit(main())
