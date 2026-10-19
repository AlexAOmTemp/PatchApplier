"""find_symbol — search CODE_INDEX.manifest.json for symbols by name.

Reads the manifest built by rebuild_code_index, walks all modules and
symbols, and returns matches with file paths and line ranges. Query is
a case-insensitive substring matched against qualname OR module path.

Useful when you know a symbol name but not which module contains it:
no need to read files or grep across the project.
"""
from __future__ import annotations

import json
from typing import Any

from ..core.backend import Backend
from ..core.models import Result


DEFAULT_MANIFEST = "CODE_INDEX.manifest.json"
DEFAULT_LIMIT = 50


class FindSymbolTool:
    name = "find_symbol"
    op = "read"
    path_args = ["manifest_path"]
    path_list_args: list[str] = []

    _code_manifest: str = DEFAULT_MANIFEST
    _csharp_manifest: str = "CODE_INDEX_CS.manifest.json"
    _lua_manifest: str = "CODE_INDEX_LUA.manifest.json"

    @classmethod
    def set_paths(cls, code_manifest: str, lua_manifest: str,
                  csharp_manifest: str | None = None) -> None:
        """Set default manifest paths from service_subdir resolution."""
        cls._code_manifest = code_manifest or DEFAULT_MANIFEST
        cls._lua_manifest = lua_manifest or "CODE_INDEX_LUA.manifest.json"
        cls._csharp_manifest = (csharp_manifest
                                or "CODE_INDEX_CS.manifest.json")

    def execute(
        self,
        backend,
        fmt,
        query: str,
        manifest_path: str | None = None,
        kind: str = "code",
        limit: int = DEFAULT_LIMIT,
        local: bool = False,
        scoped: bool = True,
        **_,
    ):
        max_bytes = _.pop("max_bytes", None)
        _explicit_manifest = manifest_path is not None
        if manifest_path is None:
            if kind == "lua":
                manifest_path = self._lua_manifest
            elif kind == "csharp":
                manifest_path = self._csharp_manifest
            else:
                manifest_path = self._code_manifest
        if not query or not query.strip():
            return Result(
                status='error',
                message='query \u043d\u0435 \u043c\u043e\u0436\u0435\u0442 \u0431\u044b\u0442\u044c \u043f\u0443\u0441\u0442\u043e\u0439',
                action='find_symbol',
                error_code='empty_query',
            )
        # local=True: read manifest from disk (Path.read_text), not via backend.
        # Needed when manifest lives on local FS but backend is MCP (DataModel).
        raw = None
        if local:
            try:
                from pathlib import Path
                raw = Path(manifest_path).read_text(encoding='utf-8')
            except Exception as e:
                return Result(
                    status='error',
                    message=f'\u041d\u0435 \u043c\u043e\u0433\u0443 \u043f\u0440\u043e\u0447\u0438\u0442\u0430\u0442\u044c \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u044b\u0439 manifest {manifest_path}: {e}',
                    action='find_symbol',
                    error_code='manifest_read_error',
                )
        else:
            if not backend.exists(manifest_path):
                return Result(
                    status='error',
                    message=(f'Manifest \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d: {manifest_path}. '
                             f'\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0437\u0430\u043f\u0443\u0441\u0442\u0438 rebuild_code_index.'),
                    action='find_symbol',
                    error_code='manifest_not_found',
                )
            try:
                raw = backend.read(manifest_path)
            except Exception as e:
                return Result(
                    status='error',
                    message=f'\u041d\u0435 \u043c\u043e\u0433\u0443 \u043f\u0440\u043e\u0447\u0438\u0442\u0430\u0442\u044c {manifest_path}: {e}',
                    action='find_symbol',
                    error_code='manifest_read_error',
                )
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError as e:
            return Result(
                status='error',
                message=f'Manifest \u043d\u0435 \u043f\u0430\u0440\u0441\u0438\u0442\u0441\u044f \u043a\u0430\u043a JSON: {e}',
                action='find_symbol',
                error_code='manifest_invalid',
            )
        if not isinstance(manifest, list):
            return Result(
                status='error',
                message='Manifest \u0434\u043e\u043b\u0436\u0435\u043d \u0431\u044b\u0442\u044c \u0441\u043f\u0438\u0441\u043a\u043e\u043c \u043c\u043e\u0434\u0443\u043b\u0435\u0439',
                action='find_symbol',
                error_code='manifest_invalid',
            )

        # Scope applies only to the default manifest path (a scan).
        # Explicit manifest_path or local=True bypass it.
        scope_obj = None
        hidden_by: dict[str, int] = {}
        scope_err: str | None = None
        if scoped and not local and not _explicit_manifest:
            from .scope import read_scope
            scope_obj, scope_err = read_scope(backend)
            if scope_err or (scope_obj and not scope_obj.rules):
                scope_obj = None

        q = query.strip().lower()
        matches: list = []
        for mod in manifest:
            if not isinstance(mod, dict):
                continue
            path = mod.get('path', '')
            if scope_obj is not None and scope_obj.is_hidden(path):
                for r in reversed(scope_obj.rules):
                    if r.negated:
                        continue
                    from ..config.llmscope import _match_path
                    if _match_path(path, r.glob):
                        hidden_by[r.glob] = hidden_by.get(r.glob, 0) + 1
                        break
                continue
            for sym in mod.get('symbols', []):
                if not isinstance(sym, dict):
                    continue
                qn = sym.get('qualname', '')
                if q in qn.lower() or q in path.lower():
                    matches.append({
                        'path': path,
                        'qualname': qn,
                        'kind': sym.get('kind', '?'),
                        'line_start': sym.get('line_start'),
                        'line_end': sym.get('line_end'),
                        'signature': sym.get('signature', ''),
                    })
                    if len(matches) >= limit:
                        break
            if len(matches) >= limit:
                break

        footer = ""
        if hidden_by:
            n = sum(hidden_by.values())
            parts = ", ".join(f"{k} {v}" for k, v in sorted(hidden_by.items()))
            footer = (f"\n[{n} file(s) hidden by scope ({parts}); "
                      f"pass scoped=false to include]")
        if scope_err:
            footer = f"\n[scope ERR: {scope_err}]"

        if not matches:
            return Result(
                status='ok',
                message=f'\u0421\u043e\u0432\u043f\u0430\u0434\u0435\u043d\u0438\u0439 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e: {query!r}' + footer,
                action='find_symbol',
            )

        lines = [f'\u041d\u0430\u0439\u0434\u0435\u043d\u043e {len(matches)} \u0441\u043e\u0432\u043f\u0430\u0434\u0435\u043d\u0438\u0439 \u0434\u043b\u044f {query!r}:']
        for m in matches:
            lines.append(
                f"  {m['path']}  ::  {m['qualname']}  "
                f"[{m['kind']}]  L{m['line_start']}\u2013L{m['line_end']}"
            )
            if m['signature']:
                lines.append(f"      {m['signature']}")
        msg = '\n'.join(lines) + footer
        from ..core.limits import clip_with_marker, resolve_cap
        msg, _ = clip_with_marker(msg, resolve_cap(max_bytes),
            "Сузь query, задай limit=N или передай max_bytes=0 для полного вывода.")
        return Result(status='ok', message=msg, action='find_symbol')
