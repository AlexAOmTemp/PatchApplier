"""grep_replace — search-and-replace across filesystem paths.

Paired with `grep`: same scope arguments, same match options, same
matcher (toolkit.matching.Pattern). Whatever `grep` reports as a match
with the same flags, `grep_replace` will replace.

Two-pass: pass 1 counts replacements without writing; a gate rejects
empty / overflow results before any write happens. Pass 2 writes only
when dry_run=False.

FS-only. For Roblox sources use `grep_replace_mcp` — different domain,
different pattern language, single `execute_luau` inside Studio.
"""
from __future__ import annotations

import fnmatch
from typing import Any

from ..core.backend import Backend
from ..core.models import Delta, Result
from ..core.paths import is_mcp_path, normalize_path
from ..matching import Pattern, is_word


class GrepReplaceTool:
    name = "grep_replace"
    op = "write"
    path_args = ["directory"]
    path_list_args = ["paths"]

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        pattern: str | None = None,
        replacement: str | None = None,
        mappings: list[dict[str, str]] | None = None,
        paths: list[str] | None = None,
        directory: str = "",
        file_glob: str = "*",
        exclude_glob: str | list[str] | None = None,
        regex: bool = True,
        fixed_strings: bool = False,
        ignore_case: bool = False,
        word_boundary: bool = False,
        max_replacements: int = 1000,
        dry_run: bool = True,
        **_: Any,
    ) -> Result:
        action = "grep_replace"

        if directory and is_mcp_path(directory) and not paths:
            return Result(
                status="error", action=action, error_code="wrong_domain",
                message=(f"grep_replace работает только с файловой системой; "
                         f"для Roblox-путей используй `grep_replace_mcp`. "
                         f"Дано: {directory!r}"),
            )

        has_pattern = pattern is not None and pattern != ""
        has_mappings = mappings is not None
        if has_pattern and has_mappings:
            return Result(status="error", action=action, error_code="bad_input",
                          message="укажи только одно из pattern / mappings")
        if not has_pattern and not has_mappings:
            return Result(status="error", action=action, error_code="bad_input",
                          message="нужно одно из pattern / mappings")

        pairs: list[tuple[str, str]] | None = None
        if has_mappings:
            if not mappings:
                return Result(status="error", action=action,
                              error_code="empty_mappings",
                              message="mappings пустой")
            if not fixed_strings:
                return Result(status="error", action=action,
                              error_code="patterns_in_mappings_not_supported",
                              message=("mappings поддерживаются только при "
                                       "fixed_strings=true (регексы нельзя "
                                       "применить как набор за один проход)"))
            if ignore_case:
                return Result(status="error", action=action,
                              error_code="bad_options",
                              message="ignore_case не поддерживается с mappings")
            seen: set[str] = set()
            acc: list[tuple[str, str]] = []
            for m in mappings:
                if not isinstance(m, dict):
                    return Result(status="error", action=action,
                                  error_code="bad_mapping",
                                  message="каждый mapping — объект {from, to}")
                f = m.get("from")
                t = m.get("to")
                if not isinstance(f, str) or not isinstance(t, str):
                    return Result(status="error", action=action,
                                  error_code="bad_mapping",
                                  message="from/to должны быть строками")
                if not f:
                    return Result(status="error", action=action,
                                  error_code="empty_mapping",
                                  message="from не может быть пустым")
                if f == t:
                    return Result(status="error", action=action,
                                  error_code="noop_mapping",
                                  message=f"from == to ({f!r}); это no-op")
                if f in seen:
                    return Result(status="error", action=action,
                                  error_code="duplicate_mapping",
                                  message=f"duplicate from: {f!r}")
                seen.add(f)
                acc.append((f, t))
            acc.sort(key=lambda p: (-len(p[0]), p[0]))
            pairs = acc

        if max_replacements <= 0:
            return Result(status="error", action=action,
                          error_code="bad_options",
                          message="max_replacements должен быть > 0")

        pat: Pattern | None = None
        if has_pattern:
            try:
                pat = Pattern(pattern, regex=regex, fixed_strings=fixed_strings,
                              ignore_case=ignore_case, word_boundary=word_boundary)
            except Exception as e:
                return Result(status="error", action=action,
                              error_code="bad_regex",
                              message=f"Некорректная регулярка: {e}")

        if paths:
            candidates = list(paths)
            if exclude_glob is None:
                excludes: list[str] = []
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
            return any(fnmatch.fnmatch(name, e) or fnmatch.fnmatch(p, e)
                       for e in excludes)

        candidates = [p for p in candidates if not _excluded(p)]
        if not candidates:
            return Result(status="ok", action=action,
                          message="Совпадений не найдено: файлов не найдено")

        per_file: list[tuple[str, int, str, str]] = []
        skipped: list[str] = []
        blocked: list[str] = []
        total = 0

        for p in candidates:
            check = backend.filter_check(p, "write")
            if check is not None:
                blocked.append(p)
                continue
            try:
                text = backend.read(p)
            except Exception:
                skipped.append(p)
                continue
            new_text, count = _apply(text, pat, pairs, replacement, word_boundary)
            if count > 0:
                per_file.append((p, count, text, new_text))
                total += count

        if total == 0:
            msg = "Совпадений не найдено"
            if has_pattern:
                msg += f": {pattern!r}"
            else:
                msg += " (mappings)"
            if skipped:
                msg += f" (пропущено файлов: {len(skipped)})"
            if blocked:
                msg += f" (заблокировано: {len(blocked)})"
            return Result(status="ok", action=action, message=msg)

        if total > max_replacements:
            return Result(
                status="error", action=action,
                error_code="too_many_replacements",
                message=(f"Слишком широкий паттерн: найдено {total} замен, "
                         f"лимит {max_replacements}. Ничего не изменено. "
                         f"Уточни pattern / добавь word_boundary=true / "
                         f"сузь scope / подними max_replacements."),
            )

        applied = False
        byte_diff = 0
        if not dry_run:
            for p, _count, old, new in per_file:
                try:
                    backend.write(p, new)
                    applied = True
                    byte_diff += len(new.encode("utf-8")) - len(old.encode("utf-8"))
                except Exception as e:
                    return Result(
                        status="error", action=action,
                        error_code="write_failed",
                        message=f"Запись {p} провалилась: {type(e).__name__}: {e}",
                    )

        mode = "APPLIED" if applied else "dry_run"
        header = f"[{mode}] файлов: {len(per_file)}, замен: {total}"
        if skipped:
            header += f" (пропущено: {len(skipped)})"
        if blocked:
            header += f" (заблокировано: {len(blocked)})"
        body = "\n".join(f"  {p}\t({n})" for p, n, _, _ in per_file)
        delta = Delta(lines=0, bytes=byte_diff, occurrences=total) if applied else None
        return Result(status="ok", action=action,
                      message=header + "\n" + body, delta=delta)


def _apply(text: str, pat: Pattern | None,
           pairs: list[tuple[str, str]] | None,
           replacement: str | None,
           word_boundary: bool) -> tuple[str, int]:
    """Per-line replace. Line endings are preserved as-is.

    A line does not include its trailing `\\n`; a `\\r` before it (CRLF
    files) is kept in the line, matching `grep`'s per-line view.
    """
    if text == "":
        return text, 0
    out: list[str] = []
    total = 0
    pos = 0
    n = len(text)
    while pos < n:
        nl = text.find("\n", pos)
        if nl < 0:
            line = text[pos:]
            pos = n
            eol = ""
        else:
            line = text[pos:nl]
            pos = nl + 1
            eol = "\n"
        if pat is not None:
            new_line, count = pat.sub(line, replacement or "")
        else:
            new_line, count = _sub_mappings(line, pairs or [], word_boundary)
        out.append(new_line)
        out.append(eol)
        total += count
    return "".join(out), total


def _sub_mappings(line: str, pairs: list[tuple[str, str]],
                  word_boundary: bool) -> tuple[str, int]:
    """Apply mappings longest-first, non-overlapping, no cascade."""
    if not pairs:
        return line, 0
    out: list[str] = []
    i = 0
    from_start = 0
    count = 0
    n = len(line)
    while i < n:
        matched = False
        for f, t in pairs:
            if line.startswith(f, i):
                b = i + len(f)
                if word_boundary:
                    left_ok = (i == 0) or not is_word(line[i - 1])
                    right_ok = (b == n) or not is_word(line[b])
                    if not (left_ok and right_ok):
                        continue
                out.append(line[from_start:i])
                out.append(t)
                i = b
                from_start = i
                count += 1
                matched = True
                break
        if not matched:
            i += 1
    out.append(line[from_start:])
    return "".join(out), count
