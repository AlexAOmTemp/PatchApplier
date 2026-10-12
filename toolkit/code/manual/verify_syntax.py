"""Compile-only smoke check.

Usage:
  run_python(script="toolkit/code/manual/verify_syntax.py")
  run_python(script="toolkit/code/manual/verify_syntax.py",
             args=["toolkit/code/toolkit/indexers/lua_runner.py",
                   "toolkit/code/toolkit/runner/gui"])

No args  -> compiles toolkit/runner/gui/*.py (the original GUI smoke).
With args -> each arg is a file or directory. Directories are recursed
             (**/*.py). Relative paths are resolved first against cwd,
             then against the project root.

Compile only -- no imports. Safe under run_python: no Tk, no keyboard
hook, no bridge side-effects, no __main__ execution.
"""
from __future__ import annotations

import py_compile
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DIR = HERE.parent / "toolkit" / "runner" / "gui"
PROJECT_ROOT = HERE.parents[2]


def _resolve(arg: str) -> Path | None:
    p = Path(arg)
    if p.is_absolute():
        return p if p.exists() else None
    if p.exists():
        return p.resolve()
    alt = PROJECT_ROOT / p
    if alt.exists():
        return alt.resolve()
    return None


def _collect(arg: str) -> list[Path]:
    p = _resolve(arg)
    if p is None:
        print(f"not found: {arg}", file=sys.stderr)
        return []
    if p.is_dir():
        return sorted(p.rglob("*.py"))
    if p.is_file():
        return [p]
    return []


def main(argv: list[str]) -> int:
    if argv:
        targets: list[Path] = []
        for a in argv:
            targets.extend(_collect(a))
    else:
        targets = sorted(DEFAULT_DIR.glob("*.py"))
    if not targets:
        print("no targets to compile", file=sys.stderr)
        return 1
    failed: list[Path] = []
    for p in targets:
        try:
            py_compile.compile(str(p), doraise=True)
            print(f"ok  {p}")
        except py_compile.PyCompileError as e:
            failed.append(p)
            print(f"FAIL {p}\n{e}", file=sys.stderr)
    if failed:
        print(f"\n{len(failed)} of {len(targets)} file(s) failed", file=sys.stderr)
        return 1
    print(f"\nall {len(targets)} file(s) compile")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
