"""Best-effort action counters for the Patcher.

Each Patcher.apply bumps per-action counters in `metrics.json` under the
toolkit runtime state dir (see config.loader). Purpose: after a few
weeks, decide whether the unit-model tools win the "honest competition"
against text tools -- see DECISIONS §2.1.

Counters, not a log. The file size is bounded by the set of
`project x action x status x error_code` combos actually seen, and it
never grows linearly with time. `since` / `updated` mark the window.

Shape:
    {
      "since":   1728000000.123,
      "updated": 1728100000.456,
      "projects": {
        "PatchApplier": {
          "replace_unit": {"ok": 40, "error": 12, "blocked": 0}
        },
        "AiTest": {...},
        "unknown": {...}
      },
      "errors": {
        "PatchApplier": {
          "replace_unit": {"empty_input_use_delete_block": 3}
        }
      }
    }

Project key comes from `set_context(project_name)` called once at
session start (GUI run(), CLI main()). Without it counters land under
"unknown". The split matters: refactoring the toolkit and modding a
Roblox game are different task profiles; a single aggregate hides the
difference.

Legacy files (flat `{counts, errors}` from the pre-project era) are
discarded on first bump: the file is rewritten in the new shape, old
counters lost. No migration -- the format change is intentional.

Reset: delete the file.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


_METRICS_PATH: Path | None = None
_RESOLVED = False
_PROJECT: str = "unknown"


def set_context(project_name: str | None) -> None:
    """Set the active project for subsequent bumps. Call once at session
    start. Empty / None falls back to "unknown".

    Best-effort: no validation, no error. Project is a namespace, not a
    key that can fail.
    """
    global _PROJECT
    name = (project_name or "").strip()
    _PROJECT = name if name else "unknown"


def _path() -> Path | None:
    global _METRICS_PATH, _RESOLVED
    if _RESOLVED:
        return _METRICS_PATH
    _RESOLVED = True
    try:
        from ..config.loader import toolkit_runtime_state_dir
        _METRICS_PATH = toolkit_runtime_state_dir() / "metrics.json"
    except Exception:
        _METRICS_PATH = None
    return _METRICS_PATH


def _load(p: Path) -> dict:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    # New-shape only. Legacy flat files (no "projects" key) are ignored
    # -- they get overwritten on the next save.
    if "projects" not in data:
        return {}
    return data


def _save(p: Path, data: dict) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, p)


def bump(action: str, status: str, error_code: str | None) -> None:
    """Increment one counter under the current project. Never raises."""
    p = _path()
    if p is None:
        return
    try:
        data = _load(p)
        now = time.time()
        data.setdefault("since", now)
        data["updated"] = now
        a = action or "?"
        s = status or "?"
        proj = _PROJECT
        projects = data.setdefault("projects", {})
        bucket = projects.setdefault(proj, {}).setdefault(a, {})
        bucket[s] = bucket.get(s, 0) + 1
        if error_code:
            errs = data.setdefault("errors", {})
            e = errs.setdefault(proj, {}).setdefault(a, {})
            e[error_code] = e.get(error_code, 0) + 1
        p.parent.mkdir(parents=True, exist_ok=True)
        _save(p, data)
    except Exception:
        pass
