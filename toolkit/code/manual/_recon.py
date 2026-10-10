"""Recon for state-dir relocation plan."""
from __future__ import annotations
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def show(label, p):
    print(f"=== {label} ===")
    print(f"path: {p}")
    print(f"exists: {p.exists()}")
    if p.is_file():
        print(f"size: {p.stat().st_size}")
        try:
            print("---")
            print(p.read_text(encoding="utf-8")[:1200])
        except Exception as e:
            print(f"read failed: {e}")
    elif p.is_dir():
        print("---")
        for c in sorted(p.iterdir()):
            kind = "D" if c.is_dir() else "F"
            try:
                size = c.stat().st_size if c.is_file() else 0
            except Exception:
                size = 0
            print(f"  [{kind}] {c.name}  ({size} B)")
    print()


show("toolkit/.patch_applier.json", ROOT / "toolkit" / ".patch_applier.json")
show("toolkit/.patch_applier/", ROOT / "toolkit" / ".patch_applier")
show("toolkit/runtime/", ROOT / "toolkit" / "runtime")
show("toolkit/.patchignore", ROOT / "toolkit" / ".patchignore")
show(".patchignore (root)", ROOT / ".patchignore")
show(".patch_applier/ (root)", ROOT / ".patch_applier")

# workspace.json location check
print("=== summary ===")
print(f"repo root: {ROOT}")
for cand in [
    ROOT / ".patch_applier" / "workspace.json",
    ROOT / "toolkit" / ".patch_applier" / "workspace.json",
]:
    print(f"  {cand}: {cand.exists()}")
