"""tree -- directory tree with per-directory aggregates and a global cap.

Shows **only directories**, not individual files. Each directory row carries:
  - total size of files directly inside it,
  - number of files directly inside it,
  - top-N file types by count, backend-supported extensions first.

Algorithm: DFS pre-order with a global ``max_dirs`` cap. When the cap hits,
remaining discovered-but-unvisited directories count as ``frontier_unexpanded``.
Subdirectories below that frontier are unknown (we never descended), so the
report says ``deeper: >=N`` rather than an exact number.

Filesystem only. MCP-only backends yield ``wrong_domain``. Hidden dirs
(matched by the workspace `.patchignore` via `backend.is_hidden`) are
skipped by default; pass `filter=false` to include them. Scope is
applied on top, same as before.
"""
from __future__ import annotations

import os
from collections import Counter, deque
from pathlib import Path
from typing import Any

from ..core.backend import Backend
from ..core.models import Result
from .scope import read_scope


# Backend-supported extensions first, in this fixed order; remaining
# extensions follow by descending count.
PRIORITY_EXTS = (".py", ".pyi", ".lua", ".luau", ".md", ".cs", ".xml")
DEFAULT_MAX_LINES = 30
DEFAULT_MAX_LINES_FILES = 100
DEFAULT_MAX_TYPES = 7


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
        max_lines: int | None = None,
        show_files: bool = False,
        max_types: int = DEFAULT_MAX_TYPES,
        show_types: bool = True,
        scoped: bool = True,
        recursive_sizes: bool = True,
        filter: bool = True,
        **_: Any,
    ) -> Result:
        if not path:
            return Result(status="error", action="tree",
                          error_code="bad_input", message="path required")
        if max_lines is None:
            max_lines = DEFAULT_MAX_LINES_FILES if show_files else DEFAULT_MAX_LINES
        try:
            max_lines = int(max_lines)
            max_types = int(max_types)
        except (TypeError, ValueError):
            return Result(status="error", action="tree",
                          error_code="bad_options",
                          message="max_lines / max_types must be ints")
        if max_lines <= 0 or max_types <= 0:
            return Result(status="error", action="tree",
                          error_code="bad_options",
                          message="max_lines / max_types must be > 0")

        rel = path.strip().strip("/")

        scope_obj = None
        exempt: set[str] = set()
        scope_err: str | None = None
        hidden_count = 0
        hidden_pi = 0
        hidden_by: dict[str, int] = {}
        if scoped:
            scope_obj, scope_err = read_scope(backend)
            if scope_err or (scope_obj and not scope_obj.rules):
                scope_obj = None
            elif scope_obj:
                exempt = scope_obj.exemptions_for(rel)

        roots = _fs_roots(backend)
        if not roots:
            return Result(
                status="error", action="tree", error_code="wrong_domain",
                message="tree работает только с файловой системой; "
                        "MCP-only backend не поддерживается",
            )

        queue: deque[tuple[Path, str, str, int]] = deque()
        implicit = roots[0][0] is None
        if implicit:
            _, root = roots[0]
            start = root if rel in ("", ".") else (root / rel)
            if not start.is_dir():
                return Result(
                    status="error", action="tree", error_code="not_found",
                    message=f"path not found or not a directory: {path}",
                )
            queue.append((start, rel or ".", "", 0))
        elif rel in ("", "."):
            for name, root in roots:
                if root.is_dir():
                    queue.append((root, name or ".", "", 0))
            if not queue:
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
                    queue.append((start, display, tail, 0))
            if not queue:
                return Result(
                    status="error", action="tree", error_code="not_found",
                    message=f"path not found or not a directory: {path}",
                )

        def _walk_recursive_totals(phys_root: Path, rel_base: str) -> dict[str, dict]:
            """Recursive totals per dir. Key: rel path ('' = root itself)."""
            stats: dict[str, dict] = {}
            def walk(phys: Path, relp: str) -> dict:
                try:
                    entries = list(os.scandir(phys))
                except OSError:
                    d = {"files": 0, "size": 0, "subdirs": 0, "types": Counter()}
                    stats[relp] = d
                    return d
                files = size = sub = 0
                types: Counter = Counter()
                for e in entries:
                    try:
                        if e.is_symlink():
                            continue
                        n = e.name
                        if e.is_dir(follow_symlinks=False):
                            child_rel = f"{relp}/{n}" if relp else n
                            if filter and backend.is_hidden(child_rel):
                                continue
                            sub += 1
                            child = walk(Path(e.path), child_rel)
                            files += child["files"]
                            size += child["size"]
                            types.update(child["types"])
                        elif e.is_file(follow_symlinks=False):
                            files += 1
                            try:
                                size += e.stat(follow_symlinks=False).st_size
                            except OSError:
                                pass
                            ext = Path(n).suffix.lower()
                            if ext:
                                types[ext] += 1
                    except OSError:
                        continue
                d = {"files": files, "size": size, "subdirs": sub, "types": types}
                stats[relp] = d
                return d
            walk(phys_root, "")
            return stats

        totals_by_display: dict[str, dict] = {}
        if recursive_sizes:
            for phys, display, relp, _depth in queue:
                subtree = _walk_recursive_totals(phys, relp)
                for r, stat in subtree.items():
                    full = f"{display}/{r}" if r else display
                    totals_by_display[full] = stat

        visited: list[dict] = []
        while queue and len(visited) < max_lines:
            phys, display, relp, depth = queue.popleft()
            try:
                entries = list(os.scandir(phys))
            except OSError:
                continue
            subdirs: list[tuple[Path, str, int]] = []
            direct_files = 0
            direct_size = 0
            direct_types: Counter = Counter()
            direct_file_names: list[str] = []
            for e in entries:
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        n = e.name
                        child_display = f"{display}/{n}"
                        child_rel = f"{relp}/{n}" if relp else n
                        if filter and backend.is_hidden(child_rel):
                            hidden_pi += 1
                            continue
                        if scope_obj is not None:
                            if scope_obj.is_hidden_ex(child_display, exempt):
                                hidden_count += 1
                                for r in reversed(scope_obj.rules):
                                    if r.negated or r.glob in exempt:
                                        continue
                                    from ..config.llmscope import _match_path
                                    if _match_path(child_display, r.glob):
                                        hidden_by[r.glob] = hidden_by.get(r.glob, 0) + 1
                                        break
                                continue
                        subdirs.append((Path(e.path), child_display, child_rel, depth + 1))
                    elif e.is_file(follow_symlinks=False):
                        n = e.name
                        child_rel = f"{relp}/{n}" if relp else n
                        if filter and backend.is_hidden(child_rel):
                            hidden_pi += 1
                            continue
                        direct_files += 1
                        try:
                            direct_size += e.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
                        ext = Path(n).suffix.lower()
                        if ext:
                            direct_types[ext] += 1
                        if show_files:
                            direct_file_names.append(n)
                except OSError:
                    continue

            pre = totals_by_display.get(display)
            if pre is not None:
                rec_files = pre["files"]
                rec_size = pre["size"]
                rec_types = pre["types"]
                n_subdirs = pre["subdirs"]
            else:
                rec_files = direct_files
                rec_size = direct_size
                rec_types = direct_types
                n_subdirs = len(subdirs)

            visited.append({
                "display": display, "depth": depth,
                "files": direct_files, "size": direct_size,
                "types": direct_types,
                "rec_files": rec_files, "rec_size": rec_size,
                "rec_types": rec_types, "subdirs_count": n_subdirs,
                "file_names": direct_file_names,
            })
            subdirs.sort(key=lambda x: x[0].name.lower())
            queue.extend(subdirs)

        if not visited:
            return Result(status="error", action="tree",
                          error_code="not_found",
                          message=f"no directories under {path!r}")

        total_files = sum(d["rec_files"] for d in visited if d["depth"] == 0)
        total_size = sum(d["rec_size"] for d in visited if d["depth"] == 0)
        max_seen = max((d["depth"] for d in visited), default=0)
        capped = len(queue) > 0
        scope_bits = ""
        if scope_err:
            scope_bits = f", scope ERR: {scope_err}"
        elif hidden_count:
            scope_bits = f", scoped: {hidden_count} hidden"
        header = (
            f"=== tree: {rel or '[' + ', '.join(n or '.' for n, _ in roots) + ']'} "
            f"({len(visited)} dirs, {total_files} files, {_human(total_size)}"
            f"{' (partial)' if capped else ''}{scope_bits}) ==="
        )
        by_depth: dict[int, list[dict]] = {}
        for d in visited:
            by_depth.setdefault(d["depth"], []).append(d)
        max_D = max(by_depth.keys()) if by_depth else 0

        def _dir_line(d: dict) -> str:
            indent = "  " * d["depth"]
            types_str = ""
            show_t = d["rec_types"] if recursive_sizes else d["types"]
            if show_types and show_t:
                t = _format_types(show_t, max_types)
                if t:
                    types_str = f", {t}"
            sub_note = ""
            if not recursive_sizes and d["subdirs_count"]:
                sub_note = f", {d['subdirs_count']} subdirs"
            size_n = d["rec_size"] if recursive_sizes else d["size"]
            files_n = d["rec_files"] if recursive_sizes else d["files"]
            return (
                f"{indent}{d['display']}  "
                f"({_human(size_n)}, {files_n} files{sub_note}{types_str})"
            )

        body: list[str] = []
        budget = max_lines
        files_available = sum(len(d.get("file_names") or []) for d in visited)
        dirs_shown = 0
        files_shown = 0

        # Root line (no N label). Its files render at N0.
        root_entry = by_depth.get(0, [None])[0] if by_depth.get(0) else None
        if root_entry is not None and budget > 0:
            body.append(_dir_line(root_entry))
            budget -= 1
            dirs_shown += 1

        # Level D block contains: dirs at depth D, then files of dirs at depth D-1.
        # So N0 = {dirs at depth 1} ∪ {files of root}, matching the BFS model.
        for D in range(1, max_D + 2):
            if budget <= 0:
                break
            dirs_at_D = by_depth.get(D, [])
            files_at_D: list[str] = []
            if show_files:
                for parent in by_depth.get(D - 1, []):
                    pdisp = parent["display"]
                    for fname in (parent.get("file_names") or []):
                        files_at_D.append(f"{pdisp}/{fname}")
            if not dirs_at_D and not files_at_D:
                continue
            body.append(f"N{D - 1}:")
            indent_D = "  " * D
            for d in dirs_at_D:
                if budget <= 0:
                    break
                body.append(_dir_line(d))
                budget -= 1
                dirs_shown += 1
            for f in files_at_D:
                if budget <= 0:
                    break
                body.append(f"{indent_D}{f}")
                budget -= 1
                files_shown += 1

        dirs_cut = len(visited) - dirs_shown
        files_cut = (files_available - files_shown) if show_files else 0
        truncated = bool(capped or dirs_cut or files_cut)

        header_final = (
            f"=== tree: {rel or '[' + ', '.join(n or '.' for n, _ in roots) + ']'} "
            f"({len(visited)} dirs, {total_files} files, {_human(total_size)}"
            f"{' (partial)' if truncated else ''}{scope_bits}) ==="
        )
        lines = [header_final] + body

        if truncated:
            bits: list[str] = [f"max_lines={max_lines}"]
            if dirs_shown or dirs_cut:
                bits.append(f"dirs {dirs_shown} of {len(visited)}")
            if files_available or files_shown:
                bits.append(f"files {files_shown} of {files_available}")
            frontier = len(queue) + dirs_cut
            if frontier > 0:
                bits.append(f"frontier+{frontier}")
            lines.append("=== stopped: " + "; ".join(bits) + " ===")

        if hidden_by and not scope_err:
            total_h = sum(hidden_by.values())
            parts = ", ".join(f"{k} {v}" for k, v in sorted(hidden_by.items()))
            lines.append(
                f"[{total_h} dir(s) hidden by scope ({parts}); pass scoped=false to include]"
            )
        if hidden_pi and not scope_err:
            lines.append(
                f"[{hidden_pi} path(s) hidden by .patchignore; pass filter=false to include]"
            )
        return Result(status="ok", action="tree", message="\n".join(lines))
