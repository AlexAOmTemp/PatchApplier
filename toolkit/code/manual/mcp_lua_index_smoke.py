"""Build Lua code index against live Roblox Studio.

Reads DataModel modules via MCPBackend, renders CODE_INDEX_LUA.md and
CODE_INDEX_LUA.manifest.json into MCPBridge/toolkit/, then exercises
find_symbol over the resulting manifest.

Read-only against Roblox -- index files land on local disk only.

Usage (from MCPBridge dir):
    python toolkit/manual_mcp_lua_index_smoke.py --yes
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import MCPBackend
from toolkit.core import Policy, Session
from toolkit.formats import Format
from toolkit.tools import TOOL_MAP


DEFAULT_BRIDGE = PROJECT_ROOT / "bridge.py"
DEFAULT_MCP_COMMAND = "cmd.exe"
DEFAULT_MCP_ARGS = r"/c cd /d %LOCALAPPDATA%\Roblox && .\mcp.bat"

# Write artifacts to project root (MCPBridge/), NOT into toolkit/.
# toolkit/ is under whitelist, so a markdown file there would be picked up
# by rebuild_index and pollute INDEX.md.
INDEX_DIR = PROJECT_ROOT
INDEX_NAME = "CODE_INDEX_LUA.md"
MANIFEST_NAME = "CODE_INDEX_LUA.manifest.json"


PASS = "[OK]  "
FAIL = "[FAIL]"


def _step(msg: str) -> None:
    print()
    print("=" * 60)
    print(msg)
    print("=" * 60)


def _expect(cond: bool, label: str, detail: str = "") -> bool:
    mark = PASS if cond else FAIL
    print(f"{mark} {label}" + (f" -- {detail}" if detail and not cond else ""))
    return cond


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bridge", default=str(DEFAULT_BRIDGE))
    ap.add_argument("--mcp-command", default=DEFAULT_MCP_COMMAND)
    ap.add_argument("--mcp-args", default=DEFAULT_MCP_ARGS)
    ap.add_argument("--working-dir", default=str(PROJECT_ROOT))
    ap.add_argument("--ready-timeout", type=float, default=120.0)
    ap.add_argument("--call-timeout", type=float, default=180.0)
    ap.add_argument("--studio-timeout", type=float, default=60.0)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    bridge = Path(args.bridge)
    if not bridge.is_file():
        print(f"[error] bridge not found: {bridge}")
        return 2

    if not args.yes:
        print("This will:")
        print("  - read all Lua modules under default Roblox roots")
        print(f"  - write {INDEX_NAME} and {MANIFEST_NAME} into {INDEX_DIR}")
        print("  - run find_symbol queries over the fresh manifest")
        print()
        ans = input("Proceed? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted.")
            return 0

    backend = MCPBackend(
        bridge_script=str(bridge),
        command=f"{sys.executable} -u",
        mcp_command=args.mcp_command,
        mcp_args=args.mcp_args,
        working_dir=args.working_dir,
        preflight=True,
        auto_switch=True,
        ready_timeout=args.ready_timeout,
        call_timeout=args.call_timeout,
        studio_timeout=args.studio_timeout,
    )

    failures = 0
    try:
        _step("Opening bridge...")
        backend.open()
        print(f"[ok] bridge alive: {backend.is_alive()}")

        _step("Building Lua code index")
        import time
        t0 = time.time()
        fmt = Format.load("default")
        # NOTE: Session here is used for its Patcher wiring only. We must NOT
        # use `with Session(...)` because that would close the backend on
        # exit -- and we still need it for read_symbol_lua below.
        session = Session(backend, fmt=fmt, tools=TOOL_MAP, policy=Policy())
        r = session.apply_patches([{
            "action": "rebuild_lua_code_index",
            "arguments": {
                "output": INDEX_NAME,
                "local_root": str(INDEX_DIR),
            },
        }])[0]
        elapsed = time.time() - t0
        print(f"  status: {r.status}")
        print(f"  elapsed: {elapsed:.1f}s")
        print(f"  bridge alive after build: {backend.is_alive()}")
        print(f"  message: {r.message[:300]}")
        if not _expect("index build ok", r.status == "ok", r.message[:200]):
            failures += 1
            raise RuntimeError("index build failed")

        out_path = INDEX_DIR / INDEX_NAME
        manifest_path = INDEX_DIR / MANIFEST_NAME
        if not _expect("index file exists", out_path.is_file()):
            failures += 1
        if not _expect("manifest file exists", manifest_path.is_file()):
            failures += 1

        _step("Index stats")
        idx_text = out_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        total_symbols = sum(len(m.get("symbols", [])) for m in manifest)
        print(f"  index length: {len(idx_text)} chars")
        print(f"  modules: {len(manifest)}")
        print(f"  symbols: {total_symbols}")
        print(f"  first 5 modules:")
        for m in manifest[:5]:
            print(f"    {m['path']}  ({len(m.get('symbols', []))} syms)")
        if not _expect("at least 10 modules", len(manifest) >= 10,
                       str(len(manifest))):
            failures += 1
        if not _expect("at least 50 symbols", total_symbols >= 50,
                       str(total_symbols)):
            failures += 1

        _step("find_symbol via manifest")
        # Direct in-process call to the tool to inspect its result.
        from toolkit.tools.find_symbol import FindSymbolTool
        fs_tool = FindSymbolTool()
        for query in ("calculatePeakPower", "ItemFormula", "CraftService"):
            r2 = fs_tool.execute(
                backend=backend, fmt=None,
                query=query,
                manifest_path=str(manifest_path),
                limit=5,
                local=True,
            )
            print(f"  query={query!r}  status={r2.status}")
            for line in r2.message.splitlines()[:6]:
                print(f"    {line}")
            if not _expect(f"query {query!r} ok", r2.status == "ok"):
                failures += 1

        _step("read_symbol_lua via index")
        # Bridge may have dropped after the long bulk-read sequence; reopen
        # if needed before the next MCP call.
        if not backend.is_alive():
            print("  [info] bridge died; reopening...")
            backend.ensure_alive()
        print(f"  bridge alive before read: {backend.is_alive()}")
        # Pick the first symbol from any module and try to read it back by
        # full DataModel path + qualname.
        target = None
        for m in manifest:
            if m.get("symbols"):
                target = (m["path"], m["symbols"][0]["qualname"])
                break
        if target:
            path, qn = target
            print(f"  target: {path} :: {qn}")
            from toolkit.tools.lua_code import ReadSymbolLuaTool
            rd = ReadSymbolLuaTool()
            r3 = rd.execute(
                backend=backend, fmt=None,
                file_path=path, qualname=qn,
            )
            print(f"  status: {r3.status}")
            print(f"  message preview: {r3.message[:200]}")
            if not _expect("read_symbol_lua ok", r3.status == "ok"):
                failures += 1
        else:
            print("  [warn] no symbols in manifest to read")

        _step("Sanity: Config_* modules have no functions?")
        # Config modules are usually data-only tables -- verify the parser
        # isn't silently dropping symbols. Read one via list_symbols_lua.
        cfg_path = "ReplicatedStorage.Config.Config_Classes"
        try:
            from toolkit.tools.lua_code import ListSymbolsLuaTool
            ls = ListSymbolsLuaTool()
            r4 = ls.execute(backend=backend, fmt=None, file_path=cfg_path)
            first_lines = r4.message.splitlines()[:6]
            print(f"  {cfg_path}: {r4.status}")
            for line in first_lines:
                print(f"    {line}")
        except Exception as e:
            print(f"  [warn] could not probe {cfg_path}: {type(e).__name__}: {e}")

    except Exception as e:
        _step(f"FATAL: {type(e).__name__}")
        print(e)
        traceback.print_exc()
        failures += 1
    finally:
        _step("Closing bridge...")
        try:
            backend.close()
        except Exception:
            pass
        print(f"[ok] closed, alive={backend.is_alive()}")

    print()
    if failures:
        print(f"=== DONE: {failures} failure(s) ===")
        return 1
    print("=== DONE: all green ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
