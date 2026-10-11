"""Dump raw metrics.json from toolkit runtime state."""
from __future__ import annotations
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
state = HERE.parents[1] / "runtime" / "state" / "metrics.json"
print(f"path: {state}")
print(f"exists: {state.exists()}")
if state.exists():
    data = json.loads(state.read_text(encoding="utf-8"))
    print(json.dumps(data, ensure_ascii=False, indent=2))
