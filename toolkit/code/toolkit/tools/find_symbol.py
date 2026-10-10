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
    _lua_manifest: str = "CODE_INDEX_LUA.manifest.json"

    @classmethod
    def set_paths(cls, code_manifest: str, lua_manifest: str) -> None:
        """Set default manifest paths from service_subdir resolution."""
        cls._code_manifest = code_manifest or DEFAULT_MANIFEST
        cls._lua_manifest = lua_manifest or "CODE_INDEX_LUA.manifest.json"

    def execute(
        self,
        backend,
        fmt,
        query: str,
        manifest_path: str | None = None,
        kind: str = "code",
        limit: int = DEFAULT_LIMIT,
        local: bool = False,
        **_,
    ):
        if manifest_path is None:
            manifest_path = (self._lua_manifest if kind == "lua"
                             else self._code_manifest)
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

        q = query.strip().lower()
        matches: list = []
        for mod in manifest:
            if not isinstance(mod, dict):
                continue
            path = mod.get('path', '')
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

        if not matches:
            return Result(
                status='ok',
                message=f'\u0421\u043e\u0432\u043f\u0430\u0434\u0435\u043d\u0438\u0439 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e: {query!r}',
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
        return Result(status='ok', message='\n'.join(lines), action='find_symbol')
