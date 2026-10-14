"""Read-only tools: read_file, file_exists, file_stat, list_files, grep."""
from __future__ import annotations

import fnmatch
import re
import time
from typing import Any

from ..core.backend import Backend
from ..core.models import Result, Section
from ..core.paths import normalize_path
from ..formats import Format
from ..formats.model import ParsedDoc
from ..matching import Pattern


class ReadFileTool:
    name = "read_file"
    op = "read"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Format | None,
        file_path: str,
        section_number: str | None = None,
        section_title: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        max_bytes: int | None = None,
        numbered: bool | None = None,
        escape: str | None = None,
        raw: str | None = None,
        **_: Any,
    ) -> Result:
        text = backend.read(file_path)

        # Two orthogonal axes:
        #   numbered — prefix each line with "N: " (for reading / replace_range)
        #   escape   — how invisible chars are shown:
        #       "perline" — every line is its own Python repr literal (default);
        #                   \n vs \r\n, trailing spaces, tabs are all visible.
        #       "blob"    — the whole selected content is a single repr literal
        #                   (copy it whole as a multi-line `search`).
        #       "none"    — raw text, no escaping.
        # Legacy `raw` (repr/text/numbered) is accepted and mapped to (numbered, escape).
        if raw is not None:
            legacy = {
                "repr": (False, "blob"),
                "text": (False, "none"),
                "numbered": (True, "none"),
            }
            if raw not in legacy:
                return Result(
                    status="error",
                    message=f"raw: repr|text|numbered, получено {raw!r}",
                    action="read_file",
                    error_code="bad_raw",
                )
            num0, esc0 = legacy[raw]
            if numbered is None:
                numbered = num0
            if escape is None:
                escape = esc0
        if numbered is None:
            numbered = True
        if escape is None:
            escape = "perline"
        if escape not in ("perline", "blob", "none"):
            return Result(
                status="error",
                message=f"escape: perline|blob|none, получено {escape!r}",
                action="read_file",
                error_code="bad_escape",
            )
        if numbered and escape == "blob":
            return Result(
                status="error",
                message="numbered=true несовместим с escape=blob",
                action="read_file",
                error_code="bad_escape",
            )

        def _render_block(lines_keep: list[str], first_no: int) -> str:
            if escape == "blob":
                return repr("".join(lines_keep))
            if escape == "none":
                body_lines = [ln.rstrip("\r\n") for ln in lines_keep]
                if numbered:
                    return "\n".join(
                        f"{first_no + i}: {ln}" for i, ln in enumerate(body_lines)
                    )
                return "\n".join(body_lines)
            # perline
            out: list[str] = []
            for i, ln in enumerate(lines_keep):
                prefix = f"{first_no + i}: " if numbered else ""
                out.append(prefix + repr(ln))
            return "\n".join(out)

        if section_number is not None or section_title is not None:
            if fmt is None:
                return Result(
                    status="error",
                    message="section_number/section_title требуют Format (fmt=None)",
                    action="read_file",
                    error_code="no_format",
                )
            doc = fmt.parse(text)
            sec = doc.find(number=section_number, title=section_title)
            if sec is None:
                what = section_number if section_number is not None else section_title
                return Result(
                    status="error",
                    message=f"Секция '{what}' не найдена в {file_path}",
                    action="read_file",
                    error_code="not_found",
                )
            end = ParsedDoc.section_full_end(sec)
            content = text[sec.heading_start:end]
            header = self._section_header(file_path, sec)
            lines_keep = content.splitlines(keepends=True)
            first_no = text[: sec.heading_start].count("\n") + 1
            body = _render_block(lines_keep, first_no)
            return self._render(header, body, max_bytes, "read_file")

        if start_line is not None or end_line is not None:
            all_lines = text.splitlines()
            s = (int(start_line) - 1) if start_line is not None else 0
            e = int(end_line) if end_line is not None else len(all_lines)
            s = max(0, s)
            e = min(len(all_lines), e)
            if s >= e:
                return Result(
                    status="error",
                    message=(f"Пустой диапазон L{start_line}–L{end_line} "
                             f"(всего {len(all_lines)} строк)"),
                    action="read_file",
                    error_code="bad_range",
                )
            header = f"{file_path} L{s + 1}–L{e}"
            lines_keep = text.splitlines(keepends=True)[s:e]
            body = _render_block(lines_keep, s + 1)
            return self._render(header, body, max_bytes, "read_file")

        lines_keep = text.splitlines(keepends=True)
        body = _render_block(lines_keep, 1)
        return self._render(file_path, body, max_bytes, "read_file")

    @staticmethod
    def _section_header(file_path: str, sec) -> str:
        hashes = "#" * sec.level
        num = f"{sec.number}. " if sec.number else ""
        return f"{file_path} [{hashes} {num}{sec.title}]"

    @staticmethod
    def _render(header: str, body: str, max_bytes: int | None, action: str) -> Result:
        truncated = False
        if max_bytes is not None and max_bytes > 0:
            enc = body.encode("utf-8")
            if len(enc) > max_bytes:
                body = enc[:max_bytes].decode("utf-8", errors="ignore")
                truncated = True
        if truncated:
            header += f" (обрезано до {max_bytes} байт)"
        return Result(status="ok", message=f"{header}\n{body}", action=action)

    def _slice_lines_keepends(self, text: str, start_line: int, end_line: int) -> str:
        """Slice text by 1-based line numbers (inclusive), preserving endings."""
        lines = text.splitlines(keepends=True)
        s = max(0, start_line - 1)
        e = min(len(lines), end_line)
        if s >= e:
            return ""
        return "".join(lines[s:e])


class FileExistsTool:
    name = "file_exists"
    op = "read"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    def execute(self, backend: Backend, fmt: Any, file_path: str, **_: Any) -> Result:
        return Result(
            status="ok",
            message=str(backend.exists(file_path)).lower(),
            action="file_exists",
        )


class FileStatTool:
    name = "file_stat"
    op = "read"
    path_args = ["file_path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Format | None,
        file_path: str,
        **_: Any,
    ) -> Result:
        st = backend.stat(file_path)
        size_kb = st.size_bytes / 1024
        mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.mtime))
        lines_out = [
            file_path,
            f"  {size_kb:.1f} KB, {st.lines} строк, mtime {mtime_str}",
        ]

        if fmt is not None:
            try:
                text = backend.read(file_path)
                doc = fmt.parse(text)
            except Exception:
                doc = None
            if doc is not None:
                flat = doc.flatten()
                if flat:
                    lines_out.append(f"  Секции ({len(flat)}):")
                    for s in flat:
                        _render_stat_section(s, text, lines_out)
                else:
                    lines_out.append("  Секции: нет")

        return Result(status="ok", message="\n".join(lines_out), action="file_stat")


def _render_stat_section(s: Section, source: str, out: list[str]) -> None:
    full_end = ParsedDoc.section_full_end(s)
    body = source[s.heading_start:full_end]
    size_kb = len(body.encode("utf-8")) / 1024
    l_start = source[:s.heading_start].count("\n") + 1
    n_newlines = body.count("\n")
    l_end = l_start + n_newlines - (1 if body.endswith("\n") else 0)
    indent = "  " * (s.level - 2)
    hashes = "#" * s.level
    num_part = f"{s.number}. " if s.number else ""
    out.append(f"    {indent}{hashes} {num_part}{s.title}  L{l_start}–L{l_end}  {size_kb:.1f} KB")


class ListFilesTool:
    name = "list_files"
    op = "read"
    path_args = ["directory"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        directory: str = "",
        glob: str = "*",
        show_size: bool = True,
        **_: Any,
    ) -> Result:
        directory = normalize_path(directory)
        # Prefer list_with_stat: for MCP backends it collapses N stat calls
        # into one execute_luau, avoiding per-file round-trips.
        fn = getattr(backend, "list_with_stat", None) if show_size else None
        if callable(fn):
            rows = fn(directory or "", glob)
            if not rows:
                return Result(status="ok", message="(пусто)", action="list_files")
            out = [f"{p}  ({ln} стр., {sz / 1024:.1f} KB)" for p, sz, ln in rows]
            if len(out) > _LIST_FILES_CAP:
                return _list_too_many(directory, len(out))
            if len(out) > 100:
                out = out[:100] + [f"... и ещё {len(rows) - 100}"]
            return Result(status="ok", message="\n".join(out), action="list_files")
        paths = backend.list(directory or "", glob)
        if not paths:
            return Result(status="ok", message="(пусто)", action="list_files")
        out: list[str] = []
        for p in paths:
            if not show_size:
                out.append(p)
                continue
            try:
                st = backend.stat(p)
                size_kb = st.size_bytes / 1024
                out.append(f"{p}  ({st.lines} стр., {size_kb:.1f} KB)")
            except Exception:
                out.append(p)
        if len(out) > _LIST_FILES_CAP:
            return _list_too_many(directory, len(out))
        if len(out) > 100:
            out = out[:100] + [f"... и ещё {len(paths) - 100}"]
        return Result(status="ok", message="\n".join(out), action="list_files")


_LIST_FILES_CAP = 2000


def _list_too_many(directory: str, n: int) -> Result:
    return Result(
        status="ok", action="list_files",
        message=(
            f"{directory or '(root)'}: {n} файлов — слишком много для плоского списка.\n"
            f"Используй `survey_dir` (агрегат по расширениям и подкаталогам) "
            f"или уточни `directory=` / `file_glob=`."
        ),
    )


class SurveyDirTool:
    """Reconnaissance: aggregate counts over a tree, for unfamiliar projects.

    Returns counts by extension plus per-first-level-subdir breakdown. Use
    before deciding roots and .patchignore; the response is small even for
    huge trees (top-N only). Read-only.
    """
    name = "survey_dir"
    op = "read"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any = None,
        path: str = "",
        ext: str | list[str] | None = None,
        top: int = 20,
        max_files: int = 200_000,
        **_: Any,
    ) -> Result:
        from collections import Counter
        path = normalize_path(path) if path else ""
        try:
            all_paths = backend.list(path, "*")
        except Exception as e:
            return Result(
                status="error", action="survey_dir",
                error_code="list_failed",
                message=(f"survey_dir: не удалось прочитать {path!r}: "
                         f"{type(e).__name__}: {e}"),
            )
        if not all_paths:
            return Result(
                status="ok", action="survey_dir",
                message=f"{path or '(root)'}: (пусто)",
            )
        if len(all_paths) > max_files:
            return Result(
                status="error", action="survey_dir",
                error_code="too_many_files",
                message=(f"survey_dir: {len(all_paths)} файлов > {max_files}. "
                         f"Уточни path."),
            )

        ext_set: set[str] | None = None
        if ext:
            if isinstance(ext, str):
                ext_set = {ext.lower()}
            else:
                ext_set = {str(e).lower() for e in ext}

        prefix = (path.rstrip("/") + "/") if path else ""

        ext_count: Counter[str] = Counter()
        first_count: Counter[str] = Counter()
        first_ext: dict[str, Counter[str]] = {}
        top_files = 0

        for p in all_paths:
            rel = p[len(prefix):] if prefix and p.startswith(prefix) else p
            if not rel:
                continue
            e = _ext_of(rel)
            if ext_set is not None and e not in ext_set:
                continue
            ext_count[e] += 1
            parts = rel.split("/")
            if len(parts) == 1:
                top_files += 1
                continue
            top_name = parts[0]
            first_count[top_name] += 1
            first_ext.setdefault(top_name, Counter())[e] += 1

        lines: list[str] = []
        head = f"{path or '(root)'}: {len(all_paths)} файлов"
        if ext_set is not None:
            head += f"  (фильтр ext: {sorted(ext_set)})"
        lines.append(head)
        lines.append("")

        lines.append(f"по расширениям (top {top}):")
        if ext_count:
            for e, c in ext_count.most_common(top):
                lines.append(f"  {e:14s}  {c:8d}")
        else:
            lines.append("  (нет)")
        lines.append("")

        if first_count:
            lines.append(f"подкаталоги 1-го уровня ({len(first_count)}, top {top}):")
            for name, c in first_count.most_common(top):
                sub = first_ext.get(name, Counter()).most_common(3)
                sub_s = "  ".join(f"{e}:{n}" for e, n in sub)
                lines.append(f"  {name:44s}  {c:8d}   [{sub_s}]")
        if top_files:
            lines.append(f"  {'(файлы в корне)':44s}  {top_files:8d}")

        return Result(status="ok", action="survey_dir", message="\n".join(lines))


def _ext_of(p: str) -> str:
    name = p.rsplit("/", 1)[-1]
    if "." not in name:
        return "(no ext)"
    return "." + name.rsplit(".", 1)[-1].lower()


class GrepTool:
    name = "grep"
    op = "read"
    path_args = ["directory"]
    path_list_args = ["paths"]

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        pattern: str,
        paths: list[str] | None = None,
        directory: str = "",
        file_glob: str = "*",
        exclude_glob: str | list[str] | None = None,
        regex: bool = True,
        fixed_strings: bool = False,
        ignore_case: bool = False,
        word_boundary: bool = False,
        before: int = 0,
        after: int = 0,
        max_results: int = 200,
        **_: Any,
    ) -> Result:
        from ..core.paths import is_mcp_path
        if directory and is_mcp_path(directory) and not paths:
            return Result(
                status="error", action="grep", error_code="wrong_domain",
                message=(f"grep работает только с файловой системой; "
                         f"для Roblox-путей используй `grep_mcp`. "
                         f"Дано: {directory!r}"),
            )
        # Explicit `paths` are taken literally: the default
        # exclude_glob (INDEX.md and friends) is meant for directory
        # scans, where skipping index artifacts avoids grep-ing the
        # index itself. When the caller names files explicitly, they
        # mean them — only a caller-supplied exclude_glob narrows that.
        if paths:
            candidates = list(paths)
            if exclude_glob is None:
                excludes = []
            elif isinstance(exclude_glob, str):
                excludes = [exclude_glob] if exclude_glob else []
            else:
                excludes = list(exclude_glob)
        else:
            directory = normalize_path(directory)
            candidates = backend.list(directory or "", file_glob)
            if isinstance(exclude_glob, str):
                excludes = [exclude_glob] if exclude_glob else []
            elif isinstance(exclude_glob, list):
                excludes = list(exclude_glob)
            else:
                excludes = ["INDEX.md"]

        def _excluded(p: str) -> bool:
            name = p.rsplit("/", 1)[-1]
            return any(fnmatch.fnmatch(name, e) or fnmatch.fnmatch(p, e) for e in excludes)

        candidates = [p for p in candidates if not _excluded(p)]

        try:
            pat = Pattern(
                pattern, regex=regex, fixed_strings=fixed_strings,
                ignore_case=ignore_case, word_boundary=word_boundary,
            )
        except re.error as e:
            return Result(
                status="error",
                message=f"Некорректная регулярка: {e}",
                action="grep",
                error_code="bad_regex",
            )
        matcher = pat.search

        has_context = before > 0 or after > 0
        results: list[str] = []
        match_count = 0
        skipped = 0

        # Prefer batch reads: on MCP this collapses N per-file round-trips
        # into a few execute_luau calls. read_many returns {path: text} and
        # silently omits paths it could not read (counted as skipped).
        texts: dict[str, str] = {}
        read_many = getattr(backend, "read_many", None)
        if callable(read_many) and candidates:
            try:
                texts = read_many(candidates)
            except Exception:
                texts = {}
        for p in candidates:
            if texts:
                text = texts.get(p)
                if text is None:
                    skipped += 1
                    continue
            else:
                try:
                    text = backend.read(p)
                except Exception:
                    skipped += 1
                    continue
            lines = text.splitlines()
            for lineno, line in enumerate(lines, start=1):
                if not matcher(line):
                    continue
                match_count += 1
                if has_context:
                    if results and results[-1] != "--":
                        results.append("--")
                    s = max(0, lineno - 1 - before)
                    e = min(len(lines), lineno + after)
                    for j in range(s, e):
                        mark = ">" if j == lineno - 1 else " "
                        results.append(f"{p}:{j + 1}: {mark} {lines[j].rstrip()}")
                else:
                    results.append(f"{p}:{lineno}: {line.rstrip()}")
                if len(results) >= max_results:
                    results.append(f"... обрезано на {max_results} строк")
                    header = f"Найдено {match_count}+ совпадений (обрезано):"
                    return Result(status="ok", message=header + "\n" + "\n".join(results),
                                  action="grep")

        if not results:
            msg = f"Совпадений не найдено: {pattern!r}"
            if skipped:
                msg += f" (пропущено файлов: {skipped})"
            return Result(status="ok", message=msg, action="grep")

        header = f"Найдено {match_count} совпадений:"
        return Result(status="ok", message=header + "\n" + "\n".join(results), action="grep")
