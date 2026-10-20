"""Python symbol tools — operations addressed by qualname.

AST helpers live in `._ast`. All write tools validate the result with
`ast.parse` before persisting; a syntax error rolls the change back and
returns `error_code="result_syntax_error"`.
"""
from __future__ import annotations

import ast
import textwrap
from typing import Any

from ...core.backend import Backend
from ...core.models import Delta, Result
from ._ast import (
    _apply_indent, _check_target_survives, _count_lines, _dedent_block,
    _delete_symbol_lines, _delta, _eol_of, _find_all_by_qualname, _is_lua_path,
    _iter_defs, _kind_of, _line_indent, _module_head_end_line,
    _resolve_insertion, _resolve_occurrence, _sign, _start_line,
)


class ListSymbolsTool:
    name = "list_symbols"
    op = "read"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        path: str,
        include_vars: bool = False,
        **_: Any,
    ) -> Result:
        if _is_lua_path(path):
            from . import lua as _lua
            return _lua.lua_list_symbols(backend, path)
        source = backend.read(path)
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Синтаксическая ошибка в {path}: {e}",
                action="list_symbols",
                error_code="syntax_error",
            )
        out = [path]
        count = 0
        for qualname, node in _iter_defs(tree, include_vars=bool(include_vars)):
            kind = _kind_of(node)
            start = _start_line(node)
            end = node.end_lineno or node.lineno
            depth = qualname.count(".")
            indent = "  " * depth
            out.append(f"{indent}- {qualname} [{kind}] L{start}\u2013L{end}")
            count += 1
        if count == 0:
            out.append("(no symbols)")
        return Result(status="ok", message="\n".join(out), action="list_symbols")


class ReadSymbolTool:
    name = "read_symbol"
    op = "read"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        path: str,
        qualname: str,
        occurrence: int | None = None,
        **_: Any,
    ) -> Result:
        if _is_lua_path(path):
            from . import lua as _lua
            return _lua.lua_read_symbol(backend, path, qualname, occurrence)
        source = backend.read(path)
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Синтаксическая ошибка в {path}: {e}",
                action="read_symbol",
                error_code="syntax_error",
            )
        lines = source.splitlines()

        if qualname == "<module>":
            head_end = _module_head_end_line(tree)
            if head_end is None:
                body = "\n".join(lines)
                header = f"{path} [<module>] L1\u2013L{len(lines)}"
            elif head_end == 1:
                return Result(
                    status="ok",
                    message=f"{path} [<module>] (empty head)",
                    action="read_symbol",
                )
            else:
                body = "\n".join(lines[:head_end - 1])
                header = f"{path} [<module>] L1\u2013L{head_end - 1}"
            return Result(status="ok", message=f"{header}\n{body}", action="read_symbol")

        matches = _find_all_by_qualname(tree, qualname, include_vars=True)
        node, err = _resolve_occurrence(matches, occurrence, qualname, "read_symbol")
        if err is not None:
            return err
        start = _start_line(node)
        end = node.end_lineno or node.lineno
        body = "\n".join(lines[start - 1:end])
        header = f"{path} [{qualname}] L{start}\u2013L{end}"
        return Result(status="ok", message=f"{header}\n{body}", action="read_symbol")


class ReplaceSymbolTool:
    name = "replace_symbol"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
            self,
            backend: Backend,
            fmt: Any,
            path: str,
            qualname: str,
            new_code: str,
            occurrence: int | None = None,
            part: str = "all",
            **_: Any,
        ) -> Result:
        if part not in ("all", "body", "signature"):
            return Result(
                status="error",
                message=f"part: all|body|signature, получено {part!r}",
                action="replace_symbol",
                error_code="bad_part",
            )
        from ...core.tool_call import call_tool
        if part == "body":
            return call_tool(
                ReplaceSymbolBodyTool, backend, fmt,
                path=path, qualname=qualname,
                new_body=new_code, occurrence=occurrence)
        if part == "signature":
            return call_tool(
                ReplaceSymbolSignatureTool, backend, fmt,
                path=path, qualname=qualname,
                new_signature=new_code, occurrence=occurrence)

        if _is_lua_path(path):
            from . import lua as _lua
            return _lua.lua_replace_symbol(backend, path, qualname,
                                           new_code, occurrence)
        if not new_code or not new_code.strip():
            return Result(
                status="error",
                message="new_code пуст",
                action="replace_symbol",
                error_code="empty_input",
            )
        source = backend.read(path)
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Синтаксическая ошибка в {path}: {e}",
                action="replace_symbol",
                error_code="syntax_error",
            )
        matches = _find_all_by_qualname(tree, qualname, include_vars=True)
        node, err = _resolve_occurrence(matches, occurrence, qualname, "replace_symbol")
        if err is not None:
            return err

        start = _start_line(node)
        end = node.end_lineno or node.lineno

        eol = _eol_of(source)
        lines = source.splitlines()
        prefix = " " * node.col_offset
        new_lines = _apply_indent(textwrap.dedent(new_code), prefix)
        result_lines = lines[:start - 1] + new_lines + lines[end:]

        new_source = eol.join(result_lines)
        if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
            new_source += eol

        ok, ec, msg = _check_target_survives(new_source, qualname)
        if not ok:
            return Result(
                status="error",
                message=msg,
                action="replace_symbol",
                error_code=ec,
            )

        backend.write(path, new_source)
        delta = _delta(source, new_source)
        new_end = start + len(new_lines) - 1
        msg = (f"{path}: {qualname} заменён "
               f"(L{start}\u2013L{end} \u2192 L{start}\u2013L{new_end}) \u2014 "
               f"{_sign(delta.lines)} стр., {_sign(delta.bytes)} Б")
        return Result(
            status="ok",
            message=msg,
            delta=delta,
            verified=True,
            action="replace_symbol",
        )


class ReplaceSymbolBodyTool:
    name = "replace_symbol_body"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        path: str,
        qualname: str,
        new_body: str,
        occurrence: int | None = None,
        **_: Any,
    ) -> Result:
        if _is_lua_path(path):
            from . import lua as _lua
            return _lua.lua_replace_symbol_body(backend, path, qualname,
                                                new_body, occurrence)
        if not new_body or not new_body.strip():
            return Result(
                status="error",
                message="new_body пуст",
                action="replace_symbol_body",
                error_code="empty_input",
            )
        source = backend.read(path)
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Синтаксическая ошибка в {path}: {e}",
                action="replace_symbol_body",
                error_code="syntax_error",
            )
        matches = _find_all_by_qualname(tree, qualname, include_vars=False)
        node, err = _resolve_occurrence(matches, occurrence, qualname, "replace_symbol_body")
        if err is not None:
            return err
        if isinstance(node, ast.ClassDef):
            return Result(
                status="error",
                message=(f"У класса '{qualname}' нет единого тела; "
                         f"используй replace_symbol"),
                action="replace_symbol_body",
                error_code="no_body_for_class",
            )
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return Result(
                status="error",
                message=f"'{qualname}' не является функцией или методом",
                action="replace_symbol_body",
                error_code="no_body",
            )
        if not getattr(node, "body", None):
            return Result(
                status="error",
                message=f"У '{qualname}' нет тела",
                action="replace_symbol_body",
                error_code="no_body",
            )

        body_start = node.body[0].lineno
        body_end = node.end_lineno or node.lineno
        if body_start == node.lineno:
            return Result(
                status="error",
                message=(f"'{qualname}' \u2014 однострочное определение; "
                         f"используй replace_symbol"),
                action="replace_symbol_body",
                error_code="one_liner",
            )

        eol = _eol_of(source)
        lines = source.splitlines()
        prefix = " " * (node.col_offset + 4)
        new_lines = _apply_indent(textwrap.dedent(new_body), prefix)
        result_lines = lines[:body_start - 1] + new_lines + lines[body_end:]

        new_source = eol.join(result_lines)
        if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
            new_source += eol

        ok, ec, msg = _check_target_survives(new_source, qualname)
        if not ok:
            return Result(
                status="error",
                message=msg,
                action="replace_symbol_body",
                error_code=ec,
            )

        backend.write(path, new_source)
        delta = _delta(source, new_source)
        new_end = body_start + len(new_lines) - 1
        msg = (f"{path}: тело {qualname} заменено "
               f"(L{body_start}\u2013L{body_end} \u2192 L{body_start}\u2013L{new_end}) \u2014 "
               f"{_sign(delta.lines)} стр., {_sign(delta.bytes)} Б")
        return Result(
            status="ok",
            message=msg,
            delta=delta,
            verified=True,
            action="replace_symbol_body",
        )


class ReplaceSymbolSignatureTool:
    name = "replace_symbol_signature"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        path: str,
        qualname: str,
        new_signature: str,
        occurrence: int | None = None,
        **_: Any,
    ) -> Result:
        if _is_lua_path(path):
            from . import lua as _lua
            return _lua.lua_replace_symbol_signature(
                backend, path, qualname, new_signature, occurrence)
        if not new_signature or not new_signature.strip():
            return Result(
                status="error",
                message="new_signature пуст",
                action="replace_symbol_signature",
                error_code="empty_input",
            )
        source = backend.read(path)
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Синтаксическая ошибка в {path}: {e}",
                action="replace_symbol_signature",
                error_code="syntax_error",
            )
        matches = _find_all_by_qualname(tree, qualname, include_vars=True)
        node, err = _resolve_occurrence(matches, occurrence, qualname, "replace_symbol_signature")
        if err is not None:
            return err
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return Result(
                status="error",
                message=(f"'{qualname}' \u2014 не функция и не класс; "
                         f"у него нет сигнатуры. Используй replace_symbol."),
                action="replace_symbol_signature",
                error_code="no_signature",
            )
        if not node.body:
            return Result(
                status="error",
                message=f"У '{qualname}' нет тела",
                action="replace_symbol_signature",
                error_code="no_body",
            )
        body_start = node.body[0].lineno
        if body_start == node.lineno:
            return Result(
                status="error",
                message=(f"'{qualname}' \u2014 однострочное определение; "
                         f"используй replace_symbol"),
                action="replace_symbol_signature",
                error_code="one_liner",
            )
        start = _start_line(node)
        end = node.body[0].lineno - 1
        eol = _eol_of(source)
        lines = source.splitlines()
        prefix = " " * node.col_offset
        new_lines = _apply_indent(textwrap.dedent(new_signature), prefix)
        result_lines = lines[:start - 1] + new_lines + lines[end:]
        new_source = eol.join(result_lines)
        if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
            new_source += eol
        ok, ec, msg = _check_target_survives(new_source, qualname)
        if not ok:
            return Result(
                status="error",
                message=msg,
                action="replace_symbol_signature",
                error_code=ec,
            )

        backend.write(path, new_source)
        delta = _delta(source, new_source)
        new_end = start + len(new_lines) - 1
        msg = (f"{path}: сигнатура {qualname} заменена "
               f"(L{start}\u2013L{end} \u2192 L{start}\u2013L{new_end}) \u2014 "
               f"{_sign(delta.lines)} стр., {_sign(delta.bytes)} Б")
        return Result(
            status="ok",
            message=msg,
            delta=delta,
            verified=True,
            action="replace_symbol_signature",
        )


class DeleteSymbolTool:
    name = "delete_symbol"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        path: str,
        qualname: str,
        occurrence: int | None = None,
        **_: Any,
    ) -> Result:
        if _is_lua_path(path):
            from . import lua as _lua
            return _lua.lua_delete_symbol(backend, path, qualname, occurrence)
        source = backend.read(path)
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Синтаксическая ошибка в {path}: {e}",
                action="delete_symbol",
                error_code="syntax_error",
            )
        matches = _find_all_by_qualname(tree, qualname, include_vars=True)
        node, err = _resolve_occurrence(matches, occurrence, qualname, "delete_symbol")
        if err is not None:
            return err
        start = _start_line(node)
        end = node.end_lineno or node.lineno
        eol = _eol_of(source)
        lines = source.splitlines()
        del lines[start - 1:end]
        if (start - 2 >= 0 and start - 1 < len(lines)
                and not lines[start - 2].strip()
                and not lines[start - 1].strip()):
            del lines[start - 1]
        new_source = eol.join(lines)
        if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
            new_source += eol
        try:
            ast.parse(new_source)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Результат не парсится: {e}. Патч отменен.",
                action="delete_symbol",
                error_code="result_syntax_error",
            )
        backend.write(path, new_source)
        delta = _delta(source, new_source)
        msg = (f"{path}: {qualname} удалён (L{start}\u2013L{end}) \u2014 "
               f"{_sign(delta.lines)} стр., {_sign(delta.bytes)} Б")
        return Result(
            status="ok",
            message=msg,
            delta=delta,
            verified=True,
            action="delete_symbol",
        )


class InsertSymbolTool:
    name = "insert_symbol"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        path: str,
        new_code: str,
        container: str | None = None,
        position: str = "end",
        anchor: str | None = None,
        **_: Any,
    ) -> Result:
        if _is_lua_path(path):
            if container is not None:
                return Result(
                    status="error",
                    message="container не поддерживается для Lua-файлов",
                    action="insert_symbol",
                    error_code="container_not_supported",
                )
            from . import lua as _lua
            return _lua.lua_insert_symbol(backend, path, new_code,
                                          position, anchor)
        if not new_code or not new_code.strip():
            return Result(
                status="error",
                message="new_code пуст",
                action="insert_symbol",
                error_code="empty_input",
            )
        if position not in ("start", "end", "before", "after"):
            return Result(
                status="error",
                message=(f"position должен быть start|end|before|after, "
                         f"дано {position!r}"),
                action="insert_symbol",
                error_code="bad_position",
            )
        if position in ("before", "after") and not anchor:
            return Result(
                status="error",
                message=f"position={position!r} требует anchor",
                action="insert_symbol",
                error_code="anchor_required",
            )
        if position in ("start", "end") and anchor:
            return Result(
                status="error",
                message=f"position={position!r} не принимает anchor",
                action="insert_symbol",
                error_code="anchor_not_allowed",
            )
        source = backend.read(path)
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Синтаксическая ошибка в {path}: {e}",
                action="insert_symbol",
                error_code="syntax_error",
            )
        eol = _eol_of(source)
        lines = source.splitlines()
        ins = _resolve_insertion(tree, lines, container, position, anchor)
        if ins[0] is None:
            _, ec, msg = ins
            return Result(status="error", message=msg, error_code=ec,
                          action="insert_symbol")
        idx, context_indent, n_blank = ins
        new_lines = _apply_indent(textwrap.dedent(new_code), context_indent)
        sep_b = [""] * n_blank if idx > 0 and lines[idx - 1].strip() else []
        sep_a = [""] * n_blank if idx < len(lines) and lines[idx].strip() else []
        lines[idx:idx] = sep_b + new_lines + sep_a
        new_source = eol.join(lines)
        if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
            new_source += eol
        try:
            ast.parse(new_source)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Результат не парсится: {e}. Патч отменен.",
                action="insert_symbol",
                error_code="result_syntax_error",
            )
        backend.write(path, new_source)
        delta = _delta(source, new_source)
        where = f"{container} ({position})" if container else f"module ({position})"
        msg = (f"{path}: вставлено в {where} "
               f"(+{len(new_lines)} стр., {_sign(delta.bytes)} Б)")
        return Result(
            status="ok",
            message=msg,
            delta=delta,
            verified=True,
            action="insert_symbol",
        )


class MoveSymbolTool:
    name = "move_symbol"
    op = "write"
    path_args = ["path", "target_file"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        path: str,
        qualname: str,
        occurrence: int | None = None,
        target_file: str | None = None,
        container: str | None = None,
        position: str = "end",
        anchor: str | None = None,
        **_: Any,
    ) -> Result:
        if _is_lua_path(path):
            if container is not None:
                return Result(
                    status="error",
                    message="container не поддерживается для Lua-файлов",
                    action="move_symbol",
                    error_code="container_not_supported",
                )
            from . import lua as _lua
            return _lua.lua_move_symbol(backend, path, qualname,
                                        occurrence, target_file,
                                        position, anchor)
        if position not in ("start", "end", "before", "after"):
            return Result(
                status="error",
                message=(f"position должен быть start|end|before|after, "
                         f"дано {position!r}"),
                action="move_symbol",
                error_code="bad_position",
            )
        if position in ("before", "after") and not anchor:
            return Result(
                status="error",
                message=f"position={position!r} требует anchor",
                action="move_symbol",
                error_code="anchor_required",
            )
        if position in ("start", "end") and anchor:
            return Result(
                status="error",
                message=f"position={position!r} не принимает anchor",
                action="move_symbol",
                error_code="anchor_not_allowed",
            )

        source = backend.read(path)
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Синтаксическая ошибка в {path}: {e}",
                action="move_symbol",
                error_code="syntax_error",
            )
        matches = _find_all_by_qualname(tree, qualname, include_vars=True)
        node, err = _resolve_occurrence(matches, occurrence, qualname, "move_symbol")
        if err is not None:
            return err

        start = _start_line(node)
        end = node.end_lineno or node.lineno
        src_lines = source.splitlines()
        node_indent = " " * node.col_offset
        block = _dedent_block(src_lines[start - 1:end], node_indent)

        same_file = (target_file is None) or (target_file == path)

        if same_file:
            mid = _delete_symbol_lines(source, start, end)
            try:
                mid_tree = ast.parse(mid)
            except SyntaxError as e:
                return Result(
                    status="error",
                    message=f"Промежуточный результат не парсится: {e}",
                    action="move_symbol",
                    error_code="result_syntax_error",
                )
            mid_eol = _eol_of(mid)
            mid_lines = mid.splitlines()
            ins = _resolve_insertion(mid_tree, mid_lines, container, position, anchor)
            if ins[0] is None:
                _, ec, msg = ins
                return Result(status="error", message=msg, error_code=ec,
                              action="move_symbol")
            idx, indent, n_blank = ins
            new_lines = _apply_indent(block, indent)
            sep_b = [""] * n_blank if idx > 0 and mid_lines[idx - 1].strip() else []
            sep_a = [""] * n_blank if idx < len(mid_lines) and mid_lines[idx].strip() else []
            mid_lines[idx:idx] = sep_b + new_lines + sep_a
            final = mid_eol.join(mid_lines)
            if mid.endswith(("\n", "\r")) and not final.endswith(("\n", "\r")):
                final += mid_eol
            try:
                ast.parse(final)
            except SyntaxError as e:
                return Result(
                    status="error",
                    message=f"Результат не парсится: {e}. Патч отменен.",
                    action="move_symbol",
                    error_code="result_syntax_error",
                )
            leaf = qualname.rsplit(".", 1)[-1]
            expected_qn = f"{container}.{leaf}" if container else leaf
            ok, ec, msg = _check_target_survives(final, expected_qn)
            if not ok:
                return Result(status="error", action="move_symbol", error_code=ec, message=msg)
            backend.write(path, final)
            delta = _delta(source, final)
            where = f"{container} ({position})" if container else f"module ({position})"
            msg = (f"{path}: {qualname} перемещён (L{start}\u2013L{end}) "
                   f"\u2192 {where} \u2014 {_sign(delta.lines)} стр., "
                   f"{_sign(delta.bytes)} Б")
            return Result(status="ok", message=msg, delta=delta,
                          verified=True, action="move_symbol")

        # Cross-file: read target, validate insertion there first.
        try:
            tgt = backend.read(target_file)
        except FileNotFoundError:
            return Result(
                status="error",
                message=f"Целевой файл не найден: {target_file}",
                action="move_symbol",
                error_code="target_not_found",
            )
        try:
            tgt_tree = ast.parse(tgt)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Синтаксическая ошибка в {target_file}: {e}",
                action="move_symbol",
                error_code="syntax_error",
            )
        tgt_eol = _eol_of(tgt) if tgt else "\n"
        tgt_lines = tgt.splitlines()
        ins = _resolve_insertion(tgt_tree, tgt_lines, container, position, anchor)
        if ins[0] is None:
            _, ec, msg = ins
            return Result(status="error", message=msg, error_code=ec,
                          action="move_symbol")
        idx, indent, n_blank = ins
        new_lines = _apply_indent(block, indent)
        sep_b = [""] * n_blank if idx > 0 and tgt_lines[idx - 1].strip() else []
        sep_a = [""] * n_blank if idx < len(tgt_lines) and tgt_lines[idx].strip() else []
        tgt_lines[idx:idx] = sep_b + new_lines + sep_a
        new_tgt = tgt_eol.join(tgt_lines)
        if tgt.endswith(("\n", "\r")) and not new_tgt.endswith(("\n", "\r")):
            new_tgt += tgt_eol
        try:
            ast.parse(new_tgt)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Новый {target_file} не парсится: {e}. Патч отменен.",
                action="move_symbol",
                error_code="result_syntax_error",
            )

        new_src = _delete_symbol_lines(source, start, end)
        try:
            ast.parse(new_src)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Новый {path} не парсится: {e}. Патч отменен.",
                action="move_symbol",
                error_code="result_syntax_error",
            )

        leaf = qualname.rsplit(".", 1)[-1]
        expected_qn = f"{container}.{leaf}" if container else leaf
        ok, ec, msg = _check_target_survives(new_tgt, expected_qn)
        if not ok:
            return Result(status="error", action="move_symbol", error_code=ec, message=msg)
        backend.write(target_file, new_tgt)
        backend.write(path, new_src)
        delta = _delta(source, new_src)
        where = f"{container} ({position})" if container else f"module ({position})"
        msg = (f"{path} \u2192 {target_file}: {qualname} перемещён "
               f"\u2192 {where} \u2014 {_sign(delta.lines)} стр. в источнике, "
               f"+{len(new_lines)} стр. в цели")
        return Result(status="ok", message=msg, delta=delta,
                      verified=True, action="move_symbol")


def copy_symbol_impl(
    backend: Backend,
    source_file: str,
    target_file: str,
    qualname: str,
    occurrence: int | None,
    container: str | None,
    position: str,
    anchor: str | None,
) -> Result:
    """Copy a Python symbol from source_file to target_file (source untouched).

    Target file is created if missing. Duplicate qualname in target is an error.
    """
    action = "copy_unit"
    if position not in ("start", "end", "before", "after"):
        return Result(status="error", action=action, error_code="bad_position",
                      message=f"position: start|end|before|after, \u0434\u0430\u043d\u043e {position!r}")
    if position in ("before", "after") and not anchor:
        return Result(status="error", action=action, error_code="anchor_required",
                      message=f"position={position!r} \u0442\u0440\u0435\u0431\u0443\u0435\u0442 anchor")
    if position in ("start", "end") and anchor:
        return Result(status="error", action=action, error_code="anchor_not_allowed",
                      message=f"position={position!r} \u043d\u0435 \u043f\u0440\u0438\u043d\u0438\u043c\u0430\u0435\u0442 anchor")

    leaf = qualname.rsplit(".", 1)[-1]
    expected_qn = f"{container}.{leaf}" if container else leaf

    source = backend.read(source_file)
    try:
        src_tree = ast.parse(source)
    except SyntaxError as e:
        return Result(status="error", action=action, error_code="syntax_error",
                      message=f"\u0421\u0438\u043d\u0442\u0430\u043a\u0441\u0438\u0447\u0435\u0441\u043a\u0430\u044f \u043e\u0448\u0438\u0431\u043a\u0430 \u0432 {source_file}: {e}")
    matches = _find_all_by_qualname(src_tree, qualname, include_vars=True)
    node, err = _resolve_occurrence(matches, occurrence, qualname, action)
    if err is not None:
        return err
    start = _start_line(node)
    end = node.end_lineno or node.lineno
    src_lines = source.splitlines()
    node_indent = " " * node.col_offset
    block = _dedent_block(src_lines[start - 1:end], node_indent)

    if not backend.exists(target_file):
        tgt_lines = []
        tgt = ""
        tgt_tree = ast.parse("")
    else:
        tgt = backend.read(target_file)
        try:
            tgt_tree = ast.parse(tgt)
        except SyntaxError as e:
            return Result(status="error", action=action, error_code="syntax_error",
                          message=f"\u0421\u0438\u043d\u0442\u0430\u043a\u0441\u0438\u0447\u0435\u0441\u043a\u0430\u044f \u043e\u0448\u0438\u0431\u043a\u0430 \u0432 {target_file}: {e}")
        if _find_all_by_qualname(tgt_tree, expected_qn, include_vars=True):
            return Result(status="error", action=action, error_code="destination_exists",
                          message=f"{qualname!r} \u0443\u0436\u0435 \u0435\u0441\u0442\u044c \u0432 {target_file}")
        tgt_lines = tgt.splitlines()

    ins = _resolve_insertion(tgt_tree, tgt_lines, container, position, anchor)
    if ins[0] is None:
        _, ec, msg = ins
        return Result(status="error", message=msg, error_code=ec, action=action)
    tgt_eol = _eol_of(tgt) if tgt else "\n"
    idx, indent, n_blank = ins
    new_lines = _apply_indent(block, indent)
    sep_b = [""] * n_blank if idx > 0 and tgt_lines[idx - 1].strip() else []
    sep_a = [""] * n_blank if idx < len(tgt_lines) and tgt_lines[idx].strip() else []
    tgt_lines[idx:idx] = sep_b + new_lines + sep_a
    new_tgt = tgt_eol.join(tgt_lines)
    if tgt.endswith(("\n", "\r")) and not new_tgt.endswith(("\n", "\r")):
        new_tgt += tgt_eol
    if not new_tgt.endswith(("\n", "\r")):
        new_tgt += tgt_eol

    ok, ec, msg = _check_target_survives(new_tgt, expected_qn)
    if not ok:
        return Result(status="error", action=action, error_code=ec, message=msg)

    backend.write(target_file, new_tgt)
    where = f"{container} ({position})" if container else f"module ({position})"
    return Result(status="ok", action=action, verified=True,
                  message=f"{source_file} \u2192 {target_file}: {qualname} \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d "
                          f"\u2192 {where} (+{len(new_lines)} \u0441\u0442\u0440.)")


class ReplaceStatementTool:
    """Replace one statement in the body of a symbol (function, class, module).

    Statements are direct children of `node.body`: for a function — its
    statements, for a class — its method/attribute definitions, for the
    module — top-level statements. Nested statements (inside `if`, `for`,
    `with`, ...) are not addressable here; edit the containing statement
    as a whole instead.

    `index` is 1-based. Empty `new_code` deletes the statement; if it was
    the only statement, it is replaced with `pass` (Python requires a
    non-empty body). The tool does not auto-fix indentation of `new_code`
    beyond the usual dedent-then-prefix path; a syntax error rolls back.

    Python-only for now: Lua has no equivalent addressable statement unit
    in the current parser.
    """

    name = "replace_statement"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        path: str,
        qualname: str,
        index: int,
        new_code: str = "",
        occurrence: int | None = None,
        **_: Any,
    ) -> Result:
        if _is_lua_path(path):
            return Result(
                status="error",
                message=("replace_statement is Python-only; for Lua use "
                         "replace_symbol or replace_symbol_body"),
                action="replace_statement",
                error_code="lua_not_supported",
            )
        source = backend.read(path)
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return Result(
                status="error",
                message=f"Синтаксическая ошибка в {path}: {e}",
                action="replace_statement",
                error_code="syntax_error",
            )
        matches = _find_all_by_qualname(tree, qualname, include_vars=True)
        node, err = _resolve_occurrence(
            matches, occurrence, qualname, "replace_statement")
        if err is not None:
            return err
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            return Result(
                status="error",
                message=f"У '{qualname}' нет тела с statements",
                action="replace_statement",
                error_code="no_body",
            )
        try:
            idx = int(index)
        except (ValueError, TypeError):
            return Result(
                status="error",
                message=f"index должен быть числом, дано {index!r}",
                action="replace_statement",
                error_code="bad_index",
            )
        if idx < 1 or idx > len(body):
            return Result(
                status="error",
                message=(f"index {idx} вне диапазона: у '{qualname}' "
                         f"{len(body)} statements"),
                action="replace_statement",
                error_code="index_out_of_range",
            )
        stmt = body[idx - 1]
        start = stmt.lineno
        end = stmt.end_lineno or stmt.lineno
        eol = _eol_of(source)
        lines = source.splitlines()
        indent = _line_indent(lines[start - 1])

        deleting = not new_code or not new_code.strip()
        if deleting:
            if len(body) == 1:
                new_lines = [indent + "pass"]
            else:
                new_lines = []
        else:
            new_lines = _apply_indent(textwrap.dedent(new_code), indent)

        lines[start - 1:end] = new_lines
        new_source = eol.join(lines)
        if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
            new_source += eol
        try:
            ast.parse(new_source)
        except SyntaxError as e:
            return Result(
                status="error",
                message=(f"Результат не парсится (line {e.lineno}): "
                         f"{e.msg}. Патч отменен."),
                action="replace_statement",
                error_code="result_syntax_error",
            )
        ok, ec, msg = _check_target_survives(new_source, qualname)
        if not ok:
            return Result(status="error", message=msg,
                          action="replace_statement", error_code=ec)
        backend.write(path, new_source)
        delta = _delta(source, new_source)
        verb = "удалён" if deleting else "заменён"
        msg = (f"{path}: statement #{idx} в {qualname} {verb} "
               f"(L{start}\u2013L{end}) \u2014 "
               f"{_sign(delta.lines)} стр., {_sign(delta.bytes)} Б")
        return Result(
            status="ok",
            message=msg,
            delta=delta,
            verified=True,
            action="replace_statement",
        )
