"""C# indexer — walk .cs files, parse via adapter_cs, render CODE_INDEX_CS.md.

Same shape as indexers/code.py: build_csharp_index(backend, ...) ->
CSharpIndexResult. The manifest mirrors the Python one (path / hash /
len / imports / symbols[]), so find_symbol can consume it with
kind="csharp".

No call graph and no used_by: both need a semantic model (overload
resolution, extension methods, virtual dispatch). Syntax-only — see
adapter_cs module docstring.
"""
from __future__ import annotations

import json
import zlib
from ..formats.hashing import content_hash
from dataclasses import dataclass

from ..core.backend import Backend
from ..core.models import Module, Symbol
from ..formats.renderer import render_code_index
from ..tools.unit import adapter_cs
from ..tools.unit.model import Unit, UnitKind


DEFAULT_SKIP_FILES = {"CODE_INDEX_CS.md"}

DEFAULT_SKIP_DIRS = {
    "__pycache__", ".git", ".idea", ".vscode", "venv", ".venv",
    "node_modules", "_reference", "bin", "obj",
}


@dataclass
class CSharpIndexResult:
    text: str
    manifest_json: str
    modules_count: int
    symbols_count: int
    modules: list[Module]


def build_csharp_index(
    backend: Backend,
    *,
    root: str = "",
    skip_files: set[str] | None = None,
    skip_dirs: set[str] | None = None,
    prev_manifest: list[dict] | None = None,
) -> CSharpIndexResult:
    """Build the C# index, reusing parsed modules from a previous manifest.

    Incremental path: when `prev_manifest` is given (the JSON that the
    previous run wrote), each file is only re-parsed if its crc32 differs
    from the one recorded there. Unchanged files reuse their Module —
    no parse, no snapshot walk. On RimWorld (3551 files, 20 MB) a
    no-op rebuild drops from ~9s to ~0.7s; a one-file edit costs about
    the same, because only that file is parsed.

    `prev_manifest=None` means a full build (first run, manifest missing,
    or manifest unreadable).
    """
    skip_f = set(skip_files or DEFAULT_SKIP_FILES)
    skip_d = set(skip_dirs or DEFAULT_SKIP_DIRS)

    prev_by_path = _index_prev_manifest(prev_manifest)
    paths = backend.list(root or "", "*.cs")
    modules: list[Module] = []

    for path in paths:
        if not _keep(path, skip_f, skip_d):
            continue
        if backend.filter_check(path, "index_cs"):
            continue
        try:
            text = backend.read(path)
        except Exception:
            continue

        data = text.encode("utf-8")
        file_hash = zlib.crc32(data)
        cached = prev_by_path.get(path)
        if (cached is not None
                and cached.get("hash") == file_hash
                and cached.get("content_hash")):
            modules.append(_module_from_manifest_entry(cached, path))
            continue

        if adapter_cs.parse_tree(text).root_node.has_error:
            # Broken C#: skip, like the Python indexer skips SyntaxError.
            continue
        try:
            root_unit = adapter_cs.build(text, path)
        except Exception:
            continue
        modules.append(_module_from_unit(path, text, root_unit))

    modules.sort(key=lambda m: m.path)
    text = render_code_index(modules)
    manifest = _build_manifest(modules)

    return CSharpIndexResult(
        text=text,
        manifest_json=json.dumps(manifest, ensure_ascii=False, indent=2),
        modules_count=len(modules),
        symbols_count=sum(len(m.symbols) for m in modules),
        modules=modules,
    )


def _index_prev_manifest(prev_manifest: list[dict] | None) -> dict[str, dict]:
    if not isinstance(prev_manifest, list):
        return {}
    out: dict[str, dict] = {}
    for entry in prev_manifest:
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            out[entry["path"]] = entry
    return out


def _module_from_manifest_entry(entry: dict, path: str) -> Module:
    """Reconstruct a Module from a manifest entry — no source, no parse.

    `source` is left empty on purpose: the renderer takes `lines` from
    the Module and never reads `source` when `lines` is set, and
    find_symbol only needs the manifest. Keeping source would defeat
    the point of skipping the parse.
    """
    symbols: list[Symbol] = []
    for s in entry.get("symbols", []) or []:
        if not isinstance(s, dict):
            continue
        symbols.append(Symbol(
            name=s.get("name", ""),
            qualname=s.get("qualname", ""),
            kind=s.get("kind", "?"),
            line_start=int(s.get("line_start") or 0),
            line_end=int(s.get("line_end") or 0),
            signature=s.get("signature", "") or "",
            parent=s.get("parent"),
        ))
    return Module(
        path=path,
        source="",
        source_hash=int(entry.get("hash") or 0),
        source_len=int(entry.get("len") or 0),
        content_hash=int(entry.get("content_hash") or 0),
        symbols=symbols,
        imports=list(entry.get("imports") or []),
        lines=int(entry.get("lines") or 0),
    )


def _module_from_unit(path: str, source: str, root: Unit) -> Module:
    symbols: list[Symbol] = []
    _walk(root, symbols)
    usings = adapter_cs.extract_usings(source)
    data = source.encode("utf-8")
    n_lines = source.count("\n") + (1 if source and not source.endswith("\n") else 0)
    # zlib.crc32, not the shared polynomial source_hash: the latter exists
    # to stay byte-compatible with the Lua-side indexer, and C# has no Lua
    # counterpart. The polynomial version cost ~1.9s on RimWorld's 20 MB
    # of .cs; crc32 is C-speed. Diff only compares numbers, so any stable
    # algorithm works here.
    return Module(
        path=path,
        source=source,
        source_hash=zlib.crc32(data),
        source_len=len(data),
        content_hash=content_hash(data),
        symbols=symbols,
        imports=usings,
        lines=n_lines,
    )


def _walk(unit: Unit, out: list[Symbol]) -> None:
    for b in unit.blocks:
        child = b.unit
        if child is None:
            continue
        out.append(_symbol(child))
        _walk(child, out)


def _symbol(u: Unit) -> Symbol:
    kind = "method" if u.kind == UnitKind.METHOD else "class"
    parent = None
    if "." in u.qualname:
        parent = u.qualname.rsplit(".", 1)[0]
    sig = f"{kind} {u.name}{u.title}"
    return Symbol(
        name=u.name,
        qualname=u.qualname,
        kind=kind,
        line_start=u.line_start,
        line_end=u.line_end,
        signature=sig,
        parent=parent,
    )


def _keep(path: str, skip_files: set[str], skip_dirs: set[str]) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name in skip_files:
        return False
    parts = path.replace("\\", "/").split("/")
    for p in parts[:-1]:
        if p in skip_dirs or p.startswith("."):
            return False
    return True


def _build_manifest(modules: list[Module]) -> list[dict]:
    out: list[dict] = []
    for m in modules:
        out.append({
            "path": m.path,
            "hash": m.source_hash,
            "len": m.source_len,
            "content_hash": m.content_hash,
            "lines": m.lines,
            "imports": list(m.imports),
            "used_by": [],
            "calls": [],
            "symbols": [
                {
                    "qualname": s.qualname,
                    "name": s.name,
                    "kind": s.kind,
                    "line_start": s.line_start,
                    "line_end": s.line_end,
                    "signature": s.signature,
                    "parent": s.parent,
                }
                for s in m.symbols
            ],
        })
    return out
