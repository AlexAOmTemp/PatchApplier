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
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Format | None,
        path: str = "",
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
        # Binary check before the full read: a 12 MB .dll would blow up on
        # UTF-8 decode after wasting the whole read. Address access still
        # honours the call — the error names the file and its size, so the
        # caller can switch to file_stat instead of guessing.
        from ..matching import is_binary
        try:
            head = backend.read_head(path)
        except Exception:
            head = b""
        if is_binary(head):
            try:
                st = backend.stat(path)
                size_s = f"{st.size_bytes / 1024:.1f} KB"
            except Exception:
                size_s = "unknown size"
            return Result(
                status="error", action="read_file",
                error_code="binary",
                message=(f"{path} is binary ({size_s}); "
                         f"use file_stat for size/mtime, or read_head for a hex dump"),
            )
        text = backend.read(path)

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
                    message=f"Секция '{what}' не найдена в {path}",
                    action="read_file",
                    error_code="not_found",
                )
            end = ParsedDoc.section_full_end(sec)
            content = text[sec.heading_start:end]
            header = self._section_header(path, sec)
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
            header = f"{path} L{s + 1}–L{e}"
            lines_keep = text.splitlines(keepends=True)[s:e]
            body = _render_block(lines_keep, s + 1)
            return self._render(header, body, max_bytes, "read_file")

        lines_keep = text.splitlines(keepends=True)
        body = _render_block(lines_keep, 1)
        return self._render(path, body, max_bytes, "read_file")

    @staticmethod
    def _section_header(path: str, sec) -> str:
        hashes = "#" * sec.level
        num = f"{sec.number}. " if sec.number else ""
        return f"{path} [{hashes} {num}{sec.title}]"

    @staticmethod
    def _render(header: str, body: str, max_bytes: int | None, action: str) -> Result:
        from ..core.limits import clip_with_marker, resolve_cap
        cap = resolve_cap(max_bytes)
        hint = ("Передай max_bytes=N для большего или читай секцией "
                "(section_number / section_title / start_line+end_line).")
        body, _ = clip_with_marker(body, cap, hint)
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
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(self, backend: Backend, fmt: Any, path: str = "", **_: Any) -> Result:
        return Result(
            status="ok",
            message=str(backend.exists(path)).lower(),
            action="file_exists",
        )


class FileStatTool:
    name = "file_stat"
    op = "read"
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Format | None,
        path: str = "",
        **_: Any,
    ) -> Result:
        st = backend.stat(path)
        size_kb = st.size_bytes / 1024
        mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.mtime))
        lines_out = [
            path,
            f"  {size_kb:.1f} KB, {st.lines} строк, mtime {mtime_str}",
        ]

        if fmt is not None:
            try:
                text = backend.read(path)
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
    path_args = ["path"]
    path_list_args: list[str] = []

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        path: str = "",
        glob: str = "*",
        show_size: bool = True,
        scoped: bool = True,
        recursive: bool = False,
        show_hidden: bool = False,
        filter: bool = True,
        **_: Any,
    ) -> Result:
        path = normalize_path(path)
        from .scope import read_scope as _rs_lf
        scope_obj = None
        hidden_by: dict[str, int] = {}
        scope_err: str | None = None
        if scoped:
            scope_obj, scope_err = _rs_lf(backend)
            if scope_err or (scope_obj and not scope_obj.rules):
                scope_obj = None

        def _filter(items: list[str]) -> list[str]:
            if scope_obj is None:
                return items
            exempt = scope_obj.exemptions_for(path)
            visible, hid = scope_obj.partition(items, exempt=exempt)
            for k, v in hid.items():
                hidden_by[k] = hidden_by.get(k, 0) + v
            keep = set(visible)
            return [p for p in items if p in keep]

        def _footer() -> str:
            if scope_err:
                return f"\n[scope ERR: {scope_err}]"
            if not hidden_by:
                return ""
            n = sum(hidden_by.values())
            parts = ", ".join(f"{k} {v}" for k, v in sorted(hidden_by.items()))
            return f"\n[{n} file(s) hidden by scope ({parts}); pass scoped=false to include]"

        fn = getattr(backend, "list_with_stat", None) if show_size else None
        if callable(fn):
            rows_all = fn(path or "", glob)
            stat_map = {p: (sz, ln) for p, sz, ln in rows_all}
            paths_all = [p for p, _, _ in rows_all]
        else:
            stat_map = {}
            paths_all = backend.list(path or "", glob)

        paths = _filter(paths_all)
        if not show_hidden and filter:
            _pfx = (path.rstrip("/") + "/") if path else ""
            def _rel_lf(p: str) -> str:
                return p[len(_pfx):] if _pfx and p.startswith(_pfx) else p
            paths = [p for p in paths if not backend.is_hidden(_rel_lf(p))]

        if not recursive:
            prefix = (path.rstrip("/") + "/") if path else ""
            direct_files: list[str] = []
            subdirs: set[str] = set()
            for p in paths:
                if prefix and not p.startswith(prefix):
                    continue
                rel = p[len(prefix):] if prefix else p
                parts = rel.split("/")
                if len(parts) == 1:
                    direct_files.append(p)
                else:
                    subdirs.add((prefix + parts[0]) if prefix else parts[0])

            out: list[str] = []
            for d in sorted(subdirs):
                out.append(f"{d}/")
            for f in sorted(direct_files):
                if not show_size:
                    out.append(f)
                    continue
                if f in stat_map:
                    sz, ln = stat_map[f]
                    out.append(f"{f}  ({ln} стр., {sz / 1024:.1f} KB)")
                else:
                    try:
                        st = backend.stat(f)
                        out.append(f"{f}  ({st.lines} стр., {st.size_bytes / 1024:.1f} KB)")
                    except Exception:
                        out.append(f)

            if not out:
                return Result(status="ok", message="(пусто)" + _footer(), action="list_files")
            if len(out) > 100:
                out = out[:100] + [f"... и ещё {len(out) - 100}"]
            return Result(status="ok", message="\n".join(out) + _footer(), action="list_files")

        if not paths:
            return Result(status="ok", message="(пусто)" + _footer(), action="list_files")
        out: list[str] = []
        for p in paths:
            if not show_size:
                out.append(p)
                continue
            if p in stat_map:
                sz, ln = stat_map[p]
                out.append(f"{p}  ({ln} стр., {sz / 1024:.1f} KB)")
            else:
                try:
                    st = backend.stat(p)
                    out.append(f"{p}  ({st.lines} стр., {st.size_bytes / 1024:.1f} KB)")
                except Exception:
                    out.append(p)
        if len(out) > _LIST_FILES_CAP:
            return _list_too_many(path, len(out))
        if len(out) > 100:
            out = out[:100] + [f"... и ещё {len(paths) - 100}"]
        return Result(status="ok", message="\n".join(out) + _footer(), action="list_files")


_LIST_FILES_CAP = 2000


def _list_too_many(path: str, n: int) -> Result:
    return Result(
        status="ok", action="list_files",
        message=(
            f"{path or '(root)'}: {n} файлов — слишком много для плоского списка.\n"
            f"Используй `recursive=False` (прямые дети) "
            f"или `survey_dir` (агрегат по расширениям и подкаталогам), "
            f"или уточни `path=` / `glob=`."
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
        scoped: bool = True,
        filter: bool = True,
        **_: Any,
    ) -> Result:
        from collections import Counter
        from .scope import read_scope as _rs_sd
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
        if filter:
            _pfx = (path.rstrip("/") + "/") if path else ""
            def _rel_sd(p: str) -> str:
                return p[len(_pfx):] if _pfx and p.startswith(_pfx) else p
            all_paths = [p for p in all_paths if not backend.is_hidden(_rel_sd(p))]

        if len(all_paths) > max_files:
            return Result(
                status="error", action="survey_dir",
                error_code="too_many_files",
                message=(f"survey_dir: {len(all_paths)} файлов > {max_files}. "
                         f"Уточни path."),
            )

        hidden_by: dict[str, int] = {}
        scope_err: str | None = None
        if scoped:
            scope_obj, scope_err = _rs_sd(backend)
            if not scope_err and scope_obj and scope_obj.rules:
                exempt = scope_obj.exemptions_for(path) if path else set()
                visible, hidden_by = scope_obj.partition(all_paths, exempt=exempt)
                keep = set(visible)
                all_paths = [p for p in all_paths if p in keep]

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

        if scope_err:
            lines.append("")
            lines.append(f"[scope ERR: {scope_err}]")
        elif hidden_by:
            n = sum(hidden_by.values())
            parts = ", ".join(f"{k} {v}" for k, v in sorted(hidden_by.items()))
            lines.append("")
            lines.append(f"[{n} file(s) hidden by scope ({parts}); pass scoped=false to include]")

        return Result(status="ok", action="survey_dir", message="\n".join(lines))


def _ext_of(p: str) -> str:
    name = p.rsplit("/", 1)[-1]
    if "." not in name:
        return "(no ext)"
    return "." + name.rsplit(".", 1)[-1].lower()


class GrepTool:
    name = "grep"
    op = "read"
    path_args = ["paths"]
    path_list_args = ["paths"]

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        pattern: str,
        paths: str | list[str],
        recursive: bool = True,
        file_glob: str = "*",
        exclude_glob: str | list[str] | None = None,
        regex: bool = True,
        fixed_strings: bool = False,
        ignore_case: bool = False,
        word_boundary: bool = False,
        before: int = 0,
        after: int = 0,
        max_results: int = 200,
        scoped: bool = True,
        filter: bool = True,
        debug_timing: bool = False,
        **_: Any,
    ) -> Result:
        import time as _time
        _timings: list[tuple[str, float]] = []
        _t_prev = [_time.perf_counter()]
        def _mark(label: str) -> None:
            if not debug_timing:
                return
            _now = _time.perf_counter()
            _timings.append((label, _now - _t_prev[0]))
            _t_prev[0] = _now
        def _timing_footer() -> str:
            if not debug_timing or not _timings:
                return ""
            total = sum(dt for _, dt in _timings)
            parts = "  ".join(f"{lbl}={dt*1000:.0f}ms" for lbl, dt in _timings)
            return f"\n[timing: {parts}  total={total*1000:.0f}ms]"
        from ..core.paths import is_mcp_path
        from .scope import read_scope as _read_scope
        _given = paths
        if isinstance(_given, str):
            _given = [_given]
        if not _given:
            return Result(
                status="error", action="grep", error_code="missing_arg",
                message=("paths is required: pass a file, a directory, or a "
                         "list of both; grep does not scan the whole workspace "
                         "by default"),
            )
        for _p in _given:
            if is_mcp_path(_p):
                return Result(
                    status="error", action="grep", error_code="wrong_domain",
                    message=(f"grep работает только с файловой системой; "
                             f"для Roblox-путей используй `grep_mcp`. "
                             f"Дано: {_p!r}"),
                )

        # Each element of `paths` is resolved by type (ripgrep model):
        #   * file -> address access: read directly, no scan filters;
        #   * dir  -> scan: `recursive` decides depth, .patchignore and
        #            scope apply. Mixed lists are allowed.
        explicit_files: list[str] = []
        scan_dirs: list[str] = []
        for _p in _given:
            _p = normalize_path(_p)
            try:
                _st = backend.stat(_p)
            except Exception:
                _st = None
            if _st is not None and _st.is_file:
                explicit_files.append(_p)
            else:
                scan_dirs.append(_p)

        # Scan dirs get the default index-artifact exclusion; explicit
        # files do not (naming a file means you mean it).
        if exclude_glob is None:
            excludes = ["INDEX.md"] if scan_dirs else []
        elif isinstance(exclude_glob, str):
            excludes = [exclude_glob] if exclude_glob else []
        else:
            excludes = list(exclude_glob)

        def _excluded(p: str) -> bool:
            name = p.rsplit("/", 1)[-1]
            return any(fnmatch.fnmatch(name, e) or fnmatch.fnmatch(p, e) for e in excludes)

        scan_files: list[str] = []
        for _d in scan_dirs:
            _batch = backend.list(_d, file_glob)
            if not recursive:
                _pfx = (_d.rstrip("/") + "/") if _d else ""
                _batch = [p for p in _batch
                          if "/" not in (p[len(_pfx):] if _pfx and p.startswith(_pfx) else p)]
            scan_files.extend(_batch)

        scan_files = [p for p in scan_files if not _excluded(p)]
        _mark("list")

        # Visibility (.patchignore) applies to scan dirs only; explicit
        # files are address access and ignore it, like `read_file` does.
        if filter and scan_files:
            _get_pred = getattr(backend, "hidden_predicate", None)
            _hidden = _get_pred() if callable(_get_pred) else backend.is_hidden
            _visible: list[str] = []
            for p in scan_files:
                rel = p
                for _d in scan_dirs:
                    _pfx = (_d.rstrip("/") + "/") if _d else ""
                    if not _pfx or p.startswith(_pfx):
                        rel = p[len(_pfx):] if _pfx else p
                        break
                if not _hidden(rel):
                    _visible.append(p)
            scan_files = _visible
        _mark("hidden")

        # Scope applies to scan dirs only. Explicit files bypass it.
        hidden_by: dict[str, int] = {}
        scope_err: str | None = None
        if scoped and scan_files:
            scope, scope_err = _read_scope(backend)
            if not scope_err and scope.rules:
                _exempt: set[str] = set()
                for _d in scan_dirs:
                    if _d:
                        _exempt |= scope.exemptions_for(_d)
                visible, hidden_by = scope.partition(scan_files, exempt=_exempt)
                keep = set(visible)
                scan_files = [p for p in scan_files if p in keep]

        candidates = explicit_files + scan_files

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
        # Binary files are only relevant for scan results. Explicit paths
        # are address access — the caller named the file, so read it.
        # Extension check only, no I/O: grep reads the file anyway, and a
        # full content check (512 B head + decision tree) costs more than
        # the read it saves. Binary bytes in a text-extension file fail
        # the read below and are counted as `skipped`.
        from ..matching import has_binary_extension
        scan_set = set(scan_files)
        binary_skipped = 0
        live = []
        for p in candidates:
            if p in scan_set and has_binary_extension(p):
                binary_skipped += 1
                continue
            live.append(p)
        candidates = live
        _mark("binary")

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
                if match_count >= max_results:
                    header = (f"Показано {match_count} совпадений "
                              f"(лимит max_results={max_results}, скан остановлен; "
                              f"реальное число может быть больше — увеличь max_results):")
                    tail = ""
                    if hidden_by:
                        n = sum(hidden_by.values())
                        parts = ", ".join(f"{k} {v}" for k, v in sorted(hidden_by.items()))
                        tail = (f"\n[{n} file(s) hidden by scope ({parts}); "
                                f"pass scoped=false to include]")
                    _mark("read+match")
                    return Result(status="ok",
                                  message=header + "\n" + "\n".join(results) + tail + _timing_footer(),
                                  action="grep")

        scope_footer = ""
        if scope_err:
            scope_footer = f"\n[scope ERR: {scope_err}]"
        elif hidden_by:
            n = sum(hidden_by.values())
            parts = ", ".join(f"{k} {v}" for k, v in sorted(hidden_by.items()))
            scope_footer = (f"\n[{n} file(s) hidden by scope ({parts}); "
                            f"pass scoped=false to include]")

        _mark("read+match")

        if not results:
            msg = f"Совпадений не найдено: {pattern!r}"
            if skipped:
                msg += f" (пропущено файлов: {skipped})"
            if binary_skipped:
                msg += f" (binary skipped: {binary_skipped})"
            return Result(status="ok", message=msg + scope_footer + _timing_footer(), action="grep")

        _mark("read+match")
        header = f"Найдено {match_count} совпадений:"
        return Result(status="ok", message=header + "\n" + "\n".join(results) + scope_footer + _timing_footer(), action="grep")
