"""Sidecar metadata for stale-detection in documents.

Stored next to the rendered index (`<index_dir>/.index_meta.json`). Each
file's sections are keyed by their heading text. Records carry:
  body_hash, body_changed_at, summary_hash, summary_changed_at.

A section is `stale` when it has a summary and the summary was last changed
before the body. `set_summary` clears it naturally: the new text produces a
new `summary_hash`, and the next rebuild bumps `summary_changed_at` above
`body_changed_at`.

Only `build_index` writes this file. Write tools do not touch it.
"""
from __future__ import annotations

import json

from ..core.backend import Backend


def load_meta(backend: Backend, path: str) -> dict:
    try:
        if not backend.exists(path):
            return {}
        data = json.loads(backend.read(path))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_meta(backend: Backend, path: str, meta: dict) -> None:
    try:
        backend.write(path, json.dumps(meta, ensure_ascii=False, indent=2))
    except Exception:
        pass


def update_file_meta(
    old_file_meta: dict,
    sections: list[dict],
    now_ts: float,
    mtime_ts: float,
) -> tuple[dict, list[str]]:
    """Recompute per-section metadata; return (new_file_meta, stale_keys).

    `sections` is a list of dicts with keys: heading, summary, body_hash,
    summary_hash. Sections missing from `old_file_meta` start with both
    timestamps at `mtime_ts` (not stale on first sight).
    """
    new_file_meta: dict = {}
    stale_keys: list[str] = []
    for s in sections:
        key = s["heading"]
        old = old_file_meta.get(key)
        if old is None:
            body_at = summary_at = mtime_ts
        else:
            body_at = old.get("body_changed_at", mtime_ts)
            summary_at = old.get("summary_changed_at", mtime_ts)
            if old.get("body_hash") != s["body_hash"]:
                body_at = now_ts
            if old.get("summary_hash") != s["summary_hash"]:
                summary_at = now_ts
        new_file_meta[key] = {
            "body_hash": s["body_hash"],
            "body_changed_at": body_at,
            "summary_hash": s["summary_hash"],
            "summary_changed_at": summary_at,
        }
        if s.get("summary") is not None and summary_at < body_at:
            stale_keys.append(key)
    return new_file_meta, stale_keys


def resolve_path(index_path: str, meta_filename: str = ".index_meta.json") -> str:
    """Sibling path for the meta sidecar given an index path.

    `Service/INDEX.md` -> `Service/.index_meta.json`.
    `INDEX.md` -> `.index_meta.json`.
    """
    if "/" in index_path:
        return index_path.rsplit("/", 1)[0] + "/" + meta_filename
    return meta_filename
