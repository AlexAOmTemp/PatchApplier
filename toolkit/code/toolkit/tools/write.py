"""Write tools: replace_in_file, replace_range, replace_section, set_summary.

replace_in_file/replace_range — байтовые операции, не требуют Format.
replace_section/set_summary — section-aware, парсят документ через Format.
"""
from __future__ import annotations

import ast
import re
from typing import Any

from ..core.backend import Backend
from ..core.models import Delta, Result
from ..formats import Format
from ..formats.model import ParsedDoc


# --- replace_in_file -------------------------------------------------------


class ReplaceInFileTool:
    name = "replace_in_file"
    op = "write"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    def execute(
            self,
            backend: Backend,
            fmt: Any,
            file_path: str,
            search: str,
            replace: str,
            occurrence: int | str = 1,
            search_repr: bool = True,
            **_: Any,
        ) -> Result:
            before_raw = backend.read(file_path)
            # CRLF normalization: match in LF-space, restore on write.
            had_crlf = "\r\n" in before_raw
            before = before_raw.replace("\r\n", "\n") if had_crlf else before_raw

            # search_repr=True (default): if `search` looks like a Python string
            # literal (starts and ends with matching quote), unwrap it via
            # ast.literal_eval. This is how `read_file raw=repr` output is
            # meant to be used. If it is not a valid literal — fall through to
            # byte-exact matching (backward compat with raw text callers).
            needle = search
            if search_repr:
                stripped = search.strip()
                if (len(stripped) >= 2
                        and stripped[0] in ("'", '"')
                        and stripped[-1] == stripped[0]):
                    try:
                        needle = ast.literal_eval(stripped)
                    except (ValueError, SyntaxError):
                        needle = search
            if "\r\n" in needle:
                needle = needle.replace("\r\n", "\n")

            repl = replace
            if "\r\n" in repl:
                repl = repl.replace("\r\n", "\n")

            total = before.count(needle)
            if total == 0:
                return Result(
                    status="error",
                    message=f"Строка не найдена в {file_path}",
                    action="replace_in_file",
                    error_code="no_match",
                )

            if occurrence == "all" or occurrence == -1:
                after = before.replace(needle, repl)
                n_occurrences = total
            else:
                try:
                    occ_num = int(occurrence)
                except (ValueError, TypeError):
                    return Result(
                        status="error",
                        message=f"Некорректное occurrence: {occurrence!r}",
                        action="replace_in_file",
                        error_code="bad_occurrence",
                    )
                if occ_num < 1:
                    return Result(
                        status="error",
                        message=f"occurrence должен быть >= 1, получено {occ_num}",
                        action="replace_in_file",
                        error_code="bad_occurrence",
                    )
                if occ_num > total:
                    return Result(
                        status="error",
                        message=f"Найдено {total} вхождений, нельзя заменить #{occ_num}",
                        action="replace_in_file",
                        error_code="bad_occurrence",
                    )
                pos = -1
                for _ in range(occ_num):
                    pos = before.find(needle, pos + 1)
                after = before[:pos] + repl + before[pos + len(needle):]
                n_occurrences = 1

            after_out = after.replace("\n", "\r\n") if had_crlf else after
            backend.write(file_path, after_out)
            delta = _delta(before_raw, after_out, n_occurrences)
            msg = _delta_msg(file_path, delta, n_occurrences, total)
            return Result(
                status="ok",
                message=msg,
                delta=delta,
                verified=True,
                action="replace_in_file",
            )


# --- replace_range ---------------------------------------------------------


class ReplaceRangeTool:
    name = "replace_range"
    op = "write"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    def execute(
            self,
            backend: Backend,
            fmt: Any,
            file_path: str,
            start_line: int,
            end_line: int,
            new_content: str,
            expected_first_line: str | None = None,
            **_: Any,
        ) -> Result:
            before_raw = backend.read(file_path)
            had_crlf = "\r\n" in before_raw
            before = before_raw.replace("\r\n", "\n") if had_crlf else before_raw
            lines = before.splitlines(keepends=True)

            try:
                s = int(start_line) - 1
                e = int(end_line)
            except (ValueError, TypeError):
                return Result(
                    status="error",
                    message="Некорректные start_line/end_line",
                    action="replace_range",
                    error_code="bad_range",
                )
            if s < 0 or e < s or e > len(lines):
                return Result(
                    status="error",
                    message=(f"Диапазон L{start_line}–L{end_line} вне файла "
                             f"(всего {len(lines)} строк)"),
                    action="replace_range",
                    error_code="bad_range",
                )

            if expected_first_line is not None:
                actual = lines[s].rstrip("\n").rstrip("\r")
                if actual != expected_first_line:
                    return Result(
                        status="error",
                        message=(f"content_mismatch: L{s + 1} = {actual!r}, "
                                 f"expected {expected_first_line!r}"),
                        action="replace_range",
                        error_code="content_mismatch",
                    )

            block = "".join(lines[s:e])
            new = new_content
            if new and not new.endswith("\n"):
                new += "\n"
            after = before[:sum(len(x) for x in lines[:s])] + new + before[
                sum(len(x) for x in lines[:e]):
            ]

            after_out = after.replace("\n", "\r\n") if had_crlf else after
            backend.write(file_path, after_out)
            delta = _delta(block, new, 1)
            msg = (f"L{start_line}–L{end_line} → L{start_line}–L{start_line + _count_lines(new) - 1} "
                   f"в {file_path} — {_sign_str(delta.lines)} стр., {_sign_str(delta.bytes)} Б")
            return Result(
                status="ok",
                message=msg,
                delta=delta,
                verified=True,
                action="replace_range",
            )


class ReplaceBetweenTool:
    name = "replace_between"
    op = "write"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        file_path: str,
        start_anchor: str,
        end_anchor: str,
        new_content: str,
        include_start: bool = True,
        include_end: bool = True,
        occurrence: int = 1,
        **_: Any,
    ) -> Result:
        if not start_anchor or not end_anchor:
            return Result(
                status="error",
                message="start_anchor и end_anchor обязательны",
                action="replace_between",
                error_code="empty_input",
            )
        before = backend.read(file_path)
        starts = _find_all(before, start_anchor)
        ends = _find_all(before, end_anchor)
        if not starts:
            return Result(status="error", message=f"start_anchor не найден: {start_anchor!r}", action="replace_between", error_code="no_match")
        if not ends:
            return Result(status="error", message=f"end_anchor не найден: {end_anchor!r}", action="replace_between", error_code="no_match")
        pairs = [(s, e) for s in starts for e in ends if e > s]
        if not pairs:
            return Result(status="error", message="end_anchor не следует за start_anchor ни в одном вхождении", action="replace_between", error_code="anchor_order")
        try:
            occ_num = int(occurrence)
        except (ValueError, TypeError):
            return Result(status="error", message=f"Некорректное occurrence: {occurrence!r}", action="replace_between", error_code="bad_occurrence")
        if occ_num < 1 or occ_num > len(pairs):
            return Result(status="error", message=f"Найдено {len(pairs)} пар (start<end), нельзя взять #{occ_num}", action="replace_between", error_code="occurrence_out_of_range")
        s, e = pairs[occ_num - 1]
        prefix = before[:s] if include_start else before[:s + len(start_anchor)]
        suffix = before[e + len(end_anchor):] if include_end else before[e:]
        after = prefix + new_content + suffix
        backend.write(file_path, after)
        s_line = before.count("\n", 0, s) + 1
        e_full = e + len(end_anchor)
        e_line = before.count("\n", 0, e_full) + 1
        new_lines = _count_lines(new_content)
        old_block = before[s:e_full]
        delta = _delta(old_block, new_content, 1)
        msg = (f"L{s_line}\u2013L{e_line} \u2192 L{s_line}\u2013L{s_line + new_lines - 1} "
               f"\u0432 {file_path} \u2014 {_sign_str(delta.lines)} \u0441\u0442\u0440., {_sign_str(delta.bytes)} \u0411")
        return Result(
            status="ok",
            message=msg,
            delta=delta,
            verified=True,
            action="replace_between",
        )


class InsertAtAnchorTool:
    name = "insert_at_anchor"
    op = "write"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        file_path: str,
        anchor: str,
        position: str,
        new_content: str,
        occurrence: int = 1,
        **_: Any,
    ) -> Result:
        if not anchor:
            return Result(status="error", message="anchor обязателен", action="insert_at_anchor", error_code="empty_input")
        if position not in ("before", "after"):
            return Result(status="error", message=f"position должен быть before|after, получено {position!r}", action="insert_at_anchor", error_code="bad_position")
        before = backend.read(file_path)
        anchors = _find_all(before, anchor)
        if not anchors:
            return Result(status="error", message=f"anchor не найден: {anchor!r}", action="insert_at_anchor", error_code="no_match")
        try:
            occ_num = int(occurrence)
        except (ValueError, TypeError):
            return Result(status="error", message=f"Некорректное occurrence: {occurrence!r}", action="insert_at_anchor", error_code="bad_occurrence")
        if occ_num < 1 or occ_num > len(anchors):
            return Result(status="error", message=f"Найдено {len(anchors)} вхождений, нельзя взять #{occ_num}", action="insert_at_anchor", error_code="occurrence_out_of_range")
        pos = anchors[occ_num - 1]
        insert_at = pos if position == "before" else pos + len(anchor)
        after = before[:insert_at] + new_content + before[insert_at:]
        backend.write(file_path, after)
        delta = _delta(before, after, 1)
        s_line = before.count("\n", 0, insert_at) + 1
        where = "\u043f\u0435\u0440\u0435\u0434" if position == "before" else "\u043f\u043e\u0441\u043b\u0435"
        msg = f"{where} L{s_line} \u0432 {file_path} \u2014 {_sign_str(delta.lines)} \u0441\u0442\u0440., {_sign_str(delta.bytes)} \u0411"
        return Result(
            status="ok",
            message=msg,
            delta=delta,
            verified=True,
            action="insert_at_anchor",
        )


class ReplaceSectionTool:
    name = "replace_section"
    op = "write"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Format | None,
        file_path: str,
        section_number: str | None = None,
        section_title: str | None = None,
        new_content: str = "",
        mode: str = "body",
        **_: Any,
    ) -> Result:
        if fmt is None:
            return Result(
                status="error",
                message="replace_section требует Format (fmt=None)",
                action="replace_section",
                error_code="no_format",
            )
        if section_number is None and section_title is None:
            return Result(
                status="error",
                message="нужен section_number или section_title",
                action="replace_section",
                error_code="no_selector",
            )
        if mode not in ("body", "all"):
            return Result(
                status="error",
                message=f"mode должен быть 'body' или 'all' (получено '{mode}')",
                action="replace_section",
                error_code="bad_mode",
            )

        before = backend.read(file_path)
        doc = fmt.parse(before)
        sec = doc.find(number=section_number, title=section_title)
        if sec is None:
            what = section_number if section_number is not None else section_title
            return Result(
                status="error",
                message=f"Секция '{what}' не найдена в {file_path}",
                action="replace_section",
                error_code="not_found",
            )

        full_end = ParsedDoc.section_full_end(sec)
        replacement = new_content.rstrip("\n")
        tail = before[full_end:]
        replacement += "\n\n" if tail else "\n"

        if mode == "all":
            old_block = before[sec.heading_start:full_end]
            new_text = before[:sec.heading_start] + replacement + tail
        else:
            old_block = before[sec.body_start:full_end]
            new_text = before[:sec.body_start] + replacement + tail

        backend.write(file_path, new_text)
        delta = _delta(old_block, replacement, 1)

        new_end = _count_lines(before[:sec.heading_start]) + _count_lines(replacement)
        start_line = _count_lines(before[:sec.heading_start]) + 1
        num_part = sec.number or "?"
        msg = (f"§{num_part} {file_path} ({mode}): {_sign_str(delta.lines)} стр., "
               f"{_sign_str(delta.bytes)} Б")
        return Result(
            status="ok",
            message=msg,
            delta=delta,
            verified=True,
            action="replace_section",
        )


# --- set_summary -----------------------------------------------------------


class SetSummaryTool:
    name = "set_summary"
    op = "write"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Format | None,
        file_path: str,
        section_number: str | None = None,
        section_title: str | None = None,
        summary: str | None = None,
        tags: list[str] | str | None = None,
        **_: Any,
    ) -> Result:
        if fmt is None:
            return Result(
                status="error",
                message="set_summary требует Format (fmt=None)",
                action="set_summary",
                error_code="no_format",
            )
        if section_number is None and section_title is None:
            return Result(
                status="error",
                message="нужен section_number или section_title",
                action="set_summary",
                error_code="no_selector",
            )
        if summary is None:
            return Result(
                status="error",
                message="нужен summary",
                action="set_summary",
                error_code="no_summary_arg",
            )

        # Normalize tags: str -> list; empty list -> None (don't touch)
        if isinstance(tags, str):
            tags_list: list[str] | None = [t.strip() for t in tags.split(",") if t.strip()]
        elif isinstance(tags, list):
            tags_list = [str(t).strip() for t in tags if str(t).strip()]
        else:
            tags_list = None
        if tags_list == []:
            tags_list = None

        before = backend.read(file_path)
        doc = fmt.parse(before)
        sec = doc.find(number=section_number, title=section_title)
        if sec is None:
            what = section_number if section_number is not None else section_title
            return Result(
                status="error",
                message=f"Секция '{what}' не найдена в {file_path}",
                action="set_summary",
                error_code="not_found",
            )

        top = before[sec.heading_end:sec.body_start]
        new_top = _rewrite_top(top, fmt, summary, tags_list)
        after = before[:sec.heading_end] + new_top + before[sec.body_start:]

        backend.write(file_path, after)
        delta = _delta(before, after, 1)
        num_part = sec.number or "?"
        tag_note = f", tags={tags_list}" if tags_list is not None else ""
        msg = f"§{num_part} в {file_path}: summary обновлён ({len(summary)} симв.{tag_note})"
        return Result(
            status="ok",
            message=msg,
            delta=delta,
            verified=True,
            action="set_summary",
        )


class VerifySectionTool:
    name = "verify_section"
    op = "write"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    _default_index: str | None = None

    @classmethod
    def set_paths(cls, index_output: str | None = None) -> None:
        """Set default INDEX.md path used to locate the meta sidecar."""
        cls._default_index = index_output or None

    def execute(
        self,
        backend: Backend,
        fmt: Format | None,
        file_path: str,
        section_number: str | None = None,
        section_title: str | None = None,
        **_: Any,
    ) -> Result:
        if fmt is None:
            return Result(
                status="error",
                message="verify_section \u0442\u0440\u0435\u0431\u0443\u0435\u0442 Format (fmt=None)",
                action="verify_section",
                error_code="no_format",
            )
        if section_number is None and section_title is None:
            return Result(
                status="error",
                message="\u043d\u0443\u0436\u0435\u043d section_number \u0438\u043b\u0438 section_title",
                action="verify_section",
                error_code="no_selector",
            )

        text = backend.read(file_path)
        try:
            doc = fmt.parse(text)
        except Exception as e:
            return Result(
                status="error",
                message=f"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0440\u0430\u0437\u043e\u0431\u0440\u0430\u0442\u044c {file_path}: {e}",
                action="verify_section",
                error_code="parse_error",
            )
        sec = doc.find(number=section_number, title=section_title)
        if sec is None:
            what = section_number if section_number is not None else section_title
            return Result(
                status="error",
                message=f"\u0421\u0435\u043a\u0446\u0438\u044f '{what}' \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430 \u0432 {file_path}",
                action="verify_section",
                error_code="not_found",
            )
        if sec.summary is None:
            return Result(
                status="error",
                message=(f"\u0423 \u0441\u0435\u043a\u0446\u0438\u0438 '{sec.number or sec.title}' "
                         f"\u043d\u0435\u0442 summary \u2014 \u043d\u0435\u0447\u0435\u0433\u043e \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0442\u044c. \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 set_summary."),
                action="verify_section",
                error_code="no_summary",
            )

        from ..indexers.meta import load_meta, save_meta, resolve_path
        index_path = self._default_index or "INDEX.md"
        meta_path = resolve_path(index_path)
        meta = load_meta(backend, meta_path)

        if sec.number is None:
            key = sec.title
        elif "." in sec.number:
            key = f"{sec.number} {sec.title}"
        else:
            key = f"{sec.number}. {sec.title}"

        file_meta = meta.setdefault(file_path, {})
        import time as _time
        now_ts = _time.time()
        entry = file_meta.get(key) or {}
        entry["body_hash"] = sec.body_hash
        entry["body_changed_at"] = entry.get("body_changed_at", now_ts)
        entry["summary_hash"] = sec.summary_hash
        entry["summary_changed_at"] = now_ts
        file_meta[key] = entry
        save_meta(backend, meta_path, meta)

        num_part = sec.number or "?"
        return Result(
            status="ok",
            message=(f"\u00a7{num_part} \u0432 {file_path}: summary \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0451\u043d "
                     f"(summary_changed_at \u043e\u0431\u043d\u043e\u0432\u043b\u0451\u043d, \u0444\u0430\u0439\u043b \u043d\u0435 \u0442\u0440\u043e\u043d\u0443\u0442)"),
            action="verify_section",
            verified=True,
        )


# --- top-region rewriting --------------------------------------------------


def _fmt_annotation(fmt: Format, keyword: str, value: str) -> str:
    return f"{fmt.ann_open} {keyword}: {value} {fmt.ann_close}"


def _rewrite_top(
    top: str,
    fmt: Format,
    summary: str,
    tags: list[str] | None,
) -> str:
    new_top = top
    if tags is not None:
        tags_line = _fmt_annotation(fmt, fmt.ann_tags, ", ".join(tags))
        new_top = _replace_or_insert(new_top, fmt, fmt.ann_tags, tags_line)
    summary_line = _fmt_annotation(fmt, fmt.ann_summary, summary)
    new_top = _replace_or_insert(new_top, fmt, fmt.ann_summary, summary_line)
    return new_top


def _replace_or_insert(top: str, fmt: Format, keyword: str, new_line: str) -> str:
    flags = 0 if fmt.case_sensitive else re.IGNORECASE
    pat = re.compile(
        rf"{re.escape(fmt.ann_open)}\s*{re.escape(keyword)}\s*:\s*.+?\s*{re.escape(fmt.ann_close)}",
        flags,
    )
    if pat.search(top):
        return pat.sub(lambda m: new_line, top, count=1)
    return _insert_annotation(top, new_line)


def _insert_annotation(top: str, new_line: str) -> str:
    stripped = top.lstrip("\n")
    if not stripped:
        # only blanks (or empty) — insert at very start
        return new_line + "\n" + top
    # insert right before first annotation (after leading blanks, if any)
    i = 0
    while i < len(top) and top[i] == "\n":
        i += 1
    return top[:i] + new_line + "\n" + top[i:]


# --- shared helpers --------------------------------------------------------


def _find_all(text: str, needle: str) -> list[int]:
    """All start offsets of non-overlapping occurrences of `needle`."""
    if not needle:
        return []
    out: list[int] = []
    pos = 0
    while True:
        i = text.find(needle, pos)
        if i < 0:
            return out
        out.append(i)
        pos = i + len(needle)


def _count_lines(text: str) -> int:
    if not text:
        return 0
    n = text.count("\n")
    if not text.endswith("\n"):
        n += 1
    return n


def _delta(before_text: str, after_text: str, occurrences: int) -> Delta:
    return Delta(
        lines=_count_lines(after_text) - _count_lines(before_text),
        bytes=len(after_text.encode("utf-8")) - len(before_text.encode("utf-8")),
        occurrences=occurrences,
    )


def _sign_str(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


def _delta_msg(path: str, delta: Delta, n_occ: int, total: int) -> str:
    tail = ""
    if n_occ < total:
        tail = f" (осталось {total - n_occ})"
    elif n_occ == total:
        tail = " (последнее)" if total == 1 else " (все)"
    return (f"{path}: заменено {n_occ} вхожд."
            f"{tail} — {_sign_str(delta.lines)} стр., {_sign_str(delta.bytes)} Б")


def copy_section_impl(
    backend: Backend,
    fmt: Format | None,
    source_file: str,
    target_file: str,
    section_number: str | None,
    section_title: str | None,
    position: str,
    anchor: str | None,
) -> Result:
    """Copy a markdown section from source_file to target_file.

    Source is not modified. If target_file does not exist it is created.
    Duplicate (same section number or matching title) in target is an error.
    """
    action = "copy_unit"
    if fmt is None:
        return Result(status="error", action=action, error_code="no_format",
                      message="copy_section требует Format")
    if position not in ("start", "end", "before", "after"):
        return Result(status="error", action=action, error_code="bad_position",
                      message=f"position: start|end|before|after, \u0434\u0430\u043d\u043e {position!r}")
    if position in ("before", "after") and not anchor:
        return Result(status="error", action=action, error_code="anchor_required",
                      message=f"position={position!r} \u0442\u0440\u0435\u0431\u0443\u0435\u0442 anchor")
    if position in ("start", "end") and anchor:
        return Result(status="error", action=action, error_code="anchor_not_allowed",
                      message=f"position={position!r} \u043d\u0435 \u043f\u0440\u0438\u043d\u0438\u043c\u0430\u0435\u0442 anchor")

    src = backend.read(source_file)
    src_doc = fmt.parse(src)
    sec = src_doc.find(number=section_number, title=section_title)
    if sec is None:
        what = section_number or section_title
        return Result(status="error", action=action, error_code="unknown_unit",
                      message=f"\u0421\u0435\u043a\u0446\u0438\u044f '{what}' \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430 \u0432 {source_file}")
    full_end = ParsedDoc.section_full_end(sec)
    block = src[sec.heading_start:full_end]
    block_trim = block.rstrip("\n")

    if not backend.exists(target_file):
        new_tgt = block_trim + "\n"
        backend.write(target_file, new_tgt)
        return Result(status="ok", action=action, verified=True,
                      message=f"{source_file} \u2192 {target_file}: \u00a7{sec.number or sec.title} \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u0430 "
                              f"({len(block_trim.splitlines())} \u0441\u0442\u0440., target \u0441\u043e\u0437\u0434\u0430\u043d)")

    tgt = backend.read(target_file)
    tgt_doc = fmt.parse(tgt)
    if tgt_doc.find(number=sec.number, title=None) is not None:
        return Result(status="error", action=action, error_code="destination_exists",
                      message=f"\u00a7{sec.number} \u0443\u0436\u0435 \u0435\u0441\u0442\u044c \u0432 {target_file}")

    if position == "end":
        new_tgt = tgt.rstrip("\n") + "\n\n" + block_trim + "\n"
    elif position == "start":
        new_tgt = block_trim + "\n\n" + tgt
    else:
        anchor_sec = tgt_doc.find(number=anchor, title=None)
        if anchor_sec is None:
            anchor_sec = tgt_doc.find(number=None, title=anchor)
        if anchor_sec is None:
            return Result(status="error", action=action, error_code="anchor_not_found",
                          message=f"anchor '{anchor}' \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d \u0432 {target_file}")
        a_start = anchor_sec.heading_start
        a_end = ParsedDoc.section_full_end(anchor_sec)
        if position == "before":
            new_tgt = tgt[:a_start] + block_trim + "\n\n" + tgt[a_start:]
        else:
            new_tgt = tgt[:a_end].rstrip("\n") + "\n\n" + block_trim + "\n" + tgt[a_end:]

    backend.write(target_file, new_tgt)
    return Result(status="ok", action=action, verified=True,
                  message=f"{source_file} \u2192 {target_file}: \u00a7{sec.number or sec.title} \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d\u0430 "
                          f"({len(block_trim.splitlines())} \u0441\u0442\u0440., {position})")
