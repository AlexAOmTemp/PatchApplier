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

Hidden paths are refused by the filesystem backend before the policy is
consulted, and not shown in the policy tree (unless "show hidden" is on).

Where: `<project_dir>/.patchignore`. Each project has its own. If the
file is missing when the backend opens, it is created with the default
text below. `Reset to default` in the GUI restores exactly that text.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path


PATCHIGNORE_NAME = ".patchignore"

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
# .patchignore — like .gitignore, but for the toolkit.
#
# Each line is a glob (*, ?, [seq]) matched against every directory
# segment of a path. A path is hidden if any of its segments matches
# a pattern. Prefix with ! to un-hide; the last matching pattern wins.
#
# Hidden paths are refused by the toolkit (read / write / index), and
# not shown in the policy tree unless "show hidden" is on.
#
# To fully open a project, delete every non-comment line, or use
# "Reset to default" / "Open all" in the toolkit settings dialog.

# Dot-directories: .git, .venv, .pytest_cache, ...
.*
# ...except this file itself, so it stays readable in the tree.
# (`.patch_applier` is hardcoded as service and needs no entry here.)
!.patchignore
!.mcpignore

# Non-dot build noise.
__pycache__
node_modules
venv
"""


def parse(text: str) -> list[tuple[str, bool]]:
    """Return [(glob, negated), ...] in file order. Malformed lines skipped."""
    out: list[tuple[str, bool]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
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
        out.append((line, negated))
    return out


def read(project_dir: Path) -> list[tuple[str, bool]]:
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


def segment_hidden(seg: str, patterns: list[tuple[str, bool]]) -> bool:
    """True if `seg` matches a hiding pattern (last match wins)."""
    hidden = False
    for glob, negated in patterns:
        if fnmatch.fnmatchcase(seg, glob):
            hidden = not negated
    return hidden


def path_hidden(rel_str: str, patterns: list[tuple[str, bool]]) -> bool:
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
