"""Tests for native MCP passthrough via Patcher and MCPBackend.invoke_native."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import RootDirBackend
from toolkit.core import Session
from toolkit.core.models import Result
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


class FakeNativeBackend(RootDirBackend):
    """Filesystem backend + invoke_native for Patcher-level tests."""

    def __init__(self, root, calls=None):
        super().__init__(root)
        self.calls = calls if calls is not None else []

    def invoke_native(self, name, args):
        self.calls.append((name, dict(args)))
        if name == "do_thing":
            return Result(status="ok", message=f"[native] {name}: done",
                          action=name)
        if name == "blocked_thing":
            return Result(status="blocked", message="disabled",
                          action=name, error_code="native_tools_disabled")
        return None  # unknown


class NoNativeBackend(RootDirBackend):
    """No invoke_native at all — Patcher falls through to skipped."""


def _run_with_backend(backend, patches):
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:
        return s.apply_patches(patches)


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        print("== patcher falls through when backend has no invoke_native ==")
        b = NoNativeBackend(root)
        r = _run_with_backend(b, [
            {"action": "not_a_tool", "arguments": {}},
        ])[0]
        t.expect("skipped", r.status == "skipped", f"{r.status}: {r.message}")

        print()
        print("== patcher dispatches to invoke_native ==")
        calls = []
        b = FakeNativeBackend(root, calls)
        r = _run_with_backend(b, [
            {"action": "do_thing", "arguments": {"x": 1}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("native marker", "[native]" in r.message)
        t.expect("called once", calls == [("do_thing", {"x": 1})])

        print()
        print("== native returns blocked -> propagates ==")
        b = FakeNativeBackend(root)
        r = _run_with_backend(b, [
            {"action": "blocked_thing", "arguments": {}},
        ])[0]
        t.expect("blocked", r.status == "blocked")
        t.expect("error_code", r.error_code == "native_tools_disabled")

        print()
        print("== unknown name still skipped ==")
        b = FakeNativeBackend(root)
        r = _run_with_backend(b, [
            {"action": "totally_unknown", "arguments": {}},
        ])[0]
        t.expect("skipped", r.status == "skipped", f"{r.status}: {r.message}")

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
