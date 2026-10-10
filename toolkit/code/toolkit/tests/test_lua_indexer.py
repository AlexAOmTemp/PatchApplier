"""Tests for indexers.lua_runner — Lua-side bulk indexing.

Python sends one execute_luau per chunk; the fake backend returns
pre-baked chunks in the shape produced by lua/code_index_regen.lua.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import FilesystemBackend
from toolkit.core import Policy, Session
from toolkit.formats import Format
from toolkit.indexers.lua_runner import build_lua_index
from toolkit.tools import TOOL_MAP


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
    """Backend with `execute` returning pre-baked driver chunks.

    Also provides the minimal Backend surface that Session and the
    rebuild_lua_code_index tool need for local file writes.
    """

    def __init__(self, chunks, working_dir: Path):
        self._chunks = list(chunks)
        self.working_dir = working_dir
        self._alive = False
        self.execute_calls: list[str] = []

    def open(self):
        self._alive = True

    def close(self):
        self._alive = False

    def is_alive(self):
        return self._alive

    def execute(self, code, datamodel_type="Edit"):
        self.execute_calls.append(code)
        if not self._chunks:
            return json.dumps({"items": [], "next_cursor": 0,
                               "done": True, "total": 0})
        return json.dumps(self._chunks.pop(0))

    def exists(self, path):
        return (self.working_dir / path).exists()

    def read(self, path):
        p = self.working_dir / path
        if not p.is_file():
            raise FileNotFoundError(path)
        return p.read_text(encoding="utf-8")

    def write(self, path, content):
        p = self.working_dir / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def list(self, root="", glob="*"):
        return []

    def stat(self, path):
        raise NotImplementedError

    def delete(self, path):
        pass

    def move(self, src, dst):
        raise NotImplementedError

    def filter_check(self, path, spec):
        return None


ITEM_MATH = {
    "path": "ReplicatedStorage.Shared.MathUtils",
    "hash": 111, "len": 200, "lines": 15,
    "imports": [],
    "symbols": [
        {"qualname": "M.round", "kind": "function",
         "line_start": 4, "line_end": 6},
        {"qualname": "M.floor", "kind": "function",
         "line_start": 8, "line_end": 10},
        {"qualname": "helper", "kind": "local_function",
         "line_start": 12, "line_end": 14},
    ],
}

ITEM_FORMULA = {
    "path": "ReplicatedStorage.Shared.ItemFormula",
    "hash": 222, "len": 300, "lines": 12,
    "imports": ["game.ReplicatedStorage.Shared.MathUtils"],
    "symbols": [
        {"qualname": "M.calculatePeakPower", "kind": "function",
         "line_start": 4, "line_end": 7},
    ],
}

ITEM_CRAFT = {
    "path": "ServerScriptService.Services.CraftService",
    "hash": 333, "len": 100, "lines": 8,
    "imports": [],
    "symbols": [
        {"qualname": "M.startCraft", "kind": "function",
         "line_start": 4, "line_end": 6},
    ],
}


def _one_chunk(items):
    return [{"items": items, "next_cursor": len(items),
             "done": True, "total": len(items)}]


def _two_chunks(items):
    half = len(items) // 2
    return [
        {"items": items[:half], "next_cursor": half,
         "done": False, "total": len(items)},
        {"items": items[half:], "next_cursor": len(items),
         "done": True, "total": len(items)},
    ]


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        print("== build_lua_index: single chunk ==")
        be = FakeMCPBackend(
            _one_chunk([ITEM_MATH, ITEM_FORMULA, ITEM_CRAFT]), root)
        be.open()
        r = build_lua_index(be)
        t.expect("3 modules", r.modules_count == 3, str(r.modules_count))
        t.expect("5 symbols", r.symbols_count == 5, str(r.symbols_count))
        t.expect("one execute call", len(be.execute_calls) == 1,
                 str(len(be.execute_calls)))
        t.expect("preamble", "# Code Index" in r.text)
        t.expect("module header",
                 "## ReplicatedStorage.Shared.MathUtils" in r.text)
        t.expect("symbol listed", "M.calculatePeakPower" in r.text)
        t.expect("kind shown", "[local_function]" in r.text)

        print()
        print("== manifest shape ==")
        manifest = json.loads(r.manifest_json)
        t.expect("list", isinstance(manifest, list))
        t.expect("3 entries", len(manifest) == 3)
        by = {m["path"]: m for m in manifest}
        mif = by.get("ReplicatedStorage.Shared.ItemFormula")
        t.expect("ItemFormula present", mif is not None)
        if mif:
            t.expect("hash present", isinstance(mif["hash"], int))
            qns = [s["qualname"] for s in mif["symbols"]]
            t.expect("calculatePeakPower in symbols",
                     "M.calculatePeakPower" in qns, qns)
            t.expect("symbol name augmented",
                     mif["symbols"][0]["name"] == "calculatePeakPower")
            t.expect("imports captured", bool(mif["imports"]))

        print()
        print("== build_lua_index: chunked ==")
        be2 = FakeMCPBackend(
            _two_chunks([ITEM_MATH, ITEM_FORMULA, ITEM_CRAFT]), root)
        be2.open()
        r2 = build_lua_index(be2)
        t.expect("2 execute calls", len(be2.execute_calls) == 2,
                 str(len(be2.execute_calls)))
        t.expect("3 modules", r2.modules_count == 3)

        print()
        print("== tool: rebuild_lua_code_index requires_mcp ==")
        fs_root = root / "fs"
        fs_root.mkdir()
        fmt = Format.load("default")
        with Session(FilesystemBackend(fs_root), fmt=fmt,
                     tools=TOOL_MAP, policy=Policy()) as s:
            res = s.apply_patches([
                {"action": "rebuild_lua_code_index", "arguments": {}}
            ])[0]
        t.expect("error", res.status == "error")
        t.expect("error_code == requires_mcp",
                 res.error_code == "requires_mcp", res.error_code)

        print()
        print("== tool: rebuild_lua_code_index ok ==")
        be3 = FakeMCPBackend(_one_chunk([ITEM_MATH, ITEM_FORMULA]), root)
        with Session(be3, fmt=fmt, tools=TOOL_MAP, policy=Policy()) as s:
            res = s.apply_patches([
                {"action": "rebuild_lua_code_index",
                 "arguments": {"output": "IDX.md"}}
            ])[0]
        t.expect("ok", res.status == "ok", f"{res.status}: {res.message}")
        t.expect("mentions module count", "модулей: 2" in res.message,
                 res.message[:200])
        t.expect("index written", (root / "IDX.md").is_file())
        t.expect("manifest written", (root / "IDX.manifest.json").is_file())
        t.expect("message has [v1]", "[v1]" in res.message, res.message[:200])
        t.expect("version file written",
                 (root / "IDX.md.version").is_file())

        # Second rebuild -> [v2]
        be3._chunks = _one_chunk([ITEM_MATH])
        with Session(be3, fmt=fmt, tools=TOOL_MAP, policy=Policy()) as s:
            res2 = s.apply_patches([
                {"action": "rebuild_lua_code_index",
                 "arguments": {"output": "IDX.md"}}
            ])[0]
        t.expect("second rebuild ok", res2.status == "ok",
                 f"{res2.status}: {res2.message}")
        t.expect("message has [v2]", "[v2]" in res2.message,
                 res2.message[:200])

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
