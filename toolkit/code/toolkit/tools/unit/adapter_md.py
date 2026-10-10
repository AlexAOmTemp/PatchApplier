"""Markdown adapter — build a Unit tree from ParsedDoc.

Uses `formats/parser.parse` via `Format.load("default")`. Offsets in
Section are byte offsets; translated to 1-based line numbers.
Blocks of a section = its subsections (each as a child unit). Plain
paragraphs between subsections are not blocks on this first pass.
"""
from __future__ import annotations

from ...formats import Format
from .model import Block, Part, Unit, UnitKind


def build(source: str, path: str = "") -> Unit:
    fmt = Format.load("default")
    doc = fmt.parse(source)

    def line_at(offset: int) -> int:
        return source[:offset].count("\n") + 1

    def section_full_end(s) -> int:
        if s.children:
            return section_full_end(s.children[-1])
        return s.body_end

    def build_section(s) -> Unit:
        head_start = line_at(s.heading_start)
        # heading_end is a byte offset just past the heading line; when it
        # lands exactly on a line boundary, line_at() bumps us to the next
        # line. Point to the character before the boundary instead.
        heading_end_off = max(s.heading_start, s.heading_end - 1)
        head_end = line_at(heading_end_off)
        line_start = head_start
        line_end = line_at(section_full_end(s))

        ann = Part()
        if s.summary:
            seg = source[s.heading_end:s.body_start]
            seg_lines = seg.splitlines()
            base = line_at(s.heading_end)
            for i, ln in enumerate(seg_lines):
                if "<!--" in ln and "summary" in ln:
                    ann = Part(base + i, base + i)
                    break

        body_start = (ann.end + 1) if ann.is_present() else (head_end + 1)
        body_part = Part(body_start, line_end) if line_end >= body_start else Part()

        blocks: list[Block] = []
        for i, child in enumerate(s.children, start=1):
            cu = build_section(child)
            blocks.append(Block(index=i, start=cu.line_start, end=cu.line_end, unit=cu))

        name = s.number or s.title
        return Unit(
            kind=UnitKind.SECTION, name=name, qualname=name,
            line_start=line_start, line_end=line_end,
            head=Part(head_start, head_end), annotation=ann,
            body=body_part, blocks=blocks,
        )

    n = len(source.splitlines()) or 1
    top_blocks: list[Block] = []
    for i, sec in enumerate(doc.sections, start=1):
        su = build_section(sec)
        top_blocks.append(Block(index=i, start=su.line_start, end=su.line_end, unit=su))

    return Unit(
        kind=UnitKind.MODULE, name="<module>", qualname="<module>",
        line_start=1, line_end=n,
        head=Part(1, 0), annotation=Part(), body=Part(1, n) if top_blocks else Part(),
        blocks=top_blocks,
    )
