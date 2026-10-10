"""Tests for read-tools (file_stat, list_files, grep) and write-tools
(replace_in_file, replace_range). Uses a temp sandbox inside tests/ to avoid
mutating real fixtures.
"""
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


def _run_patches(backend_root: Path, patches: list[dict], filter_paths: list[str] | None = None):
    backend = FilesystemBackend(backend_root)
    policy = Policy.uniform(mode="white", paths=filter_paths) if filter_paths else Policy()
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP, policy=policy) as s:
        return s.apply_patches(patches)


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.md").write_text(
            "# Doc A\n\n## 1. One\n\n<!-- summary: s1 -->\n\nAAA\nBBB\nCCC\n\n"
            "## 2. Two\n\n<!-- summary: s2 -->\n\nDDD\n",
            encoding="utf-8",
        )
        (root / "b.md").write_text(
            "# Doc B\n\n## 1. Alpha\n\nAAA one\nAAA two\n\n## 2. Beta\n\nBBB\n",
            encoding="utf-8",
        )

        # --- file_stat ---
        print("== file_stat ==")
        r = _run_patches(root, [
            {"action": "file_stat", "arguments": {"file_path": "a.md"}},
        ])[0]
        t.expect("file_stat ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("file_stat has size", "KB" in r.message, r.message[:80])
        t.expect("file_stat lists sections", "Секции (2)" in r.message, r.message[:200])
        t.expect("file_stat shows §1 title", "One" in r.message)

        # --- list_files ---
        print()
        print("== list_files ==")
        r = _run_patches(root, [
            {"action": "list_files", "arguments": {"directory": "", "glob": "*.md"}},
        ])[0]
        t.expect("list_files ok", r.status == "ok", r.status)
        t.expect("list shows a.md", "a.md" in r.message)
        t.expect("list shows b.md", "b.md" in r.message)

        # --- grep (plain) ---
        print()
        print("== grep (plain) ==")
        r = _run_patches(root, [
            {"action": "grep", "arguments": {
                "pattern": "AAA", "directory": "", "file_glob": "*.md"}},
        ])[0]
        t.expect("grep ok", r.status == "ok", r.status)
        t.expect("grep finds a.md hit", "a.md" in r.message)
        t.expect("grep finds b.md hits", "b.md" in r.message)

        # --- grep (regex, context) ---
        print()
        print("== grep (regex, before/after) ==")
        r = _run_patches(root, [
            {"action": "grep", "arguments": {
                "pattern": "^BBB", "regex": True,
                "directory": "", "file_glob": "*.md",
                "before": 1, "after": 1}},
        ])[0]
        t.expect("grep regex ok", r.status == "ok", r.status)
        t.expect("grep shows context lines", "--" in r.message, r.message[:200])
        t.expect("grep marks hit with >", ">" in r.message)

        # --- replace_in_file (occurrence=1) ---
        print()
        print("== replace_in_file #1 ==")
        r = _run_patches(root, [
            {"action": "replace_in_file", "arguments": {
                "file_path": "b.md", "search": "AAA", "replace": "XXXYYY",
                "occurrence": 1}},
        ])[0]
        t.expect("replace #1 ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("delta.occurrences == 1", r.delta.occurrences == 1)
        t.expect("delta.bytes == +3", r.delta.bytes == 3, f"got {r.delta.bytes}")
        t.expect("delta.lines == 0", r.delta.lines == 0, f"got {r.delta.lines}")
        content = (root / "b.md").read_text(encoding="utf-8")
        t.expect("first AAA changed", content.count("XXXYYY") == 1)
        t.expect("second AAA preserved", content.count("AAA") == 1)

        # --- replace_in_file (all) ---
        print()
        print("== replace_in_file all ==")
        r = _run_patches(root, [
            {"action": "replace_in_file", "arguments": {
                "file_path": "b.md", "search": "AAA", "replace": "ZZZ",
                "occurrence": "all"}},
        ])[0]
        t.expect("replace all ok", r.status == "ok")
        t.expect("delta.occurrences == 1", r.delta.occurrences == 1,
                 f"got {r.delta.occurrences}")
        content = (root / "b.md").read_text(encoding="utf-8")
        t.expect("no AAA left", "AAA" not in content)
        t.expect("one ZZZ replaced remaining AAA", content.count("ZZZ") == 1,
                 f"got {content.count('ZZZ')} ZZZ")

        # --- replace_in_file not found ---
        print()
        print("== replace_in_file not found ==")
        r = _run_patches(root, [
            {"action": "replace_in_file", "arguments": {
                "file_path": "b.md", "search": "NOPE", "replace": "x"}},
        ])[0]
        t.expect("not-found is error", r.status == "error")
        t.expect("error_code == no_match", r.error_code == "no_match")

        # --- replace_range ---
        print()
        print("== replace_range ==")
        r = _run_patches(root, [
            {"action": "replace_range", "arguments": {
                "file_path": "a.md", "start_line": 7, "end_line": 9,
                "new_content": "NEW-BODY"}},
        ])[0]
        t.expect("replace_range ok", r.status == "ok", f"{r.status}: {r.message}")
        content = (root / "a.md").read_text(encoding="utf-8")
        t.expect("NEW-BODY present", "NEW-BODY" in content)
        t.expect("old AAA gone", "AAA" not in content)
        t.expect("old BBB gone", "BBB" not in content)
        t.expect("CCC gone (was in range)", "CCC" not in content)
        t.expect("DDD preserved", "DDD" in content)

        # --- filter blocks ---
        print()
        print("== filter blocks ==")
        r = _run_patches(root, [
            {"action": "replace_in_file", "arguments": {
                "file_path": "a.md", "search": "NEW", "replace": "OLD"}},
        ], filter_paths=["sub"])[0]
        t.expect("write blocked by filter", r.status == "blocked",
                 f"{r.status}: {r.message}")

    print()
    if t.failed:
        print(f"=== ИТОГ: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== ИТОГ: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
