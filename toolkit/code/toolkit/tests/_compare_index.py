"""Ad-hoc compare: real index vs a reconstruction.

Whitespace-tolerant (strips trailing spaces, normalizes line endings,
drops trailing blank lines). Prints unified diff.

Usage:
    python toolkit/tests/_compare_index.py INDEX.md _memory_index.md
"""
from __future__ import annotations

import difflib
import sys
from pathlib import Path


def _norm(text: str) -> list[str]:
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in s.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def compare(a_path: str, b_path: str) -> int:
    a = _norm(Path(a_path).read_text(encoding="utf-8"))
    b = _norm(Path(b_path).read_text(encoding="utf-8"))
    diff = list(difflib.unified_diff(
        a, b, fromfile=a_path, tofile=b_path, lineterm=""
    ))
    if not diff:
        print(f"MATCH  ({len(a)} lines)")
        return 0
    print(f"DIFF  real={len(a)} lines, memory={len(b)} lines, "
          f"diff-lines={len(diff)}")
    for ln in diff[:400]:
        print(ln)
    if len(diff) > 400:
        print(f"... and {len(diff) - 400} more")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: _compare_index.py <real> <memory>")
        sys.exit(2)
    sys.exit(compare(sys.argv[1], sys.argv[2]))
