""".mcpignore — segment-based hiding for the MCP (Roblox) code index.

Same syntax as `.patchignore`, but matched against every dot-separated
segment of a Roblox DataModel path:

  ReplicatedStorage.Packages._Index.roblox_testez@0.4.1.testez
  -> segments: ReplicatedStorage, Packages, _Index,
               roblox_testez@0.4.1, testez

A module is skipped from the Lua index when any of its segments matches
a hiding pattern. `!pattern` un-hides; the last matching pattern wins.

Consulted only when `luau: mcp` (Roblox source mode). For `luau: rojo`
the filesystem rules in `.patchignore` apply instead — `.mcpignore`
is not created or read in that mode.

Where: `<project_dir>/.mcpignore`. Created with the default text below
when it is missing. "Reset to default" in the GUI restores exactly
that text.
"""
from __future__ import annotations

from pathlib import Path

from .patchignore import parse, segment_hidden


MCPIGNORE_NAME = ".mcpignore"


DEFAULT_MCPIGNORE = """\
# .mcpignore — like .patchignore, but for Roblox DataModel paths.
#
# Each line is a glob (*, ?, [seq]) matched against every dot-separated
# segment of a module path. A module is skipped from the Lua index when
# any of its segments matches a pattern. Prefix with ! to un-hide; the
# last matching pattern wins.
#
# Consulted only when `luau: mcp`. For `luau: rojo` the filesystem
# rules in `.patchignore` apply instead.
#
# To fully open the index, delete every non-comment line, or use
# "Reset to default" in the toolkit settings dialog.

# Wally / package-manager conventions.
_Index
Packages
# Versioned package segments: roblox_testez@0.4.1, lm-loleris_profilestore@1.0.3.
*@*
"""


def read(project_dir: Path) -> list[tuple[str, bool]]:
    """Read `.mcpignore` from project_dir. Missing file -> empty list."""
    p = Path(project_dir) / MCPIGNORE_NAME
    if not p.is_file():
        return []
    try:
        return parse(p.read_text(encoding="utf-8"))
    except OSError:
        return []


def ensure_default(project_dir: Path) -> None:
    """Create `.mcpignore` with the default text if it does not exist."""
    p = Path(project_dir) / MCPIGNORE_NAME
    if p.exists():
        return
    try:
        p.write_text(DEFAULT_MCPIGNORE, encoding="utf-8")
    except OSError:
        pass


def path_hidden(dotted_path: str, patterns: list[tuple[str, bool]]) -> bool:
    """True if any dot-separated segment of `dotted_path` matches a
    hiding pattern (last match wins, per segment)."""
    if not dotted_path or not patterns:
        return False
    for seg in dotted_path.split("."):
        if seg and segment_hidden(seg, patterns):
            return True
    return False
