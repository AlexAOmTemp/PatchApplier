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
from dataclasses import dataclass

from ..core.backend import Backend
from ..core.models import Module, Symbol
from ..formats.code import source_hash
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
) -> CSharpIndexResult:
    skip_f = set(skip_files or DEFAULT_SKIP_FILES)
    skip_d = set(skip_dirs or DEFAULT_SKIP_DIRS)

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
        try:
            root_unit = adapter_cs.build(text, path)
        except Exception:
            continue
        if adapter_cs.parse_tree(text).root_node.has_error:
            # Broken C#: skip, like the Python indexer skips SyntaxError.
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


def _module_from_unit(path: str, source: str, root: Unit) -> Module:
    symbols: list[Symbol] = []
    _walk(root, symbols)
    usings = adapter_cs.extract_usings(source)
    n_lines = source.count("\n") + (1 if source and not source.endswith("\n") else 0)
    return Module(
        path=path,
        source=source,
        source_hash=source_hash(source),
        source_len=len(source.encode("utf-8")),
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
