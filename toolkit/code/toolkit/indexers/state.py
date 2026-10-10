"""Version tracker for index files.

Each index (INDEX.md, CODE_INDEX.md, CODE_INDEX_LUA.md) has a sibling
`<index>.version` file holding {"seq": N}. `seq` increments on every
successful rebuild and never goes back. It is *not* a snapshot and does
not carry history: its only purpose is to let a long-lived consumer (an
LLM in a chat session) detect that the index changed since it last read
it. When it sees a version newer than the one it remembers, it knows to
re-read the index instead of trusting a possibly stale diff.

The version file is best-effort. Missing, unreadable, or malformed files
are treated as seq=0; write failures do not fail the surrounding rebuild.
"""
from __future__ import annotations

import json

from ..core.backend import Backend


def read_seq(backend: Backend, path: str) -> int:
    """Current version of the index at `path`, or 0 if unavailable."""
    try:
        if not backend.exists(path):
            return 0
        text = backend.read(path)
        data = json.loads(text)
        if isinstance(data, dict):
            v = data.get("seq")
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                return v
    except Exception:
        pass
    return 0


def bump_seq(backend: Backend, path: str) -> int:
    """Increment the version and return the new value.

    Write failures are swallowed: a rebuild that produced a correct index
    should not fail just because the version bookkeeping could not land.
    """
    nxt = read_seq(backend, path) + 1
    try:
        backend.write(path, json.dumps({"seq": nxt}))
    except Exception:
        pass
    return nxt
