"""Tests for Lua-index reverse dependencies (Used by)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.indexers.lua_runner import build_lua_index


PASS = "[OK]  "
FAIL = "[FAIL]"


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def expect(self, label, cond, detail=""):
        if cond:
            print(f"{PASS} {label}")
            self.passed += 1
        else:
            print(f"{FAIL} {label}" + (f" -- {detail}" if detail else ""))
            self.failed += 1


class FakeMCPBackend:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def execute(self, code, datamodel_type="Edit"):
        return json.dumps(self._chunks.pop(0))


ITEM_MATH = {
    "path": "ReplicatedStorage.Shared.MathUtils",
    "hash": 111, "len": 200, "lines": 15,
    "imports": [],
    "symbols": [
        {"qualname": "M.round", "kind": "function",
         "line_start": 4, "line_end": 6},
    ],
}

ITEM_FORMULA = {
    "path": "ReplicatedStorage.Shared.ItemFormula",
    "hash": 222, "len": 300, "lines": 12,
    "imports": ["game.ReplicatedStorage.Shared.MathUtils"],
    "symbols": [
        {"qualname": "M.calc", "kind": "function",
         "line_start": 4, "line_end": 7},
    ],
}

ITEM_CRAFT = {
    "path": "ServerScriptService.Services.CraftService",
    "hash": 333, "len": 100, "lines": 8,
    "imports": ["game.ReplicatedStorage.Shared.MathUtils",
                "game.ReplicatedStorage.Shared.ItemFormula",
                "game.ServerStorage.NotInIndex"],
    "symbols": [
        {"qualname": "M.startCraft", "kind": "function",
         "line_start": 4, "line_end": 6},
    ],
}

ITEM_SELF = {
    "path": "ReplicatedStorage.Loop",
    "hash": 444, "len": 50, "lines": 5,
    "imports": ["game.ReplicatedStorage.Loop"],
    "symbols": [],
}

ITEM_NO_PREFIX = {
    "path": "ReplicatedStorage.Bare",
    "hash": 555, "len": 50, "lines": 5,
    "imports": ["ReplicatedStorage.Shared.MathUtils"],
    "symbols": [],
}


def _one_chunk(items):
    return [{"items": items, "next_cursor": len(items),
             "done": True, "total": len(items)}]


def main():
    t = T()

    items = [ITEM_MATH, ITEM_FORMULA, ITEM_CRAFT, ITEM_SELF, ITEM_NO_PREFIX]
    be = FakeMCPBackend(_one_chunk(items))

    result = build_lua_index(be)
    manifest = json.loads(result.manifest_json)
    by_path = {m["path"]: m for m in manifest}

    math_used = by_path["ReplicatedStorage.Shared.MathUtils"]["used_by"]
    t.expect("MathUtils used by ItemFormula",
             "ReplicatedStorage.Shared.ItemFormula" in math_used, math_used)
    t.expect("MathUtils used by CraftService",
             "ServerScriptService.Services.CraftService" in math_used, math_used)
    t.expect("MathUtils used by Bare (no game. prefix)",
             "ReplicatedStorage.Bare" in math_used, math_used)
    t.expect("MathUtils used_by sorted", math_used == sorted(math_used), math_used)

    formula_used = by_path["ReplicatedStorage.Shared.ItemFormula"]["used_by"]
    t.expect("ItemFormula used by CraftService",
             "ServerScriptService.Services.CraftService" in formula_used,
             formula_used)

    t.expect("NotInIndex creates no edge",
             by_path["ReplicatedStorage.Shared.MathUtils"]["used_by"]
             and "ServerStorage.NotInIndex" not in math_used)

    t.expect("Loop not in own used_by",
             "ReplicatedStorage.Loop" not in by_path["ReplicatedStorage.Loop"]["used_by"])

    t.expect("no duplicate importer entries",
             math_used.count("ReplicatedStorage.Bare") == 1, math_used)

    text = result.text
    t.expect("rendered 'Used by:' present", "Used by:" in text, text[:600])

    # Module without importers should not have Used by line
    lines = text.splitlines()
    bare_idx = next((i for i, l in enumerate(lines)
                     if l.startswith("## ReplicatedStorage.Bare")), -1)
    t.expect("Bare block found", bare_idx >= 0)
    if bare_idx >= 0:
        block = lines[bare_idx:bare_idx + 5]
        has_used = any(l.startswith("Used by:") for l in block)
        t.expect("Bare block has no Used by line", not has_used, block)

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
