"""llmscope — soft presentation filter, managed by the LLM.

Unlike `.patchignore` (hard, user-managed, refuses access), `.llmscope`
only filters what review tools SHOW. Files remain indexed, readable by
explicit path, and greppable if the caller bypasses scope.

File format (one rule per line, mandatory reason):

    # File-level comments start with `#` at line start.
    <pattern>            # <reason>
    !<pattern>           # <reason>   (re-inclusion)

A pattern without `/` matches any single path segment (basename).
A pattern with `/` is a path pattern: prefix-match OR fnmatch, with `*`
crossing `/` (gitignore-ish). The last matching rule wins; `!` negates.
Empty file (or missing) = see everything.

Located at `.patch_applier/llmscope` (state_dir).
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import patchignore


LLMSCOPE_NAME = "llmscope"
LLMSCOPE_PATH = Path(patchignore.STATE_DIR) / LLMSCOPE_NAME


class ScopeParseError(ValueError):
    """Malformed rule line: missing reason, empty pattern, etc."""


@dataclass(frozen=True)
class Rule:
    glob: str                 # normalized: no leading/trailing '/'
    reason: str
    negated: bool = False


@dataclass
class Scope:
    rules: list[Rule] = field(default_factory=list)
    error: str | None = None  # parse error; rules stays empty if set

    @property
    def is_empty(self) -> bool:
        return not self.rules and not self.error

    def is_hidden(self, path: str) -> bool:
        hidden = False
        for r in self.rules:
            if _match_path(path, r.glob):
                hidden = not r.negated
        return hidden

    def is_hidden_ex(self, path: str, exempt: set[str] | None = None) -> bool:
        """Like is_hidden, but skips rules whose glob is in `exempt`."""
        exempt = exempt or set()
        hidden = False
        for r in self.rules:
            if r.glob in exempt:
                continue
            if _match_path(path, r.glob):
                hidden = not r.negated
        return hidden

    def partition(self, paths: Iterable[str],
                  exempt: set[str] | None = None) -> tuple[list[str], dict[str, int]]:
        """Split into visible paths and per-pattern hidden counts.

        A path is attributed to the LAST matching rule's pattern. Negated
        rules re-include: the path goes to visible, not to hidden_by.
        `exempt` is a set of glob strings to skip entirely — used by an
        explicit `path=` request to override the rules hiding that subtree
        root while keeping finer rules intact.
        """
        exempt = exempt or set()
        visible: list[str] = []
        hidden_by: dict[str, int] = {}
        for p in paths:
            matched: Rule | None = None
            for r in self.rules:
                if r.glob in exempt:
                    continue
                if _match_path(p, r.glob):
                    matched = r
            if matched is None or matched.negated:
                visible.append(p)
            else:
                key = ("!" if matched.negated else "") + matched.glob
                hidden_by[key] = hidden_by.get(key, 0) + 1
        return visible, hidden_by

    def exemptions_for(self, path_prefix: str) -> set[str]:
        """Rules whose glob would hide `path_prefix` (either the entry
        itself or any hypothetical child). Used to bypass scope on an
        explicit `path=` without disabling rules for stricter subpaths.

        Two probes: the path itself (catches `tests`, `tests/foo.py`) and
        `path/__probe__` (catches `tests/*`). Subpath rules like
        `tests/slow` match neither probe, so they keep applying.
        """
        norm = path_prefix.rstrip("/")
        if not norm:
            return set()
        probes = (norm, norm + "/__probe__")
        out: set[str] = set()
        for r in self.rules:
            if r.negated:
                continue
            if any(_match_path(pr, r.glob) for pr in probes):
                out.add(r.glob)
        return out

    def footer(self, hidden_by: dict[str, int], scoped: bool) -> str:
        if not scoped or not hidden_by:
            return ""
        total = sum(hidden_by.values())
        parts = ", ".join(f"{k} {v}" for k, v in sorted(hidden_by.items()))
        return f"{total} hidden by scope ({parts}); pass scoped=false to include"


def _match_path(path: str, pattern: str) -> bool:
    path = path.replace("\\", "/").strip("/")
    pattern = pattern.replace("\\", "/").strip("/")
    if not pattern or not path:
        return False
    if "/" not in pattern:
        return any(fnmatch.fnmatchcase(seg, pattern)
                   for seg in path.split("/") if seg)
    # Path pattern: try as prefix from the start, and on every segment
    # boundary (so `Mods/1201382956` matches `RimWorld/Mods/1201382956/x`
    # regardless of which workspace root sits in front of it).
    parts = path.split("/")
    for i in range(len(parts)):
        suffix = "/".join(parts[i:])
        if fnmatch.fnmatchcase(suffix, pattern):
            return True
        if suffix == pattern or suffix.startswith(pattern + "/"):
            return True
    return False


def parse(text: str) -> list[Rule]:
    rules: list[Rule] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if " # " not in line:
            raise ScopeParseError(
                f"line {lineno}: rule has no reason "
                f"(expected `pattern  # reason`): {line!r}"
            )
        pat_str, reason = line.split(" # ", 1)
        pat_str = pat_str.strip()
        reason = reason.strip()
        if not pat_str:
            raise ScopeParseError(f"line {lineno}: empty pattern")
        if not reason:
            raise ScopeParseError(f"line {lineno}: empty reason")
        negated = False
        if pat_str.startswith("!"):
            negated = True
            pat_str = pat_str[1:].strip()
        pat_str = pat_str.strip("/")
        if not pat_str:
            raise ScopeParseError(f"line {lineno}: empty pattern after strips")
        rules.append(Rule(glob=pat_str, reason=reason, negated=negated))
    return rules


def serialize(scope: Scope) -> str:
    if not scope.rules:
        return ""
    lines: list[str] = []
    for r in scope.rules:
        prefix = "!" if r.negated else ""
        lines.append(f"{prefix}{r.glob}  # {r.reason}")
    return "\n".join(lines) + "\n"


def load(state_dir: str | Path = patchignore.STATE_DIR) -> Scope:
    p = Path(state_dir) / LLMSCOPE_NAME
    if not p.is_file():
        return Scope()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        return Scope(error=f"read failed: {e}")
    try:
        return Scope(parse(text))
    except ScopeParseError as e:
        return Scope(error=str(e))


def save(scope: Scope, state_dir: str | Path = patchignore.STATE_DIR) -> None:
    p = Path(state_dir) / LLMSCOPE_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(serialize(scope), encoding="utf-8")
