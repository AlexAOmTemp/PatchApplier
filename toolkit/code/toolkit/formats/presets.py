"""Preset loader — reads formats/presets/*.json."""
from __future__ import annotations

import json
from pathlib import Path


PRESETS_DIR = Path(__file__).resolve().parent / "presets_data"


def list_presets() -> list[str]:
    if not PRESETS_DIR.exists():
        return []
    return sorted(p.stem for p in PRESETS_DIR.glob("*.json"))


def load_preset(name: str) -> dict:
    path = PRESETS_DIR / f"{name}.json"
    if not path.exists():
        available = ", ".join(list_presets()) or "(none)"
        raise FileNotFoundError(f"Preset '{name}' not found. Available: {available}")
    return json.loads(path.read_text(encoding="utf-8"))
