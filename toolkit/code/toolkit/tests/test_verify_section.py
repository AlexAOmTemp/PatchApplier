"""Test verify_section: clears stale without touching the file.

Scenario:
  1. doc with two sections, summaries, fresh meta
  2. edit body of section Alpha -> next rebuild marks Alpha stale
  3. verify_section(Alpha) -> summary_changed_at bumped; file untouched
  4. next rebuild -> Alpha no longer stale
  5. verify_section on a section without summary -> error no_summary
  6. verify_section on a missing section -> error not_found
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from toolkit.backends import RootDirBackend
from toolkit.formats import Format
from toolkit.indexers.meta import load_meta, resolve_path
from toolkit.tools.index import RebuildIndexTool
from toolkit.tools.write import (
    ReplaceBetweenTool, VerifySectionTool,
)


SOURCE = """\
# Test doc
<!-- summary: test file -->

## 1. Alpha
<!-- summary: first section -->

body of Alpha

## 2. Beta
<!-- summary: second section -->

body of Beta

## 3. Bare

no summary here
"""


class T:
    def __init__(self):
        self.ok = 0
        self.fail = 0

    def expect(self, name, cond, extra=""):
        if cond:
            print(f"  PASS  {name}")
            self.ok += 1
        else:
            print(f"  FAIL  {name}  {extra}")
            self.fail += 1


def _rebuild(be, fmt, tmp):
    RebuildIndexTool.set_paths("INDEX.md")
    return RebuildIndexTool().execute(backend=be, fmt=fmt)


def _index_marks_stale(tmp):
    txt = (tmp / "INDEX.md").read_text(encoding="utf-8")
    # "1. Alpha" section line must contain stale marker
    for line in txt.splitlines():
        if "Alpha" in line and line.lstrip().startswith("- 1."):
            return "stale" in line
    return None


def main():
    t = T()
    tmp = Path(__file__).resolve().parent / "_tmp_verify"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        (tmp / "doc.md").write_text(SOURCE, encoding="utf-8")
        be = RootDirBackend(str(tmp))
        be.open()
        fmt = Format.load("default", None)

        # 1. Initial rebuild -> meta created, not stale
        r = _rebuild(be, fmt, tmp)
        t.expect("initial rebuild ok", r.status == "ok", r.message)
        t.expect("Alpha not stale after first build",
                 _index_marks_stale(tmp) is False,
                 f"got {_index_marks_stale(tmp)!r}")
        meta_path = resolve_path("INDEX.md")
        meta = load_meta(be, meta_path)
        t.expect("meta has doc.md", "doc.md" in meta,
                 f"keys={list(meta.keys())}")
        t.expect("meta has Alpha", "1. Alpha" in meta.get("doc.md", {}),
                 f"keys={list(meta.get('doc.md', {}).keys())}")

        # 2. Edit Alpha body -> rebuild -> stale
        rep = ReplaceBetweenTool().execute(
            backend=be, fmt=fmt, file_path="doc.md",
            start_anchor="## 1. Alpha",
            end_anchor="## 2. Beta",
            include_start=True, include_end=False,
            new_content=("## 1. Alpha\n<!-- summary: first section -->\n\n"
                         "body of Alpha CHANGED\n\n"),
        )
        t.expect("replace_between ok", rep.status == "ok", rep.message)
        _rebuild(be, fmt, tmp)
        t.expect("Alpha stale after body edit",
                 _index_marks_stale(tmp) is True,
                 f"got {_index_marks_stale(tmp)!r}")

        # 3. verify_section -> file untouched, meta bumped
        before = (tmp / "doc.md").read_text(encoding="utf-8")
        VerifySectionTool.set_paths("INDEX.md")
        v = VerifySectionTool().execute(
            backend=be, fmt=fmt, file_path="doc.md",
            section_number="1",
        )
        after = (tmp / "doc.md").read_text(encoding="utf-8")
        t.expect("verify_section ok", v.status == "ok", v.message)
        t.expect("file untouched by verify_section", before == after)

        # 4. rebuild -> stale cleared
        _rebuild(be, fmt, tmp)
        t.expect("Alpha not stale after verify",
                 _index_marks_stale(tmp) is False,
                 f"got {_index_marks_stale(tmp)!r}")

        # 5. verify_section on bare section (no summary)
        v2 = VerifySectionTool().execute(
            backend=be, fmt=fmt, file_path="doc.md",
            section_number="3",
        )
        t.expect("no summary -> no_summary",
                 v2.error_code == "no_summary",
                 f"got {v2.error_code!r}")

        # 6. verify_section on missing section
        v3 = VerifySectionTool().execute(
            backend=be, fmt=fmt, file_path="doc.md",
            section_number="99",
        )
        t.expect("missing section -> not_found",
                 v3.error_code == "not_found",
                 f"got {v3.error_code!r}")

        be.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n=== ИТОГ: ok={t.ok}, fail={t.fail} ===")
    sys.exit(0 if t.fail == 0 else 1)


if __name__ == "__main__":
    main()
