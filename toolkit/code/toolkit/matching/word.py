"""ASCII word-character test, matching Lua's `[%w_]`."""
from __future__ import annotations


def is_word(ch: str) -> bool:
    """True if `ch` is an ASCII word character ([A-Za-z0-9_]).

    Deliberately ASCII-only: Lua's `%w` is ASCII, and word-boundary
    semantics in `grep_mcp` / `grep_replace_mcp` use `c:match('[%w_]')`.
    Using Python's `\\w` (which includes Unicode letters) here would make
    FS-side and MCP-side disagree on non-ASCII input.
    """
    if not ch:
        return False
    return ch.isascii() and (ch.isalnum() or ch == "_")
