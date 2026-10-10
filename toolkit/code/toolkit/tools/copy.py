"""Unified `copy_unit` tool: copies a markdown section or a code symbol
from one file to another, without touching the source.

Selector is an object with exactly one key:
  {"section_number": "4.1"}   # .md only
  {"section_title": "Format"} # .md only
  {"qualname": "Foo.bar", "occurrence": 1}  # .py / .lua / .luau only

The key itself determines the unit type; the file extension must match it.
"""
from __future__ import annotations

from typing import Any

from ..core.backend import Backend
from ..core.models import Result
from ..formats import Format


class CopyUnitTool:
    name = "copy_unit"
    op = "write"
    path_args = ["source_file", "target_file"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Format | None,
        source_file: str,
        target_file: str,
        selector: dict | None = None,
        position: str = "end",
        anchor: str | None = None,
        container: str | None = None,
        **_: Any,
    ) -> Result:
        action = "copy_unit"
        if not isinstance(selector, dict):
            return Result(
                status="error", action=action, error_code="bad_selector",
                message="selector \u0434\u043e\u043b\u0436\u0435\u043d \u0431\u044b\u0442\u044c \u043e\u0431\u044a\u0435\u043a\u0442\u043e\u043c \u0441 \u043e\u0434\u043d\u0438\u043c \u0438\u0437 section_number / section_title / qualname",
            )
        keys = [k for k in ("section_number", "section_title", "qualname") if k in selector]
        if len(keys) != 1:
            return Result(
                status="error", action=action, error_code="bad_selector",
                message=(f"selector \u0434\u043e\u043b\u0436\u0435\u043d \u0441\u043e\u0434\u0435\u0440\u0436\u0430\u0442\u044c \u0440\u043e\u0432\u043d\u043e \u043e\u0434\u0438\u043d \u0438\u0437 "
                         f"section_number / section_title / qualname, \u0434\u0430\u043d\u043e: {list(selector.keys())}"),
            )
        key = keys[0]

        from ..core.paths import is_mcp_path
        is_md = source_file.lower().endswith(".md")
        is_lua_roblox = is_mcp_path(source_file) or source_file.lower().endswith((".lua", ".luau"))
        is_py = source_file.lower().endswith(".py")
        is_code = is_lua_roblox or is_py
        if not (is_md or is_code):
            return Result(status="error", action=action, error_code="unknown_unit",
                          message=f"\u0420\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u0438\u0435 \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0430 \u043d\u0435 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442\u0441\u044f: {source_file}")

        if is_md and key == "qualname":
            return Result(status="error", action=action, error_code="wrong_selector",
                          message="\u0414\u043b\u044f .md \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 section_number \u0438\u043b\u0438 section_title")
        if is_code and key in ("section_number", "section_title"):
            return Result(status="error", action=action, error_code="wrong_selector",
                          message="\u0414\u043b\u044f .py/.lua \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 qualname")
        if container is not None and is_md:
            return Result(status="error", action=action, error_code="container_not_supported",
                          message="container \u043d\u0435 \u043f\u0440\u0438\u043c\u0435\u043d\u0438\u043c \u043a .md")
        if not backend.exists(source_file):
            return Result(status="error", action=action, error_code="source_not_found",
                          message=f"\u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d: {source_file}")
        if source_file == target_file:
            return Result(status="error", action=action, error_code="destination_exists",
                          message="source_file \u0438 target_file \u0441\u043e\u0432\u043f\u0430\u0434\u0430\u044e\u0442; copy \u0432 \u0442\u043e\u0442 \u0436\u0435 \u0444\u0430\u0439\u043b \u043d\u0435 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u0430\u043d")

        if is_md:
            from .write import copy_section_impl
            return copy_section_impl(
                backend=backend, fmt=fmt,
                source_file=source_file, target_file=target_file,
                section_number=selector.get("section_number"),
                section_title=selector.get("section_title"),
                position=position, anchor=anchor,
            )
        from .symbols.python import copy_symbol_impl
        if container is not None and is_lua_roblox:
            return Result(status="error", action=action, error_code="container_not_supported",
                          message="container не поддерживается для Lua-файлов")
        if is_lua_roblox:
            from .symbols import lua as _lua
            return _lua.lua_copy_symbol(
                backend=backend,
                source_file=source_file, target_file=target_file,
                qualname=selector["qualname"],
                occurrence=selector.get("occurrence"),
                position=position, anchor=anchor,
            )
        return copy_symbol_impl(
            backend=backend,
            source_file=source_file, target_file=target_file,
            qualname=selector["qualname"],
            occurrence=selector.get("occurrence"),
            container=container, position=position, anchor=anchor,
        )
