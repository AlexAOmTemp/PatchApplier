"""Index tools: rebuild_index (markdown), rebuild_code_index (Python)."""
from __future__ import annotations

import json
from typing import Any

from ..core.backend import Backend
from ..core.models import Result
from ..formats import Format
from ..formats.renderer import render_code_structure
from ..indexers.code import _build_import_graph, _find_cycles
from .scope import read_scope
from pathlib import Path

from ..indexers.doc import build_index
from ..indexers.code import build_code_index
from ..indexers.lua_code import build_lua_code_index
from ..indexers.diff import diff_index, diff_code_index


class RebuildIndexTool:
    name = "rebuild_index"
    op = "index_docs"
    path_args: list[str] = []
    path_list_args: list[str] = []

    _default_output: str | None = None

    @classmethod
    def set_paths(cls, output: str | None = None) -> None:
        """Set default output path used when the `output` arg is absent."""
        cls._default_output = output or None

    def execute(
        self,
        backend: Backend,
        fmt: Format | None,
        docs_dir: str | None = None,
        output: str | None = None,
        skip_files: list[str] | None = None,
        **_: Any,
    ) -> Result:
        if fmt is None:
            return Result(
                status="error",
                message="rebuild_index \u0442\u0440\u0435\u0431\u0443\u0435\u0442 Format (fmt=None)",
                action="rebuild_index",
                error_code="no_format",
            )

        dd = docs_dir or ""
        out_path = (output or self._default_output
                    or (f"{dd}/INDEX.md" if dd else "INDEX.md"))

        from ..indexers.meta import resolve_path as _resolve_meta
        meta_path = _resolve_meta(out_path)

        prev_text = ""
        try:
            if backend.exists(out_path):
                prev_text = backend.read(out_path)
        except Exception:
            prev_text = ""

        default_skip = {"INDEX.md", "CODE_INDEX.md", "CODE_INDEX_LUA.md"}
        try:
            result = build_index(
                backend, fmt,
                docs_dir=dd,
                skip_files=set(skip_files) if skip_files else default_skip,
                meta_path=meta_path,
            )
        except Exception as e:
            return Result(
                status="error",
                message=f"\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0435\u0440\u0435\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u0438\u043d\u0434\u0435\u043a\u0441\u0430: {type(e).__name__}: {e}",
                action="rebuild_index",
            )

        try:
            backend.write(out_path, result.text)
        except PermissionError as e:
            return Result(
                status="blocked",
                message=str(e),
                action="rebuild_index",
                error_code="sandbox",
            )

        from ..indexers.state import bump_seq
        seq = bump_seq(backend, out_path + ".version")
        dr = diff_index(prev_text, result.text)
        msg = (f"{out_path} (\u0444\u0430\u0439\u043b\u043e\u0432: {result.files_count}, "
               f"\u0431\u0435\u0437 summary: {result.missing_summary}) [v{seq}]{dr.render()}")
        return Result(status="ok", message=msg, action="rebuild_index")


class RebuildCodeIndexTool:
    name = "rebuild_code_index"
    op = "index_py"
    path_args: list[str] = []
    path_list_args: list[str] = []

    _default_output: str | None = None
    _default_manifest: str | None = None

    @classmethod
    def set_paths(cls, output: str | None = None,
                  manifest: str | None = None) -> None:
        """Set default output / manifest paths for `rebuild_code_index`."""
        cls._default_output = output or None
        cls._default_manifest = manifest or None

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        code_dir: str | None = None,
        output: str | None = None,
        manifest_output: str | None = None,
        skip_files: list[str] | None = None,
        skip_dirs: list[str] | None = None,
        **_: Any,
    ) -> Result:
        cd = code_dir or ""
        out_path = (output or self._default_output
                    or (f"{cd}/CODE_INDEX.md" if cd else "CODE_INDEX.md"))
        manifest_path = (manifest_output or self._default_manifest
                         or out_path.replace(".md", ".manifest.json"))

        prev_text = ""
        try:
            if backend.exists(out_path):
                prev_text = backend.read(out_path)
        except Exception:
            prev_text = ""

        prev_manifest = None
        try:
            if backend.exists(manifest_path):
                import json as _json
                prev_manifest = _json.loads(backend.read(manifest_path))
        except Exception:
            prev_manifest = None

        try:
            result = build_code_index(
                backend,
                root=cd,
                skip_files=set(skip_files) if skip_files else None,
                skip_dirs=set(skip_dirs) if skip_dirs else None,
                prev_manifest=prev_manifest,
            )
        except Exception as e:
            return Result(
                status="error",
                message=f"Ошибка code index: {type(e).__name__}: {e}",
                action="rebuild_code_index",
            )

        try:
            backend.write(out_path, result.text)
            backend.write(manifest_path, result.manifest_json)
        except PermissionError as e:
            return Result(
                status="blocked",
                message=str(e),
                action="rebuild_code_index",
                error_code="sandbox",
            )

        from ..indexers.state import bump_seq
        seq = bump_seq(backend, out_path + ".version")
        dr = diff_code_index(prev_text, result.text)
        msg = (f"{out_path} + {manifest_path} "
               f"(модулей: {result.modules_count}, "
               f"символов: {result.symbols_count}) [v{seq}]{dr.render()}")
        return Result(status="ok", message=msg, action="rebuild_code_index")


class GetIndexTool:
    """Return the current on-disk index to the caller.

    The point is that an LLM does not need to know where the index lives:
    paths are resolved from config via `set_paths()` (CLI and GUI install
    the actual values before the session starts). Defaults match the
    toolkit's own layout.

    `kind` may be a single string or a list. `max_bytes` is the shared
    budget across all requested indices; when the total exceeds it, each
    index is clipped at an equal share, on a line boundary, with an
    explicit "clipped to N of M bytes" note.
    """

    name = "get_index"
    op = "index"
    path_args: list[str] = []
    path_list_args: list[str] = []

    _default_paths = {
        "docs": "INDEX.md",
        "code": "CODE_INDEX.md",
        "csharp": "CODE_INDEX_CS.md",
        "lua": "CODE_INDEX_LUA.md",
        "code_manifest": "CODE_INDEX.manifest.json",
        "csharp_manifest": "CODE_INDEX_CS.manifest.json",
        "lua_manifest": "CODE_INDEX_LUA.manifest.json",
    }
    _paths: dict[str, str] = dict(_default_paths)

    @classmethod
    def set_paths(cls, paths: dict | None) -> None:
        cls._paths = dict(cls._default_paths)
        for k, v in (paths or {}).items():
            if k in cls._paths and v:
                cls._paths[k] = str(v)

    def execute(
            self,
            backend: Backend,
            fmt: Any = None,
            kind: str | list | None = None,
            max_bytes: int | None = None,
            limit: int | None = 500,
            path: str | None = None,
            sort: str = "path",
            scoped: bool = True,
            **_: Any,
        ) -> Result:
            # -- 1. normalize kind ------------------------------------------
            # `kind` is required: the index is a map, not a dump. Asking for
            # everything at once is an anti-pattern (the LLM then skips most
            # of it), and a silent default ("docs") gave the wrong impression
            # of what was returned. Force the caller to pick a domain.
            if kind is None:
                return Result(
                    status="error",
                    message=(f"`kind` is required; valid: "
                             f"{sorted(self._paths.keys())}"),
                    error_code="kind_required",
                    action="get_index",
                )
            if isinstance(kind, str):
                raw = [kind]
            elif isinstance(kind, list):
                raw = kind
            else:
                return Result(
                    status="error",
                    message="`kind` must be a string or a list of strings.",
                    error_code="bad_kind",
                    action="get_index",
                )

            seen: set[str] = set()
            kinds: list[str] = []
            for k in raw:
                if not isinstance(k, str):
                    return Result(
                        status="error",
                        message="`kind` must contain only strings.",
                        error_code="bad_kind",
                        action="get_index",
                    )
                if k not in self._paths:
                    return Result(
                        status="error",
                        message=(f"unknown kind {k!r}; valid: "
                                 f"{sorted(self._paths.keys())}"),
                        error_code="unknown_kind",
                        action="get_index",
                    )
                if k not in seen:
                    seen.add(k)
                    kinds.append(k)

            # -- 2. budget --------------------------------------------------
            # No default cap: the index is returned in full unless the caller
            # explicitly asks to clip it. A silent 12 KB default made the
            # caller believe it had seen the map when it had seen 3%.
            if max_bytes is None:
                per_kind: int | None = None
            else:
                try:
                    cap = int(max_bytes)
                except (TypeError, ValueError):
                    cap = 0
                per_kind = max(cap // len(kinds), 256) if cap > 0 else None

            # -- 3. gather --------------------------------------------------
            _MANIFEST = {"code": "code_manifest", "csharp": "csharp_manifest",
                         "lua": "lua_manifest"}
            blocks: list[str] = []
            for k in kinds:
                if k in _MANIFEST:
                    mpath = self._paths[_MANIFEST[k]]
                    blocks.append(f"{k}: " + _get_structure(
                        backend, k, mpath, limit, path, sort, per_kind, scoped))
                    continue
                spath = self._paths[k]
                blocks.append(f"{k}: " + _get_snapshot(backend, spath, per_kind))

            return Result(
                status="ok",
                message="\n\n".join(blocks),
                action="get_index",
            )


class RebuildLuaCodeIndexTool:
    name = "rebuild_lua_code_index"
    op = "index_lua"
    path_args: list[str] = []
    path_list_args: list[str] = []

    _default_output: str | None = None
    _default_manifest: str | None = None

    @classmethod
    def set_paths(cls, output: str | None = None,
                  manifest: str | None = None) -> None:
        """Set default output / manifest paths for `rebuild_lua_code_index`."""
        cls._default_output = output or None
        cls._default_manifest = manifest or None

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        output: str | None = None,
        manifest_output: str | None = None,
        roots: list[str] | None = None,
        local_root: str | None = None,
        **_: Any,
    ) -> Result:
        # Luau bulk index runs inside Studio via the bridge. Filesystem
        # backends have no `execute` — refuse instead of silently
        # falling back to a slower Python path.
        # Luau bulk index runs inside Studio via the bridge. Filesystem
        # backends have no `execute` — refuse instead of silently
        # falling back to a slower Python path.
        if not hasattr(backend, "execute"):
            return Result(
                status="error",
                message=("rebuild_lua_code_index requires an MCP backend "
                         "(Luau driver runs inside Studio)"),
                action="rebuild_lua_code_index",
                error_code="requires_mcp",
            )

        # Output paths are backend-relative, like the Python and docs
        # rebuilds. The tool must NOT stitch them to a local filesystem
        # directory: `backend.write` already resolves them, and double-
        # prefixing (".patch_applier/.patch_applier/...") was the bug.
        out_path = output or self._default_output or "CODE_INDEX_LUA.md"
        manifest_path = (
            manifest_output or self._default_manifest
            or out_path.replace(".md", ".manifest.json")
        )

        # Where the project tree lives on disk, for `.mcpignore` bookkeeping.
        # `local_root` is an override for tests; production uses the backend
        # root (workspace state dir).
        if local_root:
            local_dir = Path(local_root)
        else:
            local_dir = Path(
                getattr(backend, "_root", None)
                or getattr(backend, "working_dir", None)
                or "."
            )

        prev_text = ""
        try:
            if backend.exists(out_path):
                prev_text = backend.read(out_path)
        except Exception:
            prev_text = ""

        try:
            from ..config import mcpignore
            mcpignore.ensure_default(local_dir)
            result = build_lua_code_index(
                backend,
                roots=roots,
                project_dir=local_dir,
            )
        except Exception as e:
            return Result(
                status="error",
                message=f"Lua code index failed: {type(e).__name__}: {e}",
                action="rebuild_lua_code_index",
            )

        try:
            backend.write(out_path, result.text)
            backend.write(manifest_path, result.manifest_json)
        except PermissionError as e:
            return Result(
                status="blocked",
                message=str(e),
                action="rebuild_lua_code_index",
                error_code="sandbox",
            )
        except Exception as e:
            return Result(
                status="error",
                message=f"Cannot write index files: {type(e).__name__}: {e}",
                action="rebuild_lua_code_index",
            )

        from ..indexers.state import bump_seq
        seq = bump_seq(backend, out_path + ".version")
        dr = diff_code_index(prev_text, result.text)
        msg = (f"{out_path} + {manifest_path} "
               f"(модулей: {result.modules_count}, "
               f"символов: {result.symbols_count}) [v{seq}]{dr.render()}")
        return Result(status="ok", message=msg, action="rebuild_lua_code_index")


def install_index_paths(cfg: dict) -> None:
    """Push resolved index paths from config into class-level defaults.

    CLI and GUI call this once per session start, so that the tools
    compute paths from `service_subdir` (+ optional overrides) without
    every call site passing them explicitly.
    """
    from ..config.loader import resolve_index_paths
    paths = resolve_index_paths(cfg)
    RebuildIndexTool.set_paths(paths["docs"])
    from .write import VerifySectionTool
    VerifySectionTool.set_paths(paths["docs"])
    RebuildCodeIndexTool.set_paths(paths["code"], paths["code_manifest"])
    RebuildCsharpIndexTool.set_paths(paths["csharp"], paths["csharp_manifest"])
    RebuildLuaCodeIndexTool.set_paths(paths["lua"], paths["lua_manifest"])
    GetIndexTool.set_paths({
        "docs": paths["docs"],
        "code": paths["code"],
        "csharp": paths["csharp"],
        "lua":  paths["lua"],
        "code_manifest": paths["code_manifest"],
        "csharp_manifest": paths["csharp_manifest"],
        "lua_manifest": paths["lua_manifest"],
    })
    from .find_symbol import FindSymbolTool
    from .find_usages import FindUsagesTool
    from .symbol_graph import SymbolGraphTool
    FindSymbolTool.set_paths(paths["code_manifest"], paths["lua_manifest"],
                             paths["csharp_manifest"])
    FindUsagesTool.set_paths(paths["code_manifest"], paths["lua_manifest"])
    SymbolGraphTool.set_paths(paths["code_manifest"], paths["lua_manifest"])

class RebuildCsharpIndexTool:
    name = "rebuild_csharp_index"
    op = "index_cs"
    path_args: list[str] = []
    path_list_args: list[str] = []

    _default_output: str | None = None
    _default_manifest: str | None = None

    @classmethod
    def set_paths(cls, output: str | None = None,
                  manifest: str | None = None) -> None:
        """Set default output / manifest paths for `rebuild_csharp_index`."""
        cls._default_output = output or None
        cls._default_manifest = manifest or None

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        code_dir: str | None = None,
        output: str | None = None,
        manifest_output: str | None = None,
        skip_files: list[str] | None = None,
        skip_dirs: list[str] | None = None,
        **_: Any,
    ) -> Result:
        cd = code_dir or ""
        out_path = (output or self._default_output
                    or (f"{cd}/CODE_INDEX_CS.md" if cd else "CODE_INDEX_CS.md"))
        manifest_path = (manifest_output or self._default_manifest
                         or out_path.replace(".md", ".manifest.json"))

        prev_text = ""
        try:
            if backend.exists(out_path):
                prev_text = backend.read(out_path)
        except Exception:
            prev_text = ""

        prev_manifest = None
        try:
            if backend.exists(manifest_path):
                import json as _json
                prev_manifest = _json.loads(backend.read(manifest_path))
        except Exception:
            prev_manifest = None

        try:
            from ..indexers.csharp import build_csharp_index
            result = build_csharp_index(
                backend,
                root=cd,
                skip_files=set(skip_files) if skip_files else None,
                skip_dirs=set(skip_dirs) if skip_dirs else None,
                prev_manifest=prev_manifest,
            )
        except Exception as e:
            return Result(
                status="error",
                message=f"Ошибка C# index: {type(e).__name__}: {e}",
                action="rebuild_csharp_index",
            )

        try:
            backend.write(out_path, result.text)
            backend.write(manifest_path, result.manifest_json)
        except PermissionError as e:
            return Result(
                status="blocked",
                message=str(e),
                action="rebuild_csharp_index",
                error_code="sandbox",
            )

        from ..indexers.state import bump_seq
        seq = bump_seq(backend, out_path + ".version")
        from ..indexers.diff import diff_code_index
        dr = diff_code_index(prev_text, result.text)
        msg = (f"{out_path} + {manifest_path} "
               f"(модулей: {result.modules_count}, "
               f"символов: {result.symbols_count}) [v{seq}]{dr.render()}")
        return Result(status="ok", message=msg, action="rebuild_csharp_index")


class _ModView:
    """Duck-typed view of a manifest entry for structure rendering.

    Only fields consumed by _module_markers / _structure_line / import
    graph are populated. Symbols are dropped: structure does not render
    them; symbol listings are handled by list_units / read_unit.
    """
    __slots__ = ("path", "source", "source_hash", "source_len",
                 "content_hash", "lines", "symbols", "imports",
                 "imported_modules", "suppress", "has_main",
                 "calls", "import_bindings")

    def __init__(self, e: dict) -> None:
        self.path = e.get("path", "")
        self.source = ""
        self.source_hash = int(e.get("hash") or 0)
        self.source_len = int(e.get("len") or 0)
        self.content_hash = int(e.get("content_hash") or 0)
        self.lines = int(e.get("lines") or 0)
        self.symbols = []
        self.imports = list(e.get("imports") or [])
        self.imported_modules = list(e.get("imported_modules") or [])
        self.suppress = frozenset(e.get("suppress") or ())
        self.has_main = bool(e.get("has_main"))
        self.calls = list(e.get("raw_calls") or [])
        self.import_bindings = list(e.get("import_bindings") or [])


def _get_snapshot(backend, path: str, per_kind: int | None) -> str:
    """Read on-disk .md, optionally clip to per_kind bytes on a line boundary."""
    from ..indexers.state import read_seq
    if not backend.exists(path):
        return f"{path}  (not found; run rebuild_index first)"
    try:
        text = backend.read(path)
    except Exception as e:
        return f"{path}  (read failed: {e})"
    ver = read_seq(backend, path + ".version")
    raw = text.encode("utf-8")
    total_b = len(raw)
    n_lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    if per_kind is None or total_b <= per_kind:
        head = f"{path} [v{ver}] ({total_b / 1024:.1f} KB, {n_lines} lines)"
        return head + "\n" + text.rstrip("\n")
    clipped = raw[:per_kind]
    nl = clipped.rfind(b"\n")
    if nl > per_kind // 2:
        clipped = clipped[:nl]
    clipped_text = clipped.decode("utf-8", errors="replace")
    head = (f"{path} [v{ver}] ({total_b / 1024:.1f} KB, {n_lines} lines, "
            f"clipped to {len(clipped)} of {total_b} bytes; pass larger max_bytes)")
    return head + "\n" + clipped_text.rstrip("\n")


def _get_structure(backend, k: str, manifest_path: str,
                   limit: int | None, path_filter: str | None,
                   sort: str, per_kind: int | None, scoped: bool = True) -> str:
    """Render one-line-per-module structure from the manifest.

    `scoped=True` (default) drops modules hidden by `.patch_applier/llmscope`
    and reports the count in a footer. `scoped=False` sees everything.
    """
    if not backend.exists(manifest_path):
        return f"{manifest_path}  (not found; run rebuild_{k}_index first)"
    try:
        text = backend.read(manifest_path)
        entries = json.loads(text)
    except Exception as e:
        return f"{manifest_path}  (read/parse failed: {e})"
    if not isinstance(entries, list):
        return f"{manifest_path}  (unexpected manifest shape)"
    mods = [_ModView(e) for e in entries if isinstance(e, dict)]

    # Subtree filter first: `path=` limits both what is rendered and which
    # paths participate in scope partition.
    pool = mods
    if path_filter:
        norm = path_filter.rstrip("/")
        pool = [m for m in pool if m.path == norm or m.path.startswith(norm + "/")]

    hidden_by: dict[str, int] = {}
    exempt: set[str] = set()
    scope_err: str | None = None
    if scoped:
        scope, scope_err = read_scope(backend)
        if not scope_err and scope.rules:
            if path_filter:
                exempt = scope.exemptions_for(path_filter)
            paths = [m.path for m in pool]
            visible, hidden_by = scope.partition(paths, exempt=exempt)
            visible_set = set(visible)
            pool = [m for m in pool if m.path in visible_set]

    used_by, uses = _build_import_graph(pool)
    cycles = _find_cycles(uses)
    lim = 500 if limit is None else int(limit)
    body, shown, total = render_code_structure(
        pool, used_by_map=used_by, uses_map=uses, cycles=cycles,
        limit=lim, path_prefix=None, sort=sort,
    )
    scope_note = ""
    if scope_err:
        scope_note = f", scope ERR: {scope_err}"
    else:
        bits = []
        if scoped and hidden_by:
            bits.append(f"scoped: {sum(hidden_by.values())} hidden")
        if exempt:
            bits.append(f"bypass: {len(exempt)} rule(s)")
        if bits:
            scope_note = ", " + "; ".join(bits)
    head = (f"structure ({shown} of {total} modules; "
            f"limit={lim}, sort={sort}"
            + (f", path={path_filter}" if path_filter else "")
            + scope_note
            + ")")
    full = head + "\n" + body.rstrip("\n")
    if per_kind is not None:
        raw = full.encode("utf-8")
        if len(raw) > per_kind:
            clipped = raw[:per_kind]
            nl = clipped.rfind(b"\n")
            if nl > per_kind // 2:
                clipped = clipped[:nl]
            full = clipped.decode("utf-8", errors="replace").rstrip("\n")
            full += f"\n... clipped to {len(clipped)} of {len(raw)} bytes"
    if scoped and hidden_by and not scope_err:
        parts = ", ".join(f"{k2} {v}" for k2, v in sorted(hidden_by.items()))
        full += f"\n[{sum(hidden_by.values())} hidden by scope ({parts}); pass scoped=false to include]"
    return full
