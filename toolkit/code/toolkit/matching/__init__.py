"""Shared matchers for grep-family and write-family tools.

Pure functions over (text, pattern) — no I/O, no backend, no format.

- `Pattern` (from .pattern) — regex/literal matching for `grep` /
  `grep_replace`. What `grep` finds with given flags, `grep_replace`
  replaces.
- `find_text` / `find_all_text` (from .text) — byte-exact matching with
  optional trailing-whitespace tolerance, for `replace_in_file` /
  `replace_between` / `insert_at_anchor`. Shared so all three tools
  have identical tier semantics by construction.
"""
from .binary import (
    get_timings,
    has_binary_extension,
    is_binary,
    is_binary_file,
    reset_timings,
)
from .pattern import Pattern
from .word import is_word
from .text import (
    TextMatch,
    find_all_text,
    find_text,
    mark_invisible,
    similar_lines,
)

__all__ = [
    "has_binary_extension",
    "is_binary",
    "is_binary_file",
    "get_timings",
    "reset_timings",
    "Pattern",
    "is_word",
    "TextMatch",
    "find_all_text",
    "find_text",
    "mark_invisible",
    "similar_lines",
]
