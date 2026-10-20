"""LLM starter text: locate and read LLM_START.<lang>.md.

Pure filesystem helpers, no Tk, no globals. Callers in app.py pass the
language code and get back text + the language actually used (with the
`en` fallback). The docs directory is derived from `state.TOOLKIT_ROOT`.
"""
from __future__ import annotations

from pathlib import Path

from .state import TOOLKIT_ROOT


def docs_dir() -> Path:
    """<toolkit_root>/docs — where LLM_START.<lang>.md lives."""
    return TOOLKIT_ROOT / "docs"


def scan_langs() -> list[str]:
    """Return sorted list of language codes with an LLM_START.<lang>.md."""
    d = docs_dir()
    if not d.is_dir():
        return []
    langs = []
    for p in d.glob("LLM_START.*.md"):
        parts = p.name.split(".")  # LLM_START.ru.md -> ["LLM_START", "ru", "md"]
        if len(parts) == 3 and parts[0] == "LLM_START":
            langs.append(parts[1])
    return sorted(set(langs))


def read_text(lang: str) -> tuple[str | None, str | None]:
    """Return (text, used_lang) or (None, None). Falls back to 'en'."""
    d = docs_dir()
    candidates = [lang] if lang else []
    candidates += [c for c in scan_langs() if c not in candidates]
    for cand in candidates:
        if not cand:
            continue
        p = d / f"LLM_START.{cand}.md"
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8"), cand
            except Exception:
                continue
    return None, None
