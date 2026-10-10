"""Smoke test for FilesystemBackend + core imports."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))


PASS = "[OK]  "
FAIL = "[FAIL]"


def check(label, fn):
    """Expect a normal return."""
    try:
        result = fn()
        print(f"{PASS} {label}: {result!r}")
        return True
    except Exception as e:
        print(f"{FAIL} {label}: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


def check_raises(label, fn, exc_type):
    """Expect a specific exception. Success if it's raised."""
    try:
        fn()
    except exc_type as e:
        print(f"{PASS} {label}: {type(e).__name__}: {e}")
        return True
    except Exception as e:
        print(f"{FAIL} {label}: wrong exception {type(e).__name__}: {e}")
        traceback.print_exc()
        return False
    print(f"{FAIL} {label}: no exception raised (expected {exc_type.__name__})")
    return False


def main():
    print(f"Toolkit root: {TOOLKIT_ROOT}")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python: {sys.version.split()[0]}")
    print()

    failures = 0

    print("== Imports ==")
    try:
        from toolkit.core import (
            Section, Delta, Result, FilterSpec, FileStat, Backend, Tool,
            Patcher, Session,
        )
        from toolkit.backends import FilesystemBackend
        print(f"{PASS} toolkit.core + toolkit.backends imported")
    except Exception as e:
        print(f"{FAIL} import failed: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1
    print()

    print("== Backend lifecycle ==")
    backend = FilesystemBackend(TOOLKIT_ROOT)
    if not check("open()", lambda: (backend.open(), "ok")[1]):
        failures += 1
    if not check("is_alive()", lambda: backend.is_alive()):
        failures += 1
    print()

    print("== Data operations ==")
    if not check("list *.md", lambda: backend.list("tests/fixtures", "*.md")):
        failures += 1
    if not check("read simple.md", lambda: backend.read("tests/fixtures/simple.md")[:40]):
        failures += 1
    if not check(
        "stat simple.md",
        lambda: (lambda s: f"size={s.size_bytes} lines={s.lines} file={s.is_file}")(
            backend.stat("tests/fixtures/simple.md")
        ),
    ):
        failures += 1
    if not check("exists simple.md", lambda: backend.exists("tests/fixtures/simple.md")):
        failures += 1
    print()

    print("== Filter checks (new overrides model) ==")
    spec_white_tests = FilterSpec.from_legacy("white", ["tests"])
    spec_white_core = FilterSpec.from_legacy("white", ["core"])
    spec_black_tests = FilterSpec.from_legacy("black", ["tests"])
    spec_none = FilterSpec()

    check("white[tests] on tests/... (expect None)",
          lambda: backend.filter_check("tests/fixtures/simple.md", spec_white_tests))
    check("white[tests] on core/... (expect rejection)",
          lambda: backend.filter_check("core/models.py", spec_white_tests))
    check("white[core] on core/... (expect None)",
          lambda: backend.filter_check("core/models.py", spec_white_core))
    check("black[tests] on tests/... (expect rejection)",
          lambda: backend.filter_check("tests/fixtures/simple.md", spec_black_tests))
    check("none on any path (expect None)",
          lambda: backend.filter_check("core/models.py", spec_none))
    print()

    print("== Sandbox check ==")
    if not check_raises(
        "sandbox rejection: ../../etc/passwd",
        lambda: backend.read("../../etc/passwd"),
        PermissionError,
    ):
        failures += 1
    print()

    backend.close()
    check("is_alive() after close", lambda: backend.is_alive())

    print()
    if failures:
        print(f"=== \u0418\u0422\u041e\u0413: {failures} failure(s) ===")
        return 1
    print("=== \u0418\u0422\u041e\u0413: ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
