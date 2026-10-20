"""Runtime tools for the unit model — read only for now.

`read_unit` and `list_units` take a `path` and read the source via
the backend (path policy applies as for any read tool). The model itself
is in `model.py` + `adapter_*.py` + `reader.py`; see `MODEL.md` in
`manual/unit_proto/` for the specification.
"""
from __future__ import annotations

from typing import Any

from ...core.backend import Backend
from ...core.models import Result
from . import reader, writer


class ReadUnitTool:
    name = "read_unit"
    op = "read"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        address: dict | None = None,
        part: str | list | None = None,
        block: int | str | list | None = None,
        max_bytes: int | None = None,
        **_: Any,
    ) -> Result:
        if not path:
            return Result(status="error", message="path required",
                          action="read_unit", error_code="bad_input")
        if not isinstance(address, dict):
            return Result(status="error",
                          message="address must be a JSON object with qualname / section_number / section_title",
                          action="read_unit", error_code="bad_input")
        try:
            src = backend.read(path)
        except FileNotFoundError as e:
            return Result(status="error", message=str(e),
                          action="read_unit", error_code="not_found")
        except PermissionError as e:
            return Result(status="blocked", message=str(e),
                          action="read_unit", error_code="filter")
        try:
            text = reader.read_unit(src, path, address, part=part, block=block)
        except KeyError as e:
            msg = e.args[0] if e.args else str(e)
            code = "not_found"
            if msg.startswith("ambiguous"):
                code = "ambiguous_symbol"
            elif msg.startswith("occurrence_out_of_range"):
                code = "occurrence_out_of_range"
            elif msg.startswith("block_out_of_range"):
                code = "block_out_of_range"
            elif msg.startswith("not_applicable"):
                code = "not_applicable"
            return Result(status="error", message=msg, action="read_unit",
                          error_code=code)
        except ValueError as e:
            msg = str(e)
            code = "bad_argument"
            if msg.startswith("bad_part"):
                code = "bad_part"
            elif msg.startswith("bad_block"):
                code = "bad_block"
            return Result(status="error", message=msg, action="read_unit",
                          error_code=code)
        except SyntaxError as e:
            return Result(status="error", message=f"syntax_error: {e}",
                          action="read_unit", error_code="syntax_error")
        from ...core.limits import clip_with_marker, resolve_cap
        cap = resolve_cap(max_bytes)
        hint = ("Передай max_bytes=N для большего или читай по частям "
                "(part= / block= / section_number).")
        text, _ = clip_with_marker(text, cap, hint)
        return Result(status="ok", message=text, action="read_unit")


class SetAnnotationTool:
    name = "set_annotation"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        address: dict | None = None,
        text: str = "",
        **_: Any,
    ) -> Result:
        if not path:
            return Result(status="error", message="path required",
                          action="set_annotation", error_code="bad_input")
        if not isinstance(address, dict):
            return Result(status="error",
                          message="address must be a JSON object",
                          action="set_annotation", error_code="bad_input")
        try:
            src = backend.read(path)
        except FileNotFoundError as e:
            return Result(status="error", message=str(e),
                          action="set_annotation", error_code="not_found")
        except PermissionError as e:
            return Result(status="blocked", message=str(e),
                          action="set_annotation", error_code="filter")
        try:
            new = writer.set_annotation(src, path, address, text)
        except KeyError as e:
            msg = e.args[0] if e.args else str(e)
            code = "not_found"
            if msg.startswith("no_annotation"):
                code = "no_annotation"
            elif msg.startswith("ambiguous"):
                code = "ambiguous_symbol"
            return Result(status="error", message=msg,
                          action="set_annotation", error_code=code)
        except ValueError as e:
            msg = str(e)
            code = "bad_argument"
            for prefix in ("empty_input", "bad_text", "result_syntax_error",
                           "result_missing_symbol", "result_parse_error",
                           "result_missing_section"):
                if msg.startswith(prefix):
                    code = prefix
                    break
            return Result(status="error", message=msg,
                          action="set_annotation", error_code=code)
        try:
            backend.write(path, new)
        except PermissionError as e:
            return Result(status="blocked", message=str(e),
                          action="set_annotation", error_code="filter")
        from ...core.models import Delta
        old_lines = src.count("\n") + (0 if src.endswith("\n") else 1)
        new_lines = new.count("\n") + (0 if new.endswith("\n") else 1)
        delta = Delta(lines=new_lines - old_lines,
                      bytes=len(new.encode("utf-8")) - len(src.encode("utf-8")),
                      occurrences=1)
        return Result(
            status="ok",
            message=f"{path}: annotation обновлён",
            delta=delta, verified=True, action="set_annotation",
        )


class ReplaceUnitTool:
    name = "replace_unit"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        address: dict | None = None,
        new_text: str = "",
        part=None,
        block=None,
        **_: Any,
    ) -> Result:
        return _write_call(
            backend, path, "replace_unit", address,
            lambda src: writer.replace_unit(
                src, path, address, new_text, part, block),
        )


class ReplaceBlockTool:
    name = "replace_block"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        address: dict | None = None,
        block=None,
        new_text: str = "",
        **_: Any,
    ) -> Result:
        return _write_call(
            backend, path, "replace_block", address,
            lambda src: writer.replace_block(src, path, address, block, new_text),
        )


class DeleteBlockTool:
    name = "delete_block"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        address: dict | None = None,
        block=None,
        **_: Any,
    ) -> Result:
        return _write_call(
            backend, path, "delete_block", address,
            lambda src: writer.replace_block(src, path, address, block, ""),
        )


class InsertBlockTool:
    name = "insert_block"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        address: dict | None = None,
        new_text: str = "",
        position: str = "end",
        before_anchor=None,
        after_anchor=None,
        **_: Any,
    ) -> Result:
        return _write_call(
            backend, path, "insert_block", address,
            lambda src: writer.insert_block(
                src, path, address, new_text,
                position, before_anchor, after_anchor),
        )


class RemoveUnitTool:
    name = "remove_unit"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        address: dict | None = None,
        part=None,
        block=None,
        **_: Any,
    ) -> Result:
        return _write_call(
            backend, path, "remove_unit", address,
            lambda src: writer.remove_unit(src, path, address, part, block),
        )


class CreateUnitTool:
    name = "create_unit"
    op = "write"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        address: dict | None = None,
        part=None,
        new_text: str = "",
        **_: Any,
    ) -> Result:
        return _write_call(
            backend, path, "create_unit", address,
            lambda src: writer.create_unit(src, path, address, part, new_text),
        )


def _write_call(backend, path, action, address, apply_fn) -> Result:
    if not path:
        return Result(status="error", message="path required",
                      action=action, error_code="bad_input")
    if not isinstance(address, dict):
        return Result(status="error", message="address must be a JSON object",
                      action=action, error_code="bad_input")
    try:
        src = backend.read(path)
    except FileNotFoundError as e:
        return Result(status="error", message=str(e),
                      action=action, error_code="not_found")
    except PermissionError as e:
        return Result(status="blocked", message=str(e),
                      action=action, error_code="filter")
    try:
        new = apply_fn(src)
    except KeyError as e:
        msg = e.args[0] if e.args else str(e)
        code = "not_found"
        for p in ("not_applicable", "already_exists",
                  "block_out_of_range", "anchor_not_found",
                  "no_parts", "no_annotation"):
            if msg.startswith(p):
                code = p
                break
        if msg.startswith("ambiguous"):
            code = "ambiguous_symbol"
        return Result(status="error", message=msg, action=action, error_code=code)
    except ValueError as e:
        msg = str(e)
        code = "bad_argument"
        for p in ("scope_required", "scope_conflict",
                  "empty_input",
                  "bad_block_range", "bad_block", "bad_position",
                  "anchor_required", "bad_anchor", "bad_text",
                  "result_syntax_error", "result_missing_symbol",
                  "result_parse_error", "result_missing_section"):
            if msg.startswith(p):
                code = p
                break
        return Result(status="error", message=msg, action=action, error_code=code)
    try:
        backend.write(path, new)
    except PermissionError as e:
        return Result(status="blocked", message=str(e),
                      action=action, error_code="filter")
    from ...core.models import Delta
    old_lines = src.count("\n") + (0 if src.endswith("\n") else 1)
    new_lines = new.count("\n") + (0 if new.endswith("\n") else 1)
    delta = Delta(lines=new_lines - old_lines,
                  bytes=len(new.encode("utf-8")) - len(src.encode("utf-8")),
                  occurrences=1)
    return Result(status="ok", message=f"{path}: {action} применён",
                  delta=delta, verified=True, action=action)


class ListUnitsTool:
    name = "list_units"
    op = "read"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        max_bytes: int | None = None,
        **_: Any,
    ) -> Result:
        if not path:
            return Result(status="error", message="path required",
                          action="list_units", error_code="bad_input")
        try:
            src = backend.read(path)
        except FileNotFoundError as e:
            return Result(status="error", message=str(e),
                          action="list_units", error_code="not_found")
        except PermissionError as e:
            return Result(status="blocked", message=str(e),
                          action="list_units", error_code="filter")
        try:
            text = reader.list_units(src, path)
        except ValueError as e:
            return Result(status="error", message=str(e),
                          action="list_units", error_code="bad_argument")
        except SyntaxError as e:
            return Result(status="error", message=f"syntax_error: {e}",
                          action="list_units", error_code="syntax_error")
        from ...core.limits import clip_with_marker, resolve_cap
        text, _ = clip_with_marker(text, resolve_cap(max_bytes),
            "Читай по одному через read_unit(address={qualname: ...}) или передай max_bytes=0.")
        return Result(status="ok", message=text, action="list_units")
