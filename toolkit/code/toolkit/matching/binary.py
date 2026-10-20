"""Binary detection for scan tools (grep, grep_replace).

Thin layer over `binaryornot` (a hard dependency — see requirements.txt).

Two checks, different costs:

* `has_binary_extension(path)` — no I/O, matches the suffix against a
  list of ~140 known binary extensions. This is what scan tools use in
  the hot path.
* `is_binary_file(path)` / `is_binary(head)` — content check. Reads the
  512-byte head and runs binaryornot's decision tree (24 features, a
  few encoding probes). Accurate, but ~0.15 ms/file.

Why scan tools prefer the extension check: grep reads every surviving
file anyway, and a plain read is ~0.05 ms/file — three times cheaper
than the content check it would save. A `.txt` file with binary bytes
is simply counted as `skipped` when the read fails to decode. On a
RimWorld-sized tree (24k text-extension files) this turns a ~3.7 s
binary pass into ~0.09 s.

`binaryornot` checks the extension itself inside `is_binary`, so the
two-step order (extension, then content) is preserved for callers that
want a content check — they just pay for it only on text-extension files.

There is no stdlib fallback: the NUL-byte heuristic was less accurate
for Windows code pages and never ran in practice (binaryornot is always
installed).
"""
from __future__ import annotations

import time

from binaryornot.check import (
    has_binary_extension,
    is_binary as _bo_is_binary_path,
    is_binary_string as _bo_is_binary_string,
)


__all__ = [
    "has_binary_extension",
    "is_binary",
    "is_binary_file",
    "get_timings",
    "reset_timings",
]


# Instrumentation: which branch ran and how long it took.
TIMINGS: dict[str, float] = {
    "lib_calls": 0, "lib_ms": 0.0,
    "fallback_calls": 0, "fallback_ms": 0.0,
}


def reset_timings() -> None:
    for k in TIMINGS:
        TIMINGS[k] = 0


def get_timings() -> dict[str, float]:
    return dict(TIMINGS)


def is_binary(head: bytes) -> bool:
    """True if `head` (first bytes of a file) looks binary."""
    if not head:
        return False
    return _bo_is_binary_string(head)


def is_binary_file(path) -> bool:
    """Open `path` and decide if binary via binaryornot.

    Extension is checked first (no I/O); only text-extension files pay
    for the 512-byte head read. Any error (missing file, permission)
    returns False — the caller's real `read` will surface the problem.
    """
    _t0 = time.perf_counter()
    try:
        result = bool(_bo_is_binary_path(str(path)))
    except Exception:
        result = False
    TIMINGS["lib_calls"] += 1
    TIMINGS["lib_ms"] += (time.perf_counter() - _t0) * 1000.0
    return result
