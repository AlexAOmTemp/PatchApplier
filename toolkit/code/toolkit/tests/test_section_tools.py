"""Tests for replace_section and set_summary."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import FilesystemBackend
from toolkit.core import FilterSpec, Session
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


SEED = (
    "# Test Doc\n\n"
    "## 1. One\n"
    "<!-- summary: first summary -->\n"
    "<!-- tags: a, b -->\n\n"
    "Body 1 line 1\n"
    "Body 1 line 2\n\n"
    "## 2. Two\n\n"
    "Body 2 content\n"
)


SEED_WITH_CHILD = (
    "# Test\n\n"
    "## 1. Parent\n"
    "<!-- summary: parent -->\n\n"
    "Parent intro\n\n"
    "### 1.1 Child\n"
    "<!-- summary: child -->\n\n"
    "Child body\n\n"
    "## 2. Sibling\n\n"
    "<!-- summary: sibling -->\n\n"
    "Sibling body\n"
)


def _run(root: Path, patches: list[dict]):
    backend = FilesystemBackend(root)
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:
        return s.apply_patches(patches)


def main():
    t = T()
    fmt = Format.load("default")

    # ================== replace_section ==================
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / "doc.md"
        p.write_text(SEED, encoding="utf-8")

        # --- mode="body" on §1 ---
        print("== replace_section mode=body ==")
        r = _run(root, [{
            "action": "replace_section",
            "arguments": {
                "file_path": "doc.md",
                "section_number": "1",
                "new_content": "REPLACED BODY",
                "mode": "body",
            },
        }])[0]
        t.expect("body mode ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("§1 heading preserved", "## 1. One" in content)
        t.expect("§1 summary preserved", "<!-- summary: first summary -->" in content)
        t.expect("§1 tags preserved", "<!-- tags: a, b -->" in content)
        t.expect("§1 body replaced", "REPLACED BODY" in content)
        t.expect("old body gone", "Body 1 line 1" not in content)
        t.expect("§2 intact", "## 2. Two" in content and "Body 2 content" in content)
        t.expect("delta.lines == -1", r.delta.lines == -1, f"got {r.delta.lines}")

        # --- mode="all" on §2 ---
        print()
        print("== replace_section mode=all ==")
        r = _run(root, [{
            "action": "replace_section",
            "arguments": {
                "file_path": "doc.md",
                "section_number": "2",
                "new_content": "## 2. Renamed\n<!-- summary: new -->\n\nNew body",
                "mode": "all",
            },
        }])[0]
        t.expect("all mode ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("§2 renamed", "## 2. Renamed" in content)
        t.expect("§2 summary replaced", "<!-- summary: new -->" in content)
        t.expect("§2 body replaced", "New body" in content)
        t.expect("old §2 title gone", "## 2. Two" not in content)
        t.expect("§1 still intact", "## 1. One" in content and "REPLACED BODY" in content)

        # --- section not found ---
        print()
        print("== replace_section: not found ==")
        r = _run(root, [{
            "action": "replace_section",
            "arguments": {"file_path": "doc.md", "section_number": "99",
                          "new_content": "x"},
        }])[0]
        t.expect("not-found is error", r.status == "error")
        t.expect("error_code == not_found", r.error_code == "not_found")

    # ================== replace_section on parent with children ==================
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / "tree.md"
        p.write_text(SEED_WITH_CHILD, encoding="utf-8")

        print()
        print("== replace_section on parent replaces whole subtree ==")
        r = _run(root, [{
            "action": "replace_section",
            "arguments": {
                "file_path": "tree.md",
                "section_number": "1",
                "new_content": "Parent new body without children",
                "mode": "body",
            },
        }])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("parent intro replaced",
                 "Parent new body without children" in content)
        t.expect("child §1.1 removed",
                 "### 1.1 Child" not in content, content)
        t.expect("sibling §2 intact", "## 2. Sibling" in content)

    # ================== set_summary ==================
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / "s.md"
        p.write_text(SEED, encoding="utf-8")

        # --- replace existing summary ---
        print()
        print("== set_summary: replace existing ==")
        r = _run(root, [{
            "action": "set_summary",
            "arguments": {"file_path": "s.md", "section_number": "1",
                          "summary": "NEW TEXT"},
        }])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("new summary present", "<!-- summary: NEW TEXT -->" in content)
        t.expect("old summary gone", "first summary" not in content)
        t.expect("tags untouched", "<!-- tags: a, b -->" in content)

        # --- insert summary on §2 (no summary) ---
        print()
        print("== set_summary: insert on §2 ==")
        r = _run(root, [{
            "action": "set_summary",
            "arguments": {"file_path": "s.md", "section_number": "2",
                          "summary": "fresh"},
        }])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("fresh summary present", "<!-- summary: fresh -->" in content)
        # Structure: §2 heading, then summary on next line
        t.expect("§2 heading followed by summary",
                 "## 2. Two\n<!-- summary: fresh -->" in content, content)

        # --- replace summary + add tags ---
        print()
        print("== set_summary: replace + add tags ==")
        r = _run(root, [{
            "action": "set_summary",
            "arguments": {"file_path": "s.md", "section_number": "2",
                          "summary": "with tags", "tags": ["x", "y"]},
        }])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("summary updated", "<!-- summary: with tags -->" in content)
        t.expect("tags added", "<!-- tags: x, y -->" in content)
        t.expect("§1 tags untouched", "<!-- tags: a, b -->" in content)

        # --- tags=None doesn't touch tags ---
        print()
        print("== set_summary: tags=None doesn't touch tags ==")
        r = _run(root, [{
            "action": "set_summary",
            "arguments": {"file_path": "s.md", "section_number": "1",
                          "summary": "again"},
        }])[0]
        t.expect("ok", r.status == "ok")
        content = p.read_text(encoding="utf-8")
        t.expect("§1 tags still there", "<!-- tags: a, b -->" in content)
        t.expect("§1 summary updated", "<!-- summary: again -->" in content)

        # --- section not found ---
        print()
        print("== set_summary: not found ==")
        r = _run(root, [{
            "action": "set_summary",
            "arguments": {"file_path": "s.md", "section_number": "77",
                          "summary": "x"},
        }])[0]
        t.expect("not-found is error", r.status == "error")
        t.expect("error_code == not_found", r.error_code == "not_found")

        # --- reparse after edits ---
        print()
        print("== reparse after edits ==")
        content = p.read_text(encoding="utf-8")
        doc = fmt.parse(content)
        s1 = doc.find(number="1")
        s2 = doc.find(number="2")
        t.expect("§1 summary == 'again'", s1.summary == "again",
                 f"got {s1.summary!r}")
        t.expect("§1 tags == ['a','b']", s1.tags == ["a", "b"], f"got {s1.tags}")
        t.expect("§2 summary == 'with tags'", s2.summary == "with tags",
                 f"got {s2.summary!r}")
        t.expect("§2 tags == ['x','y']", s2.tags == ["x", "y"], f"got {s2.tags}")

    print()
    if t.failed:
        print(f"=== ИТОГ: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== ИТОГ: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
