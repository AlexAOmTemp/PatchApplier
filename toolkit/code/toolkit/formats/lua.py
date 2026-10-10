'''Lua/Luau parser -- symbol extraction via token scanning.

Not a full parser. Scans for function declarations, tracks block depth
(function / if / do / repeat ... end / until), extracts qualname and
line range. Handles:

    local function name(...) ... end
    function name(...) ... end
    function M.name(...) ... end
    function M:method(...) ... end
    Name = function(...) ... end
    local Name = function(...) ... end

Ignores comments and string literals. No AST -- Lua has no standard
Python parser and writing a full one is out of scope.

Output: list[Symbol] where qualname is the name as written in source,
kind is one of: local_function, function, method, assigned.
'''
from __future__ import annotations

import re

from ..core.models import Symbol


KEYWORDS = frozenset({
    'and', 'break', 'do', 'else', 'elseif', 'end', 'false', 'for',
    'function', 'if', 'in', 'local', 'nil', 'not', 'or', 'repeat',
    'return', 'then', 'true', 'until', 'while',
})

_OPENERS = frozenset({'function', 'if', 'do', 'repeat'})
_CLOSERS = frozenset({'end', 'until'})


def parse_lua_symbols(source):
    tokens = list(_tokenize(source))
    line_of = _make_line_index(source)
    return _collect_symbols(tokens, source, line_of)


def find_lua_symbol(symbols, qualname):
    for s in symbols:
        if s.qualname == qualname:
            return s
    return None


_REQUIRE_RE = re.compile(r"require\s*\(\s*([^)]+?)\s*\)")


def extract_lua_imports(source):
    """Best-effort extraction of require() targets.

    Simple regex -- doesn't try to be precise about nested parens or
    require inside string literals / comments. For a first-pass index
    this is acceptable and matches what a human would grep for.
    """
    out = []
    seen = set()
    for m in _REQUIRE_RE.finditer(source):
        target = m.group(1).strip()
        if not target or target in seen:
            continue
        seen.add(target)
        out.append(target)
    return out


def _tokenize(src):
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c == '-' and i + 1 < n and src[i + 1] == '-':
            j = i + 2
            eq = 0
            while j < n and src[j] == '=':
                eq += 1
                j += 1
            if j < n and src[j] == '[':
                closer = ']' + '=' * eq + ']'
                k = src.find(closer, j + 1)
                i = n if k == -1 else k + len(closer)
                continue
            k = src.find(chr(10), i)
            i = n if k == -1 else k + 1
            continue
        if c == '[':
            j = i + 1
            eq = 0
            while j < n and src[j] == '=':
                eq += 1
                j += 1
            if j < n and src[j] == '[':
                closer = ']' + '=' * eq + ']'
                k = src.find(closer, j + 1)
                if k == -1:
                    yield ('string', src[i:], i)
                    i = n
                else:
                    yield ('string', src[i:k + len(closer)], i)
                    i = k + len(closer)
                continue
        if c == chr(39) or c == chr(34):
            quote = c
            j = i + 1
            while j < n:
                ch = src[j]
                if ch == chr(92) and j + 1 < n:
                    j += 2
                    continue
                if ch == quote:
                    j += 1
                    break
                if ch == chr(10):
                    break
                j += 1
            yield ('string', src[i:j], i)
            i = j
            continue
        if c.isalpha() or c == '_':
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == '_'):
                j += 1
            word = src[i:j]
            kind = 'keyword' if word in KEYWORDS else 'ident'
            yield (kind, word, i)
            i = j
            continue
        if c.isdigit():
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] in '._'):
                j += 1
            yield ('number', src[i:j], i)
            i = j
            continue
        yield ('punct', c, i)
        i += 1


def _make_line_index(src):
    line_starts = [0]
    for idx, ch in enumerate(src):
        if ch == chr(10):
            line_starts.append(idx + 1)

    def line_of(pos):
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    return line_of


def _collect_symbols(tokens, source, line_of):
    symbols = []
    i = 0
    while i < len(tokens):
        kind, text, pos = tokens[i]
        if kind == 'keyword' and text == 'function':
            info = _read_function_name(tokens, source, i)
            end_idx = _find_block_end(tokens, i)
            if info is not None and end_idx is not None:
                qualname, name, sym_kind, sig = info
                start_line = line_of(pos)
                end_line = line_of(tokens[end_idx][2])
                symbols.append(Symbol(
                    name=name,
                    qualname=qualname,
                    kind=sym_kind,
                    line_start=start_line,
                    line_end=end_line,
                    signature=sig,
                    docstring=None,
                    decorators=[],
                    parent=None,
                ))
                i = end_idx + 1
                continue
        i += 1
    return symbols


def _read_function_name(tokens, source, func_idx):
    j = func_idx + 1
    parts = []
    colon_used = False
    while j < len(tokens):
        k, t, _ = tokens[j]
        if k == 'punct' and t == '(':
            qualname = ''.join(parts)
            if not qualname:
                break
            name = qualname.rsplit('.', 1)[-1].rsplit(':', 1)[-1]
            sym_kind = 'method' if colon_used else 'function'
            if func_idx > 0 and tokens[func_idx - 1][0] == 'keyword' \
                    and tokens[func_idx - 1][1] == 'local':
                sym_kind = 'local_function'
            sig = _slice_signature(source, tokens, func_idx, '')
            return qualname, name, sym_kind, sig
        if k == 'ident':
            parts.append(t)
            j += 1
            continue
        if k == 'punct' and t in ('.', ':'):
            parts.append(t)
            if t == ':':
                colon_used = True
            j += 1
            continue
        break
    j = func_idx - 1
    if j >= 0 and tokens[j][0] == 'punct' and tokens[j][1] == '=':
        j -= 1
        rev = []
        while j >= 0:
            k, t, _ = tokens[j]
            if k == 'ident':
                rev.append(t)
                j -= 1
            elif k == 'punct' and t in ('.', ':'):
                rev.append(t)
                j -= 1
            else:
                break
        rev.reverse()
        qualname = ''.join(rev)
        if not qualname:
            return None
        name = qualname.rsplit('.', 1)[-1].rsplit(':', 1)[-1]
        sym_kind = 'method' if ':' in qualname else 'assigned'
        sig = _slice_signature(source, tokens, func_idx, qualname + ' = ')
        return qualname, name, sym_kind, sig
    return None


def _slice_signature(source, tokens, func_idx, prefix):
    j = func_idx + 1
    while j < len(tokens) and not (tokens[j][0] == 'punct' and tokens[j][1] == '('):
        j += 1
    if j >= len(tokens):
        return prefix + '(...)'
    depth = 0
    close_pos = None
    while j < len(tokens):
        k, t, pos = tokens[j]
        if k == 'punct' and t == '(':
            depth += 1
        elif k == 'punct' and t == ')':
            depth -= 1
            if depth == 0:
                close_pos = pos
                break
        j += 1
    if close_pos is None:
        return prefix + '(...)'
    raw = source[tokens[func_idx][2]:close_pos + 1]
    raw = raw.replace(chr(10), ' ').replace(chr(13), ' ')
    return prefix + raw


def _find_block_end(tokens, func_idx):
    depth = 0
    j = func_idx
    while j < len(tokens):
        k, t, _ = tokens[j]
        if k == 'keyword':
            if t in _OPENERS:
                depth += 1
            elif t in _CLOSERS:
                depth -= 1
                if depth == 0:
                    return j
        j += 1
    return None


def find_all_lua_symbols(symbols, qualname):
    """All Lua symbols with the given qualname, in source order."""
    out = [s for s in symbols if s.qualname == qualname]
    out.sort(key=lambda s: s.line_start)
    return out


def lua_signature_end_line(source, symbol):
    """1-based line where the signature of `symbol` ends.

    Signature = `function NAME(params)` -- everything up to and including
    the closing `)` of the parameter list. Returns None if it cannot be
    located (defensive; should not happen on a well-formed Symbol).
    """
    tokens = list(_tokenize(source))
    line_of = _make_line_index(source)
    # Find the 'function' keyword on symbol.line_start.
    func_idx = None
    for i, (kind, text, pos) in enumerate(tokens):
        if kind == 'keyword' and text == 'function' and line_of(pos) == symbol.line_start:
            func_idx = i
            break
    if func_idx is None:
        return None
    # Walk to the first '(' after it, then balance parens.
    j = func_idx + 1
    while j < len(tokens) and not (tokens[j][0] == 'punct' and tokens[j][1] == '('):
        j += 1
    if j >= len(tokens):
        return None
    depth = 0
    while j < len(tokens):
        kind, text, pos = tokens[j]
        if kind == 'punct' and text == '(':
            depth += 1
        elif kind == 'punct' and text == ')':
            depth -= 1
            if depth == 0:
                return line_of(pos)
        j += 1
    return None


def lua_body_bounds(source, symbol):
    """1-based inclusive (body_start, body_end) of `symbol`'s body.

    Body = lines strictly between the signature and the closing `end`.
    Returns None for one-liners (`function f() return 1 end`), where there
    is no line-level body to address, or when the signature cannot be
    located.
    """
    sig_end = lua_signature_end_line(source, symbol)
    if sig_end is None:
        return None
    body_start = sig_end + 1
    body_end = symbol.line_end - 1
    if body_start > body_end:
        return None
    return body_start, body_end


def lua_signature_bounds(source, symbol):
    """1-based inclusive (sig_start, sig_end) covering the signature line(s).

    For multi-line signatures (`function f(\n    a,\n    b)`), returns the
    whole range. For one-liners -- (line, line). Returns None if signature
    cannot be located.
    """
    sig_end = lua_signature_end_line(source, symbol)
    if sig_end is None:
        return None
    return symbol.line_start, sig_end


__all__ = [
    'parse_lua_symbols', 'find_lua_symbol', 'find_all_lua_symbols',
    'extract_lua_imports',
    'lua_signature_end_line', 'lua_signature_bounds', 'lua_body_bounds',
]




