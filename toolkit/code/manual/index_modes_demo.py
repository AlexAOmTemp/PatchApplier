"""Demo: render the existing CODE_INDEX.md in tree / structure modes.

Read-only. Not a tool — a one-shot script to evaluate the two proposed
modes against the real index before touching renderer.py.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path


# toolkit/code/manual/ -> parents[3] = PatchApplier (project root)
INDEX = Path(__file__).resolve().parents[3] / ".patch_applier" / "CODE_INDEX.md"
STRIP_PREFIX = "PatchAppliers/PatchApplier/"
MODULE_RE = re.compile(
    r"^##\s+(.+?)\s{2,}\((\d+)\s+\u0441\u0442\u0440\.,\s+([\d.]+)\s+KB\)(.*)$"
)


def _load_modules():
    text = INDEX.read_text(encoding="utf-8")
    modules = []
    for line in text.splitlines():
        m = MODULE_RE.match(line)
        if m:
            modules.append({
                "path": m.group(1),
                "lines": int(m.group(2)),
                "kb": float(m.group(3)),
                "markers": m.group(4).strip(),
            })
    return text, modules


def _strip(p: str) -> str:
    return p[len(STRIP_PREFIX):] if p.startswith(STRIP_PREFIX) else p


def render_structure(modules):
    out = []
    for m in sorted(modules, key=lambda x: x["path"]):
        p = _strip(m["path"])
        ms = ("  " + m["markers"]) if m["markers"] else ""
        out.append(
            f"{p:<62} {m['lines']:>5} \u0441\u0442\u0440.  {m['kb']:>6.1f} KB{ms}"
        )
    return out


def render_tree(modules, depth=3):
    dirs = defaultdict(
        lambda: {"files": 0, "lines": 0, "kb": 0.0, "large": 0, "main": 0}
    )
    for m in modules:
        p = _strip(m["path"])
        parts = p.split("/")
        for i in range(1, len(parts)):
            d = "/".join(parts[:i])
            dirs[d]["files"] += 1
            dirs[d]["lines"] += m["lines"]
            dirs[d]["kb"] += m["kb"]
            if "\u26a0 large" in m["markers"]:
                dirs[d]["large"] += 1
            if "\u25c9" in m["markers"]:
                dirs[d]["main"] += 1
    out = []
    for d in sorted(dirs.keys()):
        lvl = d.count("/")
        if lvl > depth:
            continue
        indent = "  " * lvl
        name = d.split("/")[-1]
        info = dirs[d]
        extra = ""
        if info["main"]:
            extra += f"  \u25c9{info['main']}"
        if info["large"]:
            extra += f"  \u26a0{info['large']}"
        out.append(
            f"{indent}{name}/  {info['files']:>4} files  "
            f"{info['kb']:>7.1f} KB  {info['lines']:>6} \u0441\u0442\u0440.{extra}"
        )
    return out


def main():
    text, modules = _load_modules()
    print(f"Parsed {len(modules)} modules from {INDEX}")
    print(f"Source index: {len(text)} bytes, {len(text.splitlines())} lines")
    print()

    struct_lines = render_structure(modules)
    print("=== STRUCTURE ===")
    print(f"({len(struct_lines)} lines, "
          f"{sum(len(l) for l in struct_lines)} chars)")
    print()
    for line in struct_lines:
        print(line)
    print()

    tree_lines = render_tree(modules, depth=3)
    print("=== TREE (depth=3) ===")
    print(f"({len(tree_lines)} lines, "
          f"{sum(len(l) for l in tree_lines)} chars)")
    print()
    for line in tree_lines:
        print(line)


if __name__ == "__main__":
    main()
