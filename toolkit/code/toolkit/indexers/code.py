"""Code indexer — walk .py files, parse, render CODE_INDEX.md.

Mirrors the doc indexer shape: build_index(backend, fmt, ...) -> BuildResult.
Also emits a machine-readable manifest for future symbol-tools.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..core.backend import Backend
from ..core.models import Module
from ..formats import CodeFormat
from ..formats.renderer import render_code_index


DEFAULT_SKIP_FILES = {"CODE_INDEX.md"}
import builtins as _builtins_mod

# Python builtins, minus dunder-ish privates. Used by _resolve_calls to drop
# bare-name calls (isinstance, print, len, ...) that are language noise,
# not project edges. A module that shadows a builtin keeps the edge.
_BUILTIN_NAMES: frozenset[str] = frozenset(
    n for n in dir(_builtins_mod) if not n.startswith("_")
) | frozenset({"__import__"})


DEFAULT_SKIP_DIRS = {
    "__pycache__", ".git", ".idea", ".vscode", "venv", ".venv",
    "node_modules", "_reference",
}


@dataclass
class CodeIndexResult:
    text: str
    manifest_json: str
    modules_count: int
    symbols_count: int
    modules: list[Module]


def _module_dotted(path: str) -> tuple[str, bool]:
    """Path -> (dotted_module_name, is_package).

    'pkg/a.py' -> ('pkg.a', False); 'pkg/__init__.py' -> ('pkg', True);
    'a.py' -> ('a', False).
    """
    p = path[:-3] if path.endswith(".py") else path
    parts = p.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
        is_package = True
    else:
        is_package = False
    return ".".join(parts), is_package


def _resolve_relative(importer_dotted: str, is_package: bool, raw: str) -> str | None:
    """Resolve a possibly-relative imported module name to a dotted name
    (relative to the index root). Absolute names pass through unchanged.
    Returns None if resolution is not possible.
    """
    if not raw.startswith("."):
        return raw
    level = 0
    while level < len(raw) and raw[level] == ".":
        level += 1
    rest = raw[level:]
    parts = importer_dotted.split(".") if importer_dotted else []
    # For a package (__init__.py), the importer's dotted name is already
    # the package; level=1 means "this package" (drop 0 parts).
    drop = level if not is_package else max(level - 1, 0)
    if drop > len(parts):
        return None
    base_parts = parts[: len(parts) - drop] if drop else parts
    if rest:
        if base_parts:
            return ".".join(base_parts + [rest])
        return rest
    return ".".join(base_parts) if base_parts else ""



def build_code_index(
    backend: Backend,
    *,
    root: str = "",
    skip_files: set[str] | None = None,
    skip_dirs: set[str] | None = None,
) -> CodeIndexResult:
    skip_f = set(skip_files or DEFAULT_SKIP_FILES)
    skip_d = set(skip_dirs or DEFAULT_SKIP_DIRS)
    fmt = CodeFormat.load()

    paths = backend.list(root or "", "*.py")
    modules: list[Module] = []

    for path in paths:
        if not _keep(path, skip_f, skip_d):
            continue
        if backend.filter_check(path, "index_py"):
            continue
        try:
            text = backend.read(path)
        except Exception:
            continue
        try:
            m = fmt.parse(text, path=path)
        except SyntaxError:
            # TODO: surface as a warning rather than dropping silently.
            continue
        modules.append(m)

    modules.sort(key=lambda m: m.path)
    used_by_map, uses_map = _build_import_graph(modules)
    calls_map = _resolve_calls(modules)
    cycles = _find_cycles(uses_map)
    text = render_code_index(modules, used_by_map=used_by_map,
                             uses_map=uses_map, cycles=cycles)
    manifest = _build_manifest(modules, used_by_map=used_by_map,
                               calls_map=calls_map)

    return CodeIndexResult(
        text=text,
        manifest_json=json.dumps(manifest, ensure_ascii=False, indent=2),
        modules_count=len(modules),
        symbols_count=sum(len(m.symbols) for m in modules),
        modules=modules,
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


def _build_manifest(
    modules: list[Module],
    used_by_map: dict[str, list[str]] | None = None,
    calls_map: dict[str, list[dict]] | None = None,
) -> list[dict]:
    out: list[dict] = []
    for m in modules:
        out.append({
            "path": m.path,
            "hash": m.source_hash,
            "len": m.source_len,
            "imports": list(m.imports),
            "used_by": list(used_by_map.get(m.path, [])) if used_by_map else [],
            "calls": list(calls_map.get(m.path, [])) if calls_map else [],
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


def _build_import_graph(modules: list) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build both halves of the internal import graph in one pass.

    Returns (used_by, uses):
      used_by[path] = sorted list of internal importers
      uses[path]    = sorted list of internal imports

    Only edges pointing to modules inside the same index count (internal).
    Standard library and third-party imports are ignored.
    """
    info: dict[str, tuple[str, bool]] = {
        m.path: _module_dotted(m.path) for m in modules
    }
    internal_dotted: dict[str, str] = {dotted: path for path, (dotted, _) in info.items()}

    def resolve_target(raw: str) -> str | None:
        if raw in internal_dotted:
            return internal_dotted[raw]
        # Suffix match: absolute import may use a shorter form when the
        # project has a nested package structure (e.g. 'toolkit.core' vs
        # the internal name 'toolkit.code.toolkit.core'). Match only when
        # the internal name is a unique suffix.
        suffix = "." + raw
        matches = [p for d, p in internal_dotted.items() if d.endswith(suffix)]
        if len(matches) == 1:
            return matches[0]
        return None

    used_by: dict[str, list[str]] = {m.path: [] for m in modules}
    uses: dict[str, list[str]] = {m.path: [] for m in modules}
    for m in modules:
        dotted, is_package = info[m.path]
        seen: set[str] = set()
        raw_list = getattr(m, "imported_modules", None) or []
        for raw in raw_list:
            if not raw:
                continue
            resolved = _resolve_relative(dotted, is_package, raw)
            if not resolved:
                continue
            target = resolve_target(resolved)
            if target is None or target == m.path or target in seen:
                continue
            seen.add(target)
            used_by[target].append(m.path)
            uses[m.path].append(target)
    for k in used_by:
        used_by[k].sort()
        uses[k].sort()
    return used_by, uses


def _find_cycles(uses_map: dict[str, list[str]]) -> set[str]:
    """Return paths that participate in at least one import cycle.

    Fact from the internal import graph: a path is in a cycle if it can
    reach itself by following edges. Iterative DFS with explicit color
    marking; on detecting a back-edge, walks back up the current stack
    and marks every node on the ring.

    Iterative to avoid recursion limits on deep chains.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {p: WHITE for p in uses_map}
    on_cycle: set[str] = set()

    for start in uses_map:
        if color[start] != WHITE:
            continue
        # Stack of (node, iterator-position). Path is the gray chain of nodes.
        stack: list[tuple[str, int]] = [(start, 0)]
        color[start] = GRAY
        path: list[str] = [start]
        while stack:
            node, i = stack[-1]
            neighbours = uses_map.get(node, [])
            if i < len(neighbours):
                stack[-1] = (node, i + 1)
                nxt = neighbours[i]
                c = color.get(nxt, BLACK)
                if c == GRAY:
                    # Back-edge: nodes from nxt to the top of path form a cycle.
                    if nxt in path:
                        idx = path.index(nxt)
                        on_cycle.update(path[idx:])
                elif c == WHITE:
                    color[nxt] = GRAY
                    stack.append((nxt, 0))
                    path.append(nxt)
            else:
                color[node] = BLACK
                stack.pop()
                path.pop()
    return on_cycle


def _resolve_calls(modules: list) -> dict[str, list[dict]]:
    """Resolve raw `target_text` from each module's `.calls` into a
    qualified target when possible.

    Returns path -> list of edges:
        {"caller": qualname | "<module>", "line": int,
         "target_text": str, "target": "path::qualname" | None}

    Heuristic. Resolved: local names, `self.X` (enclosing class), cross-module
    names imported by `import X` / `import X as Y` / `from X import Y`.
    Everything else (dynamic access, `from X import *`, non-trivial
    expressions) is left with target=None.

    Bare Python builtins (`isinstance`, `print`, `len`, ...) are dropped
    entirely — they are language, not project edges. So is `variable.method`
    where `variable` is neither a local symbol nor an import binding: without
    type inference we can never resolve the class of a local, and it would
    flood the unresolved bucket with noise. `self.X` is kept — the enclosing
    class is known from the caller's qualname.
    """
    info = {m.path: _module_dotted(m.path) for m in modules}
    internal_dotted = {dotted: path for path, (dotted, _) in info.items()}

    def resolve_module(raw: str) -> str | None:
        if raw in internal_dotted:
            return internal_dotted[raw]
        suffix = "." + raw
        matches = [p for d, p in internal_dotted.items() if d.endswith(suffix)]
        if len(matches) == 1:
            return matches[0]
        return None

    syms = {m.path: {s.qualname for s in m.symbols} for m in modules}
    classes = {
        m.path: {s.qualname for s in m.symbols if s.kind == "class"}
        for m in modules
    }

    # Bindings with relative-import normalization applied at populate time:
    # `..core.models` becomes `toolkit.code.toolkit.core.models`, which is
    # what resolve_module can then match exactly. Without this step every
    # relative import falls through to unresolved, which is most imports in
    # this project.
    bindings: dict[str, dict[str, tuple[str, str | None]]] = {}
    for m in modules:
        dotted, is_package = info[m.path]
        b: dict[str, tuple[str, str | None]] = {}
        for ib in getattr(m, "import_bindings", []) or []:
            raw_dotted = ib["dotted"]
            resolved = _resolve_relative(dotted, is_package, raw_dotted)
            if resolved is None:
                resolved = raw_dotted
            b[ib["local"]] = (resolved, ib.get("attr"))
        bindings[m.path] = b

    def resolve_one(path: str, caller: str, text: str) -> str | None:
        parts = text.split(".")
        local_syms = syms.get(path, set())

        if len(parts) == 1:
            name = parts[0]
            if name in local_syms:
                return f"{path}::{name}"
            b = bindings.get(path, {}).get(name)
            if b:
                dotted, attr = b
                target_path = resolve_module(dotted)
                if target_path and attr and attr in syms.get(target_path, set()):
                    return f"{target_path}::{attr}"
            return None

        if len(parts) == 2:
            head, rest = parts
            if head == "self" and "." in caller:
                cls = caller.rsplit(".", 1)[0]
                if cls in classes.get(path, set()):
                    candidate = f"{cls}.{rest}"
                    if candidate in local_syms:
                        return f"{path}::{candidate}"
            if head in local_syms:
                candidate = f"{head}.{rest}"
                if candidate in local_syms:
                    return f"{path}::{candidate}"
            b = bindings.get(path, {}).get(head)
            if b:
                dotted, attr = b
                target_path = resolve_module(dotted)
                if target_path:
                    if attr is None and rest in syms.get(target_path, set()):
                        return f"{target_path}::{rest}"
                    if attr:
                        candidate = f"{attr}.{rest}"
                        if candidate in syms.get(target_path, set()):
                            return f"{target_path}::{candidate}"
            return None

        return None

    out: dict[str, list[dict]] = {}
    for m in modules:
        edges: list[dict] = []
        local_syms = syms.get(m.path, set())
        local_binds = bindings.get(m.path, {})
        for c in getattr(m, "calls", []) or []:
            text = c.get("target_text", "")
            # Bare builtin, unshadowed — language, not project edge.
            if ("." not in text and text in _BUILTIN_NAMES
                    and text not in local_syms and text not in local_binds):
                continue
            # `variable.method` where the head is neither a local symbol nor
            # an import binding: we can never resolve its class without type
            # inference, and it would flood the unresolved bucket. `self.X`
            # is kept — the enclosing class is known from the caller.
            parts = text.split(".")
            if len(parts) == 2:
                head = parts[0]
                if (head != "self"
                        and head not in local_syms
                        and head not in local_binds):
                    continue
            target = resolve_one(m.path, c.get("caller", ""), text)
            edges.append({
                "caller": c.get("caller", ""),
                "line": c.get("line", 0),
                "target_text": text,
                "target": target,
            })
        out[m.path] = edges
    return out
