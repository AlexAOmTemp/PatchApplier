""".patchignore — gitignore-like hiding rules for the toolkit.

Format (a simplification of `.gitignore`, tuned for our case):

  * One glob pattern per line. `#` starts a comment; blank lines are
    ignored. Leading/trailing `/` is stripped (patterns are not anchored).
  * `*` matches any run of characters, `?` one character, `[seq]` one
    character from the set (fnmatch semantics). Patterns match a single
    path segment — `*` does not cross `/`.
  * `!pattern` is a negation: a segment that matches it is NOT hidden.
  * Order matters — the last matching pattern wins.
  * A path is hidden if any of its directory segments is hidden.

Hidden paths are excluded from scan-time walks (tree / list_files /
survey_dir / grep / index rebuild). Address access is NOT blocked:
`read_file(".git/config")` works. Writes to hidden paths will require
`force=true` (handled by the write tools, not here).

Where: `<project_dir>/.patchignore`. Each project has its own. If the
file is missing when the backend opens, it is created with the default
text below. `Reset to default` in the GUI restores exactly that text.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path


PATCHIGNORE_NAME = ".patchignore"


@dataclass(frozen=True)
class Rule:
    """One hiding rule.

    `enabled=False` (written as `@pattern` in the file) means the rule is
    preserved but not consulted — a way to keep a rule around without
    deleting it. `negated` (written as `!pattern`) un-hides a segment.
    The prefix order in the file is `@` then `!`: `@!foo` is a disabled
    negation.
    """
    glob: str
    negated: bool = False
    enabled: bool = True

# Service directory: toolkit state (indices, .version, MCP runtime).
# Hardcoded, not governed by .patchignore:
#   * the user cannot accidentally hide it (the toolkit would break);
#   * the tree never shows it except with the "show hidden" toggle;
#   * the filesystem backend grants access unconditionally so index and
#     MCP tools can reach their own files.
STATE_DIR = ".patch_applier"


def is_state_path(rel_str: str) -> bool:
    """True if `rel_str` is STATE_DIR or lives under it."""
    s = rel_str.replace("\\", "/").strip("/")
    return s == STATE_DIR or s.startswith(STATE_DIR + "/")


DEFAULT_PATCHIGNORE = """\
.*
!.patchignore
!.mcpignore
__pycache__
node_modules
venv
"""


def parse(text: str) -> list[Rule]:
    """Return [Rule, ...] in file order. Malformed lines skipped.

    Line syntax: `# comment`, `pattern`, `!pattern` (negation),
    `@pattern` (disabled), `@!pattern` (disabled negation).
    """
    out: list[Rule] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        enabled = True
        if line.startswith("@"):
            enabled = False
            line = line[1:].strip()
            if not line:
                continue
        negated = False
        if line.startswith("!"):
            negated = True
            line = line[1:].strip()
            if not line:
                continue
        # Slashes are not anchors in our segment model: strip them.
        line = line.strip("/")
        if not line:
            continue
        out.append(Rule(line, negated, enabled))
    return out


def serialize(rules: list[Rule]) -> str:
    """Render rules back to file text (with @ / ! prefixes)."""
    lines: list[str] = []
    for r in rules:
        prefix = "" if r.enabled else "@"
        if r.negated:
            prefix += "!"
        lines.append(prefix + r.glob)
    return "\n".join(lines) + ("\n" if lines else "")


def read(project_dir: Path) -> list[Rule]:
    """Read `.patchignore` from project_dir. Missing file -> empty list."""
    p = Path(project_dir) / PATCHIGNORE_NAME
    if not p.is_file():
        return []
    try:
        return parse(p.read_text(encoding="utf-8"))
    except OSError:
        return []


def ensure_default(project_dir: Path) -> None:
    """Create `.patchignore` with the default text if it does not exist."""
    p = Path(project_dir) / PATCHIGNORE_NAME
    if p.exists():
        return
    try:
        p.write_text(DEFAULT_PATCHIGNORE, encoding="utf-8")
    except OSError:
        pass


def segment_hidden(seg: str, patterns: list[Rule]) -> bool:
    """True if `seg` matches an enabled hiding pattern (last match wins)."""
    hidden = False
    for r in patterns:
        if not r.enabled:
            continue
        if fnmatch.fnmatchcase(seg, r.glob):
            hidden = not r.negated
    return hidden


def path_hidden(rel_str: str, patterns: list[Rule]) -> bool:
    """True if any directory segment of `rel_str` is hidden.

    Patterns match a single path segment only (no `/` in the pattern
    itself). `*` does not cross `/`, so `.*` matches `.git` but not
    `.git/config`; this is what makes `!pattern` exceptions work — the
    exception names the segment, not the whole path under it.

    The last matching pattern wins (`!` negates), so the file's order is
    significant: put broad patterns first, narrow exceptions after.
    """
    if not rel_str or not patterns:
        return False
    parts = [s for s in rel_str.replace("\\", "/").split("/") if s and s != "."]
    for seg in parts:
        if segment_hidden(seg, patterns):
            return True
    return False


def is_hidden(rel_str: str, patterns: list[Rule]) -> bool:
    """True if `rel_str` matches an enabled hiding pattern.

    Name used by backends and scan tools. Alias of `path_hidden` for
    callers that think in terms of visibility rather than path shape;
    the semantics are identical (any segment matches, last rule wins).
    """
    return path_hidden(rel_str, patterns)
