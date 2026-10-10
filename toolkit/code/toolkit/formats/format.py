"""Format — dataclass with compiled rules; parse(text) -> ParsedDoc."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .model import ParsedDoc
from .presets import load_preset


@dataclass
class Format:
    heading_prefix: str
    min_level: int
    max_level: int
    numbering_pattern: re.Pattern[str]
    trailing_dot: bool
    ann_open: str | None
    ann_close: str | None
    case_sensitive: bool
    ann_summary: str | None
    ann_tags: str | None
    ann_large_ok: str | None
    ann_flat: str | None

    # --- construction ------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "Format":
        h = data.get("heading") or {}
        n = data.get("numbering") or {}
        a = data.get("annotations") or {}

        def _kw(d):
            if not isinstance(d, dict):
                return None
            k = d.get("keyword")
            return k if isinstance(k, str) and k else None

        num_pat = n.get("pattern") or r"^\d+(?:\.\d+)*\.?"

        return cls(
            heading_prefix=h.get("prefix", "#"),
            min_level=int(h.get("min_level", 2)),
            max_level=int(h.get("max_level", 8)),
            numbering_pattern=re.compile(num_pat),
            trailing_dot=bool(n.get("trailing_dot", True)),
            ann_open=a.get("open"),
            ann_close=a.get("close"),
            case_sensitive=bool(a.get("case_sensitive", False)),
            ann_summary=_kw(a.get("summary")),
            ann_tags=_kw(a.get("tags")),
            ann_large_ok=_kw(a.get("large_ok")),
            ann_flat=_kw(a.get("flat")),
        )

    @classmethod
    def load(cls, preset: str = "default", overrides: dict | None = None) -> "Format":
        data = load_preset(preset)
        if overrides:
            data = _deep_merge(data, overrides)
        return cls.from_dict(data)

    # --- parsing -----------------------------------------------------------

    def parse(self, text: str) -> ParsedDoc:
        from .parser import parse as _parse
        return _parse(text, self)


# --- helpers --------------------------------------------------------------


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
