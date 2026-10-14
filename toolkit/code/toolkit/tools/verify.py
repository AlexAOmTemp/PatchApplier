"""verify_syntax — compile-only check for Python files and directories.

No imports, no execution: builtin `compile(src, path, "exec")` parses
each target. Catches syntax errors and most class-level mistakes that would
only surface at import time. Safe to call on live code — no side effects.

Replaces the ad-hoc `run_python(script="manual/verify_syntax.py")`
pattern with a standard tool: one call, structured Result, no need to
remember the script path.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.backend import Backend
from ..core.models import Result


class VerifySyntaxTool:
    name = "verify_syntax"
    op = "read"
    path_args: list[str] = []
    path_list_args = ["paths"]

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        paths: list[str] | str | None = None,
        directory: str = "",
        **_: Any,
    ) -> Result:
        targets: list[str] = []
        if isinstance(paths, str):
            targets.append(paths)
        elif isinstance(paths, list):
            targets.extend(p for p in paths if isinstance(p, str) and p)
        if directory:
            targets.append(directory)
        if not targets:
            return Result(
                status="error", action="verify_syntax",
                error_code="empty_input",
                message="нужен `paths` (список файлов/каталогов) или `directory`",
            )

        files: list[str] = []
        for t in targets:
            try:
                if backend.exists(t):
                    st = backend.stat(t)
                else:
                    return Result(
                        status="error", action="verify_syntax",
                        error_code="not_found",
                        message=f"не найдено: {t}",
                    )
            except Exception as e:
                return Result(
                    status="error", action="verify_syntax",
                    error_code="stat_failed",
                    message=f"{t}: {type(e).__name__}: {e}",
                )
            if st.is_file:
                if not t.endswith(".py"):
                    return Result(
                        status="error", action="verify_syntax",
                        error_code="not_python",
                        message=f"не .py файл: {t}",
                    )
                files.append(t)
            else:
                try:
                    listed = backend.list(t, "*.py")
                except Exception as e:
                    return Result(
                        status="error", action="verify_syntax",
                        error_code="list_failed",
                        message=f"{t}: {type(e).__name__}: {e}",
                    )
                files.extend(listed)

        if not files:
            return Result(
                status="ok", action="verify_syntax",
                message=f"нечего проверять: {targets}",
            )

        failed: list[tuple[str, str]] = []
        for f in files:
            try:
                src = backend.read(f)
            except Exception as e:
                failed.append((f, f"read: {type(e).__name__}: {e}"))
                continue
            try:
                compile(src, f, "exec")
            except SyntaxError as e:
                line = e.lineno or 0
                col = e.offset or 0
                failed.append((f, f"SyntaxError L{line}:{col}: {e.msg}"))
            except Exception as e:
                failed.append((f, f"{type(e).__name__}: {e}"))

        if failed:
            head = f"{len(failed)} of {len(files)} file(s) failed"
            body = "\n".join(f"  {f}\n    {msg}" for f, msg in failed)
            return Result(
                status="error", action="verify_syntax",
                error_code="syntax_error",
                message=head + "\n" + body,
            )
        return Result(
            status="ok", action="verify_syntax",
            message=f"all {len(files)} file(s) compile",
        )
