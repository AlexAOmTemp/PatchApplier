"""symbol_graph — BFS traversal of the symbol call graph.

Reads the manifest built by rebuild_code_index. Call edges live in each
module's `calls` field, one entry per `ast.Call` site, with `target`
resolved to `path::qualname` when the resolver could trace it, or null
when it couldn't (dynamic access, external library, `from X import *`).

Given a root qualname, walks callees to `depth` levels and callers one
level up. Output is a compact text tree; only names, no bodies.

The graph is heuristic — see indexers/code.py:_resolve_calls for the
exact rules. Cross-module edges appear only for `import X` / `from X
import Y` forms. Everything else shows up under "unresolved".
"""
from __future__ import annotations

import json
from typing import Any

from ..core.backend import Backend
from ..core.models import Result


DEFAULT_MANIFEST = "CODE_INDEX.manifest.json"
DEFAULT_DEPTH = 1
DEFAULT_MAX_NODES = 300


class SymbolGraphTool:
    name = "symbol_graph"
    op = "read"
    path_args = ["manifest_path"]
    path_list_args: list[str] = []

    _code_manifest: str = DEFAULT_MANIFEST
    _lua_manifest: str = "CODE_INDEX_LUA.manifest.json"

    @classmethod
    def set_paths(cls, code_manifest: str, lua_manifest: str) -> None:
        cls._code_manifest = code_manifest or DEFAULT_MANIFEST
        cls._lua_manifest = lua_manifest or "CODE_INDEX_LUA.manifest.json"

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        qualname: str,
        occurrence: int | None = None,
        depth: int = DEFAULT_DEPTH,
        max_nodes: int = DEFAULT_MAX_NODES,
        manifest_path: str | None = None,
        kind: str = "code",
        local: bool = False,
        **_: Any,
    ) -> Result:
        if manifest_path is None:
            manifest_path = (self._lua_manifest if kind == "lua"
                             else self._code_manifest)
        if not qualname or not qualname.strip():
            return Result(
                status="error",
                message="qualname не может быть пустой",
                action="symbol_graph",
                error_code="empty_query",
            )
        try:
            depth = int(depth)
        except (TypeError, ValueError):
            return Result(
                status="error",
                message=f"depth должен быть целым: {depth!r}",
                action="symbol_graph",
                error_code="bad_depth",
            )
        if depth < 1:
            depth = 1
        try:
            max_nodes = int(max_nodes)
        except (TypeError, ValueError):
            return Result(
                status="error",
                message=f"max_nodes должен быть целым: {max_nodes!r}",
                action="symbol_graph",
                error_code="bad_max_nodes",
            )
        if max_nodes < 1:
            max_nodes = 1

        raw = None
        if local:
            try:
                from pathlib import Path
                raw = Path(manifest_path).read_text(encoding="utf-8")
            except Exception as e:
                return Result(
                    status="error",
                    message=f"Не могу прочитать локальный manifest {manifest_path}: {e}",
                    action="symbol_graph",
                    error_code="manifest_read_error",
                )
        else:
            if not backend.exists(manifest_path):
                return Result(
                    status="error",
                    message=(f"Manifest не найден: {manifest_path}. "
                             f"Сначала запусти rebuild_code_index."),
                    action="symbol_graph",
                    error_code="manifest_not_found",
                )
            try:
                raw = backend.read(manifest_path)
            except Exception as e:
                return Result(
                    status="error",
                    message=f"Не могу прочитать {manifest_path}: {e}",
                    action="symbol_graph",
                    error_code="manifest_read_error",
                )
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError as e:
            return Result(
                status="error",
                message=f"Manifest не парсится как JSON: {e}",
                action="symbol_graph",
                error_code="manifest_invalid",
            )
        if not isinstance(manifest, list):
            return Result(
                status="error",
                message="Manifest должен быть списком модулей",
                action="symbol_graph",
                error_code="manifest_invalid",
            )

        lookup: dict[str, dict] = {}
        for mod in manifest:
            if not isinstance(mod, dict):
                continue
            m_path = mod.get("path", "")
            for sym in mod.get("symbols", []) or []:
                if not isinstance(sym, dict):
                    continue
                qn = sym.get("qualname", "")
                if not qn:
                    continue
                key = f"{m_path}::{qn}"
                lookup[key] = {
                    "path": m_path,
                    "qualname": qn,
                    "kind": sym.get("kind", "?"),
                    "line_start": sym.get("line_start"),
                    "line_end": sym.get("line_end"),
                }

        q = qualname.strip()
        candidates: list[str] = []
        for key, info in lookup.items():
            if info["qualname"] == q:
                candidates.append(key)
        if not candidates:
            for key, info in lookup.items():
                if q in info["qualname"]:
                    candidates.append(key)
        candidates.sort()

        if not candidates:
            return Result(
                status="ok",
                message=f"Символ не найден: {qualname!r}",
                action="symbol_graph",
            )
        if len(candidates) > 1:
            if occurrence is None:
                lines = [f"Найдено несколько символов для {qualname!r}:"]
                for i, c in enumerate(candidates, start=1):
                    info = lookup[c]
                    lines.append(
                        f"  [{i}] {c}  ({info['kind']}, "
                        f"L{info['line_start']}–L{info['line_end']})")
                lines.append("")
                lines.append("Передай occurrence=N, чтобы выбрать один.")
                return Result(
                    status="error",
                    message="\n".join(lines),
                    action="symbol_graph",
                    error_code="ambiguous_symbol",
                )
            if occurrence < 1 or occurrence > len(candidates):
                return Result(
                    status="error",
                    message=(f"occurrence={occurrence} вне диапазона "
                             f"(всего {len(candidates)})"),
                    action="symbol_graph",
                    error_code="occurrence_out_of_range",
                )
            root_key = candidates[occurrence - 1]
        else:
            root_key = candidates[0]

        forward: dict[str, dict[str, list[int]]] = {}
        reverse: dict[str, list[dict]] = {}
        unresolved_map: dict[str, list[dict]] = {}

        for mod in manifest:
            if not isinstance(mod, dict):
                continue
            m_path = mod.get("path", "")
            for c in mod.get("calls", []) or []:
                if not isinstance(c, dict):
                    continue
                caller = c.get("caller", "")
                if not caller:
                    continue
                caller_key = f"{m_path}::{caller}"
                line = c.get("line", 0)
                target = c.get("target")
                if target:
                    forward.setdefault(caller_key, {}).setdefault(
                        target, []).append(line)
                    reverse.setdefault(target, []).append(
                        {"caller": caller_key, "line": line})
                else:
                    unresolved_map.setdefault(caller_key, []).append(
                        {"text": c.get("target_text", "?"), "line": line})

        root_info = lookup[root_key]
        out: list[str] = []
        out.append(
            f"{root_key}  (L{root_info['line_start']}–L{root_info['line_end']})"
            f"  [{root_info['kind']}]"
        )
        out.append("")

        visited: set[str] = {root_key}
        emitted = {"count": 0}
        skipped = {"count": 0}

        def _at_str(parent_key: str, ls: list[int]) -> str:
            p_path = parent_key.split("::", 1)[0]
            return ", ".join(f"{p_path}:L{x}" for x in sorted(ls))

        def _emit_children(parent_key: str, indent: str, cur_depth: int) -> None:
            if cur_depth > depth:
                return
            kids = forward.get(parent_key, {})
            if not kids:
                return
            for target in sorted(kids):
                if target in visited:
                    continue
                if emitted["count"] >= max_nodes:
                    skipped["count"] += 1
                    continue
                visited.add(target)
                emitted["count"] += 1
                t_info = lookup.get(target, {})
                t_qn = t_info.get("qualname", target.split("::", 1)[1])
                t_start = t_info.get("line_start", "?")
                t_end = t_info.get("line_end", "?")
                t_path = target.split("::", 1)[0]
                at = _at_str(parent_key, kids[target])
                out.append(
                    f"{indent}→ {t_qn}  ({t_path}:L{t_start}–L{t_end})  at {at}")
                _emit_children(target, indent + "  ", cur_depth + 1)

        out.append(f"calls (depth<={depth}):")
        _emit_children(root_key, "  ", 1)
        if emitted["count"] == 0:
            out.append("  (none)")
        if skipped["count"]:
            out.append(
                f"  +{skipped['count']} more (raise max_nodes or lower depth)")

        out.append("")
        callers = reverse.get(root_key, [])
        out.append(f"called by ({len(callers)}):")
        if callers:
            for c in callers:
                c_key = c["caller"]
                c_info = lookup.get(c_key, {})
                c_qn = c_info.get("qualname", c_key.split("::", 1)[1])
                c_path = c_key.split("::", 1)[0]
                c_start = c_info.get("line_start", "?")
                c_end = c_info.get("line_end", "?")
                out.append(
                    f"  ← {c_qn}  ({c_path}:L{c_start}–L{c_end})"
                    f"  at {c_path}:L{c['line']}")
        else:
            out.append("  (none)")

        unres = unresolved_map.get(root_key, [])
        if unres:
            out.append("")
            out.append(f"unresolved ({len(unres)}):")
            root_path = root_key.split("::", 1)[0]
            for u in unres:
                out.append(
                    f"  ? {u['text']}  at {root_path}:L{u['line']}")

        return Result(
            status="ok",
            message="\n".join(out),
            action="symbol_graph",
        )
