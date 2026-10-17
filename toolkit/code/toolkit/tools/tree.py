"""tree -- directory tree with per-directory aggregates and a global cap.

Shows **only directories**, not individual files. Each directory row carries:
  - total size of files directly inside it,
  - number of files directly inside it,
  - top-N file types by count, backend-supported extensions first.

Algorithm: DFS pre-order with a global ``max_dirs`` cap. When the cap hits,
remaining discovered-but-unvisited directories count as ``frontier_unexpanded``.
Subdirectories below that frontier are unknown (we never descended), so the
report says ``deeper: >=N`` rather than an exact number.

Filesystem only. MCP-only backends yield ``wrong_domain``. Dotdirs are
skipped by default (no `.patchignore` parsing here -- that lives in the
backend; this tool is a read-only aggregate for reconnaissance).
"""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any

from ..core.backend import Backend
from ..core.models import Result


# Backend-supported extensions first, in this fixed order; remaining
# extensions follow by descending count.
PRIORITY_EXTS = (".py", ".pyi", ".lua", ".luau", ".md", ".cs", ".xml")
DEFAULT_MAX_DIRS = 500
DEFAULT_MAX_TYPES = 7
DEFAULT_MAX_DEPTH = 50


def _human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    v = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        v /= 1024.0
        if v < 1024:
            return f"{v:.1f} {unit}"
    return f"{v:.1f} PB"


def _fs_roots(backend: Backend) -> list[tuple[str | None, Path]]:
    """Return [(name_or_None, Path)] for FS roots.

    - MultiDomainBackend: recurses into its 'fs' sub-backend only.
    - MultiRootFsBackend: returns [(root_name, root_path)] for each root.
    - RootDirBackend: returns [(None, _root)] -- one implicit root.
    """
    pairs = getattr(backend, "_pairs", None)
    if pairs is not None:
        for name, sub in pairs:
            if name == "fs":
                return _fs_roots(sub)
        return []
    roots = getattr(backend, "roots", None)
    if roots is not None:
        return [(n, Path(fb._root)) for n, fb in roots.items()
                if getattr(fb, "_root", None) is not None]
    r = getattr(backend, "_root", None)
    if r is not None:
        return [(None, Path(r))]
    return []


def _format_types(counts: Counter, max_types: int) -> str:
    if not counts:
        return ""
    priority = [(ext, counts[ext]) for ext in PRIORITY_EXTS if counts.get(ext)]
    others = sorted(
        ((ext, n) for ext, n in counts.items() if ext not in PRIORITY_EXTS),
        key=lambda x: (-x[1], x[0]),
    )
    ordered = priority + others
    show = ordered[:max_types]
    rest = len(ordered) - len(show)
    parts = [f"{ext} {n}" for ext, n in show]
    if rest > 0:
        parts.append(f"+{rest} more")
    return ", ".join(parts)


class TreeTool:
    name = "tree"
    op = "read"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        max_dirs: int = DEFAULT_MAX_DIRS,
        max_types: int = DEFAULT_MAX_TYPES,
        max_depth: int = DEFAULT_MAX_DEPTH,
        show_types: bool = True,
        **_: Any,
    ) -> Result:
        if not path:
            return Result(status="error", action="tree",
                          error_code="bad_input", message="path required")
        try:
            max_dirs = int(max_dirs)
            max_types = int(max_types)
            max_depth = int(max_depth)
        except (TypeError, ValueError):
            return Result(status="error", action="tree",
                          error_code="bad_options",
                          message="max_dirs / max_types / max_depth must be ints")
        if max_dirs <= 0 or max_types <= 0 or max_depth < 0:
            return Result(status="error", action="tree",
                          error_code="bad_options",
                          message="max_dirs / max_types must be > 0; max_depth >= 0")

        rel = path.strip().strip("/")
        roots = _fs_roots(backend)
        if not roots:
            return Result(
                status="error", action="tree", error_code="wrong_domain",
                message="tree работает только с файловой системой; "
                        "MCP-only backend не поддерживается",
            )

        # Resolve `path` to a starting set of (physical, display, depth).
        # Semantics mirror `read`/`list`: for a concrete path the first
        # segment selects the root by name; only the empty path ("" / ".")
        # means "all roots". RootDirBackend has an implicit root -- any
        # path is root-relative.
        stack: list[tuple[Path, str, int]] = []
        implicit = roots[0][0] is None
        if implicit:
            _, root = roots[0]
            start = root if rel in ("", ".") else (root / rel)
            if not start.is_dir():
                return Result(
                    status="error", action="tree", error_code="not_found",
                    message=f"path not found or not a directory: {path}",
                )
            stack.append((start, rel or ".", 0))
        elif rel in ("", "."):
            for name, root in roots:
                if root.is_dir():
                    stack.append((root, name or ".", 0))
            if not stack:
                return Result(
                    status="error", action="tree", error_code="not_found",
                    message=f"no roots available under {path!r}",
                )
        else:
            head, _, tail = rel.partition("/")
            matches = [(n, r) for n, r in roots if n == head]
            if not matches:
                return Result(
                    status="error", action="tree", error_code="not_found",
                    message=(
                        f"root {head!r} not in workspace "
                        f"(known: {sorted(n for n, _ in roots if n)})"
                    ),
                )
            for name, root in matches:
                start = root / tail if tail else root
                display = f"{name}/{tail}" if tail else name
                if start.is_dir():
                    stack.append((start, display, 0))
            if not stack:
                return Result(
                    status="error", action="tree", error_code="not_found",
                    message=f"path not found or not a directory: {path}",
                )

        visited: list[dict] = []
        # DFS pre-order (LIFO stack). Push in reverse so leftmost child is
        # visited first, yielding an alphabetically-correct pre-order for a
        # stable-looking tree.
        while stack and len(visited) < max_dirs:
            phys, display, depth = stack.pop()
            if depth > max_depth:
                continue
            try:
                entries = list(os.scandir(phys))
            except OSError:
                continue
            subdirs: list[tuple[Path, str, int]] = []
            files = 0
            size = 0
            types: Counter = Counter()
            for e in entries:
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        n = e.name
                        if n.startswith("."):
                            continue
                        subdirs.append((Path(e.path), f"{display}/{n}", depth + 1))
                    elif e.is_file(follow_symlinks=False):
                        files += 1
                        try:
                            size += e.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
                        ext = Path(e.name).suffix.lower()
                        if ext:
                            types[ext] += 1
                except OSError:
                    continue
            visited.append({
                "display": display, "depth": depth,
                "files": files, "size": size, "types": types,
            })
            subdirs.sort(key=lambda x: x[0].name.lower())
            stack.extend(reversed(subdirs))

        total_files = sum(d["files"] for d in visited)
        total_size = sum(d["size"] for d in visited)
        max_seen = max((d["depth"] for d in visited), default=0)

        capped = len(stack) > 0
        header = (
            f"=== tree: {rel or '[' + ', '.join(n or '.' for n, _ in roots) + ']'} "
            f"({len(visited)} dirs, {total_files} files, {_human(total_size)}"
            f"{' (partial)' if capped else ''}) ==="
        )
        lines = [header]
        for d in visited:
            indent = "  " * d["depth"]
            types_str = ""
            if show_types and d["types"]:
                t = _format_types(d["types"], max_types)
                if t:
                    types_str = f", {t}"
            lines.append(
                f"{indent}{d['display']}  "
                f"({_human(d['size'])}, {d['files']} files{types_str})"
            )
        if capped:
            lines.append(
                f"=== stopped: max_dirs={max_dirs} reached at depth {max_seen}; "
                f"frontier_unexpanded={len(stack)} (deeper: >={len(stack)}) ==="
            )
        return Result(status="ok", action="tree", message="\n".join(lines))
