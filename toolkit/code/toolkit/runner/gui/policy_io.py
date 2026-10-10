"""Policy load/save helpers for the settings dialog.

load_policy reads a config dict into {role: {path: bool}}, transparently
converting legacy `filter_mode` / `filter_dirs` and dropping overrides for
directories that no longer exist on disk.

save_policy_into writes back into the *given* config dict rather than the
module-global CONFIG, so callers stay explicit about what they mutate.
"""
from __future__ import annotations

from pathlib import Path


def load_policy(cfg: dict) -> dict:
    """Returns {role: {path: bool}}. Legacy mode/paths converted to overrides.

    Stale entries for directories that no longer exist on disk are dropped.
    If project_dir is empty or not a directory, filtering is skipped (the
    config is returned as-is).
    """
    proj = str(cfg.get("project_dir") or "").strip()
    proj_path = Path(proj) if proj and Path(proj).is_dir() else None

    def _drop_missing(ov: dict) -> dict:
        if proj_path is None:
            return ov
        out = {}
        for p, v in ov.items():
            if p == ".":
                out[p] = v
                continue
            try:
                if (proj_path / p).exists():
                    out[p] = v
            except OSError:
                pass
        return out

    def _legacy_to_overrides(mode, paths):
        if mode == "none" or not paths:
            return {}
        norm = [str(p).replace("\\", "/").strip("/") for p in paths if p]
        norm = [p for p in norm if p]
        if not norm:
            return {}
        if mode == "white":
            ov = {".": False}
            for p in norm:
                ov[p] = True
            return ov
        if mode == "black":
            ov = {}
            for p in norm:
                ov[p] = False
            return ov
        return {}

    out = {"read": {}, "write": {}, "index": {}}
    f = cfg.get("filter")
    if isinstance(f, dict) and f:
        for role in ("read", "write", "index"):
            spec = f.get(role) or {}
            if not isinstance(spec, dict):
                continue
            if "overrides" in spec:
                ov = spec.get("overrides") or {}
                cleaned = {str(k).replace("\\", "/").strip("/"): bool(v)
                           for k, v in ov.items()
                           if str(k).replace("\\", "/").strip("/")}
                out[role] = _drop_missing(cleaned)
            else:
                mode = spec.get("mode", "none")
                paths = list(spec.get("paths", []) or [])
                out[role] = _drop_missing(_legacy_to_overrides(mode, paths))
        return out
    fm = cfg.get("filter_mode", "none") or "none"
    fd = list(cfg.get("filter_dirs", []) or [])
    ov = _drop_missing(_legacy_to_overrides(fm, fd))
    for r in out:
        out[r] = dict(ov)
    return out


def save_policy_into(cfg: dict, policy: dict) -> None:
    """Write policy under cfg['filter'] in the overrides shape."""
    cfg["filter"] = {
        "read":  {"overrides": dict(policy.get("read", {}))},
        "write": {"overrides": dict(policy.get("write", {}))},
        "index": {"overrides": dict(policy.get("index", {}))},
    }
