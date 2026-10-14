"""Survey a directory tree — counts by extension, per-subdir breakdown.

Prototype for a future `survey_dir` tool. Read-only, no state.

Usage:
    python toolkit/code/manual/survey_dir.py <root> [--top N]

Companion to the reconnaissance workflow discussed for external
projects (RimWorld / Factorio). Used to look at an unfamiliar tree
before deciding roots and .patchignore.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path


def human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    x = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        x /= 1024
        if x < 1024 or unit == "TB":
            return f"{x:.1f} {unit}"
    return f"{x:.1f} PB"


def survey(root: Path, top: int = 20) -> None:
    if not root.is_dir():
        print(f"not a directory: {root}")
        return

    ext_count: Counter[str] = Counter()
    ext_size: Counter[int] = Counter()
    total_files = 0
    total_size = 0
    first: dict[str, dict] = {}

    for p in root.rglob("*"):
        try:
            if not p.is_file():
                continue
            sz = p.stat().st_size
        except OSError:
            continue
        total_files += 1
        total_size += sz
        e = p.suffix.lower() or "(no ext)"
        ext_count[e] += 1
        ext_size[e] += sz

        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) >= 2:
            top_name = parts[0]
            info = first.setdefault(
                top_name, {"files": 0, "size": 0, "ext": Counter()})
            info["files"] += 1
            info["size"] += sz
            info["ext"][e] += 1

    print(f"root: {root}")
    print(f"files: {total_files}, total: {human(total_size)}")
    print()

    print(f"by extension (top {top}):")
    for e, c in ext_count.most_common(top):
        print(f"  {e:14s}  {c:8d}  {human(ext_size[e])}")
    print()

    print(f"first-level dirs ({len(first)} total, top {top} by file count):")
    for name, info in sorted(first.items(), key=lambda x: -x[1]["files"])[:top]:
        top_ext = "  ".join(
            f"{e}:{c}" for e, c in info["ext"].most_common(3))
        print(f"  {name:44s}  {info['files']:8d}  {human(info['size'])}   [{top_ext}]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="directory to survey")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()
    survey(Path(args.root), args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
