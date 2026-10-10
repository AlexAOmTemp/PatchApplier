"""AST helpers shared by Python symbol tools.

Extracted from toolkit/tools/code.py. This module knows only about the
Python AST and about Delta. It does not depend on Backend, Result, or any
specific tool class.
"""
from __future__ import annotations

import ast
import textwrap

from ...core.models import Delta, Result
from ...core.paths import is_mcp_path


def _sign(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


def _eol_of(source: str) -> str:
    """Dominant line ending of `source`: '\\r\\n' or '\\n'.

    Symbol-tools use splitlines() (which strips endings) + join(eol) to
    reassemble the file. Without this helper join('\\n') silently converts
    every CRLF file to LF on the first symbol edit.
    """
    return "\r\n" if "\r\n" in source else "\n"


def _apply_indent(text: str, indent: str) -> list[str]:
    """Apply `indent` to each non-blank line of `text`.

    Normalizes input first:
    - strips trailing newlines (they would otherwise become a phantom
      blank element in the output);
    - dedents any common leading whitespace so callers may pass the block
      either indented or not without doubling the target indent.
    """
    text = textwrap.dedent(text.rstrip("\n"))
    out: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            out.append("")
        else:
            out.append(indent + line)
    return out


def _count_lines(text: str) -> int:
    if not text:
        return 0
    n = text.count("\n")
    if not text.endswith("\n"):
        n += 1
    return n


def _dedent_block(block_lines: list[str], node_indent: str) -> str:
    if not node_indent:
        return "\n".join(block_lines)
    out: list[str] = []
    for ln in block_lines:
        if not ln.strip():
            out.append("")
        elif ln.startswith(node_indent):
            out.append(ln[len(node_indent):])
        else:
            out.append(ln)
    return "\n".join(out)


def _delete_symbol_lines(source: str, start: int, end: int) -> str:
    lines = source.splitlines()
    del lines[start - 1:end]
    if (start - 2 >= 0 and start - 1 < len(lines)
            and not lines[start - 2].strip()
            and not lines[start - 1].strip()):
        del lines[start - 1]
    eol = _eol_of(source)
    out = eol.join(lines)
    if source.endswith(("\n", "\r")) and not out.endswith(("\n", "\r")):
        out += eol
    return out


def _delta(before: str, after: str) -> Delta:
    return Delta(
        lines=_count_lines(after) - _count_lines(before),
        bytes=len(after.encode("utf-8")) - len(before.encode("utf-8")),
        occurrences=1,
    )


def _find_all_by_qualname(tree, qualname: str, include_vars: bool = False) -> list:
    """All nodes with the given qualname, in source order (top-down)."""
    out = []
    for qn, node in _iter_defs(tree, include_vars=include_vars):
        if qn == qualname:
            out.append(node)
    out.sort(key=_start_line)
    return out


def _find_by_qualname(tree, qualname: str):
    for qn, node in _iter_defs(tree):
        if qn == qualname:
            return node
    return None


def _iter_defs(node, prefix: str = "", include_vars: bool = False, in_func: bool = False):
    """Recursively yield (qualname, node) for module/class-scope symbols.

    Yields FunctionDef / AsyncFunctionDef / ClassDef. When include_vars is
    True, also yields simple Assign / AnnAssign statements at module or
    class scope; assignments inside function bodies are skipped.

    Recurses into control-flow wrappers (if/for/while/try/with) at any
    level, matching formats.code._walk_body.
    """
    body = getattr(node, "body", None)
    if not isinstance(body, list):
        return
    for child in body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qn = f"{prefix}.{child.name}" if prefix else child.name
            yield qn, child
            yield from _iter_defs(child, qn, include_vars=include_vars, in_func=True)
            continue
        if isinstance(child, ast.ClassDef):
            qn = f"{prefix}.{child.name}" if prefix else child.name
            yield qn, child
            yield from _iter_defs(child, qn, include_vars=include_vars, in_func=False)
            continue
        if include_vars and not in_func:
            tgt = None
            if isinstance(child, ast.Assign) and len(child.targets) == 1:
                if isinstance(child.targets[0], ast.Name):
                    tgt = child.targets[0]
            elif (isinstance(child, ast.AnnAssign)
                  and isinstance(child.target, ast.Name)
                  and child.value is not None):
                tgt = child.target
            if tgt is not None:
                qn = f"{prefix}.{tgt.id}" if prefix else tgt.id
                yield qn, child
                continue
        yield from _iter_defs(child, prefix, include_vars=include_vars, in_func=in_func)


def _kind_of(node) -> str:
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, ast.AsyncFunctionDef):
        return "async_function"
    if isinstance(node, ast.FunctionDef):
        return "function"
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        tgt = node.targets[0] if isinstance(node, ast.Assign) else node.target
        if (isinstance(tgt, ast.Name)
                and tgt.id.isupper()
                and any(c.isalpha() for c in tgt.id)):
            return "const"
        return "var"
    return "unknown"


def _module_head_end_line(tree):
    """1-based line just before the first top-level def/class, or None."""
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return _start_line(stmt)
    return None


def _resolve_insertion(tree, lines, container, position, anchor):
    """Compute where to splice new code.

    Returns (idx, indent, n_blank) on success, or (None, error_code, message)
    on failure. idx is a 0-based line index suitable for list-splice; indent
    is the leading string to apply to each non-blank line of new_code;
    n_blank is the number of blank lines to insert around the block.
    """
    if container is None:
        scope_node = tree
        scope_body = tree.body
        indent = ""
        n_blank = 2
    else:
        c_matches = _find_all_by_qualname(tree, container, include_vars=False)
        if not c_matches:
            return None, "container_not_found", f"Контейнер '{container}' не найден"
        if len(c_matches) > 1:
            return None, "ambiguous_container", (
                f"Контейнер '{container}' встречается {len(c_matches)} раз"
            )
        scope_node = c_matches[0]
        if not isinstance(scope_node, ast.ClassDef):
            return None, "container_not_class", (
                f"Контейнер '{container}' \u2014 не класс"
            )
        scope_body = scope_node.body
        indent = " " * (scope_node.col_offset + 4)
        n_blank = 1

    if not scope_body:
        idx = 0
    elif position == "end":
        idx = scope_body[-1].end_lineno or scope_body[-1].lineno
    elif position == "start":
        idx = 0 if container is None else (scope_body[0].lineno - 1)
    else:
        a_matches = _find_all_by_qualname(scope_node, anchor, include_vars=True)
        if not a_matches:
            return None, "anchor_not_found", f"Anchor '{anchor}' не найден"
        if len(a_matches) > 1:
            return None, "ambiguous_anchor", (
                f"Anchor '{anchor}' встречается {len(a_matches)} раз"
            )
        a_node = a_matches[0]
        if position == "before":
            idx = _start_line(a_node) - 1
        else:
            idx = a_node.end_lineno or a_node.lineno

    if idx < 0:
        idx = 0
    if idx > len(lines):
        idx = len(lines)
    return idx, indent, n_blank


def _resolve_occurrence(matches, occurrence, qualname: str, action: str):
    """(node, None) on success; (None, Result) on failure."""
    if not matches:
        return None, Result(
            status="error",
            message=f"Символ '{qualname}' не найден",
            action=action,
            error_code="not_found",
        )
    if len(matches) == 1:
        if occurrence is not None and occurrence != 1:
            return None, Result(
                status="error",
                message=(f"Символ '{qualname}' встречается один раз; "
                         f"occurrence={occurrence} вне диапазона"),
                action=action,
                error_code="occurrence_out_of_range",
            )
        return matches[0], None
    if occurrence is None:
        where = ", ".join(f"L{_symbol_line(n)}" for n in matches)
        return None, Result(
            status="error",
            message=(f"Символ '{qualname}' встречается {len(matches)} раз "
                     f"({where}). Укажи occurrence=N."),
            action=action,
            error_code="ambiguous_symbol",
        )
    if isinstance(occurrence, bool) or not isinstance(occurrence, int):
        return None, Result(
            status="error",
            message="occurrence должен быть целым числом",
            action=action,
            error_code="bad_occurrence",
        )
    if occurrence < 1 or occurrence > len(matches):
        return None, Result(
            status="error",
            message=f"occurrence={occurrence} вне диапазона 1..{len(matches)}",
            action=action,
            error_code="occurrence_out_of_range",
        )
    return matches[occurrence - 1], None


def _start_line(node) -> int:
    if getattr(node, "decorator_list", None):
        return node.decorator_list[0].lineno
    return node.lineno


def _symbol_line(node) -> int:
    """Start line of a symbol.

    Works for Python AST nodes (decorators considered) and for Lua Symbol
    objects (which expose `line_start`).
    """
    if hasattr(node, "line_start"):
        return node.line_start
    if getattr(node, "decorator_list", None):
        return node.decorator_list[0].lineno
    return node.lineno


def _line_indent(line: str) -> str:
    """Leading whitespace of a source line."""
    return line[:len(line) - len(line.lstrip())]


LUA_EXTS = (".lua", ".luau")


def _is_lua_path(file_path: str) -> bool:
    """True if the path points to Lua/Luau source.

    Two cases:
    - a filesystem path ending in .lua/.luau;
    - a Roblox DataModel path (ReplicatedStorage.X, ServerScriptService.Y.Z)
      — every script there is Luau regardless of any extension suffix.
    """
    if file_path.lower().endswith(LUA_EXTS):
        return True
    return is_mcp_path(file_path)


def _check_target_survives(new_source: str, qualname: str) -> tuple[bool, str, str]:
    """Verify that after a replacement the target qualname still resolves.

    Catches silent corruption where the result parses but the symbol moved
    out of its context (e.g. a class method replaced at column 0 becomes a
    top-level function, and `Foo.b` no longer exists).

    Returns (ok, error_code, message). On failure the caller must not write.
    """
    try:
        tree = ast.parse(new_source)
    except SyntaxError as e:
        return False, "result_syntax_error", _format_result_syntax_error(e, new_source)
    matches = _find_all_by_qualname(tree, qualname, include_vars=True)
    if not matches:
        return False, "qualname_lost", (
            f"Символ {qualname!r} исчез после правки. "
            f"Вероятная причина — неверный indent (результат парсится, "
            f"но символ оказался вне своего контекста). Патч отменен."
        )
    return True, "", ""


def _format_result_syntax_error(e: SyntaxError, new_source: str) -> str:
    """Turn a raw ast SyntaxError into an actionable message.

    The tool does not auto-fix indentation: if the proposed content is
    structurally broken, the caller sees exactly where and why. We surface
    the offending line and column so the author can correct the input.
    """
    lineno = e.lineno or 0
    offset = e.offset or 0
    msg = e.msg or "syntax error"
    lines = new_source.splitlines()
    loc = f"line {lineno}" + (f", col {offset}" if offset else "")
    head = f"Результат не парсится ({loc}): {msg}."
    hint = ""
    if 1 <= lineno <= len(lines):
        bad = lines[lineno - 1]
        stripped = bad.lstrip(" \t")
        indent = bad[: len(bad) - len(stripped)]
        indent_s = repr(indent) if indent else "(none)"
        hint = (
            f" Строка {lineno}: {bad!r}. "
            f"Отступ этой строки: {indent_s}. "
            f"Проверь отступы переданного фрагмента: инструмент их не правит."
        )
    return head + hint + " Патч отменен."
