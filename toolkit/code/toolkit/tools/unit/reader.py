"""Reader — resolve an address against a Unit tree and return text.

Implements `read_unit`, `list_units`, `dump_tree` per MODEL.md.
Text output for blocks: `=== block N ===` markers when more than one
block is returned, none when exactly one.
"""
from __future__ import annotations

from pathlib import Path

from .model import Block, Part, Unit, UnitKind
from ...core.paths import is_mcp_path


def _build(source: str, path: str) -> Unit:
    # MCP (Roblox) paths carry no extension; their source is Luau.
    if is_mcp_path(path):
        from . import adapter_lua as a
        return a.build(source, path)
    ext = Path(path).suffix.lower()
    if ext == ".py":
        from . import adapter_py as a
    elif ext in (".lua", ".luau"):
        from . import adapter_lua as a
    elif ext == ".md":
        from . import adapter_md as a
    else:
        raise ValueError(f"unsupported extension: {ext}")
    return a.build(source, path)


def _iter_units(root: Unit):
    yield root
    for b in root.blocks:
        if b.unit is not None:
            yield from _iter_units(b.unit)


def _parse_blocks(spec) -> list[int]:
    if spec is None:
        return []
    out: set[int] = set()
    items = spec if isinstance(spec, list) else [spec]
    for it in items:
        if isinstance(it, int):
            out.add(it)
        elif isinstance(it, str):
            for chunk in it.split(","):
                chunk = chunk.strip()
                if not chunk:
                    continue
                if "-" in chunk:
                    a, b = chunk.split("-", 1)
                    a, b = int(a), int(b)
                    out.update(range(a, b + 1))
                else:
                    out.add(int(chunk))
        else:
            raise ValueError(f"bad_block: {it!r}")
    return sorted(out)


def _resolve(root: Unit, address: dict) -> Unit:
    occ = int(address.get("occurrence", 0)) or None
    if "qualname" in address:
        qn = address["qualname"]
        matches = [u for u in _iter_units(root) if u.qualname == qn]
        label = f"qualname={qn!r}"
    elif "section_number" in address:
        n = str(address["section_number"]).strip()
        matches = [u for u in _iter_units(root) if u.qualname == n]
        label = f"section_number={n!r}"
    elif "section_title" in address:
        t = str(address["section_title"]).lower()
        matches = [u for u in _iter_units(root)
                   if u.kind == UnitKind.SECTION and t in u.name.lower()]
        label = f"section_title={t!r}"
    else:
        raise KeyError("address must have qualname / section_number / section_title")
    if not matches:
        raise KeyError(f"not_found: {label}")
    if len(matches) == 1:
        return matches[0]
    if occ is None:
        where = ", ".join(f"L{u.line_start}" for u in matches)
        raise KeyError(f"ambiguous: {label} — matches at {where}; pass occurrence")
    if occ < 1 or occ > len(matches):
        raise KeyError(f"occurrence_out_of_range: {occ} for {len(matches)} matches")
    return matches[occ - 1]


def _slice(source: str, part: Part) -> str:
    if not part.is_present():
        return ""
    lines = source.splitlines()
    s = max(0, part.start - 1)
    e = min(len(lines), part.end)
    return "\n".join(lines[s:e])


def _slice_lines(source: str, a: int, b: int) -> str:
    lines = source.splitlines()
    return "\n".join(lines[max(0, a - 1):min(len(lines), b)])


def _render_unit(source: str, unit: Unit, parts: list[str], blocks: list[int]) -> str:
    if blocks:
        return _render_blocks(source, unit, parts, blocks)
    if not parts or parts == ["all"]:
        return _slice_lines(source, unit.line_start, unit.line_end)
    chunks: list[str] = []
    for p in ("head", "annotation", "body"):
        if p in parts:
            text = _slice(source, getattr(unit, p))
            if text:
                chunks.append(text)
    return "\n".join(chunks)


def _render_blocks(source: str, unit: Unit, parts: list[str], blocks: list[int]) -> str:
    body = unit.body
    if not body.is_present():
        raise KeyError("not_applicable: block outside body")
    if not unit.blocks:
        raise KeyError("not_applicable: this unit has no blocks")
    max_i = max(b.index for b in unit.blocks)
    for i in blocks:
        if i < 1 or i > max_i:
            raise KeyError(f"block_out_of_range: {i} (max {max_i})")
    by_index = {b.index: b for b in unit.blocks}
    multi = len(blocks) > 1
    out: list[str] = []
    for i in blocks:
        b = by_index[i]
        if multi:
            out.append(f"=== block {i} ===")
        if not parts or parts == ["all"]:
            out.append(_slice_lines(source, b.start, b.end))
        else:
            sub = b.unit
            if sub is None:
                out.append(_slice_lines(source, b.start, b.end))
            else:
                for p in ("head", "annotation", "body"):
                    if p in parts:
                        t = _slice(source, getattr(sub, p))
                        if t:
                            out.append(t)
    return "\n".join(out)


def _normalize_parts(part) -> list[str]:
    """Accept `head`, `head,annotation`, `[\"head\", \"annotation\"]`.

    A bare string may hold a comma-separated list — same format the CLI
    uses — so both `part="head,annotation"` and `part=["head", "annotation"]`
    work identically.
    """
    if part is None:
        return ["all"]
    if isinstance(part, str):
        parts = [p.strip() for p in part.split(",") if p.strip()]
    elif isinstance(part, list):
        parts = [str(p).strip() for p in part if str(p).strip()]
    else:
        raise ValueError(f"bad_part: {part!r}")
    if not parts:
        raise ValueError(f"bad_part: {part!r}")
    valid = {"all", "head", "annotation", "body"}
    for p in parts:
        if p not in valid:
            raise ValueError(f"bad_part: {p!r}")
    if "all" in parts:
        return ["all"]
    return [p for p in ("head", "annotation", "body") if p in parts]


def resolve(source: str, path: str, address: dict):
    """Resolve an address against the file's unit tree.

    Public entry point for other tools (writer.py, etc.) that need the
    resolved Unit rather than rendered text. Raises KeyError/ValueError
    on the same conditions as `read_unit`.
    """
    root = _build(source, path)
    return _resolve(root, address)


def read_unit(source: str, path: str, address: dict,
              part=None, block=None) -> str:
    root = _build(source, path)
    unit = _resolve(root, address)
    parts = _normalize_parts(part)
    blocks = _parse_blocks(block)
    if blocks and parts and parts != ["all"]:
        raise ValueError("part and block together: use block only, or part only")
    if blocks:
        parts = []
    return _render_unit(source, unit, parts, blocks)


def list_units(source: str, path: str) -> str:
    root = _build(source, path)
    rows: list[str] = []
    for u in _iter_units(root):
        rows.append(
            f"{u.qualname:<40} [{u.kind.value:<8}] "
            f"L{u.line_start}-{u.line_end}  blocks={len(u.blocks)}"
        )
    return "\n".join(rows)
