"""Tests for create_file, overwrite_file, delete_file, move_file."""
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
    with Session(backend, fmt=fmt, tools=TOOL_MAP, policy=policy or Policy()) as s:
        return s.apply_patches(patches)


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # --- create_file ---
        print("== create_file ==")
        r = _run(root, [
            {"action": "create_file",
             "arguments": {"file_path": "new.md", "file_content": "# New\n\nbody\n"}},
        ])[0]
        t.expect("create ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("file on disk", (root / "new.md").is_file())

        print()
        print("== create_file: already exists ==")
        r = _run(root, [
            {"action": "create_file",
             "arguments": {"file_path": "new.md", "file_content": "x"}},
        ])[0]
        t.expect("error on existing", r.status == "error")
        t.expect("error_code == already_exists", r.error_code == "already_exists")

        # --- overwrite_file ---
        print()
        print("== overwrite_file ==")
        r = _run(root, [
            {"action": "overwrite_file",
             "arguments": {"file_path": "new.md", "file_content": "# Replaced\n\nnew body\n"}},
        ])[0]
        t.expect("overwrite ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("content replaced", "Replaced" in (root / "new.md").read_text(encoding="utf-8"))

        # --- move_file ---
        print()
        print("== move_file ==")
        (root / "sub").mkdir()
        r = _run(root, [
            {"action": "move_file",
             "arguments": {"source_path": "new.md", "destination_path": "sub/moved.md"}},
        ])[0]
        t.expect("move ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("source gone", not (root / "new.md").exists())
        t.expect("destination exists", (root / "sub" / "moved.md").is_file())
        t.expect("content preserved", "Replaced" in (root / "sub" / "moved.md").read_text(encoding="utf-8"))

        print()
        print("== move_file: source missing ==")
        r = _run(root, [
            {"action": "move_file",
             "arguments": {"source_path": "nope.md", "destination_path": "x.md"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == source_not_found", r.error_code == "source_not_found")

        print()
        print("== move_file: destination exists ==")
        r = _run(root, [
            {"action": "move_file",
             "arguments": {"source_path": "sub/moved.md", "destination_path": "sub/moved.md"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == destination_exists", r.error_code == "destination_exists")

        # --- delete_file ---
        print()
        print("== delete_file ==")
        r = _run(root, [
            {"action": "delete_file",
             "arguments": {"file_path": "sub/moved.md"}},
        ])[0]
        t.expect("delete ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("file gone", not (root / "sub" / "moved.md").exists())

        print()
        print("== delete_file: missing ==")
        r = _run(root, [
            {"action": "delete_file",
             "arguments": {"file_path": "sub/moved.md"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == not_found", r.error_code == "not_found")

        # --- move blocked by filter ---
        print()
        print("== move_file blocked by write filter ==")
        (root / "sandbox").mkdir()
        (root / "sandbox" / "x.md").write_text("# X\n", encoding="utf-8")
        policy = Policy.uniform(mode="white", paths=["sub"])
        r = _run(root, [
            {"action": "move_file",
             "arguments": {"source_path": "sandbox/x.md", "destination_path": "sub/x.md"}},
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
