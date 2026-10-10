"""Best-effort action counters for the Patcher.

Each Patcher.apply bumps per-action counters in `metrics.json` under the
toolkit runtime state dir (see config.loader). Purpose: after a few
weeks, decide whether the unit-model tools win the "honest competition"
against text tools — see DECISIONS §2.1.

Counters, not a log. The file size is bounded by the set of
`action × status × error_code` combos actually seen, and it never grows
linearly with time. `since` / `updated` mark the window.

All writes are best-effort and atomic: a broken counter file must never
break a patch. On any error the call is a silent no-op.

Shape:
    {
      "since":   1728000000.123,     # first bump
      "updated": 1728100000.456,     # most recent bump
      "counts": {
        "replace_block": {"ok": 42, "error": 3, "blocked": 0, "skipped": 0},
        "read_unit":     {"ok": 118, "error": 5, "blocked": 0, "skipped": 0}
      },
      "errors": {
        "replace_block": {"block_out_of_range": 2, "not_applicable": 1}
      }
    }

Reset: delete the file (or use `manual/metrics_report.py --reset`).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


_METRICS_PATH: Path | None = None
_RESOLVED = False


def _path() -> Path | None:
    """Resolve the metrics path once. None when the runtime state dir is
    unavailable — the caller falls through silently."""
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
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def _save(p: Path, data: dict) -> None:
    """Atomic write: temp file + os.replace."""
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, p)


def bump(action: str, status: str, error_code: str | None) -> None:
    """Increment one counter. Never raises."""
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
        counts = data.setdefault("counts", {})
        bucket = counts.setdefault(a, {})
        bucket[s] = bucket.get(s, 0) + 1
        if error_code:
            errs = data.setdefault("errors", {})
            e = errs.setdefault(a, {})
            e[error_code] = e.get(error_code, 0) + 1
        p.parent.mkdir(parents=True, exist_ok=True)
        _save(p, data)
    except Exception:
        # Silent: metrics must never block a patch.
        pass
