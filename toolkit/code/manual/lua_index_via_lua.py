"""Run code_index_regen.lua on live Studio, in chunked (cursor) mode.

Python-side concatenates:
    __cursor = N        -- cursor for this call
    flattened lua_symbols.lua
    code_index_regen.lua
and sends as one execute_luau per chunk. Loops until done=true.

Usage (from MCPBridge dir):
    python toolkit/manual_lua_index_via_lua.py --yes
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import MCPBackend


DEFAULT_BRIDGE = PROJECT_ROOT / "bridge.py"
DEFAULT_MCP_COMMAND = "cmd.exe"
DEFAULT_MCP_ARGS = r"/c cd /d %LOCALAPPDATA%\Roblox && .\mcp.bat"

LUA_PARSER = HERE / "lua" / "lua_symbols.lua"
LUA_DRIVER = HERE / "lua" / "code_index_regen.lua"

MAX_CHUNKS = 40  # safety net against infinite loop


def _flatten_parser(src: str) -> str:
    text = src.replace("function M.parse(src)", "local function parse(src)")
    stripped = text.rstrip()
    if stripped.endswith("return M"):
        text = stripped[:-len("return M")].rstrip()
    return text


def _payload_for_cursor(cursor: int) -> str:
    parser_flat = _flatten_parser(LUA_PARSER.read_text(encoding="utf-8"))
    driver = LUA_DRIVER.read_text(encoding="utf-8")
    return (
        f"__cursor = {cursor}\n"
        "-- === begin lua_symbols.lua (flattened) ===\n"
        + parser_flat + "\n"
        + "-- === end lua_symbols.lua ===\n"
        + "-- === begin code_index_regen.lua ===\n"
        + driver + "\n"
        + "-- === end code_index_regen.lua ===\n"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bridge", default=str(DEFAULT_BRIDGE))
    ap.add_argument("--mcp-command", default=DEFAULT_MCP_COMMAND)
    ap.add_argument("--mcp-args", default=DEFAULT_MCP_ARGS)
    ap.add_argument("--working-dir", default=str(PROJECT_ROOT))
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    if not LUA_PARSER.is_file() or not LUA_DRIVER.is_file():
        print(f"[error] missing parser or driver")
        return 2

    backend = MCPBackend(
        bridge_script=str(DEFAULT_BRIDGE),
        command=f"{sys.executable} -u",
        mcp_command=args.mcp_command,
        mcp_args=args.mcp_args,
        working_dir=args.working_dir,
        preflight=True,
        auto_switch=True,
        ready_timeout=120.0,
        call_timeout=240.0,
        studio_timeout=60.0,
    )

    try:
        backend.open()
        print(f"[ok] bridge alive: {backend.is_alive()}")
        print()

        all_items = []
        cursor = 0
        chunk_no = 0
        total_reported = None
        t0 = time.time()
        while chunk_no < MAX_CHUNKS:
            chunk_no += 1
            payload = _payload_for_cursor(cursor)
            print(f"Chunk {chunk_no}: cursor={cursor}, "
                  f"payload={len(payload)} chars")

            t_chunk = time.time()
            try:
                raw = backend.execute(payload)
            except Exception as e:
                print(f"  [FAIL] {type(e).__name__}: {e}")
                return 1
            chunk_elapsed = time.time() - t_chunk

            print(f"  response: {len(raw)} chars in {chunk_elapsed:.2f}s")
            try:
                data = json.loads(raw)
            except Exception as e:
                print(f"  [FAIL] not JSON: {e}")
                print(f"  preview: {raw[:200]}")
                return 1

            if not isinstance(data, dict):
                print(f"  [FAIL] expected dict, got {type(data).__name__}")
                return 1
            items = data.get("items", [])
            next_cursor = int(data.get("next_cursor", 0))
            done = bool(data.get("done", False))
            total = int(data.get("total", 0))
            total_reported = total

            print(f"  got {len(items)} items, next_cursor={next_cursor}, "
                  f"done={done}, total={total}")
            all_items.extend(items)

            if done:
                break
            if next_cursor <= cursor:
                print("  [FAIL] cursor did not advance, aborting")
                return 1
            cursor = next_cursor

        total_elapsed = time.time() - t0
        print()

        n_modules = len(all_items)
        n_symbols = sum(len(m.get("symbols", [])) for m in all_items)
        print(f"DONE: {chunk_no} chunks, "
              f"{n_modules} modules, {n_symbols} symbols, "
              f"{total_elapsed:.2f}s total")
        if total_reported is not None and total_reported != n_modules:
            print(f"[WARN] total reported by driver ({total_reported}) "
                  f"!= received ({n_modules})")

        # Save for diff.
        out_path = HERE / "_debug_lua_manifest.json"
        out_path.write_text(
            json.dumps(all_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"saved: {out_path.name}")

        # Quick sanity for known paths.
        by_path = {m.get("path"): m for m in all_items}
        for target in ("ReplicatedStorage.Shared.Domain.ItemFormula",
                       "ServerScriptService.Services.CraftService"):
            m = by_path.get(target)
            if m:
                print(f"{target}: hash={m.get('hash')} len={m.get('len')} "
                      f"symbols={len(m.get('symbols', []))}")

        return 0
    except Exception as e:
        print(f"[FATAL] {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1
    finally:
        try:
            backend.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
