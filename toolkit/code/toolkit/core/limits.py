"""Shared output-size limits for read tools.

The default cap is loud, never silent: any clipped payload carries a
marker telling the caller exactly what to pass to see the rest. This
is deliberate — a silent default once made the caller believe it had
seen the map when it had seen 3%.
"""
from __future__ import annotations


DEFAULT_MAX_BYTES = 32 * 1024  # 32 KB ≈ 800 lines


def resolve_cap(max_bytes: int | None) -> int | None:
    """Resolve a caller-supplied byte budget into an effective cap.

    None -> DEFAULT_MAX_BYTES (safe default for read tools).
    0    -> None (explicit opt-out: return everything).
    N>0  -> N.
    """
    if max_bytes is None:
        return DEFAULT_MAX_BYTES
    try:
        n = int(max_bytes)
    except (TypeError, ValueError):
        return DEFAULT_MAX_BYTES
    return None if n <= 0 else n


def clip_with_marker(text: str, cap: int | None, hint: str) -> tuple[str, bool]:
    """Trim ``text`` to ``cap`` bytes on a newline boundary.

    Returns ``(possibly-clipped text, was_clipped)``. When clipped, appends
a loud marker with byte counts, the effective cap, and ``hint`` (what the
caller should pass to read the rest). A ``None`` cap means no clipping.
    """
    if cap is None:
        return text, False
    raw = text.encode("utf-8")
    total = len(raw)
    if total <= cap:
        return text, False
    clipped = raw[:cap]
    nl = clipped.rfind(b"\n")
    if nl > cap // 2:
        clipped = clipped[:nl]
    n = len(clipped)
    out = clipped.decode("utf-8", errors="replace")
    out += f"\n... обрезано: {n} из {total} байт (лимит {cap}). {hint}"
    return out, True
