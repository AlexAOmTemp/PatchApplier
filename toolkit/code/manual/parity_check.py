"""Compare Lua-side manifest with Python-side manifest.

Reads:
    toolkit/CODE_INDEX_LUA.manifest.json  -- built by Python path
                                              (rebuild_lua_code_index,
                                              backend-based, 7.5s)
    toolkit/_debug_lua_manifest.json      -- built by Lua path
                                              (manual_lua_index_via_lua.py,
                                              0.41s)

Checks per common module:
    - hash matches
    - len matches
    - symbol set matches on (qualname, kind, line_start, line_end)

Note: Python path only covers modules passing the index-policy filter; Lua
path covers all four root services. Sets of modules may differ -- we compare
only on the intersection.

Usage (from MCPBridge dir):
    python toolkit/manual_parity_check.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent

# Python-side manifest lives wherever rebuild_lua_code_index wrote it.
# By default that's the working_dir (MCPBridge/). Lua-side debug manifest
# is written by manual_lua_index_via_lua.py into the toolkit/ folder.
PY_CANDIDATES = [
    PROJECT_ROOT / "CODE_INDEX_LUA.manifest.json",
    HERE / "CODE_INDEX_LUA.manifest.json",
]
LUA_CANDIDATES = [
    HERE / "_debug_lua_manifest.json",
    PROJECT_ROOT / "_debug_lua_manifest.json",
]


def _pick(candidates, label):
    for p in candidates:
        if p.is_file():
            return p
    print(f"[error] cannot find {label} in any of:")
    for p in candidates:
        print(f"  {p}")
    return None

PY_MANIFEST = _pick(PY_CANDIDATES, "Python manifest")
LUA_MANIFEST = _pick(LUA_CANDIDATES, "Lua manifest")


def _symbol_key(s: dict) -> tuple:
    return (s.get("qualname"), s.get("kind"),
            s.get("line_start"), s.get("line_end"))


def main() -> int:
    if PY_MANIFEST is None:
        print("  run rebuild_lua_code_index first (Python-side manifest)")
        return 2
    if LUA_MANIFEST is None:
        print("  run manual_lua_index_via_lua.py first (Lua-side manifest)")
        return 2

    print(f"Python manifest: {PY_MANIFEST}")
    print(f"Lua manifest:    {LUA_MANIFEST}")
    print()

    py = json.loads(PY_MANIFEST.read_text(encoding="utf-8"))
    lua = json.loads(LUA_MANIFEST.read_text(encoding="utf-8"))

    print(f"Python manifest: {len(py)} modules")
    print(f"Lua manifest:    {len(lua)} modules")
    print()

    py_by = {m["path"]: m for m in py}
    lua_by = {m["path"]: m for m in lua}

    common = set(py_by) & set(lua_by)
    only_py = set(py_by) - set(lua_by)
    only_lua = set(lua_by) - set(py_by)

    print(f"Common:       {len(common)}")
    print(f"Only Python:  {len(only_py)}")
    print(f"Only Lua:     {len(only_lua)}")
    print()

    if only_py:
        print(f"Sample: only in Python manifest ({len(only_py)} total):")
        for p in sorted(only_py)[:10]:
            print(f"  {p}")
        if len(only_py) > 10:
            print(f"  ... and {len(only_py) - 10} more")
        print()
    if only_lua:
        print(f"Sample: only in Lua manifest ({len(only_lua)} total):")
        for p in sorted(only_lua)[:10]:
            print(f"  {p}")
        if len(only_lua) > 10:
            print(f"  ... and {len(only_lua) - 10} more")
        print()

    # Compare hash/len/symbols on common set.
    hash_mismatches = []
    sym_mismatches = []
    total_py_syms = 0
    total_lua_syms = 0
    common_syms_py = 0
    common_syms_lua = 0

    for path in sorted(common):
        p = py_by[path]
        l = lua_by[path]
        if p.get("hash") != l.get("hash") or p.get("len") != l.get("len"):
            hash_mismatches.append((path, p.get("hash"), l.get("hash"),
                                    p.get("len"), l.get("len")))
        py_syms = {_symbol_key(s) for s in p.get("symbols", [])}
        lua_syms = {_symbol_key(s) for s in l.get("symbols", [])}
        total_py_syms += len(py_syms)
        total_lua_syms += len(lua_syms)
        common_syms_py += len(py_syms)
        common_syms_lua += len(lua_syms)
        if py_syms != lua_syms:
            sym_mismatches.append((path, py_syms, lua_syms))

    print(f"Symbols on common set:")
    print(f"  Python: {common_syms_py}")
    print(f"  Lua:    {common_syms_lua}")
    print()

    if hash_mismatches:
        print(f"[FAIL] Hash/len mismatches: {len(hash_mismatches)}")
        for path, ph, lh, pl, ll in hash_mismatches[:10]:
            print(f"  {path}")
            print(f"    py  hash={ph} len={pl}")
            print(f"    lua hash={lh} len={ll}")
        print()
    else:
        print("[OK] Hash and len match on all common modules")
        print()

    if sym_mismatches:
        print(f"[FAIL] Symbol mismatches: {len(sym_mismatches)}")
        for path, ps, ls in sym_mismatches[:5]:
            print(f"  {path}:")
            only_in_py = sorted(ps - ls)
            only_in_lua = sorted(ls - ps)
            print(f"    only_py  ({len(only_in_py)}): {only_in_py[:5]}")
            print(f"    only_lua ({len(only_in_lua)}): {only_in_lua[:5]}")
        if len(sym_mismatches) > 5:
            print(f"  ... and {len(sym_mismatches) - 5} more")
        print()
    else:
        print("[OK] Symbol sets match on all common modules")

    print()
    if hash_mismatches or sym_mismatches:
        print(f"=== PARITY: {len(hash_mismatches)} hash, "
              f"{len(sym_mismatches)} symbol mismatches ===")
        return 1
    print("=== PARITY: OK ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
