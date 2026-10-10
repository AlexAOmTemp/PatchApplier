"""Luau adapter — MVP.

Uses `formats/lua.parse_lua_symbols` plus `lua_signature_bounds` /
`lua_body_bounds` from the same module. Blocks inside a function body
are not enumerated on this pass: the tokenizer only produces function
boundaries, not statements. See MODEL.md §5.
"""
from __future__ import annotations

from ...formats import lua as _lua
from .model import Block, Part, Unit, UnitKind


def build(source: str, path: str = "") -> Unit:
    syms = _lua.parse_lua_symbols(source)
    lines = source.splitlines()
    n = len(lines) or 1

    units: list[Unit] = []
    for s in syms:
        kind = UnitKind.METHOD if ":" in s.qualname else UnitKind.FUNCTION
        head_b = _lua.lua_signature_bounds(source, s)
        body_b = _lua.lua_body_bounds(source, s)
        head = Part(*head_b) if head_b else Part()
        body = Part(*body_b) if body_b else Part()
        ann = _find_lua_annotation(lines, s.line_start)
        units.append(Unit(
            kind=kind, name=s.qualname.rsplit(".", 1)[-1], qualname=s.qualname,
            line_start=s.line_start, line_end=s.line_end,
            head=head, annotation=ann, body=body, blocks=[],
        ))

    top_blocks: list[Block] = []
    for i, u in enumerate(units, start=1):
        top_blocks.append(Block(index=i, start=u.line_start, end=u.line_end, unit=u))

    return Unit(
        kind=UnitKind.MODULE, name="<module>", qualname="<module>",
        line_start=1, line_end=n,
        head=Part(1, 0), annotation=Part(),
        body=Part(1, n) if top_blocks else Part(),
        blocks=top_blocks,
    )


def _find_lua_annotation(lines: list[str], func_line: int) -> Part:
    """Look immediately above the function line for an annotation.

    Two shapes: a `--[[ ... ]]` block ending on the line just above the
    function; a run of consecutive `---` comment lines. Both must sit
    directly above (no blank line).
    """
    j = func_line - 2
    if j < 0:
        return Part()
    for probe in range(j, max(-1, j - 60), -1):
        s = lines[probe]
        if "--[[" in s:
            body = "\n".join(lines[probe:j + 1])
            after = body.split("--[[", 1)[1]
            if "]]" in after:
                return Part(probe + 1, j + 1)
            return Part()
        if s.strip() == "":
            break
    i = j
    while i >= 0 and lines[i].lstrip().startswith("---"):
        i -= 1
    start_i = i + 1
    if start_i <= j:
        return Part(start_i + 1, j + 1)
    return Part()
