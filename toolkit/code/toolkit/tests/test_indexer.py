"""Tests for indexers: render + diff."""
from __future__ import annotations

import re
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import FilesystemBackend
from toolkit.core import FilterSpec
from toolkit.formats import Format
from toolkit.indexers.doc import build_index
from toolkit.indexers.diff import diff_index, parse_index_text


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


def main():
    t = T()
    backend = FilesystemBackend(TOOLKIT_ROOT)
    backend.open()
    fmt = Format.load("default")

    # --- build_index ---
    print("== build_index ==")
    result = build_index(
        backend, fmt,
        docs_dir="tests/fixtures",
        filter_spec=FilterSpec(),
        skip_files={"INDEX.md", "INDEX_TEST.md"},
    )
    text = result.text

    t.expect("files_count == 4", result.files_count == 4,
             f"got {result.files_count}")
    t.expect("missing_summary == 3", result.missing_summary == 3,
             f"got {result.missing_summary}")
    t.expect("contains simple.md", "tests/fixtures/simple.md" in text)
    t.expect("contains with_subsections.md", "with_subsections.md" in text)
    t.expect("contains §1 title", "Первая секция" in text)
    t.expect("contains subsection indent", "  - 1.1 " in text,
             "subsection not indented")
    t.expect("root section has trailing dot", "- 1. Первая секция" in text,
             "root num missing trailing dot")
    t.expect("subsection has no trailing dot", "  - 1.1. " not in text,
             "subsection num has stray dot")
    t.expect("contains ⚠ no summary marker", "⚠ no summary" in text)
    t.expect("contains summary text", "Одна секция с summary" in text)
    t.expect("contains tags", "[fixture, simple]" in text)

    print()
    print("== parsed structure ==")
    parsed = parse_index_text(text)
    t.expect("parse_index_text found >= 5 sections", len(parsed) >= 5,
             f"got {len(parsed)}")

    # --- diff: no changes ---
    print()
    print("== diff: no changes ==")
    dr = diff_index(text, text)
    t.expect("header == [без изменений]", dr.header == " [без изменений]",
             f"got {dr.header!r}")

    # --- diff: shift ---
    print()
    print("== diff: shifted section ==")
    m = re.search(r"\(L(\d+)[–-]L(\d+),\s+([\d.]+)\s*KB", text)
    t.expect("first L-range found", m is not None)
    if m:
        shifted = text[:m.start(1)] + str(int(m.group(1)) + 1) + text[m.end(1):]
        dr = diff_index(text, shifted)
        t.expect("shift detected (⇅)", "⇅" in dr.header, f"header: {dr.header!r}")

    # --- diff: size change ---
    print()
    print("== diff: size changed ==")
    m = re.search(r"\(L(\d+)[–-]L(\d+),\s+([\d.]+)\s*KB", text)
    if m:
        old_kb = float(m.group(3))
        changed = text[:m.start(3)] + f"{old_kb + 5.0:.1f}" + text[m.end(3):]
        dr = diff_index(text, changed)
        t.expect("change detected (~)", "~" in dr.header, f"header: {dr.header!r}")

    # --- diff: file removed ---
    print()
    print("== diff: file removed ==")
    lines = text.splitlines(keepends=True)
    out_lines: list[str] = []
    skip = False
    for ln in lines:
        if ln.startswith("## tests/fixtures/no_summary.md"):
            skip = True
            continue
        if skip and ln.startswith("## "):
            skip = False
        if not skip:
            out_lines.append(ln)
    removed_text = "".join(out_lines)
    dr = diff_index(text, removed_text)
    t.expect("removed detected (-)", "-" in dr.header, f"header: {dr.header!r}")

    # --- diff: fresh build ---
    print()
    print("== diff: created ==")
    dr = diff_index("", text)
    t.expect("created marker", "создан" in dr.header, f"header: {dr.header!r}")

    backend.close()

    print()
    if t.failed:
        print(f"=== ИТОГ: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== ИТОГ: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
