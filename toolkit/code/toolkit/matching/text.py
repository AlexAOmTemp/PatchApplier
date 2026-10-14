"""Shared text matcher for write tools.

Byte-exact matching with optional trailing-whitespace tolerance. Used by
`replace_in_file`, `replace_between`, `insert_at_anchor` (single anchor
matching) so all three share the same tier semantics by construction.

EOL (CRLF vs LF) normalisation is **not** part of this module. Each tool
normalises its haystack to LF before calling and restores CRLF on write.
Keeping EOL handling in the tool avoids doubling the position arithmetic
and preserves the tool's existing byte-exact contract on disk.

Tiers:
  - "none"     — byte-exact match, applied silently
  - "trailing" — matched after rstrip on every line of both needle and
                 haystack; the tool surfaces this in the Result message

Leading whitespace (indent) is never normalised — it is meaningful.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Normalization = Literal["none", "trailing"]


@dataclass(frozen=True)
class TextMatch:
    """A single match of `needle` in `haystack`.

    `start` and `end` are half-open offsets into the LF-normalised haystack.
    `normalization` records which tier produced this match.
    """
    start: int
    end: int
    normalization: Normalization

    @property
    def is_exact(self) -> bool:
        return self.normalization == "none"


# --- public API ------------------------------------------------------------


def find_all_text(
    haystack: str,
    needle: str,
    *,
    normalize_trailing: bool = True,
) -> list[TextMatch]:
    """All non-overlapping matches of `needle` in `haystack`, source order.

    Tier 1 tried first: if any byte-exact matches exist, returns them and
    only them. Otherwise, when `normalize_trailing=True`, falls back to
    trailing-whitespace tolerance: each line of `needle` is rstripped and
    matched against rstripped haystack lines. Leading whitespace is kept.
    Returns [] if neither tier matches.
    """
    if not needle:
        return []
    exact = _find_exact(haystack, needle)
    if exact:
        return exact
    if not normalize_trailing:
        return []
    return _find_trailing_normalized(haystack, needle)


def find_text(
    haystack: str,
    needle: str,
    *,
    normalize_trailing: bool = True,
) -> TextMatch | None:
    """First match of `needle` in `haystack`, or None."""
    matches = find_all_text(haystack, needle, normalize_trailing=normalize_trailing)
    return matches[0] if matches else None


def mark_invisible(s: str) -> str:
    """Render a line with invisible chars shown, for no_match diagnostics.

    Trailing whitespace becomes \u2423 (space) / \u21e5 (tab). Tabs
    elsewhere become \u21e5. Internal spaces stay as spaces.
    """
    stripped = s.rstrip()
    tail = s[len(stripped):]
    out = stripped.replace("\t", "\u21e5")
    if tail:
        out += tail.replace(" ", "\u2423").replace("\t", "\u21e5")
    return out


def similar_lines(
    haystack: str,
    needle: str,
    n: int = 3,
) -> list[tuple[int, str, float]]:
    """Top-n haystack lines (1-based) most similar to the first needle line.

    Returns [(line_no, marked_text, ratio), ...], sorted by ratio desc.
    Used for no_match diagnostics when neither tier matched.
    """
    import difflib
    needle_first = needle.split("\n", 1)[0]
    out: list[tuple[int, str, float]] = []
    for i, line in enumerate(haystack.split("\n"), start=1):
        r = difflib.SequenceMatcher(None, line, needle_first).ratio()
        if r > 0.5:
            out.append((i, mark_invisible(line), r))
    out.sort(key=lambda x: -x[2])
    return out[:n]


# --- internals -------------------------------------------------------------


def _find_exact(haystack: str, needle: str) -> list[TextMatch]:
    """All non-overlapping byte-exact matches."""
    out: list[TextMatch] = []
    n = len(needle)
    pos = 0
    while True:
        i = haystack.find(needle, pos)
        if i < 0:
            return out
        out.append(TextMatch(i, i + n, "none"))
        pos = i + n


def _find_trailing_normalized(haystack: str, needle: str) -> list[TextMatch]:
    """Ranges matching `needle` after rstrip on every line of both.

    Both inputs are expected to be LF-normalised (the caller's job).
    Returns non-overlapping matches in source order. Empty when the needle
    has more lines than the haystack or no window matches.
    """
    if not needle:
        return []
    needle_lines = needle.split("\n")
    file_lines = haystack.split("\n")
    k = len(needle_lines)
    if k > len(file_lines):
        return []
    needle_norm = [ln.rstrip() for ln in needle_lines]
    line_starts: list[int] = [0]
    off = 0
    for ln in file_lines[:-1]:
        off += len(ln) + 1
        line_starts.append(off)

    matches: list[TextMatch] = []
    for j in range(len(file_lines) - k + 1):
        ok = True
        for i in range(k):
            if file_lines[j + i].rstrip() != needle_norm[i]:
                ok = False
                break
        if not ok:
            continue
        start_off = line_starts[j]
        end_off = line_starts[j + k - 1] + len(file_lines[j + k - 1])
        if matches and start_off < matches[-1].end:
            continue
        matches.append(TextMatch(start_off, end_off, "trailing"))
    return matches
