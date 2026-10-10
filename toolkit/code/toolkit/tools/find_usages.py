"""find_usages — query CODE_INDEX.manifest.json for module-level edges.

Complements find_symbol. Where find_symbol answers "where is symbol X",
this answers "who imports module X / what does module X import".
Reads the reverse graph (used_by) and forward graph (imports) already
stored in the manifest by rebuild_code_index.

Query is a case-insensitive substring matched against module path only.
"""
from __future__ import annotations

import json
from typing import Any

from ..core.backend import Backend
from ..core.models import Result


DEFAULT_MANIFEST = "CODE_INDEX.manifest.json"
DEFAULT_LIMIT = 20


class FindUsagesTool:
    name = "find_usages"
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
        backend: Backend,
        fmt: Any,
        query: str,
        manifest_path: str | None = None,
        kind: str = "code",
        limit: int = DEFAULT_LIMIT,
        local: bool = False,
        **_: Any,
    ) -> Result:
        if manifest_path is None:
            manifest_path = (self._lua_manifest if kind == "lua"
                             else self._code_manifest)
        if not query or not query.strip():
            return Result(
                status="error",
                message="query не может быть пустой",
                action="find_usages",
                error_code="empty_query",
            )

        raw = None
        if local:
            try:
                from pathlib import Path
                raw = Path(manifest_path).read_text(encoding="utf-8")
            except Exception as e:
                return Result(
                    status="error",
                    message=f"Не могу прочитать локальный manifest {manifest_path}: {e}",
                    action="find_usages",
                    error_code="manifest_read_error",
                )
        else:
            if not backend.exists(manifest_path):
                return Result(
                    status="error",
                    message=(f"Manifest не найден: {manifest_path}. "
                             f"Сначала запусти rebuild_code_index."),
                    action="find_usages",
                    error_code="manifest_not_found",
                )
            try:
                raw = backend.read(manifest_path)
            except Exception as e:
                return Result(
                    status="error",
                    message=f"Не могу прочитать {manifest_path}: {e}",
                    action="find_usages",
                    error_code="manifest_read_error",
                )

        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError as e:
            return Result(
                status="error",
                message=f"Manifest не парсится как JSON: {e}",
                action="find_usages",
                error_code="manifest_invalid",
            )
        if not isinstance(manifest, list):
            return Result(
                status="error",
                message="Manifest должен быть списком модулей",
                action="find_usages",
                error_code="manifest_invalid",
            )

        q = query.strip().lower()
        matches: list[dict] = []
        for mod in manifest:
            if not isinstance(mod, dict):
                continue
            path = mod.get("path", "")
            if q not in path.lower():
                continue
            matches.append(mod)
            if len(matches) >= limit:
                break

        if not matches:
            return Result(
                status="ok",
                message=f"Модулей не найдено: {query!r}",
                action="find_usages",
            )

        lines = [f"Найдено {len(matches)} модулей для {query!r}:"]
        for mod in matches:
            path = mod.get("path", "")
            imports = mod.get("imports") or []
            used_by = mod.get("used_by") or []
            lines.append(f"  {path}")
            if imports:
                lines.append(f"      imports:  {', '.join(imports)}")
            else:
                lines.append(f"      imports:  (none)")
            if used_by:
                lines.append(f"      used by:  {', '.join(used_by)}")
            else:
                lines.append(f"      used by:  (none)")

        return Result(status="ok", message="\n".join(lines), action="find_usages")
