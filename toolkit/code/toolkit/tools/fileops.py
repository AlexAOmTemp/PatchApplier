"""Thin file-operation tools: create, overwrite, delete, move.

All are wrappers over Backend data methods. Sandbox + whitelist checks
happen in the Patcher, before Tool.execute is called.
"""
from __future__ import annotations

from typing import Any

from ..core.backend import Backend
from ..core.models import Result


def _check_content_syntax(file_path: str, content: str) -> str | None:
    """Syntax-check content for formats we can parse. Returns None if OK.

    .py -> ast.parse; .json -> json.loads. Other extensions are not
    checked (md, txt, custom formats). This catches the common footgun
    where an LLM mis-escapes a triple quote and creates a .py file that
    cannot be imported.
    """
    from pathlib import Path as _P
    ext = _P(file_path).suffix.lower()
    if ext == ".py":
        import ast
        try:
            ast.parse(content)
        except SyntaxError as e:
            return f"content_syntax_error: {e}"
    elif ext == ".json":
        import json
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            return f"content_syntax_error: {e}"
    return None


class CreateFileTool:
    name = "create_file"
    op = "write"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        file_path: str,
        file_content: str,
        class_name: str = "ModuleScript",
        **_: Any,
    ) -> Result:
        if backend.exists(file_path):
            return Result(
                status="error",
                message=f"Файл уже существует: {file_path}. Используйте overwrite_file.",
                action="create_file",
                error_code="already_exists",
            )
        err = _check_content_syntax(file_path, file_content)
        if err is not None:
            return Result(
                status="error",
                message=f"Не создаю {file_path}: {err}",
                action="create_file",
                error_code="content_syntax_error",
            )
        create_fn = getattr(backend, "create", None)
        try:
            if callable(create_fn):
                create_fn(file_path, file_content, class_name=class_name)
            else:
                backend.write(file_path, file_content)
        except FileExistsError:
            return Result(
                status="error",
                message=f"Файл уже существует: {file_path}. Используйте overwrite_file.",
                action="create_file",
                error_code="already_exists",
            )
        except Exception as e:
            return Result(
                status="error",
                message=f"Не удалось создать {file_path}: {e}",
                action="create_file",
                error_code="create_failed",
            )
        st = backend.stat(file_path)
        return Result(
            status="ok",
            message=f"Файл создан: {file_path} ({st.lines} стр., {st.size_bytes} Б)",
            action="create_file",
        )


class OverwriteFileTool:
    name = "overwrite_file"
    op = "write"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        file_path: str,
        file_content: str,
        **_: Any,
    ) -> Result:
        err = _check_content_syntax(file_path, file_content)
        if err is not None:
            return Result(
                status="error",
                message=f"Не перезаписываю {file_path}: {err}",
                action="overwrite_file",
                error_code="content_syntax_error",
            )
        existed = backend.exists(file_path)
        before_lines = 0
        before_bytes = 0
        if existed:
            try:
                st = backend.stat(file_path)
                before_lines = st.lines
                before_bytes = st.size_bytes
            except Exception:
                pass
        backend.write(file_path, file_content)
        st_after = backend.stat(file_path)
        verb = "перезаписан" if existed else "создан"
        delta_lines = st_after.lines - before_lines
        delta_bytes = st_after.size_bytes - before_bytes
        sign_l = f"+{delta_lines}" if delta_lines >= 0 else str(delta_lines)
        sign_b = f"+{delta_bytes}" if delta_bytes >= 0 else str(delta_bytes)
        return Result(
            status="ok",
            message=f"Файл {verb}: {file_path} ({sign_l} стр., {sign_b} Б)",
            action="overwrite_file",
        )


class DeleteFileTool:
    name = "delete_file"
    op = "write"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        file_path: str,
        **_: Any,
    ) -> Result:
        if not backend.exists(file_path):
            return Result(
                status="error",
                message=f"Файл не найден: {file_path}",
                action="delete_file",
                error_code="not_found",
            )
        try:
            st = backend.stat(file_path)
            size = st.size_bytes
            lines = st.lines
        except Exception:
            size = 0
            lines = 0
        backend.delete(file_path)
        return Result(
            status="ok",
            message=f"Файл удалён: {file_path} ({lines} стр., {size} Б)",
            action="delete_file",
        )


class MoveFileTool:
    name = "move_file"
    op = "write"
    # Both paths participate in the filter check.
    path_args = ["source_path", "destination_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        source_path: str,
        destination_path: str,
        **_: Any,
    ) -> Result:
        if not backend.exists(source_path):
            return Result(
                status="error",
                message=f"Исходный файл не найден: {source_path}",
                action="move_file",
                error_code="source_not_found",
            )
        if backend.exists(destination_path):
            return Result(
                status="error",
                message=f"Файл назначения уже существует: {destination_path}",
                action="move_file",
                error_code="destination_exists",
            )
        try:
            st = backend.stat(source_path)
            size = st.size_bytes
            lines = st.lines
        except Exception:
            size = 0
            lines = 0
        backend.move(source_path, destination_path)
        return Result(
            status="ok",
            message=(f"Файл перемещён: {source_path} -> {destination_path} "
                     f"({lines} стр., {size} Б)"),
            action="move_file",
        )


class CopyFileTool:
    name = "copy_file"
    op = "write"
    path_args = ["source_path", "destination_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        source_path: str,
        destination_path: str,
        **_: Any,
    ) -> Result:
        if not backend.exists(source_path):
            return Result(
                status="error",
                message=f"\u0418\u0441\u0445\u043e\u0434\u043d\u044b\u0439 \u0444\u0430\u0439\u043b \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d: {source_path}",
                action="copy_file",
                error_code="source_not_found",
            )
        if backend.exists(destination_path):
            return Result(
                status="error",
                message=f"\u0424\u0430\u0439\u043b \u043d\u0430\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u044f \u0443\u0436\u0435 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u0435\u0442: {destination_path}",
                action="copy_file",
                error_code="destination_exists",
            )
        try:
            backend.copy(source_path, destination_path)
        except NotImplementedError as e:
            return Result(
                status="error",
                message=f"copy_file \u043d\u0435 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442\u0441\u044f \u044d\u0442\u0438\u043c backend'\u043e\u043c: {e}",
                action="copy_file",
                error_code="backend_not_supported",
            )
        try:
            st = backend.stat(destination_path)
            size = st.size_bytes
            lines = st.lines
        except Exception:
            size = 0
            lines = 0
        return Result(
            status="ok",
            message=(f"\u0424\u0430\u0439\u043b \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d: {source_path} -> {destination_path} "
                     f"({lines} \u0441\u0442\u0440., {size} \u0411)"),
            action="copy_file",
        )
