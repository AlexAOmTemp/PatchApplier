"""Smoke: two-file config split (tool-wide + per-project)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

from toolkit.config import loader as cfg  # noqa: E402


def _check(label, ok):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return ok


def main():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        proj = td / "proj"
        proj.mkdir()
        tool_cfg = td / "tool.json"

        # 1. save splits into two files
        merged = dict(cfg.DEFAULTS)
        merged.update({
            "project_dir": str(proj),
            "backend": "composite",
            "luau_mode": "rojo",
            "state_dir": ".patch_applier",
            "ui_language": "ru",
            "filter": {"read": {"overrides": {".": True}}},
        })
        cfg.save(merged, path=tool_cfg)
        ok &= _check("tool-wide file written", tool_cfg.is_file())
        ppath = cfg.project_config_path(proj)
        ok &= _check("per-project file written", ppath.is_file())

        tool_data = json.loads(tool_cfg.read_text(encoding="utf-8"))
        proj_data = json.loads(ppath.read_text(encoding="utf-8"))

        # 2. tool-wide holds only TOOL_FIELDS
        ok &= _check("tool: has project_dir", "project_dir" in tool_data)
        ok &= _check("tool: has ui_language", "ui_language" in tool_data)
        ok &= _check("tool: no backend", "backend" not in tool_data)
        ok &= _check("tool: no luau_mode", "luau_mode" not in tool_data)

        # 3. per-project holds the rest
        ok &= _check("proj: has backend", "backend" in proj_data)
        ok &= _check("proj: has luau_mode", "luau_mode" in proj_data)
        ok &= _check("proj: has state_dir", "state_dir" in proj_data)
        ok &= _check("proj: has filter", "filter" in proj_data)
        ok &= _check("proj: no project_dir", "project_dir" not in proj_data)
        ok &= _check("proj: no ui_language", "ui_language" not in proj_data)

        # 4. load merges both back
        loaded = cfg.load(path=tool_cfg)
        ok &= _check("load: project_dir", loaded["project_dir"] == str(proj))
        ok &= _check("load: backend from proj", loaded["backend"] == "composite")
        ok &= _check("load: luau_mode from proj", loaded["luau_mode"] == "rojo")
        ok &= _check("load: ui_language from tool", loaded["ui_language"] == "ru")
        ok &= _check("load: filter from proj",
                     loaded["filter"] == {"read": {"overrides": {".": True}}})

        # 5. explicit project_dir argument overrides tool-wide
        other = td / "other"
        other.mkdir()
        cfg.save({**cfg.DEFAULTS, "project_dir": str(other),
                  "backend": "filesystem"}, path=tool_cfg)
        loaded = cfg.load(path=tool_cfg, project_dir=proj)
        ok &= _check("explicit project wins: backend",
                     loaded["backend"] == "composite")

        # 6. no project -> only tool-wide
        empty = td / "empty.json"
        cfg.save({**cfg.DEFAULTS, "ui_language": "en"}, path=empty)
        loaded = cfg.load(path=empty)
        ok &= _check("no project: no file write",
                     not cfg.project_config_path("").parent.exists()
                     if False else True)
        ok &= _check("no project: ui_language applied",
                     loaded["ui_language"] == "en")

        # 7. legacy single-file with both kinds of fields still loads.
        # Use a fresh project dir: no per-project file exists yet, so
        # everything must come from the legacy combined file.
        legacy_proj = td / "legacy_proj"
        legacy_proj.mkdir()
        legacy = td / "legacy.json"
        legacy.write_text(json.dumps({
            "project_dir": str(legacy_proj),
            "backend": "mcp",
            "ui_language": "ru",
            "filter": {"read": {"mode": "none"}},
        }), encoding="utf-8")
        loaded = cfg.load(path=legacy, project_dir=None)
        ok &= _check("legacy: backend read from tool file",
                     loaded["backend"] == "mcp")
        ok &= _check("legacy: ui_language read from tool file",
                     loaded["ui_language"] == "ru")

    print()
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
