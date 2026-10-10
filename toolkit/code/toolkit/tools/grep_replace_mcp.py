"""grep_replace_mcp — search-and-replace over LuaSourceContainers via MCP.

Distinct from `grep_replace` (filesystem, planned): a different domain,
a different pattern language (Lua patterns, not Python regex), and a
different transport (a single execute_luau inside Studio).

Two-pass on the Studio side. Pass 1 counts replacements per file without
writing. A gate rejects empty / overflow results before any write
happens. Pass 2 writes .Source only when dry_run=False.
"""
from __future__ import annotations

from typing import Any

from ..core.backend import Backend
from ..core.models import Result
from ..core.paths import is_mcp_path


class GrepReplaceMcpTool:
    name = "grep_replace_mcp"
    op = "write"
    path_args = ["directory"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        directory: str = "",
        pattern: str | None = None,
        replacement: str | None = None,
        mappings: list[dict[str, str]] | None = None,
        fixed_strings: bool = False,
        ignore_case: bool = False,
        word_boundary: bool = False,
        max_replacements: int = 1000,
        dry_run: bool = True,
        **_: Any,
    ) -> Result:
        action = "grep_replace_mcp"

        if not directory or not is_mcp_path(directory):
            return Result(
                status="error", action=action, error_code="wrong_domain",
                message=(f"grep_replace_mcp работает только по Roblox-путям "
                         f"(ReplicatedStorage.X, ServerScriptService.Y). "
                         f"Для файловой системы — `grep_replace` (позже). "
                         f"Дано: {directory!r}"),
            )

        has_pattern = pattern is not None and pattern != ""
        has_mappings = mappings is not None
        if has_pattern and has_mappings:
            return Result(status="error", action=action, error_code="bad_input",
                          message="укажи только одно из pattern / mappings")
        if not has_pattern and not has_mappings:
            return Result(status="error", action=action, error_code="bad_input",
                          message="нужно одно из pattern / mappings")
        if has_mappings:
            if not mappings:
                return Result(status="error", action=action,
                              error_code="empty_mappings",
                              message="mappings пустой")
            if not fixed_strings:
                return Result(status="error", action=action,
                              error_code="patterns_in_mappings_not_supported",
                              message=("mappings поддерживаются только при "
                                       "fixed_strings=true (Lua patterns "
                                       "нельзя применить как набор за один проход)"))
            if ignore_case:
                return Result(status="error", action=action,
                              error_code="bad_options",
                              message="ignore_case не поддерживается с mappings")

        if has_pattern and ignore_case and not fixed_strings:
            return Result(status="error", action=action,
                          error_code="bad_options",
                          message=("ignore_case требует fixed_strings=true "
                                   "(Lua patterns с case folding небезопасны)"))
        if max_replacements <= 0:
            return Result(status="error", action=action,
                          error_code="bad_options",
                          message="max_replacements должен быть > 0")

        fn = getattr(backend, "grep_replace_mcp", None)
        if not callable(fn):
            return Result(
                status="error", action=action,
                error_code="backend_not_supported",
                message="Текущий backend не поддерживает grep_replace_mcp (нужен MCP)",
            )

        mappings_arg: list[tuple[str, str]] | None = None
        if has_mappings:
            seen: set[str] = set()
            normalized: list[tuple[str, str]] = []
            for m in mappings:
                if not isinstance(m, dict):
                    return Result(status="error", action=action,
                                  error_code="bad_mapping",
                                  message="каждый mapping — объект {from, to}")
                f = m.get("from")
                t = m.get("to")
                if not isinstance(f, str) or not isinstance(t, str):
                    return Result(status="error", action=action,
                                  error_code="bad_mapping",
                                  message="from/to должны быть строками")
                if not f:
                    return Result(status="error", action=action,
                                  error_code="empty_mapping",
                                  message="from не может быть пустым")
                if f == t:
                    return Result(status="error", action=action,
                                  error_code="noop_mapping",
                                  message=f"from == to ({f!r}); это no-op")
                if f in seen:
                    return Result(status="error", action=action,
                                  error_code="duplicate_mapping",
                                  message=f"duplicate from: {f!r}")
                seen.add(f)
                normalized.append((f, t))
            mappings_arg = normalized

        try:
            raw = fn(
                root=directory,
                pattern=pattern if has_pattern else None,
                replacement=replacement if has_pattern else None,
                mappings=mappings_arg,
                fixed_strings=bool(fixed_strings),
                ignore_case=bool(ignore_case),
                word_boundary=bool(word_boundary),
                max_replacements=int(max_replacements),
                dry_run=bool(dry_run),
            )
        except ValueError as e:
            return Result(status="error", action=action,
                          error_code="bad_options", message=str(e))
        except Exception as e:
            return Result(status="error", action=action,
                          error_code="native_error",
                          message=f"grep_replace_mcp failed: {type(e).__name__}: {e}")

        if raw == "__MISSING__":
            return Result(status="error", action=action, error_code="not_found",
                          message=f"Корень не найден: {directory}")
        if raw == "__EMPTY__":
            what = repr(pattern) if has_pattern else "(mappings)"
            return Result(status="error", action=action,
                          error_code="no_matches",
                          message=f"Совпадений не найдено: {what}")

        if raw.startswith("__OVERFLOW__\t"):
            parts = raw.split("\t")
            found = parts[1] if len(parts) > 1 else "?"
            limit = parts[2] if len(parts) > 2 else "?"
            return Result(
                status="error", action=action,
                error_code="too_many_replacements",
                message=(f"Слишком широкий паттерн: найдено {found} замен, "
                         f"лимит {limit}. Ничего не изменено. "
                         f"Уточни pattern / добавь word_boundary=true / "
                         f"сузь scope / подними max_replacements."),
            )

        lines = raw.split("\n")
        changed: list[tuple[str, int]] = []
        summary: dict[str, str] = {}
        for ln in lines:
            if not ln:
                continue
            if ln.startswith("CHANGED\t"):
                parts = ln.split("\t")
                if len(parts) == 3:
                    try:
                        changed.append((parts[1], int(parts[2])))
                    except ValueError:
                        pass
            elif ln.startswith("__SUMMARY__\t"):
                for kv in ln.split("\t")[1:]:
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        summary[k] = v

        files = summary.get("files", str(len(changed)))
        repls = summary.get("replacements", str(sum((c for _, c in changed), 0)))
        applied = summary.get("applied", "false") == "true"
        mode = "APPLIED" if applied else "dry_run"
        header = f"[{mode}] файлов: {files}, замен: {repls}"
        body = "\n".join(f"  {p}\t({n})" for p, n in changed)
        return Result(status="ok", action=action, message=header + "\n" + body)