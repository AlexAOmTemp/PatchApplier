"""Tolerant patch parser with compiler-style diagnostics.

Accepted shapes (all equivalent, no mode switch):

  - single object:      {...}
  - array of objects:   [{...}, {...}]
  - several arrays:     [...] [...]
  - arrays with commas: [...], [...]
  - JSONL:              {...}\n{...}

Every action is a JSON object with an `id` field. `id` may hold any JSON
value (number, string, null, ...); it is used only as a label in the log
and in `##RESULT`. Values are not validated; only the presence of the
`id` key is required.

Fragments that fail JSON parsing, or that parse to objects without `id`,
produce diagnostics with source position (line, column) and are ignored.
Duplicate `id` values emit a warning but both actions still apply.

Algorithm: scan the text for top-level `{`. Each `{` is decoded with
`json.JSONDecoder.raw_decode` — an object is either accepted (with an
`id`) or produces a diagnostic. On syntax failure, recovery seeks the
next valid document (line-start first, then any position where
`raw_decode` succeeds), so that a broken object does not swallow its
siblings. Nested arrays (`[[...]]`, `[[{...}]]`) are handled naturally:
array brackets are skipped and only the top-level `{` are decoded.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)
_DEC = json.JSONDecoder()
_MAX_FRAGMENT = 60


@dataclass
class Diagnostic:
    """A compiler-style message about a fragment of the patch text.

    kind     — "syntax" | "missing_id" | "duplicate_id"
    line/col — 1-based source position in the original text
    fragment — short excerpt for context (<=60 chars), for human lookup
    """
    kind: str
    line: int
    column: int
    message: str
    fragment: str = ""


@dataclass
class ParseResult:
    """What `parse_patches` returns: actions + diagnostics.

    `actions` — list of action dicts, each with an `id` field.
    `diagnostics` — compiler-style messages about malformed or incomplete
    fragments. Those fragments are ignored; the rest of the patch applies.
    """
    actions: list[dict] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


def parse_patches(text: str) -> ParseResult:
    """Parse patch text into actions plus diagnostics. Never raises."""
    text = _strip_fence(text)
    if not text.strip():
        return ParseResult()
    return _scan(text)


def _strip_fence(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    m = _FENCE_RE.match(t)
    if m:
        return m.group(1).strip()
    t = t.strip("`").strip()
    if t.lower().startswith("json"):
        t = t[4:].lstrip()
    return t


def _scan(text: str) -> ParseResult:
    result = ParseResult()
    seen_ids: dict[str, int] = {}   # repr(id_value) -> first line
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace() or c in ",[]":
            i += 1
            continue
        if c != "{":
            # Stray non-{ character outside any document.
            i += 1
            continue
        try:
            value, end = _DEC.raw_decode(text, i)
        except json.JSONDecodeError as e:
            nxt = _next_group_start(text, i + 1)
            frag_end = nxt if nxt is not None else n
            result.diagnostics.append(Diagnostic(
                kind="syntax",
                line=e.lineno,
                column=e.colno,
                message=e.msg,
                fragment=_clip(text[i:frag_end]),
            ))
            if nxt is None:
                break
            i = nxt
            continue
        if not isinstance(value, dict):
            i = end
            continue
        _ingest_object(value, text, i, result, seen_ids)
        i = end
    return result


def _ingest_object(obj, text, start, result, seen_ids):
    if "id" not in obj:
        result.diagnostics.append(Diagnostic(
            kind="missing_id",
            line=_line_of(text, start),
            column=_col_of(text, start),
            message="object has no 'id' field",
            fragment=_clip(text[start:start + _MAX_FRAGMENT]),
        ))
        return
    id_value = obj["id"]
    key = repr(id_value)
    if key in seen_ids:
        result.diagnostics.append(Diagnostic(
            kind="duplicate_id",
            line=_line_of(text, start),
            column=_col_of(text, start),
            message=f"id={id_value!r} already seen at line {seen_ids[key]}",
            fragment=_clip(text[start:start + _MAX_FRAGMENT]),
        ))
    else:
        seen_ids[key] = _line_of(text, start)
    result.actions.append(obj)


def _next_group_start(text: str, from_idx: int) -> int | None:
    """Find next position that plausibly starts a new group.

    Two-tier search:
      1. `{` / `[` at line start (only whitespace before). Safe: JSON
         strings cannot contain a raw newline, so a line-start brace
         cannot be inside a string literal.
      2. Any `{` / `[` where `raw_decode` succeeds. Handles one-line
         patches where tier 1 finds nothing.

    Returns None if neither tier finds a position — the caller then
    consumes the remainder as one final syntax diagnostic.
    """
    n = len(text)
    # Tier 1: line-start, must be a valid document
    i = from_idx
    while i < n:
        nl = text.find("\n", i)
        if nl < 0:
            break
        k = nl + 1
        while k < n and text[k] in " \t":
            k += 1
        if k < n and text[k] in "[{":
            try:
                _DEC.raw_decode(text, k)
                return k
            except json.JSONDecodeError:
                pass
        i = nl + 1
    # Tier 2: any valid document start
    i = from_idx
    while i < n:
        k1 = text.find("{", i)
        k2 = text.find("[", i)
        ks = [k for k in (k1, k2) if k >= 0]
        if not ks:
            return None
        k = min(ks)
        try:
            _DEC.raw_decode(text, k)
            return k
        except json.JSONDecodeError:
            i = k + 1
    return None


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _col_of(text: str, pos: int) -> int:
    nl = text.rfind("\n", 0, pos)
    return pos - nl if nl >= 0 else pos + 1


def _clip(s: str) -> str:
    s = s.strip()
    return s if len(s) <= _MAX_FRAGMENT else s[:_MAX_FRAGMENT] + "…"
