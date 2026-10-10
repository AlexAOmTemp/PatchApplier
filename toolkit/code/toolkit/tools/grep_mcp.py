"""grep_mcp — pattern search over Roblox LuaSourceContainers.

Distinct from `grep` (filesystem only): a different domain, a different
pattern language (Lua patterns, not Python regex), and a different
transport (a single execute_luau inside Studio, not per-file reads).
The `_mcp` suffix marks the transport (bridge), not the language —
in Rojo mode the same `.luau` files are searched by `grep`, not this
tool. Legacy name `grep_lua` is kept as an alias in `TOOL_MAP`.
"""
from __future__ import annotations

from typing import Any

from ..core.backend import Backend
from ..core.models import Result
from ..core.paths import is_mcp_path


class GrepMcpTool:
    name = "grep_mcp"
    op = "read"
    path_args = ["directory"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        pattern: str,
        directory: str = "",
        fixed_strings: bool = False,
        ignore_case: bool = False,
        word_boundary: bool = False,
        max_results: int = 200,
        before: int = 0,
        after: int = 0,
        **_: Any,
    ) -> Result:
        action = "grep_mcp"
        if not pattern:
            return Result(status="error", action=action, error_code="empty_pattern",
                          message="pattern не может быть пустым")
        if not directory or not is_mcp_path(directory):
            return Result(
                status="error", action=action, error_code="wrong_domain",
                message=(f"grep_mcp работает только по Roblox-путям "
                         f"(ReplicatedStorage.X, ServerScriptService.Y). "
                         f"Для файловой системы используй `grep`. "
                         f"Дано: {directory!r}"),
            )
        fn = getattr(backend, "grep_mcp", None)
        if not callable(fn):
            return Result(
                status="error", action=action, error_code="backend_not_supported",
                message="Текущий backend не поддерживает grep_mcp (нужен MCP)",
            )
        try:
            raw = fn(
                root=directory,
                pattern=pattern,
                fixed_strings=bool(fixed_strings),
                ignore_case=bool(ignore_case),
                word_boundary=bool(word_boundary),
                max_results=int(max_results),
                before=int(before),
                after=int(after),
            )
        except ValueError as e:
            return Result(status="error", action=action, error_code="bad_options",
                          message=str(e))
        except Exception as e:
            return Result(status="error", action=action, error_code="native_error",
                          message=f"grep_mcp failed: {type(e).__name__}: {e}")

        if raw == "__MISSING__":
            return Result(status="error", action=action, error_code="not_found",
                          message=f"Корень не найден: {directory}")
        if raw == "__EMPTY__" or not raw:
            return Result(status="ok", action=action,
                          message=f"Совпадений не найдено: {pattern!r}")

        trunc_marker = ""
        for m in ("__TRUNCATED_MATCHES__", "__TRUNCATED_BYTES__"):
            if raw.endswith(m):
                trunc_marker = m
                raw = raw[: -len(m)].rstrip("\n")
                break
        lines = raw.split("\n")
        header = f"Найдено {len(lines)} строк"
        if trunc_marker == "__TRUNCATED_MATCHES__":
            header += f" (обрезано на max_results={max_results})"
        elif trunc_marker == "__TRUNCATED_BYTES__":
            header += " (обрезано на 100 KB)"
        header += ":"
        return Result(status="ok", action=action, message=header + "\n" + raw)
