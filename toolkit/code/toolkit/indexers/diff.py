"""Structure diff — key-agnostic.

Used for doc INDEX (key = (file, heading)) and, later, for code manifest
(key = module path or (module, symbol)). The diff algorithm is the same:
compare two dict[K, M] and classify every key as changed/shifted/added/removed.

"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_FILE_RE = re.compile(r"^##\s+(\S+)")
_SECTION_RE = re.compile(
    r"^(\s*)-\s+(.+?)\s+\(L(\d+)[–-]L(\d+),\s+([\d.]+)\s*KB"
)


# Markers (◉ ← 1 imp → 2 users [tests/] ⚠ large) are rendered AFTER
# `(N стр., M KB)`. Do not anchor `$` at the end — the module line must
# match whether or not markers are present.
CODE_MODULE_RE = re.compile(r"^##\s+(.+?)\s+\((\d+)\s+\u0441\u0442\u0440\.\s*,\s*([\d.]+)\s+KB\)")
CODE_HASH_RE = re.compile(r"^Hash:\s+(\d+)\s+Len:\s+(\d+)")
CODE_SYM_RE = re.compile(r"^(\s*)-\s+(\S+)\s+\[([^\]]+)\]\s+\(L(\d+)[\u2013-]L(\d+)\)(?:\s+H(\d+))?")


@dataclass
class DiffResult:
    header: str
    lines: list[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.lines:
            return self.header
        return self.header + "\n" + "\n".join(self.lines)


@dataclass
class CodeDiffResult:
    header: str
    lines: list[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.lines:
            return self.header
        return self.header + "\n" + "\n".join(self.lines)


def parse_code_index_text(text: str) -> dict:
    """Parse a rendered CODE_INDEX.md into {path: {hash, len, lines, size_kb, symbols}}.

    symbols: {qualname: {kind, line_start, line_end}}
    """
    modules: dict = {}
    current = None
    for line in text.splitlines():
        m = CODE_MODULE_RE.match(line)
        if m:
            path = m.group(1)
            current = {
                "lines": int(m.group(2)),
                "size_kb": float(m.group(3)),
                "hash": None,
                "len": None,
                "symbols": {},
            }
            modules[path] = current
            continue
        if current is None:
            continue
        m = CODE_HASH_RE.match(line)
        if m:
            current["hash"] = int(m.group(1))
            current["len"] = int(m.group(2))
            continue
        m = CODE_SYM_RE.match(line)
        if m:
            qualname = m.group(2)
            kind = m.group(3)
            sym_hash = int(m.group(6)) if m.group(6) is not None else None
            current["symbols"][qualname] = {
                "kind": kind,
                "line_start": int(m.group(4)),
                "line_end": int(m.group(5)),
                "hash": sym_hash,
            }
    return modules


def diff_code_index(prev_text: str, new_text: str) -> CodeDiffResult:
    """Code-specific diff: modules + symbol-level detail for changed modules."""
    if not prev_text and new_text:
        n = len(new_text.splitlines())
        return CodeDiffResult(header=f" [\u0441\u043e\u0437\u0434\u0430\u043d, {n} \u0441\u0442\u0440\u043e\u043a]")
    if prev_text and not new_text:
        return CodeDiffResult(header=" [\u0443\u0434\u0430\u043b\u0451\u043d]")
    if prev_text == new_text:
        return CodeDiffResult(header=" [\u0431\u0435\u0437 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0439]")

    prev = parse_code_index_text(prev_text)
    new = parse_code_index_text(new_text)

    added_mods: list = []
    removed_mods: list = []
    changed_mods: list = []

    for path, nm in new.items():
        if path not in prev:
            added_mods.append((path, nm))
            continue
        pm = prev[path]
        if pm.get("hash") != nm.get("hash"):
            changed_mods.append((path, pm, nm))

    for path, pm in prev.items():
        if path not in new:
            removed_mods.append((path, pm))

    if not (added_mods or removed_mods or changed_mods):
        return CodeDiffResult(header=" [\u0431\u0435\u0437 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0439]")

    # Per-symbol classification for every changed module. `shifted_syms` are
    # counted in the header only: a line-range move without a hash change
    # is bookkeeping, not a real edit, and would otherwise flood the body
    # (a single insert shifts every later symbol).
    module_syms: list = []  # (path, added, removed, changed, shifted)
    total_shifted = 0
    for path, pm, nm in changed_mods:
        added_syms: list = []
        removed_syms: list = []
        changed_syms: list = []
        shifted_syms: list = []
        for qn, ns in nm["symbols"].items():
            if qn not in pm["symbols"]:
                added_syms.append((qn, ns))
                continue
            ps = pm["symbols"][qn]
            line_moved = (ps["line_start"] != ns["line_start"]
                          or ps["line_end"] != ns["line_end"])
            ph, nh = ps.get("hash"), ns.get("hash")
            hash_changed = (ph is not None and nh is not None and ph != nh)
            if hash_changed:
                changed_syms.append((qn, ps, ns))
            elif line_moved and ph is not None and nh is not None:
                # Both hashes present and equal -> pure shift, no content edit.
                shifted_syms.append((qn, ps, ns))
            elif line_moved:
                # Legacy index (no hashes): keep old behaviour.
                changed_syms.append((qn, ps, ns))
        for qn, ps in pm["symbols"].items():
            if qn not in nm["symbols"]:
                removed_syms.append((qn, ps))
        total_shifted += len(shifted_syms)
        module_syms.append((path, added_syms, removed_syms, changed_syms, shifted_syms))

    parts = []
    if changed_mods: parts.append(f"~{len(changed_mods)}")
    if added_mods: parts.append(f"+{len(added_mods)}")
    if removed_mods: parts.append(f"-{len(removed_mods)}")
    if total_shifted: parts.append(f"\u21c5{total_shifted}")
    header = f" [{', '.join(parts)}]"

    lines: list[str] = []
    for path, pm, nm in changed_mods[:20]:
        delta_lines = nm["lines"] - pm["lines"]
        delta_kb = nm["size_kb"] - pm["size_kb"]
        sign_l = f"+{delta_lines}" if delta_lines >= 0 else str(delta_lines)
        lines.append(f"  ~ {path}  ({sign_l} \u0441\u0442\u0440., {delta_kb:+.1f} KB)")

    # Detail is emitted after all module summary lines, grouped per module,
    # so a reader scanning the diff sees "which modules" first, "what inside"
    # second. Keeps the noisy per-symbol lines out of the header area.
    for path, added_syms, removed_syms, changed_syms, shifted_syms in module_syms:
        for qn, ns in added_syms[:3]:
            lines.append(f"      + {path} :: {qn}  [{ns['kind']}]  L{ns['line_start']}\u2013L{ns['line_end']}")
        if len(added_syms) > 3:
            lines.append(f"      + ... \u0438 \u0435\u0449\u0451 {len(added_syms) - 3}")
        for qn, ps in removed_syms[:3]:
            lines.append(f"      - {path} :: {qn}  [{ps['kind']}]  L{ps['line_start']}\u2013L{ps['line_end']}")
        if len(removed_syms) > 3:
            lines.append(f"      - ... \u0438 \u0435\u0449\u0451 {len(removed_syms) - 3}")
        for qn, ps, ns in changed_syms[:3]:
            if (ps["line_start"] == ns["line_start"]
                    and ps["line_end"] == ns["line_end"]):
                lines.append(f"      ~ {path} :: {qn}  [{ns['kind']}]  L{ns['line_start']}\u2013L{ns['line_end']} (\u0438\u0437\u043c\u0435\u043d\u0451\u043d)")
            else:
                lines.append(f"      ~ {path} :: {qn}  [{ns['kind']}]  L{ps['line_start']}\u2013L{ps['line_end']} \u2192 L{ns['line_start']}\u2013L{ns['line_end']}")
        if len(changed_syms) > 3:
            lines.append(f"      ~ ... \u0438 \u0435\u0449\u0451 {len(changed_syms) - 3}")

    if len(changed_mods) > 20:
        lines.append(f"  ~ ... \u0438 \u0435\u0449\u0451 {len(changed_mods) - 20}")

    for path, nm in added_mods[:10]:
        lines.append(f"  + {path}  ({nm['lines']} \u0441\u0442\u0440., {nm['size_kb']:.1f} KB)")
    if len(added_mods) > 10:
        lines.append(f"  + ... \u0438 \u0435\u0449\u0451 {len(added_mods) - 10}")

    for path, pm in removed_mods[:10]:
        lines.append(f"  - {path}  ({pm['lines']} \u0441\u0442\u0440., {pm['size_kb']:.1f} KB)")
    if len(removed_mods) > 10:
        lines.append(f"  - ... \u0438 \u0435\u0449\u0451 {len(removed_mods) - 10}")

    return CodeDiffResult(header=header, lines=lines)


def parse_index_text(text: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Parse a rendered INDEX.md back into {(file, heading): {...}}.

    Each entry carries the raw section line (`line`), so a diff can report
    what actually changed, not just "L moved". Without it, edits that keep
    L and the rounded size_kb identical (summary rewrites, tag changes)
    are invisible to the diff.
    """
    items: dict[tuple[str, str], dict[str, Any]] = {}
    current_file: str | None = None
    for line in text.splitlines():
        m = _FILE_RE.match(line)
        if m:
            current_file = m.group(1)
            continue
        if not current_file:
            continue
        m = _SECTION_RE.match(line)
        if not m:
            continue
        heading = m.group(2).strip()
        items[(current_file, heading)] = {
            "l_start": int(m.group(3)),
            "l_end": int(m.group(4)),
            "size_kb": float(m.group(5)),
            "line": line.strip(),
        }
    return items


def _file_list(text: str) -> list[str]:
    """Unique files referenced by an index text, sorted.

    Every key in parse_index_text() is (file, heading), so the file list is
    just the set of first components. Used when the whole index appears or
    disappears and we want the caller to see *what* it contains, not just a
    line count.
    """
    items = parse_index_text(text)
    return sorted(set(k[0] for k in items))


def _parse_file_headers(text: str) -> dict[str, str]:
    """Map file path -> its full `## path  (N стр., M KB, mtime ...)` line."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _FILE_RE.match(line)
        if m:
            out[m.group(1)] = line.strip()
    return out


_MAX_DIFF_LINES = 500


def diff_index(prev_text: str, new_text: str) -> DiffResult:
    if prev_text == new_text:
        return DiffResult(header=" [без изменений]")
    if not prev_text and new_text:
        files = _file_list(new_text)
        n = len(new_text.splitlines())
        return DiffResult(
            header=f" [создан, {len(files)} файлов, {n} строк]",
            lines=[f"  + {f}" for f in files],
        )
    if prev_text and not new_text:
        files = _file_list(prev_text)
        n = len(prev_text.splitlines())
        return DiffResult(
            header=f" [удалён, {len(files)} файлов, {n} строк]",
            lines=[f"  - {f}" for f in files],
        )

    prev_items = parse_index_text(prev_text)
    new_items = parse_index_text(new_text)
    prev_hdr = _parse_file_headers(prev_text)
    new_hdr = _parse_file_headers(new_text)

    added_files = sorted(f for f in new_hdr if f not in prev_hdr)
    removed_files = sorted(f for f in prev_hdr if f not in new_hdr)

    # Sections of wholly added/removed files are folded into the file-level
    # line: one line per file, not one per section.
    prev_kept = {k: v for k, v in prev_items.items() if k[0] not in removed_files}
    new_kept = {k: v for k, v in new_items.items() if k[0] not in added_files}

    changed: list = []
    shifted: list = []
    added: list = []
    removed: list = []

    for key, n in new_kept.items():
        p = prev_kept.get(key)
        if p is None:
            added.append((key, n))
            continue
        # Full-line compare catches summary/tag edits invisible to L+size.
        if p.get("line") == n.get("line"):
            continue
        same_l = p["l_start"] == n["l_start"] and p["l_end"] == n["l_end"]
        same_s = abs(p.get("size_kb", 0.0) - n.get("size_kb", 0.0)) < 0.05
        if same_l and same_s:
            changed.append((key, p, n))
        elif same_s:
            shifted.append((key, p, n))
        else:
            changed.append((key, p, n))

    for key, p in prev_kept.items():
        if key not in new_kept:
            removed.append((key, p))

    if not (added_files or removed_files or added or removed or changed or shifted):
        return DiffResult(header=" [без изменений]")

    parts: list[str] = []
    if changed: parts.append(f"~{len(changed)}")
    if shifted: parts.append(f"⇅{len(shifted)}")
    n_add = len(added) + len(added_files)
    n_rem = len(removed) + len(removed_files)
    if n_add: parts.append(f"+{n_add}")
    if n_rem: parts.append(f"-{n_rem}")
    header = f" [{', '.join(parts)}]"

    lines: list[str] = []

    for key, p, n in changed[:_MAX_DIFF_LINES]:
        lines.append("  ~ " + _fmt_change(key, p, n, None))
    if len(changed) > _MAX_DIFF_LINES:
        lines.append(f"  ~ ... и ещё {len(changed) - _MAX_DIFF_LINES}")

    for f in added_files:
        lines.append(f"  + {new_hdr[f]}")
    for key, n in added[:_MAX_DIFF_LINES]:
        lines.append("  + " + _fmt_add_remove(key, n, None))
    if len(added) > _MAX_DIFF_LINES:
        lines.append(f"  + ... и ещё {len(added) - _MAX_DIFF_LINES}")

    for f in removed_files:
        lines.append(f"  - {prev_hdr[f]}")
    for key, p in removed[:_MAX_DIFF_LINES]:
        lines.append("  - " + _fmt_add_remove(key, p, None))
    if len(removed) > _MAX_DIFF_LINES:
        lines.append(f"  - ... и ещё {len(removed) - _MAX_DIFF_LINES}")

    return DiffResult(header=header, lines=lines)



def diff_structures(
    prev: dict[Any, dict[str, Any]],
    new: dict[Any, dict[str, Any]],
    *,
    name_fn=None,
    max_changed: int = 500,
    max_shifted_names: int = 8,
) -> DiffResult:
    added, removed, changed, shifted = [], [], [], []

    for key, n in new.items():
        if key not in prev:
            added.append((key, n))
            continue
        p = prev[key]
        same_l = (p["l_start"] == n["l_start"] and p["l_end"] == n["l_end"])
        same_s = abs(p.get("size_kb", 0.0) - n.get("size_kb", 0.0)) < 0.05
        if same_l and same_s:
            continue
        if same_s:
            shifted.append((key, p, n))
        else:
            changed.append((key, p, n))

    for key, p in prev.items():
        if key not in new:
            removed.append((key, p))

    if not (added or removed or changed or shifted):
        return DiffResult(header=" [без изменений]")

    parts = []
    if changed: parts.append(f"~{len(changed)}")
    if shifted: parts.append(f"⇅{len(shifted)}")
    if added: parts.append(f"+{len(added)}")
    if removed: parts.append(f"-{len(removed)}")
    header = f" [{', '.join(parts)}]"

    lines: list[str] = []

    for key, p, n in changed[:max_changed]:
        lines.append("  ~ " + _fmt_change(key, p, n, name_fn))
    if len(changed) > max_changed:
        lines.append(f"  ~ ... и ещё {len(changed) - max_changed}")

    for key, n in added[:max_changed]:
        lines.append("  + " + _fmt_add_remove(key, n, name_fn))
    if len(added) > max_changed:
        lines.append(f"  + ... и ещё {len(added) - max_changed}")

    for key, p in removed[:max_changed]:
        lines.append("  - " + _fmt_add_remove(key, p, name_fn))
    if len(removed) > max_changed:
        lines.append(f"  - ... и ещё {len(removed) - max_changed}")

    return DiffResult(header=header, lines=lines)


# --- formatting helpers ---------------------------------------------------


def _key_str(key, name_fn) -> str:
    if name_fn:
        return name_fn(key)
    if isinstance(key, tuple):
        fname, heading = key[0], key[1]
        h = heading if len(heading) <= 50 else heading[:47] + "..."
        return f"{fname} §{h}"
    return str(key)


def _short_name(key, name_fn) -> str:
    if name_fn:
        return name_fn(key)
    if isinstance(key, tuple):
        fname, heading = key[0], key[1]
        parts = heading.split()
        short = " ".join(parts[:2]) if len(parts) >= 2 else heading
        return f"{fname.split('/')[-1]} §{short}"
    return str(key)


def _fmt_change(key, p, n, name_fn) -> str:
    raw = n.get("line")
    if raw and isinstance(key, tuple):
        body = raw.lstrip("- ").strip()
        return f"{key[0]} §{body}"
    if raw:
        return raw
    label = _key_str(key, name_fn)
    lb = (f"L{p['l_start']}–L{p['l_end']} → L{n['l_start']}–L{n['l_end']}"
          if (p["l_start"] != n["l_start"] or p["l_end"] != n["l_end"])
          else f"L{n['l_start']}–L{n['l_end']}")
    d = n.get("size_kb", 0.0) - p.get("size_kb", 0.0)
    sb = f", {d:+.1f} KB" if abs(d) >= 0.05 else ""
    return f"{label} ({lb}{sb})"


def _fmt_add_remove(key, m, name_fn) -> str:
    raw = m.get("line")
    if raw and isinstance(key, tuple):
        body = raw.lstrip("- ").strip()
        return f"{key[0]} §{body}"
    if raw:
        return raw
    label = _key_str(key, name_fn)
    return f"{label} (L{m['l_start']}–L{m['l_end']})"
