"""Benchmark full and incremental rebuild of the code index (PY + CS).

Usage:
  python bench_rebuild.py [--kind py|cs|both] [--cold-only] [--warm-only]

Cold: prev_manifest=None — every module is parsed.
Warm: prev_manifest=<current manifest> — only changed files are parsed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

ROOT = HERE.parents[2]  # PatchApplier/
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.indexers.code import build_code_index
from toolkit.indexers.csharp import build_csharp_index


MANIFESTS = {
    "py": "CODE_INDEX.manifest.json",
    "cs": "CODE_INDEX_CS.manifest.json",
}

BUILDERS = {
    "py": build_code_index,
    "cs": build_csharp_index,
}


def load_manifest(kind: str) -> list[dict] | None:
    p = STATE / MANIFESTS[kind]
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [warn] cannot read {p}: {e}")
        return None


def run(kind: str, wb: MultiRootFsBackend, prev: list[dict] | None) -> float:
    builder = BUILDERS[kind]
    t0 = time.perf_counter()
    r = builder(wb, prev_manifest=prev)
    dt = time.perf_counter() - t0
    return dt, r.modules_count, r.symbols_count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["py", "cs", "both"], default="both")
    ap.add_argument("--cold-only", action="store_true")
    ap.add_argument("--warm-only", action="store_true")
    args = ap.parse_args()

    kinds = ["py", "cs"] if args.kind == "both" else [args.kind]

    ws = load_workspace({"project_dir": str(ROOT), "state_dir": ".patch_applier"})
    if ws is None:
        print("[FAIL] no workspace")
        return 1
    print(f"workspace: {ws.name}  roots={ws.root_names()}")
    wb = MultiRootFsBackend(ws, STATE)
    wb.open()

    try:
        for kind in kinds:
            prev = load_manifest(kind)
            print()
            print(f"=== {kind.upper()} ===  manifest: {'yes' if prev else 'no'}")

            if not args.warm_only:
                t, m, s = run(kind, wb, None)
                print(f"  cold: {t:>7.3f}s  modules={m:<5d} symbols={s}")

            if not args.cold_only and prev is not None:
                t, m, s = run(kind, wb, prev)
                print(f"  warm: {t:>7.3f}s  modules={m:<5d} symbols={s}")

    finally:
        wb.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
