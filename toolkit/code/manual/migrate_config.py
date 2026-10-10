"""One-shot: split legacy combined .patch_applier.json
into tool-wide + per-project files.

Usage:
    python manual/migrate_config.py <config_path>

Reads the legacy file, re-saves via loader.save(), which writes:
  <toolkit_root>/.patch_applier.json        (tool-wide only)
  <project_dir>/.patch_applier/config.json  (per-project only)
Idempotent: re-running on an already-split pair is a no-op.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

from toolkit.config import loader as cfg  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: migrate_config.py <config_path>", file=sys.stderr)
        return 2
    p = Path(argv[1]).resolve()
    if not p.is_file():
        print(f"[error] not a file: {p}", file=sys.stderr)
        return 2
    before = json.loads(p.read_text(encoding="utf-8"))
    print(f"before: {len(before)} keys in {p}")
    merged = cfg.load(path=p)
    proj = merged.get("project_dir") or ""
    if not proj:
        print("[error] project_dir is empty; cannot split", file=sys.stderr)
        return 1
    ppath = cfg.project_config_path(proj)
    ok = cfg.save(merged, path=p)
    if not ok:
        print("[error] save failed", file=sys.stderr)
        return 1
    tool_after = json.loads(p.read_text(encoding="utf-8"))
    proj_after = json.loads(ppath.read_text(encoding="utf-8"))
    print(f"after tool-wide: {len(tool_after)} keys -> {p}")
    print(f"after per-proj:  {len(proj_after)} keys -> {ppath}")
    print()
    print("tool-wide:", sorted(tool_after.keys()))
    print("per-proj: ", sorted(proj_after.keys()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
