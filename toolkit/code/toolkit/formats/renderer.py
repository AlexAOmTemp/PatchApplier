"""Renderer: Section[] + file meta -> INDEX.md text."""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..core.models import Section
from .model import ParsedDoc


LARGE_KB = 16.0

PREAMBLE = [
    "# Index",
    "",
    "> **Формат индекса:**",
    "> - `## filename  (N стр., M KB, mtime YYYY-MM-DD HH:MM)` — метрики файла.",
    "> - `- N. Заголовок (Lstart–Lend, K KB[, ⚠ no summary|⚠ large]) — summary — [tags]` — метрики узла.",
    "> - Подсекции идут с отступом под родителем.",
    "> - `⚠ no summary` — секция без summary.",
    "> - `⚠ large` — листовая секция >16 KB, стоит разбить на подсекции.",
    "",
]


@dataclass
class FileIndex:
    path: str
    lines: int
    size_bytes: int
    mtime: float
    source: str
    sections: list[Section]


def render_index(files: list[FileIndex], preamble: list[str] | None = None) -> str:
    parts: list[str] = list(preamble if preamble is not None else PREAMBLE)
    for f in files:
        parts.append("")
        parts.extend(_render_file_block(f))
    return "\n".join(parts) + "\n"


def _render_file_block(f: FileIndex) -> list[str]:
    mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.mtime))
    kb = f.size_bytes / 1024
    out = [f"## {f.path}  ({f.lines} стр., {kb:.1f} KB, mtime {mtime_str})"]
    for s in f.sections:
        _render_section(s, 0, f.source, out)
    return out


# --- code index rendering -------------------------------------------------


CODE_PREAMBLE = [
    "# Code Index",
    "",
    "> Формат: модуль → дерево символов с L-диапазонами.",
    "> - `## path  (N стр., M KB, mtime ...)` — модуль.",
    "> - `Hash: X  Len: Y` — source_hash и длина в байтах.",
    "> - `- qualname [kind] (Lstart–Lend) — docstring` — символ.",
    "> - Вложенные символы (methods, nested functions) идут с отступом.",
    "",
]


def render_code_index(
    modules,
    preamble: list[str] | None = None,
    used_by_map: dict[str, list[str]] | None = None,
    uses_map: dict[str, list[str]] | None = None,
    cycles: set[str] | None = None,
) -> str:
    parts: list[str] = list(preamble if preamble is not None else CODE_PREAMBLE)
    for m in modules:
        parts.append("")
        ub = used_by_map.get(m.path) if used_by_map else None
        us = uses_map.get(m.path) if uses_map else None
        in_cycle = bool(cycles and m.path in cycles)
        parts.extend(_render_module_block(m, used_by=ub, uses=us,
                                          in_cycle=in_cycle))
    return "\n".join(parts) + "\n"


def _render_module_block(m, used_by=None, uses=None,
                            in_cycle: bool = False) -> list[str]:
    if getattr(m, "lines", 0):
        lines = m.lines
    else:
        lines = m.source.count("\n")
        if m.source and not m.source.endswith("\n"):
            lines += 1
    size_kb = m.source_len / 1024
    markers = _module_markers(m, lines, size_kb, used_by, uses, in_cycle)
    suffix = ("  " + " ".join(markers)) if markers else ""
    out = [f"## {m.path}  ({lines} \u0441\u0442\u0440., {size_kb:.1f} KB){suffix}"]
    out.append(f"Hash: {m.source_hash}  Len: {m.source_len}")
    if m.imports:
        shown = m.imports[:6]
        rest = len(m.imports) - len(shown)
        imp = ", ".join(shown)
        if rest > 0:
            imp += f" (+{rest})"
        out.append(f"Imports: {imp}")
    if used_by:
        shown = used_by[:6]
        rest = len(used_by) - len(shown)
        ub = ", ".join(shown)
        if rest > 0:
            ub += f" (+{rest})"
        out.append(f"Used by: {ub}")
    if not m.symbols:
        out.append("(no symbols)")
        return out

    supp = getattr(m, "suppress", frozenset()) or frozenset()
    large_on = "all" not in supp and "large" not in supp

    for s in m.symbols:
        depth = s.qualname.count(".")
        indent = "  " * depth
        kind = f"[{s.kind}]"
        line = f"{indent}- {s.qualname} {kind} (L{s.line_start}\u2013L{s.line_end})"
        if getattr(s, "source_hash", None) is not None:
            line += f" H{s.source_hash}"
        if large_on and (s.line_end - s.line_start + 1) > _LARGE_SYMBOL_LINES:
            line += " \u26a0 large"
        if s.docstring:
            line += f" \u2014 {s.docstring}"
        out.append(line)
    return out


_LARGE_FILE_LINES = 300
_LARGE_FILE_KB = 16.0
_LARGE_SYMBOL_LINES = 100


def _module_markers(m, lines: int, size_kb: float,
                    used_by, uses, in_cycle: bool = False,
                    dup_id: int | None = None) -> list[str]:
    """Factual markers for the module header line.

    Facts only — every entry is verifiable from the source or the import
    graph. Interpretation ("hub", "entry", "dead") is left to the reader.
    Suppressible via `# pa: <name>` directives in the file head.
    """
    supp = getattr(m, "suppress", frozenset()) or frozenset()

    def _on(name: str) -> bool:
        return "all" not in supp and name not in supp

    out: list[str] = []
    if getattr(m, "has_main", False) and _on("main"):
        out.append("\u25c9")
    # `← N imp` and `→ N users` are shown only when the count is non-zero:
    # a wall of `→ 0 users` on standalone scripts is noise, not signal.
    if uses and _on("imports"):
        out.append(f"\u2190 {len(uses)} imp")
    if used_by and _on("users"):
        n = len(used_by)
        tests = sum(1 for p in used_by if _is_test_path(p))
        out.append(f"\u2192 {n} users" + (f" ({tests} tests)" if tests else ""))
    path_l = "/" + m.path.lower().lstrip("/")
    if _on("vendor") and ("/vendor/" in path_l or "/_index/" in path_l
                            or "/node_modules/" in path_l):
        out.append("[vendor/]")
    if _on("large") and (lines > _LARGE_FILE_LINES or size_kb > _LARGE_FILE_KB):
        out.append("\u26a0 large")
    if _on("cycle") and in_cycle:
        out.append("\u26a0 cycle")
    if _on("dup") and dup_id is not None:
        out.append(f"\u29c9dub:{dup_id}")
    return out


def _is_test_path(path: str) -> bool:
    p = path.replace("\\", "/").lower()
    return "/tests/" in p or "/test_" in p or p.startswith("tests/") \
        or p.rsplit("/", 1)[-1].startswith("test_")


def _render_section(s: Section, depth: int, source: str, out: list[str]) -> None:
    indent = "  " * depth
    full_end = ParsedDoc.section_full_end(s)
    body = source[s.heading_start:full_end]
    size_kb = len(body.encode("utf-8")) / 1024

    l_start = source[:s.heading_start].count("\n") + 1
    n_newlines = body.count("\n")
    if body.endswith("\n"):
        l_end = l_start + n_newlines - 1
    else:
        l_end = l_start + n_newlines

    markers: list[str] = []
    # `⚠ no summary` is shown only for top-level sections (`##`). In a
    # project where the convention is "summary only on `##`", marking
    # every `###`/`####` produced 90% noise. A subsection is expected to
    # inherit context from its parent.
    if s.summary is None and s.level <= 2 and "no-summary" not in s.suppress:
        markers.append("\u26a0 no summary")
    elif s.stale:
        markers.append("\u26a0 stale")
    if not s.children and size_kb > LARGE_KB and not s.large_ok:
        markers.append("\u26a0 large")
    marker_str = (", " + ", ".join(markers)) if markers else ""

    if s.number:
        # Root sections render as "N. Title"; subsections as "N.M Title" (no trailing dot).
        num_part = f"{s.number} " if "." in s.number else f"{s.number}. "
    else:
        num_part = ""
    line = f"{indent}- {num_part}{s.title} (L{l_start}\u2013L{l_end}, {size_kb:.1f} KB{marker_str})"
    if s.summary:
        line += f" \u2014 {s.summary}"
    if s.tags:
        line += f" \u2014 [{', '.join(s.tags)}]"
    out.append(line)

    for child in s.children:
        _render_section(child, depth + 1, source, out)


def _assign_dup_ids(modules) -> dict[int, int]:
    """Map content_hash -> sequential dup_id for groups with >1 member.

    Empty files (source_len == 0) are skipped: every empty file has the
    same hash, and marking them all as duplicates is noise.
    """
    from collections import Counter
    keys = [(getattr(m, "content_hash", 0), m.source_len)
            for m in modules if m.source_len > 0]
    counts = Counter(keys)
    mapping: dict[int, int] = {}
    next_id = 0
    for m in modules:
        if m.source_len == 0:
            continue
        key = (getattr(m, "content_hash", 0), m.source_len)
        if counts[key] < 2:
            continue
        if key[0] not in mapping:
            next_id += 1
            mapping[key[0]] = next_id
    return mapping


def render_code_structure(
    modules,
    used_by_map: dict[str, list[str]] | None = None,
    uses_map: dict[str, list[str]] | None = None,
    cycles: set[str] | None = None,
    *,
    limit: int = 500,
    path_prefix: str | None = None,
    sort: str = "path",
) -> tuple[str, int, int]:
    """Render one line per module. Returns (text, shown, total).

    `limit=0` means no cap (all modules). `path_prefix` filters by path
    prefix (no leading slash). `sort` is 'path' or 'size' (size = desc).
    """
    pool = list(modules)
    if path_prefix:
        norm = path_prefix.rstrip("/")
        pool = [m for m in pool if m.path == norm or m.path.startswith(norm + "/")]
    if sort == "size":
        pool.sort(key=lambda m: (-m.source_len, m.path))
    else:
        pool.sort(key=lambda m: m.path)
    total = len(pool)
    dup_map = _assign_dup_ids(modules)

    shown = pool if limit <= 0 else pool[:limit]
    lines: list[str] = []
    for m in shown:
        lines.append(_structure_line(m, used_by_map, uses_map, cycles, dup_map, path_prefix))
    text = "\n".join(lines) + ("\n" if lines else "")
    return text, len(shown), total


def _structure_line(m, used_by_map, uses_map, cycles, dup_map,
                    path_prefix: str | None = None) -> str:
    lines_n = m.lines or (m.source.count("\n") + (1 if m.source and not m.source.endswith("\n") else 0))
    size_kb = m.source_len / 1024
    ub = used_by_map.get(m.path) if used_by_map else None
    us = uses_map.get(m.path) if uses_map else None
    in_cycle = bool(cycles and m.path in cycles)
    dup_id = dup_map.get(getattr(m, "content_hash", 0))
    markers = _module_markers(m, lines_n, size_kb, ub, us, in_cycle, dup_id=dup_id)
    suffix = ("  " + " ".join(markers)) if markers else ""
    disp = m.path
    if path_prefix:
        norm = path_prefix.rstrip("/") + "/"
        if disp.startswith(norm):
            disp = disp[len(norm):]
    return f"## {disp}  ({lines_n} \u0441\u0442\u0440., {size_kb:.1f} KB){suffix}"
