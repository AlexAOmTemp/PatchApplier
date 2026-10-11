"""Write operations for the unit model. Wave 2, tool 1: set_annotation.

Cross-format annotation setter. Replaces an existing annotation in
place. If the unit has no annotation, fails with `no_annotation` —
creating one requires knowing the surrounding indentation and quoting
rules per format, which is out of scope here.

Per-format behaviour:
  .py ............ replace the triple-quoted docstring
  .lua / .luau ... replace the --[[ ... ]] block or a run of --- lines
  .md ............ replace the summary HTML comment line

Text is written literally (no escaping). If the text contains the
surrounding delimiter, the result will not parse — validation after
write catches this and the file is left untouched.
"""
from __future__ import annotations

from pathlib import Path

from . import reader
from .model import UnitKind


def set_annotation(source: str, path: str, address: dict, text: str) -> str:
    """Return the new source with the annotation replaced.

    Raises ValueError for empty text or unsupported extensions; KeyError
    for not_found / ambiguous / no_annotation. The caller writes the
    result via the backend; this function is pure.
    """
    if text is None or not text.strip():
        raise ValueError("empty_input")
    ext = Path(path).suffix.lower()
    if ext not in (".py", ".lua", ".luau", ".md"):
        raise ValueError(f"unsupported extension: {ext}")

    unit = reader.resolve(source, path, address)
    if not unit.annotation.is_present():
        raise KeyError(f"no_annotation: {unit.qualname}")

    a = unit.annotation
    lines = source.splitlines(keepends=False)
    start_i = a.start - 1
    end_i = a.end  # slice end (exclusive)

    if ext == ".py":
        new_lines = _render_py(text, lines[start_i])
    elif ext in (".lua", ".luau"):
        new_lines = _render_lua(text)
    else:
        new_lines = _render_md(text)

    new_source_lines = lines[:start_i] + new_lines + lines[end_i:]
    eol = "\r\n" if "\r\n" in source else "\n"
    new_source = eol.join(new_source_lines)
    if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
        new_source += eol

    _check_parses(new_source, path, unit, ext, source)
    return new_source


def _render_py(text: str, sample_line: str) -> list[str]:
    """Render a Python docstring, preserving the indentation of the old
    one. Chooses `\"\"\"` unless the text contains it, then `'''`.
    """
    indent_len = len(sample_line) - len(sample_line.lstrip())
    indent = " " * indent_len
    if '\"\"\"' not in text:
        q = '\"\"\"'
    elif "'''" not in text:
        q = "'''"
    else:
        raise ValueError("bad_text: cannot choose a quote that does not appear in the annotation")
    body = text
    if "\n" in body:
        lines = body.splitlines()
        out = [f"{indent}{q}{lines[0]}"]
        for ln in lines[1:]:
            out.append(f"{indent}{ln}" if ln else "")
        out.append(f"{indent}{q}")
        return out
    return [f"{indent}{q}{body}{q}"]


def _render_lua(text: str) -> list[str]:
    """Render a Lua annotation as `--[[ ... ]]` — multi-line if needed."""
    if "\n" in text:
        return ["--[[ " + text + " ]]"]
    return [f"--[[ {text} ]]" ]


def _render_md(text: str) -> list[str]:
    """Markdown summary must be a single line."""
    flat = " ".join(text.splitlines()).strip()
    return [f"<!-- summary: {flat} -->"]


def replace_unit(source: str, path: str, address: dict,
                 new_text: str, part=None, block=None) -> str:
    """Replace a unit — wholly, a part of it, or a range of blocks.

    Exactly one of `part` / `block` is required:

      part="all"        — the whole unit (head + annotation + body)
      part="body"       — body only, head and annotation kept
      part="own_body"   — body without subsections (section-only view)
      part="head"       — declaration only
      part="annotation" — docstring / summary only
      part=["head","annotation"] — several parts
      block=N | "1-4" | [1,3] — one or more blocks in body

    No default: callers must say what they are replacing. This removes
    the class of bugs where "thought I was editing a block, replaced
    the whole body". `scope_required` if neither part nor block given;
    `scope_conflict` if both.

    Empty `new_text` with `block` = delete those blocks. Empty
    `new_text` with `part` = error `empty_input_use_delete_block`.
    """
    if new_text is None:
        new_text = ""
    if part is None and block is None:
        raise ValueError(
            "scope_required: pass part= or block= "
            "(part=all replaces the whole unit; block=N replaces N-th block)"
        )
    if part is not None and block is not None:
        raise ValueError("scope_conflict: use part= or block=, not both")
    if block is not None:
        return replace_block(source, path, address, block, new_text)

    ext = Path(path).suffix.lower()
    unit = reader.resolve(source, path, address)
    parts = reader._normalize_parts(part)
    if parts == ["all"] and not (new_text or "").strip():
        raise ValueError(
            "empty_input_use_delete_block: replace_unit does not delete a unit"
        )
    if parts == ["all"]:
        start, end = unit.line_start, unit.line_end
    else:
        start, end = None, None
        for p in parts:
            if p == "own_body":
                ps = _own_body_part(unit)
            else:
                ps = getattr(unit, p)
            if ps.is_present():
                if start is None or ps.start < start:
                    start = ps.start
                if end is None or ps.end > end:
                    end = ps.end
        if start is None:
            raise KeyError("no_parts: none of the requested parts are present")

    lines = source.splitlines()
    first_line = lines[start - 1]
    indent = _line_indent(first_line)
    new_lines = _apply_indent(new_text, indent)
    out_lines = lines[:start - 1] + new_lines + lines[end:]

    eol = "\r\n" if "\r\n" in source else "\n"
    new_source = eol.join(out_lines)
    if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
        new_source += eol

    _check_parses(new_source, path, unit, ext, source)
    return new_source


def replace_block(source: str, path: str, address: dict,
                  block_spec, new_text: str) -> str:
    """Replace one block or a contiguous range of blocks in a unit's body.

    `block_spec` — an int, a comma-separated string ("1-4"), or a list of
    ints, all of which must denote a contiguous range (no gaps). A gap
    raises `bad_block_range`. Empty `new_text` deletes the range.
    """
    if new_text is None:
        new_text = ""
    ext = Path(path).suffix.lower()
    unit = reader.resolve(source, path, address)
    if not unit.blocks:
        raise KeyError("not_applicable: this unit has no blocks")
    indices = reader._parse_blocks(block_spec)
    if not indices:
        raise ValueError("bad_block: empty block spec")
    # must be contiguous
    for a, b in zip(indices, indices[1:]):
        if b != a + 1:
            raise ValueError(f"bad_block_range: blocks {a} and {b} are not adjacent")
    by_index = {b.index: b for b in unit.blocks}
    for i in indices:
        if i not in by_index:
            max_i = max(by_index)
            raise KeyError(f"block_out_of_range: {i} (max {max_i})")

    start = by_index[indices[0]].start
    end = by_index[indices[-1]].end
    lines = source.splitlines()
    indent = _line_indent(lines[start - 1])
    if new_text.strip():
        new_lines = _apply_indent(new_text, indent)
    else:
        new_lines = []
    out_lines = lines[:start - 1] + new_lines + lines[end:]

    eol = "\r\n" if "\r\n" in source else "\n"
    new_source = eol.join(out_lines)
    if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
        new_source += eol

    _check_parses(new_source, path, unit, ext, source)
    return new_source


def insert_block(source: str, path: str, address: dict,
                 new_text: str, position: str = "end",
                 anchor: int | str | None = None) -> str:
    """Insert a block into a unit's body.

    `position` — "start" | "end" | "before" | "after". "before"/"after"
    require `anchor` (block index or qualname of a block-unit).
    "start"/"end" place at the first/last block boundary; "end" appends
    after the last block.
    """
    if not new_text or not new_text.strip():
        raise ValueError("empty_input")
    ext = Path(path).suffix.lower()
    unit = reader.resolve(source, path, address)
    if not unit.blocks:
        raise KeyError("not_applicable: this unit has no blocks")
    by_index = {b.index: b for b in unit.blocks}
    lines = source.splitlines()

    if position in ("start", "end"):
        if position == "start":
            ref = by_index[1]
            insert_at = ref.start
            indent = _line_indent(lines[ref.start - 1])
        else:
            ref = by_index[max(by_index)]
            insert_at = ref.end + 1
            indent = _line_indent(lines[ref.start - 1])
    elif position in ("before", "after"):
        if anchor is None:
            raise ValueError("anchor_required: before/after need an anchor")
        ref = _find_anchor_block(by_index, anchor)
        indent = _line_indent(lines[ref.start - 1])
        insert_at = ref.start if position == "before" else ref.end + 1
    else:
        raise ValueError(f"bad_position: {position!r}")

    new_lines = _apply_indent(new_text, indent)
    out_lines = lines[:insert_at - 1] + new_lines + lines[insert_at - 1:]

    eol = "\r\n" if "\r\n" in source else "\n"
    new_source = eol.join(out_lines)
    if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
        new_source += eol

    _check_parses(new_source, path, unit, ext, source)
    return new_source


def _find_anchor_block(by_index: dict, anchor) -> "Block":
    if isinstance(anchor, int):
        if anchor not in by_index:
            raise KeyError(f"anchor_not_found: block {anchor}")
        return by_index[anchor]
    if isinstance(anchor, str):
        if anchor.isdigit():
            return _find_anchor_block(by_index, int(anchor))
        for b in by_index.values():
            if b.unit and b.unit.qualname == anchor:
                return b
        raise KeyError(f"anchor_not_found: {anchor!r}")
    raise ValueError(f"bad_anchor: {anchor!r}")


def _line_indent(line: str) -> str:
    return line[:len(line) - len(line.lstrip())]


def _apply_indent(text: str, indent: str) -> list[str]:
    import textwrap
    text = textwrap.dedent(text.rstrip("\n"))
    out: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            out.append("")
        else:
            out.append(indent + line)
    return out


def _own_body_part(unit):
    """Body range excluding subsections (same rule as reader._own_body_part)."""
    from .model import Part as _P
    if not unit.body.is_present():
        return _P()
    first_child = None
    for b in unit.blocks:
        if b.unit is not None:
            first_child = b.start
            break
    if first_child is None:
        return unit.body
    end = first_child - 1
    if end < unit.body.start:
        return _P()
    return _P(unit.body.start, end)


def _check_parses(new_source: str, path: str, unit, ext: str,
                  old_source: str | None = None) -> None:
    """Confirm the edited source still parses and the target survives.

    When `old_source` is provided, additionally verify that no *unrelated*
    unit has been lost. The target and its descendants are allowed to
    change or vanish (that is the point of the edit); everything else must
    survive. This catches the markdown off-by-one where `part="body"` on
    a section used to eat the following section's heading.
    """
    if ext == ".py":
        import ast
        try:
            tree = ast.parse(new_source)
        except SyntaxError as e:
            raise ValueError(f"result_syntax_error: {e}")
        # qualname must still be present
        if unit.qualname != "<module>":
            found = False
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = node.name
                    if name == unit.name:
                        found = True
                        break
            if not found:
                raise ValueError(f"result_missing_symbol: {unit.qualname}")
    elif ext in (".lua", ".luau"):
        from ...formats import lua as _lua
        try:
            syms = _lua.parse_lua_symbols(new_source)
        except Exception as e:
            raise ValueError(f"result_parse_error: {e}")
        if unit.qualname != "<module>":
            if not any(s.qualname == unit.qualname for s in syms):
                raise ValueError(f"result_missing_symbol: {unit.qualname}")
    else:  # .md
        from ...formats import Format
        try:
            doc = Format.load("default").parse(new_source)
        except Exception as e:
            raise ValueError(f"result_parse_error: {e}")
        if unit.kind == UnitKind.SECTION:
            if doc.find(number=unit.name) is None and doc.find(title=unit.name) is None:
                raise ValueError(f"result_missing_section: {unit.name}")
            if old_source is not None:
                old_doc = Format.load("default").parse(old_source)
                old_ids = {str(s.number or s.title) for s in old_doc.flatten()}
                new_ids = {str(s.number or s.title) for s in doc.flatten()}
                target = str(unit.name)
                # Descendants of the target (e.g. 2.1 when target is 2)
                # may change or vanish — they are the target's own body.
                lost = {l for l in (old_ids - new_ids)
                        if l != target and not l.startswith(target + ".")}
                if lost:
                    raise ValueError(
                        f"result_missing_section: unintended loss of "
                        f"{sorted(lost)} (target \u00a7{target})"
                    )
