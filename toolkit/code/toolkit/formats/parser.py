"""Markdown parser — state machine over lines.

Handles:
  - fenced code blocks (``` / ~~~) -- headings inside are ignored
  - HTML-comment annotations (<!-- -->) -- single-line and multi-line
  - heading detection with configurable level range
  - top-region extraction (blank lines + annotation comments after heading)
  - nesting by heading level (### is child of ##)
"""
from __future__ import annotations

import re

from ..core.models import Section
from .format import Format
from .model import ParsedDoc


_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_HEADING_ANY = re.compile(r"^(#{1,8})\s+(.+?)\s*$")


# --- public ---------------------------------------------------------------


def parse(text: str, fmt: Format) -> ParsedDoc:
    headings = _find_headings(text, fmt)
    sections = _build_tree(headings, text, fmt)
    return ParsedDoc(source=text, sections=sections)


# --- internal -------------------------------------------------------------


def _iter_lines(text: str):
    """Yield (line_text, start, end) -- end is offset after the '\n', or len(text)."""
    start = 0
    n = len(text)
    while start < n:
        nl = text.find("\n", start)
        if nl == -1:
            yield text[start:], start, n
            return
        yield text[start:nl], start, nl + 1
        start = nl + 1


def _heading_re(fmt: Format) -> re.Pattern[str]:
    return re.compile(
        rf"^#{{{fmt.min_level},{fmt.max_level}}}\s+(.+?)\s*$"
    )


def _find_headings(text: str, fmt: Format) -> list[dict]:
    """First pass: collect heading positions, ignoring fences and comments."""
    results: list[dict] = []
    h_re = _heading_re(fmt)
    in_fence = False
    fence_char: str | None = None
    in_comment = False

    for line, start, end in _iter_lines(text):
        # --- fence toggling ---
        fm = _FENCE_RE.match(line)
        if fm:
            token = fm.group(1)
            c = token[0]
            if not in_fence:
                in_fence = True
                fence_char = c
            elif fence_char == c:
                in_fence = False
                fence_char = None
            continue
        if in_fence:
            continue

        # --- comment tracking ---
        if fmt.ann_open and fmt.ann_close:
            if in_comment:
                if fmt.ann_close in line:
                    in_comment = False
                continue
            # check for comment open
            op = line.find(fmt.ann_open)
            if op != -1:
                cp = line.find(fmt.ann_close, op + len(fmt.ann_open))
                if cp == -1:
                    # multi-line comment starts; heading cannot be here
                    in_comment = True
                    continue
                # single-line comment: strip it out before heading check
                line = line[:op] + line[cp + len(fmt.ann_close):]

        # --- heading check ---
        m = h_re.match(line)
        if not m:
            continue
        # heading must start at column 0
        if not line.startswith(fmt.heading_prefix):
            continue
        results.append({
            "level": len(line) - len(line.lstrip(fmt.heading_prefix)),
            "title_full": m.group(1),
            "line_start": start,
            "line_end": end,
        })
    return results


def _scan_top_region(text: str, pos: int, limit: int, fmt: Format) -> int:
    """Scan past blank lines and annotation-comment lines. Return end offset."""
    if not (fmt.ann_open and fmt.ann_close):
        # annotations off -- top region = blank lines only
        while pos < limit:
            nl = text.find("\n", pos)
            if nl == -1:
                nl = limit
            if text[pos:nl].strip():
                break
            pos = nl + 1
        return pos

    in_comment = False
    while pos < limit:
        nl = text.find("\n", pos)
        if nl == -1:
            nl = limit
        line = text[pos:nl]
        stripped = line.strip()

        if in_comment:
            if fmt.ann_close in line:
                in_comment = False
            pos = nl + 1
            continue

        if not stripped:
            pos = nl + 1
            continue

        if stripped.startswith(fmt.ann_open):
            cp = stripped.find(fmt.ann_close, len(fmt.ann_open))
            if cp == -1:
                in_comment = True
            pos = nl + 1
            continue

        # first non-blank, non-comment line -- top region ends here
        break
    return pos


def _extract_summary(top: str, fmt: Format) -> str | None:
    if not (fmt.ann_summary and fmt.ann_open and fmt.ann_close):
        return None
    flags = 0 if fmt.case_sensitive else re.IGNORECASE
    pat = re.compile(
        rf"{re.escape(fmt.ann_open)}\s*{re.escape(fmt.ann_summary)}\s*:\s*(.+?)\s*{re.escape(fmt.ann_close)}",
        re.DOTALL | flags,
    )
    m = pat.search(top)
    return m.group(1).strip() if m else None


def _extract_tags(top: str, fmt: Format) -> list[str]:
    if not (fmt.ann_tags and fmt.ann_open and fmt.ann_close):
        return []
    flags = 0 if fmt.case_sensitive else re.IGNORECASE
    pat = re.compile(
        rf"{re.escape(fmt.ann_open)}\s*{re.escape(fmt.ann_tags)}\s*:\s*(.+?)\s*{re.escape(fmt.ann_close)}",
        re.DOTALL | flags,
    )
    m = pat.search(top)
    if not m:
        return []
    return [t.strip() for t in m.group(1).split(",") if t.strip()]


def _has_bare(top: str, keyword: str | None, fmt: Format) -> bool:
    if not (keyword and fmt.ann_open and fmt.ann_close):
        return False
    flags = 0 if fmt.case_sensitive else re.IGNORECASE
    pat = re.compile(
        rf"{re.escape(fmt.ann_open)}\s*{re.escape(keyword)}\s*{re.escape(fmt.ann_close)}",
        flags,
    )
    return bool(pat.search(top))


def _split_number(title_full: str, fmt: Format) -> tuple[str | None, str]:
    m = fmt.numbering_pattern.match(title_full)
    if not m:
        return None, title_full.strip()
    number = m.group(0)
    if fmt.trailing_dot:
        number = number.rstrip(".")
    number = number.strip()
    rest = title_full[m.end():].strip()
    if not number:
        return None, title_full.strip()
    return number, rest


def _build_tree(headings: list[dict], text: str, fmt: Format) -> list[Section]:
    from .hashing import hash_text, normalize_body

    if not headings:
        return []

    # Precompute section_end (offset where full block ends) for each heading.
    n = len(headings)
    full_end: list[int] = [len(text)] * n
    for i in range(n):
        lvl = headings[i]["level"]
        for j in range(i + 1, n):
            if headings[j]["level"] <= lvl:
                full_end[i] = headings[j]["line_start"]
                break

    sections: list[Section] = []
    stack: list[tuple[Section, int]] = []  # (section, level)

    for i, h in enumerate(headings):
        level = h["level"]
        heading_start = h["line_start"]
        heading_end = h["line_end"]

        # body_end for a section = next heading (any level), or EOF
        if i + 1 < n:
            body_end = headings[i + 1]["line_start"]
        else:
            body_end = len(text)

        top_end = _scan_top_region(text, heading_end, body_end, fmt)
        top_text = text[heading_end:top_end]

        number, title = _split_number(h["title_full"], fmt)
        summary = _extract_summary(top_text, fmt)
        body_only = text[top_end:body_end]

        section = Section(
            level=level,
            number=number,
            title=title,
            heading_start=heading_start,
            heading_end=heading_end,
            summary=summary,
            tags=_extract_tags(top_text, fmt),
            large_ok=_has_bare(top_text, fmt.ann_large_ok, fmt),
            flat_scope=_has_bare(top_text, fmt.ann_flat, fmt),
            body_start=top_end,
            body_end=body_end,
            children=[],
            body_hash=hash_text(normalize_body(body_only)),
            summary_hash=hash_text(summary) if summary else "",
        )

        while stack and stack[-1][1] >= level:
            stack.pop()
        if stack:
            stack[-1][0].children.append(section)
        else:
            sections.append(section)
        stack.append((section, level))

    return sections
