"""Unit tests for formats.parser -- runs standalone, no external deps."""
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.formats import Format, list_presets


FIX = HERE / "fixtures"
PASS = "[OK]  "
FAIL = "[FAIL]"


class TestRunner:
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


def main():
    fmt = Format.load("default")
    t = TestRunner()

    print(f"Presets available: {list_presets()}")
    print()

    # --- simple.md ---
    print("== simple.md ==")
    text = (FIX / "simple.md").read_text(encoding="utf-8")
    doc = fmt.parse(text)
    t.expect("2 top-level sections", len(doc.sections) == 2,
             f"got {len(doc.sections)}")
    s1 = doc.sections[0]
    t.expect("section[0].number == '1'", s1.number == "1", f"got {s1.number!r}")
    t.expect("section[0].title == 'Первая секция'",
             s1.title == "Первая секция", f"got {s1.title!r}")
    t.expect("section[0].summary present", s1.summary is not None)
    t.expect("section[0].tags == ['fixture','simple']",
             s1.tags == ["fixture", "simple"], f"got {s1.tags}")
    t.expect("section[0].body contains 'Тело секции'",
             "Тело секции" in text[s1.body_start:s1.body_end])

    # --- with_subsections.md ---
    print()
    print("== with_subsections.md ==")
    text = (FIX / "with_subsections.md").read_text(encoding="utf-8")
    doc = fmt.parse(text)
    t.expect("2 top-level sections", len(doc.sections) == 2,
             f"got {len(doc.sections)}")
    parent = doc.sections[0]
    t.expect("parent has 2 children", len(parent.children) == 2,
             f"got {len(parent.children)}")
    t.expect("first child number == '1.1'",
             parent.children[0].number == "1.1",
             f"got {parent.children[0].number!r}")
    t.expect("second child number == '1.2'",
             parent.children[1].number == "1.2",
             f"got {parent.children[1].number!r}")
    t.expect("parent.body_end == child heading_start",
             parent.body_end == parent.children[0].heading_start,
             f"{parent.body_end} != {parent.children[0].heading_start}")
    t.expect("find('1.1') returns first child",
             doc.find(number="1.1") is parent.children[0])

    # --- no_summary.md ---
    print()
    print("== no_summary.md ==")
    text = (FIX / "no_summary.md").read_text(encoding="utf-8")
    doc = fmt.parse(text)
    t.expect("2 sections", len(doc.sections) == 2)
    t.expect("section[0].summary is None", doc.sections[0].summary is None)
    t.expect("section[1].tags == ['only-tags']",
             doc.sections[1].tags == ["only-tags"],
             f"got {doc.sections[1].tags}")
    t.expect("section[1].summary is None", doc.sections[1].summary is None)

    # --- with_code_fence.md ---
    print()
    print("== with_code_fence.md ==")
    text = (FIX / "with_code_fence.md").read_text(encoding="utf-8")
    doc = fmt.parse(text)
    t.expect("exactly 2 sections (## inside fence ignored)",
             len(doc.sections) == 2, f"got {len(doc.sections)}")
    t.expect("section[0].number == '1'", doc.sections[0].number == "1")
    t.expect("section[1].number == '2'", doc.sections[1].number == "2")
    # ensure fenced content remains inside section 1 body
    t.expect("fence content in section[0].body",
             "def foo():" in text[doc.sections[0].body_start:doc.sections[0].body_end])

    # --- plain preset ---
    print()
    print("== plain preset ==")
    fmt_plain = Format.load("plain")
    text = (FIX / "simple.md").read_text(encoding="utf-8")
    doc = fmt_plain.parse(text)
    t.expect("plain: 2 sections still found", len(doc.sections) == 2)
    t.expect("plain: summary is None", doc.sections[0].summary is None)
    t.expect("plain: tags empty", doc.sections[0].tags == [])

    # --- find by title ---
    print()
    print("== find by title ==")
    doc = fmt.parse((FIX / "simple.md").read_text(encoding="utf-8"))
    t.expect("find(title='вторая') finds section 2",
             doc.find(title="вторая") is doc.sections[1])
    t.expect("find(title='nope') returns None",
             doc.find(title="nope") is None)

    print()
    if t.failed:
        print(f"=== ИТОГ: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== ИТОГ: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
