"""Lua bulk indexer — runs the Lua-side parser and driver inside Studio.

Replaces the Python-side bulk path that walked the DataModel via
`read_many` and parsed every script locally. Python sends one
`execute_luau` per chunk; `code_index_regen.lua` walks the DataModel,
parses each script with `lua_symbols.lua`, and returns a bounded JSON
chunk. Python assembles the index and manifest from those chunks.

Requires `backend.execute(code, datamodel_type)`. For filesystem
backends there is no `execute`, so `RebuildLuaCodeIndexTool` returns
`error_code="requires_mcp"` before reaching here.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..core.backend import Backend


_LUA_DIR = Path(__file__).resolve().parent.parent / "lua"
_LUA_PARSER = _LUA_DIR / "lua_symbols.lua"
_LUA_DRIVER = _LUA_DIR / "code_index_regen.lua"

_MAX_CHUNKS = 100


@dataclass
class LuaIndexResult:
    text: str
    manifest_json: str
    modules_count: int
    symbols_count: int


def _flatten_parser(src: str) -> str:
    text = src.replace("function M.parse(src)", "local function parse(src)")
    stripped = text.rstrip()
    if stripped.endswith("return M"):
        text = stripped[:-len("return M")].rstrip()
    return text


def _make_payload(cursor: int) -> str:
    parser_flat = _flatten_parser(_LUA_PARSER.read_text(encoding="utf-8"))
    driver = _LUA_DRIVER.read_text(encoding="utf-8")
    return (
        f"__cursor = {cursor}\n"
        "-- === begin lua_symbols.lua (flattened) ===\n"
        + parser_flat + "\n"
        + "-- === end lua_symbols.lua ===\n"
        + "-- === begin code_index_regen.lua ===\n"
        + driver + "\n"
        + "-- === end code_index_regen.lua ===\n"
    )


def _augment_symbol(s: dict) -> dict:
    """Match the shape produced by formats.lua.parse_lua_symbols."""
    qn = s.get("qualname", "") or ""
    name = qn.rsplit(".", 1)[-1] if "." in qn else qn
    if ":" in name:
        name = name.rsplit(":", 1)[-1]
    return {
        "qualname": qn,
        "name": name,
        "kind": s.get("kind", "unknown"),
        "line_start": int(s.get("line_start", 0) or 0),
        "line_end": int(s.get("line_end", 0) or 0),
        "hash": int(s.get("hash", 0) or 0),
        "signature": "",
        "parent": None,
    }


def _build_manifest(
    items: list[dict],
    used_by_map: dict[str, list[str]] | None = None,
) -> list[dict]:
    out: list[dict] = []
    for m in items:
        path = m.get("path", "")
        out.append({
            "path": path,
            "hash": m.get("hash", 0),
            "len": m.get("len", 0),
            "imports": list(m.get("imports") or []),
            "used_by": list((used_by_map or {}).get(path, [])),
            "symbols": [_augment_symbol(s) for s in (m.get("symbols") or [])],
        })
    return out


def _normalize_lua_path(raw: str) -> str:
    """game.ReplicatedStorage.X -> ReplicatedStorage.X; other forms pass through."""
    if isinstance(raw, str) and raw.startswith("game."):
        return raw[5:]
    return raw


def _invert_lua_imports(items: list[dict]) -> dict[str, list[str]]:
    """Reverse dependency map for Lua modules: {path: [importer_path, ...]}.

    Import targets come from the Luau driver as absolute DataModel paths
    (typically `game.ReplicatedStorage.X`). Resolution is exact after
    stripping the optional `game.` prefix.

    Dynamic `require` (string concat, variable module names) is not
    visible here and is simply absent from the graph. See DECISIONS.md.
    """
    by_path = {m.get("path", ""): m for m in items}
    used_by: dict[str, list[str]] = {m.get("path", ""): [] for m in items}
    for m in items:
        src = m.get("path", "")
        seen: set[str] = set()
        for raw in m.get("imports") or []:
            if not isinstance(raw, str) or not raw:
                continue
            norm = _normalize_lua_path(raw)
            if norm not in by_path or norm == src or norm in seen:
                continue
            seen.add(norm)
            used_by[norm].append(src)
    for k in used_by:
        used_by[k].sort()
    return used_by


def _render_index(
    items: list[dict],
    used_by_map: dict[str, list[str]] | None = None,
) -> str:
    from ..formats.renderer import CODE_PREAMBLE

    def _is_vendor(p: str) -> bool:
        # Roblox paths are dotted; check segments, not substrings.
        # ReplicatedStorage.Packages.TestEZ, X._Index.foo@1.0 — vendor.
        for seg in p.lower().replace("\\", "/").split("."):
            if seg in ("packages", "_index", "vendor", "node_modules"):
                return True
        return False

    def _is_test(p: str) -> bool:
        q = "/" + p.lower().replace("\\", "/").lstrip("/")
        return ".__tests__." in q or ".tests." in q or "/tests/" in q

    parts: list[str] = list(CODE_PREAMBLE)
    items = sorted(
        items,
        key=lambda m: (_is_vendor(m.get("path", "")), m.get("path", "")),
    )
    for m in items:
        path = m.get("path", "")
        lines = m.get("lines", 0)
        size_kb = (m.get("len", 0) or 0) / 1024.0
        markers: list[str] = []
        if _is_test(path):
            markers.append("[tests/]")
        if _is_vendor(path):
            markers.append("[vendor/]")
        if lines > 300 or size_kb > 16.0:
            markers.append("⚠ large")
        suffix = ("  " + " ".join(markers)) if markers else ""
        parts.append("")
        parts.append("")
        parts.append(f"## {path}  ({lines} стр., {size_kb:.1f} KB){suffix}")
        parts.append(f"Hash: {m.get('hash', 0)}  Len: {m.get('len', 0)}")
        imports = m.get("imports") or []
        if imports:
            parts.append("Imports: " + ", ".join(imports))
        if used_by_map:
            ub = used_by_map.get(path) or []
            if ub:
                parts.append("Used by: " + ", ".join(ub))
        syms = m.get("symbols") or []
        if not syms:
            parts.append("(no symbols)")
        else:
            for s in syms:
                qn = s.get("qualname", "")
                depth = qn.count(".")
                indent = "  " * depth
                parts.append(
                    f"{indent}- {qn} [{s.get('kind', '?')}] "
                    f"(L{s.get('line_start', 0)}–L{s.get('line_end', 0)}) "
                    f"H{s.get('hash', 0)}"
                )
    return "\n".join(parts) + "\n"


def build_lua_index(
    backend: Backend,
    roots: list[str] | None = None,
    project_dir: Path | None = None,
) -> LuaIndexResult:
    """Build the Lua index via one or more execute_luau calls.

    `roots` is accepted for backwards compatibility with the old
    Python-side bulk path but ignored: roots are fixed in the Lua
    driver. Roblox paths are not subject to path policy (see
    DECISIONS.md).
    """
    if not _LUA_PARSER.is_file() or not _LUA_DRIVER.is_file():
        raise RuntimeError(
            f"Lua parser/driver not found: {_LUA_PARSER}, {_LUA_DRIVER}"
        )

    t0 = time.time()
    items: list[dict] = []
    cursor = 0
    total_reported = None
    chunk_count = 0

    while chunk_count < _MAX_CHUNKS:
        chunk_count += 1
        payload = _make_payload(cursor)
        raw = backend.execute(payload, datamodel_type="Edit")
        try:
            data = json.loads(raw)
        except Exception as e:
            raise RuntimeError(
                f"lua driver returned non-JSON: {e}: {raw[:200]!r}"
            )
        if not isinstance(data, dict):
            raise RuntimeError(
                f"lua driver returned {type(data).__name__}, expected dict"
            )
        chunk = data.get("items") or []
        items.extend(chunk)
        total_reported = int(data.get("total", 0))
        if data.get("done"):
            break
        next_cursor = int(data.get("next_cursor", 0))
        if next_cursor <= cursor:
            raise RuntimeError(
                f"lua driver cursor did not advance ({cursor} -> {next_cursor})"
            )
        cursor = next_cursor

    # Skip patterns from `.mcpignore` (segment-based, dot-separated paths).
    # Applied before the reverse graph and rendering so skipped modules
    # do not leak into `Used by:` lines of user modules.
    items_before_filter = len(items)
    if project_dir is not None:
        from ..config import mcpignore
        patterns = mcpignore.read(Path(project_dir))
        if patterns:
            items = [m for m in items
                     if not mcpignore.path_hidden(m.get("path", ""), patterns)]

    hidden = items_before_filter - len(items)

    elapsed = time.time() - t0
    # `sys.stderr` is None under pythonw.exe (no console attached). All
    # diagnostics here are best-effort — guard instead of crashing the
    # whole rebuild when the GUI runs without a console.
    _err = sys.stderr
    if _err is not None:
        if total_reported is not None and total_reported != items_before_filter:
            _err.write(
                f"[lua.index.lua] WARN total={total_reported} != received={items_before_filter}\n"
            )
        if hidden:
            _err.write(
                f"[lua.index.lua] hidden={hidden} by .mcpignore\n"
            )

    used_by_map = _invert_lua_imports(items)
    text = _render_index(items, used_by_map=used_by_map)
    manifest = _build_manifest(items, used_by_map=used_by_map)
    n_syms = sum(len(m.get("symbols") or []) for m in items)
    if _err is not None:
        _err.write(
            f"[lua.index.lua] chunks={chunk_count} modules={len(items)} "
            f"symbols={n_syms} total={elapsed:.3f}s\n"
        )
        _err.flush()
    return LuaIndexResult(
        text=text,
        manifest_json=json.dumps(manifest, ensure_ascii=False, indent=2),
        modules_count=len(items),
        symbols_count=n_syms,
    )
