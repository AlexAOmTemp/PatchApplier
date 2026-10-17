"""Tests for grep `paths` validation: directory entries -> bad_options."""
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


def _run(root: Path, patches: list[dict]):
    backend = FilesystemBackend(root)
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:
        return s.apply_patches(patches)


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "file.py").write_text("NEEDLE here\n", encoding="utf-8")
        (root / "sub").mkdir()
        (root / "sub" / "inner.py").write_text("NEEDLE inner\n", encoding="utf-8")

        # --- file-only paths: works as before ---
        print("== paths=[file.py]: ok ==")
        r = _run(root, [{"action": "grep", "arguments": {
            "pattern": "NEEDLE",
            "paths": ["file.py"],
            "fixed_strings": True,
        }}])[0]
        t.expect("ok", r.status == "ok", r.message)
        t.expect("match found", "NEEDLE" in r.message)

        print("== paths=[file.py, sub/inner.py]: ok ==")
        r = _run(root, [{"action": "grep", "arguments": {
            "pattern": "NEEDLE",
            "paths": ["file.py", "sub/inner.py"],
            "fixed_strings": True,
        }}])[0]
        t.expect("ok", r.status == "ok", r.message)
        t.expect("both matched",
                 "file.py" in r.message and "sub/inner.py" in r.message)

        # --- directory in paths: bad_options ---
        print("== paths=[sub]: bad_options ==")
        r = _run(root, [{"action": "grep", "arguments": {
            "pattern": "NEEDLE",
            "paths": ["sub"],
            "fixed_strings": True,
        }}])[0]
        t.expect("error", r.status == "error", r.message)
        t.expect("bad_options",
                 r.error_code == "bad_options", r.error_code)
        t.expect("message hints directory",
                 "directory" in r.message.lower(), r.message)

        # --- mixed: file + directory ---
        print("== paths=[file.py, sub]: bad_options ==")
        r = _run(root, [{"action": "grep", "arguments": {
            "pattern": "NEEDLE",
            "paths": ["file.py", "sub"],
            "fixed_strings": True,
        }}])[0]
        t.expect("error", r.status == "error", r.message)
        t.expect("bad_options",
                 r.error_code == "bad_options", r.error_code)

        # --- empty paths: directory fallback still works ---
        print("== paths=[]: directory fallback ==")
        r = _run(root, [{"action": "grep", "arguments": {
            "pattern": "NEEDLE",
            "paths": [],
            "directory": "",
            "fixed_strings": True,
        }}])[0]
        t.expect("ok", r.status == "ok", r.message)

        # --- no paths, only directory: still works ---
        print("== no paths, directory=sub: ok ==")
        r = _run(root, [{"action": "grep", "arguments": {
            "pattern": "NEEDLE",
            "directory": "sub",
            "fixed_strings": True,
        }}])[0]
        t.expect("ok", r.status == "ok", r.message)
        t.expect("inner matched", "sub/inner.py" in r.message)

    print()
    print(f"=== {t.passed} ok, {t.failed} failed ===")
    return 0 if t.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
