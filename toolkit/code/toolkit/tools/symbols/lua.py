"""Lua/Luau symbol operations — plain-function implementations.

Not registered in TOOL_MAP yet. Stage 2 of the dispatcher plan: the
Python symbol tools will call these when `file_path` ends with .lua/.luau.

Each function mirrors a Python symbol operation 1:1:

    lua_list_symbols              <-> list_symbols
    lua_read_symbol               <-> read_symbol
    lua_replace_symbol            <-> replace_symbol
    lua_replace_symbol_signature  <-> replace_symbol_signature
    lua_replace_symbol_body       <-> replace_symbol_body
    lua_delete_symbol             <-> delete_symbol
    lua_insert_symbol             <-> insert_symbol
    lua_move_symbol               <-> move_symbol

Backend is passed in; parsing is done by `toolkit.formats.lua` (token
scanner). All write functions validate the result with parse_lua_symbols
before persisting; on error the file is left untouched.
"""
from __future__ import annotations

from ...core.backend import Backend
from ...core.models import Delta, Result
from ...formats.lua import (
    parse_lua_symbols, find_lua_symbol, find_all_lua_symbols,
    lua_signature_bounds, lua_body_bounds,
)
from ._ast import (
    _apply_indent, _count_lines, _dedent_block, _delete_symbol_lines,
    _delta, _eol_of, _line_indent, _resolve_occurrence, _sign, _symbol_line,
)


_POSITIONS = ("start", "end", "before", "after")


# --- helpers --------------------------------------------------------------


def _validate_position(position: str, anchor: str | None, action: str) -> Result | None:
    if position not in _POSITIONS:
        return Result(
            status="error",
            message=(f"position должен быть start|end|before|after, "
                     f"дано {position!r}"),
            action=action,
            error_code="bad_position",
        )
    if position in ("before", "after") and not anchor:
        return Result(
            status="error",
            message=f"position={position!r} требует anchor",
            action=action,
            error_code="anchor_required",
        )
    if position in ("start", "end") and anchor:
        return Result(
            status="error",
            message=f"position={position!r} не принимает anchor",
            action=action,
            error_code="anchor_not_allowed",
        )
    return None


def _parse(source: str, file_path: str, action: str) -> list | Result:
    try:
        return parse_lua_symbols(source)
    except Exception as e:
        return Result(
            status="error",
            message=f"Lua parse failed for {file_path}: {e}",
            action=action,
            error_code="parse_error",
        )


def _resolve(symbols, qualname, occurrence, action):
    matches = find_all_lua_symbols(symbols, qualname)
    return _resolve_occurrence(matches, occurrence, qualname, action)


def _module_end_idx(lines: list) -> int:
    """Index for position='end': before a trailing `return ...`.

    Standard Lua module pattern is `local M = {} ... return M`.
    Inserting after that return produces dead code (unreachable at runtime),
    so position='end' inserts before the trailing return, or at len(lines)
    if there is none.
    """
    i = len(lines)
    while i > 0 and not lines[i - 1].strip():
        i -= 1
    if i == 0:
        return len(lines)
    stripped = lines[i - 1].strip()
    if stripped == "return" or stripped.startswith("return ") or stripped.startswith("return\t"):
        return i - 1
    return len(lines)


def _insert_lines(lines: list, idx: int, block_text: str, indent: str) -> None:
    """Splice `block_text` into `lines` at index `idx`, adding blank lines
    around it if the neighbours are non-blank."""
    new_lines = _apply_indent(block_text, indent)
    sep_b = [""] if idx > 0 and lines[idx - 1].strip() else []
    sep_a = [""] if idx < len(lines) and lines[idx].strip() else []
    lines[idx:idx] = sep_b + new_lines + sep_a


# --- read -----------------------------------------------------------------


def lua_list_symbols(backend: Backend, file_path: str) -> Result:
    """Tree of symbols in a .lua/.luau file."""
    source = backend.read(file_path)
    symbols = _parse(source, file_path, "list_symbols")
    if isinstance(symbols, Result):
        return symbols
    out = [file_path]
    if not symbols:
        out.append("(no symbols)")
    else:
        for s in symbols:
            out.append(f"- {s.qualname} [{s.kind}] L{s.line_start}-L{s.line_end}")
    return Result(status="ok", message="\n".join(out), action="list_symbols")


def lua_read_symbol(
    backend: Backend,
    file_path: str,
    qualname: str,
    occurrence: int | None = None,
) -> Result:
    source = backend.read(file_path)
    symbols = _parse(source, file_path, "read_symbol")
    if isinstance(symbols, Result):
        return symbols
    sym, err = _resolve(symbols, qualname, occurrence, "read_symbol")
    if err is not None:
        return err
    lines = source.splitlines()
    body = "\n".join(lines[sym.line_start - 1:sym.line_end])
    header = f"{file_path} [{qualname}] L{sym.line_start}-L{sym.line_end}"
    return Result(status="ok", message=f"{header}\n{body}", action="read_symbol")


# --- replace --------------------------------------------------------------


def lua_replace_symbol(
    backend: Backend,
    file_path: str,
    qualname: str,
    new_code: str,
    occurrence: int | None = None,
) -> Result:
    action = "replace_symbol_lua"
    if not new_code or not new_code.strip():
        return Result(status="error", message="new_code пуст",
                      action=action, error_code="empty_input")
    source = backend.read(file_path)
    symbols = _parse(source, file_path, action)
    if isinstance(symbols, Result):
        return symbols
    sym, err = _resolve(symbols, qualname, occurrence, action)
    if err is not None:
        return err
    eol = _eol_of(source)
    lines = source.splitlines()
    indent = _line_indent(lines[sym.line_start - 1])
    new_lines = _apply_indent(new_code, indent)
    result_lines = lines[:sym.line_start - 1] + new_lines + lines[sym.line_end:]
    new_source = eol.join(result_lines)
    if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
        new_source += eol
    check = _parse(new_source, file_path, action)
    if isinstance(check, Result):
        return Result(
            status="error",
            message="Результат не парсится. Патч отменен.",
            action=action, error_code="result_parse_error",
        )
    if not find_all_lua_symbols(check, qualname):
        return Result(
            status="error",
            message=f"Result missing symbol '{qualname}'. Rollback.",
            action=action, error_code="result_missing_symbol",
        )
    backend.write(file_path, new_source)
    delta = _delta(source, new_source)
    new_end = sym.line_start + len(new_lines) - 1
    msg = (f"{file_path}: {qualname} заменён "
           f"(L{sym.line_start}-L{sym.line_end} -> L{sym.line_start}-L{new_end}) "
           f"- {_sign(delta.lines)} lines, {_sign(delta.bytes)} bytes")
    return Result(status="ok", message=msg, delta=delta, verified=True,
                  action=action)


def lua_replace_symbol_signature(
    backend: Backend,
    file_path: str,
    qualname: str,
    new_signature: str,
    occurrence: int | None = None,
) -> Result:
    action = "replace_symbol_signature_lua"
    if not new_signature or not new_signature.strip():
        return Result(status="error", message="new_signature пуст",
                      action=action, error_code="empty_input")
    source = backend.read(file_path)
    symbols = _parse(source, file_path, action)
    if isinstance(symbols, Result):
        return symbols
    sym, err = _resolve(symbols, qualname, occurrence, action)
    if err is not None:
        return err
    bounds = lua_signature_bounds(source, sym)
    if bounds is None:
        return Result(
            status="error",
            message=f"Не удалось найти границы сигнатуры '{qualname}'",
            action=action, error_code="no_signature",
        )
    sig_start, sig_end = bounds
    if sig_start == sym.line_end:
        return Result(
            status="error",
            message=(f"'{qualname}' — однострочное определение; "
                     f"используй replace_symbol"),
            action=action, error_code="one_liner",
        )
    eol = _eol_of(source)
    lines = source.splitlines()
    indent = _line_indent(lines[sym.line_start - 1])
    new_lines = _apply_indent(new_signature, indent)
    result_lines = lines[:sig_start - 1] + new_lines + lines[sig_end:]
    new_source = eol.join(result_lines)
    if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
        new_source += eol
    check = _parse(new_source, file_path, action)
    if isinstance(check, Result):
        return Result(
            status="error",
            message="Результат не парсится. Патч отменен.",
            action=action, error_code="result_parse_error",
        )
    if not find_all_lua_symbols(check, qualname):
        return Result(
            status="error",
            message=f"Result missing symbol '{qualname}'. Rollback.",
            action=action, error_code="result_missing_symbol",
        )
    backend.write(file_path, new_source)
    delta = _delta(source, new_source)
    msg = (f"{file_path}: сигнатура {qualname} заменена "
           f"(L{sig_start}-L{sig_end}) - {_sign(delta.lines)} lines, "
           f"{_sign(delta.bytes)} bytes")
    return Result(status="ok", message=msg, delta=delta, verified=True,
                  action=action)


def _body_indent(lines: list, sym) -> str:
    """Actual indent of the first non-blank body line of `sym`.

    Preserves the file's existing style (tabs vs spaces, width) instead of
    hardcoding a 4-space unit. Falls back to signature indent + 4 spaces
    when the body has no indented line (one-liner or empty body).
    """
    sig_indent = _line_indent(lines[sym.line_start - 1])
    for i in range(sym.line_start, sym.line_end):
        if lines[i].strip():
            return _line_indent(lines[i])
    return sig_indent + "    "


def lua_replace_symbol_body(
    backend: Backend,
    file_path: str,
    qualname: str,
    new_body: str,
    occurrence: int | None = None,
) -> Result:
    action = "replace_symbol_body_lua"
    if not new_body or not new_body.strip():
        return Result(status="error", message="new_body пуст",
                      action=action, error_code="empty_input")
    source = backend.read(file_path)
    symbols = _parse(source, file_path, action)
    if isinstance(symbols, Result):
        return symbols
    sym, err = _resolve(symbols, qualname, occurrence, action)
    if err is not None:
        return err
    bounds = lua_body_bounds(source, sym)
    if bounds is None:
        return Result(
            status="error",
            message=(f"У '{qualname}' нет отдельного тела "
                     f"(однострочник или сигнатура не найдена)"),
            action=action, error_code="no_body",
        )
    body_start, body_end = bounds
    eol = _eol_of(source)
    lines = source.splitlines()
    indent = _body_indent(lines, sym)
    new_lines = _apply_indent(new_body, indent)
    result_lines = lines[:body_start - 1] + new_lines + lines[body_end:]
    new_source = eol.join(result_lines)
    if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
        new_source += eol
    check = _parse(new_source, file_path, action)
    if isinstance(check, Result):
        return Result(
            status="error",
            message="Результат не парсится. Патч отменен.",
            action=action, error_code="result_parse_error",
        )
    if not find_all_lua_symbols(check, qualname):
        return Result(
            status="error",
            message=f"Result missing symbol '{qualname}'. Rollback.",
            action=action, error_code="result_missing_symbol",
        )
    backend.write(file_path, new_source)
    delta = _delta(source, new_source)
    msg = (f"{file_path}: тело {qualname} заменено "
           f"(L{body_start}-L{body_end}) - {_sign(delta.lines)} lines, "
           f"{_sign(delta.bytes)} bytes")
    return Result(status="ok", message=msg, delta=delta, verified=True,
                  action=action)


# --- delete ---------------------------------------------------------------


def lua_delete_symbol(
    backend: Backend,
    file_path: str,
    qualname: str,
    occurrence: int | None = None,
) -> Result:
    action = "delete_symbol_lua"
    source = backend.read(file_path)
    symbols = _parse(source, file_path, action)
    if isinstance(symbols, Result):
        return symbols
    sym, err = _resolve(symbols, qualname, occurrence, action)
    if err is not None:
        return err
    new_source = _delete_symbol_lines(source, sym.line_start, sym.line_end)
    check = _parse(new_source, file_path, action)
    if isinstance(check, Result):
        return Result(
            status="error",
            message="Результат не парсится. Патч отменен.",
            action=action, error_code="result_parse_error",
        )
    backend.write(file_path, new_source)
    delta = _delta(source, new_source)
    msg = (f"{file_path}: {qualname} удалён "
           f"(L{sym.line_start}-L{sym.line_end}) - "
           f"{_sign(delta.lines)} lines, {_sign(delta.bytes)} bytes")
    return Result(status="ok", message=msg, delta=delta, verified=True,
                  action=action)


# --- insert ---------------------------------------------------------------


def lua_insert_symbol(
    backend: Backend,
    file_path: str,
    new_code: str,
    position: str = "end",
    anchor: str | None = None,
) -> Result:
    action = "insert_symbol_lua"
    if not new_code or not new_code.strip():
        return Result(status="error", message="new_code пуст",
                      action=action, error_code="empty_input")
    verr = _validate_position(position, anchor, action)
    if verr is not None:
        return verr
    source = backend.read(file_path)
    symbols = _parse(source, file_path, action)
    if isinstance(symbols, Result):
        return symbols
    lines = source.splitlines()
    if position == "start":
        idx = 0
    elif position == "end":
        idx = _module_end_idx(lines)
    else:
        a_matches = find_all_lua_symbols(symbols, anchor)
        if not a_matches:
            return Result(
                status="error",
                message=f"Anchor '{anchor}' не найден",
                action=action, error_code="anchor_not_found",
            )
        if len(a_matches) > 1:
            return Result(
                status="error",
                message=f"Anchor '{anchor}' встречается {len(a_matches)} раз",
                action=action, error_code="ambiguous_anchor",
            )
        a = a_matches[0]
        idx = (a.line_start - 1) if position == "before" else a.line_end
    _insert_lines(lines, idx, new_code, "")
    eol = _eol_of(source)
    new_source = eol.join(lines)
    if source.endswith(("\n", "\r")) and not new_source.endswith(("\n", "\r")):
        new_source += eol
    check = _parse(new_source, file_path, action)
    if isinstance(check, Result):
        return Result(
            status="error",
            message="Результат не парсится. Патч отменен.",
            action=action, error_code="result_parse_error",
        )
    backend.write(file_path, new_source)
    delta = _delta(source, new_source)
    where = f"module ({position})"
    msg = (f"{file_path}: вставлено в {where} "
           f"(+{_count_lines(new_code)} lines, {_sign(delta.bytes)} bytes)")
    return Result(status="ok", message=msg, delta=delta, verified=True,
                  action=action)


# --- move -----------------------------------------------------------------


def lua_move_symbol(
    backend: Backend,
    file_path: str,
    qualname: str,
    occurrence: int | None = None,
    target_file: str | None = None,
    position: str = "end",
    anchor: str | None = None,
) -> Result:
    action = "move_symbol_lua"
    verr = _validate_position(position, anchor, action)
    if verr is not None:
        return verr
    source = backend.read(file_path)
    symbols = _parse(source, file_path, action)
    if isinstance(symbols, Result):
        return symbols
    sym, err = _resolve(symbols, qualname, occurrence, action)
    if err is not None:
        return err
    lines = source.splitlines()
    indent = _line_indent(lines[sym.line_start - 1])
    block = _dedent_block(lines[sym.line_start - 1:sym.line_end], indent)
    same_file = (target_file is None) or (target_file == file_path)

    if same_file:
        mid = _delete_symbol_lines(source, sym.line_start, sym.line_end)
        mid_syms = _parse(mid, file_path, action)
        if isinstance(mid_syms, Result):
            return Result(
                status="error",
                message="Промежуточный результат не парсится.",
                action=action, error_code="result_parse_error",
            )
        mid_lines = mid.splitlines()
        if position == "start":
            idx = 0
        elif position == "end":
            idx = _module_end_idx(mid_lines)
        else:
            a_matches = find_all_lua_symbols(mid_syms, anchor)
            if not a_matches:
                return Result(
                    status="error",
                    message=f"Anchor '{anchor}' не найден",
                    action=action, error_code="anchor_not_found",
                )
            if len(a_matches) > 1:
                return Result(
                    status="error",
                    message=f"Anchor '{anchor}' встречается {len(a_matches)} раз",
                    action=action, error_code="ambiguous_anchor",
                )
            a = a_matches[0]
            idx = (a.line_start - 1) if position == "before" else a.line_end
        _insert_lines(mid_lines, idx, block, "")
        mid_eol = _eol_of(mid)
        final = mid_eol.join(mid_lines)
        if mid.endswith(("\n", "\r")) and not final.endswith(("\n", "\r")):
            final += mid_eol
        check = _parse(final, file_path, action)
        if isinstance(check, Result):
            return Result(
                status="error",
                message="Результат не парсится. Патч отменен.",
                action=action, error_code="result_parse_error",
            )
        if not find_all_lua_symbols(check, qualname):
            return Result(
                status="error",
                message=f"Result missing symbol '{qualname}'. Rollback.",
                action=action, error_code="result_missing_symbol",
            )
        backend.write(file_path, final)
        delta = _delta(source, final)
        msg = (f"{file_path}: {qualname} перемещён "
               f"(L{sym.line_start}-L{sym.line_end}) -> module ({position})"
               f" - {_sign(delta.lines)} lines in source")
        return Result(status="ok", message=msg, delta=delta, verified=True,
                      action=action)

    # cross-file
    try:
        tgt = backend.read(target_file)
    except FileNotFoundError:
        return Result(
            status="error",
            message=f"Целевой файл не найден: {target_file}",
            action=action, error_code="target_not_found",
        )
    tgt_syms = _parse(tgt, target_file, action)
    if isinstance(tgt_syms, Result):
        return tgt_syms
    tgt_lines = tgt.splitlines()
    if position == "start":
        idx = 0
    elif position == "end":
        idx = _module_end_idx(tgt_lines)
    else:
        a_matches = find_all_lua_symbols(tgt_syms, anchor)
        if not a_matches:
            return Result(
                status="error",
                message=f"Anchor '{anchor}' не найден в {target_file}",
                action=action, error_code="anchor_not_found",
            )
        if len(a_matches) > 1:
            return Result(
                status="error",
                message=f"Anchor '{anchor}' встречается {len(a_matches)} раз",
                action=action, error_code="ambiguous_anchor",
            )
        a = a_matches[0]
        idx = (a.line_start - 1) if position == "before" else a.line_end
    _insert_lines(tgt_lines, idx, block, "")
    tgt_eol = _eol_of(tgt) if tgt else "\n"
    new_tgt = tgt_eol.join(tgt_lines)
    if tgt.endswith(("\n", "\r")) and not new_tgt.endswith(("\n", "\r")):
        new_tgt += tgt_eol
    chk_tgt = _parse(new_tgt, target_file, action)
    if isinstance(chk_tgt, Result):
        return Result(
            status="error",
            message=f"Новый {target_file} не парсится. Патч отменен.",
            action=action, error_code="result_parse_error",
        )
    if not find_all_lua_symbols(chk_tgt, qualname):
        return Result(
            status="error",
            message=f"Result missing symbol '{qualname}'. Rollback.",
            action=action, error_code="result_missing_symbol",
        )
    new_src = _delete_symbol_lines(source, sym.line_start, sym.line_end)
    chk_src = _parse(new_src, file_path, action)
    if isinstance(chk_src, Result):
        return Result(
            status="error",
            message=f"Новый {file_path} не парсится. Патч отменен.",
            action=action, error_code="result_parse_error",
        )
    backend.write(target_file, new_tgt)
    backend.write(file_path, new_src)
    delta = _delta(source, new_src)
    msg = (f"{file_path} -> {target_file}: {qualname} перемещён "
           f"-> module ({position})")
    return Result(status="ok", message=msg, delta=delta, verified=True,
                  action=action)


__all__ = [
    "lua_list_symbols", "lua_read_symbol",
    "lua_replace_symbol", "lua_replace_symbol_signature",
    "lua_replace_symbol_body", "lua_delete_symbol",
    "lua_insert_symbol", "lua_move_symbol",
]


def lua_copy_symbol(
    backend: Backend,
    source_file: str,
    target_file: str,
    qualname: str,
    occurrence: int | None,
    position: str,
    anchor: str | None,
) -> Result:
    """Copy a Lua symbol from source_file to target_file (source untouched)."""
    action = "copy_unit"
    verr = _validate_position(position, anchor, action)
    if verr is not None:
        return verr
    source = backend.read(source_file)
    symbols = _parse(source, source_file, action)
    if isinstance(symbols, Result):
        return symbols
    sym, err = _resolve(symbols, qualname, occurrence, action)
    if err is not None:
        return err
    lines = source.splitlines()
    indent = _line_indent(lines[sym.line_start - 1])
    block = _dedent_block(lines[sym.line_start - 1:sym.line_end], indent)

    if not backend.exists(target_file):
        tgt_lines = []
        tgt = ""
        tgt_syms = []
    else:
        tgt = backend.read(target_file)
        tgt_syms = _parse(tgt, target_file, action)
        if isinstance(tgt_syms, Result):
            return tgt_syms
        if find_all_lua_symbols(tgt_syms, qualname):
            return Result(status="error", action=action, error_code="destination_exists",
                          message=f"{qualname!r} \u0443\u0436\u0435 \u0435\u0441\u0442\u044c \u0432 {target_file}")
        tgt_lines = tgt.splitlines()

    if position == "start":
        idx = 0
    elif position == "end":
        idx = _module_end_idx(tgt_lines)
    else:
        a_matches = find_all_lua_symbols(tgt_syms, anchor) if tgt_syms else []
        if not a_matches:
            return Result(status="error", action=action, error_code="anchor_not_found",
                          message=f"anchor '{anchor}' \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d \u0432 {target_file}")
        if len(a_matches) > 1:
            return Result(status="error", action=action, error_code="ambiguous_anchor",
                          message=f"anchor '{anchor}' \u0432\u0441\u0442\u0440\u0435\u0447\u0430\u0435\u0442\u0441\u044f {len(a_matches)} \u0440\u0430\u0437")
        a = a_matches[0]
        idx = (a.line_start - 1) if position == "before" else a.line_end

    _insert_lines(tgt_lines, idx, block, "")
    tgt_eol = _eol_of(tgt) if tgt else "\n"
    new_tgt = tgt_eol.join(tgt_lines)
    if tgt.endswith(("\n", "\r")) and not new_tgt.endswith(("\n", "\r")):
        new_tgt += tgt_eol
    if not new_tgt.endswith(("\n", "\r")):
        new_tgt += tgt_eol
    chk = _parse(new_tgt, target_file, action)
    if isinstance(chk, Result):
        return Result(status="error", action=action, error_code="result_parse_error",
                      message=f"\u041d\u043e\u0432\u044b\u0439 {target_file} \u043d\u0435 \u043f\u0430\u0440\u0441\u0438\u0442\u0441\u044f. \u041f\u0430\u0442\u0447 \u043e\u0442\u043a\u0430\u0447\u0435\u043d.")
    backend.write(target_file, new_tgt)
    return Result(status="ok", action=action, verified=True,
                  message=f"{source_file} \u2192 {target_file}: {qualname} \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d (+{len(block)} \u0441\u0442\u0440.)")
