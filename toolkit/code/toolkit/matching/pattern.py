"""Compiled matcher shared by `grep` and `grep_replace`.

A single `Pattern` instance answers the questions both tools ask:

    search(line)            -> bool           (grep)
    finditer(line)          -> [(a, b), ...]  (grep_replace: spans)
    sub(line, replacement)  -> (new, count)   (grep_replace: apply)

Using the same object for both tools is the point: whatever `grep`
reports as a match with the same flags, `grep_replace` will replace.
"""
from __future__ import annotations

import re
from typing import Iterator

from .word import is_word


class Pattern:
    """Compiled pattern.

    `regex` defaults to True — same as `grep`'s default. `fixed_strings`
    takes priority: when True, `regex` is ignored and the pattern is
    matched literally.

    `ignore_case` in literal mode lowercases both sides; in regex mode it
    sets re.IGNORECASE.

    `word_boundary` requires a non-word char on each side of a match
    (start/end of line count as boundaries). Implemented manually against
    `is_word`, so semantics match the Lua side and do not depend on
    Python's `\\b` (which is Unicode-aware and would drift).
    """

    def __init__(
        self,
        pattern: str,
        *,
        regex: bool = True,
        fixed_strings: bool = False,
        ignore_case: bool = False,
        word_boundary: bool = False,
    ):
        self.raw = pattern
        self.regex_mode = bool(regex) and not bool(fixed_strings)
        self.ignore_case = bool(ignore_case)
        self.word_boundary = bool(word_boundary)

        if self.regex_mode:
            flags = re.IGNORECASE if self.ignore_case else 0
            # re.error bubbles up; callers turn it into bad_regex.
            self._compiled = re.compile(pattern, flags)
            self._needle = ""
        else:
            self._compiled = None
            self._needle = pattern.lower() if self.ignore_case else pattern

    def search(self, line: str) -> bool:
        """True if the line has at least one match.

        Fast path: in regex mode without a word-boundary check the compiled
        pattern answers directly. `finditer` allocates a generator per line
        (millions of calls on a large scan) and costs ~3x more for the same
        boolean answer.
        """
        if self.regex_mode and not self.word_boundary:
            return self._compiled.search(line) is not None
        for _ in self.finditer(line):
            return True
        return False

    def finditer(self, line: str) -> Iterator[tuple[int, int]]:
        """Yield (start, end) half-open spans of non-overlapping matches.

        Word-boundary is applied per candidate. In literal mode a failed
        boundary advances by one char (the next occurrence may start
        inside the current one); in regex mode `re` already yields
        non-overlapping candidates and the filter just drops those that
        fail the check.
        """
        if self.regex_mode:
            for m in self._compiled.finditer(line):
                a, b = m.start(), m.end()
                if self._passes_boundary(line, a, b):
                    yield a, b
            return

        if not self._needle:
            return
        hay = line.lower() if self.ignore_case else line
        needle = self._needle
        nlen = len(needle)
        n = len(hay)
        start = 0
        while start <= n - nlen:
            a = hay.find(needle, start)
            if a < 0:
                return
            b = a + nlen
            if self._passes_boundary(line, a, b):
                yield a, b
                start = b
            else:
                start = a + 1

    def sub(self, line: str, replacement: str) -> tuple[str, int]:
        """Replace every non-overlapping match. Returns (new_line, count)."""
        spans = list(self.finditer(line))
        if not spans:
            return line, 0
        out: list[str] = []
        cursor = 0
        for a, b in spans:
            out.append(line[cursor:a])
            out.append(replacement)
            cursor = b
        out.append(line[cursor:])
        return "".join(out), len(spans)

    def _passes_boundary(self, line: str, a: int, b: int) -> bool:
        if not self.word_boundary:
            return True
        left_ok = (a == 0) or not is_word(line[a - 1])
        right_ok = (b == len(line)) or not is_word(line[b])
        return left_ok and right_ok
