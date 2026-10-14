"""Inventory RimWorld mods — one row per workshop folder.

Reads About/About.xml for the human name and packageId. Counts XML /
CS / DLL / PNG per mod so a human can pick which roots matter.

Read-only. Usage:
    python toolkit/code/manual/rimworld_inventory.py <Mods root>
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


# About.xml is small and well-formed. Use the stdlib parser and read
# only direct children of ModMetaData — a regex would catch the first
# <packageId> anywhere, which is usually inside <modDependencies>
# (a bug we hit on the very first run).


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return p.read_text(encoding="utf-8-sig")
        except Exception:
            return ""
    except OSError:
        return ""


def _find_about(mod_dir: Path) -> Path | None:
    for cand in (mod_dir / "About" / "About.xml",
                 mod_dir / "about" / "about.xml"):
        if cand.is_file():
            return cand
    return None


def _ext_counts(mod_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in mod_dir.rglob("*"):
        if not p.is_file():
            continue
        e = p.suffix.lower() or "(none)"
        counts[e] = counts.get(e, 0) + 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="Mods/ directory")
    ap.add_argument("--sort", choices=["name", "xml", "cs", "size"],
                    default="name")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"not a directory: {root}")
        return 1

    rows: list[dict] = []
    for mod_dir in sorted(root.iterdir()):
        if not mod_dir.is_dir():
            continue
        if not mod_dir.name.isdigit():
            continue
        about = _find_about(mod_dir)
        name = "(no About.xml)"
        pkg = ""
        deps: list[str] = []
        if about:
            try:
                root = ET.fromstring(_read_text(about))
            except ET.ParseError:
                root = None
            if root is not None:
                n = root.findtext("name")
                if n:
                    name = n.strip()
                p = root.findtext("packageId")
                if p:
                    pkg = p.strip()
                dep_block = root.find("modDependencies")
                if dep_block is not None:
                    for li in dep_block.findall("li"):
                        dp = li.findtext("packageId")
                        if dp:
                            deps.append(dp.strip())
        ext = _ext_counts(mod_dir)
        rows.append({
            "id": mod_dir.name,
            "name": name,
            "pkg": pkg,
            "deps": deps,
            "xml": ext.get(".xml", 0),
            "cs": ext.get(".cs", 0),
            "dll": ext.get(".dll", 0),
            "png": ext.get(".png", 0),
            "files": sum(ext.values()),
        })

    if args.sort == "name":
        rows.sort(key=lambda r: r["name"].lower())
    elif args.sort == "xml":
        rows.sort(key=lambda r: -r["xml"])
    elif args.sort == "cs":
        rows.sort(key=lambda r: -r["cs"])
    elif args.sort == "size":
        rows.sort(key=lambda r: -r["files"])

    print(f"mods: {len(rows)}")
    print()
    print(f"{'id':<12}  {'xml':>5}  {'cs':>4}  {'dll':>4}  {'png':>5}  "
          f"{'files':>6}  name (packageId)")
    print("-" * 120)
    for r in rows:
        pkg = f" ({r['pkg']})" if r['pkg'] else ""
        print(f"{r['id']:<12}  {r['xml']:>5}  {r['cs']:>4}  {r['dll']:>4}  "
              f"{r['png']:>5}  {r['files']:>6}  {r['name']}{pkg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
