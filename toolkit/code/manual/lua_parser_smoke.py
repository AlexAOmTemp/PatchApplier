"""Quick smoke: run toolkit/lua/lua_symbols.lua inline on live Studio.

Instead of wrapping the parser in an IIFE, we splice it inline as a flat
script (matching how code_index_regen.lua was structured). Two textual
substitutions turn the module into flat code:
    - `function M.parse(src)` -> `local function parse(src)`
    - trailing `return M`     -> removed
Then we append a top-level `return JSONEncode(...)`.

Usage (from MCPBridge dir):
    python toolkit/manual_lua_parser_smoke.py --yes
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


DEFAULT_BRIDGE = PROJECT_ROOT / "bridge.py"
DEFAULT_MCP_COMMAND = "cmd.exe"
DEFAULT_MCP_ARGS = r"/c cd /d %LOCALAPPDATA%\Roblox && .\mcp.bat"

LUA_PARSER = HERE / "lua" / "lua_symbols.lua"

SAMPLE_LUA = "\n".join([
    "-- Sample Lua module",
    "local M = {}",
    "",
    "function M.hello(name)",
    "    return \"hello \" .. name",
    "end",
    "",
    "function M:method(x)",
    "    return self.value + x",
    "end",
    "",
    "local function helper(a, b)",
    "    return a + b",
    "end",
    "",
    "M.assigned = function(y)",
    "    return y * 2",
    "end",
    "",
    "local anon = function(z)",
    "    return z",
    "end",
    "",
    "return M",
    "",
])


def _flatten_parser(src):
    """Turn a module file (ends with `return M`) into flat inline code."""
    text = src
    # Replace public entry: `function M.parse(src)` -> `local function parse(src)`
    text = text.replace("function M.parse(src)", "local function parse(src)")
    # Strip trailing `return M` (with or without trailing whitespace)
    stripped = text.rstrip()
    if stripped.endswith("return M"):
        text = stripped[:-len("return M")].rstrip()
    return text


def _build_payload():
    if not LUA_PARSER.is_file():
        raise FileNotFoundError(f"parser not found: {LUA_PARSER}")
    parser_src = LUA_PARSER.read_text(encoding="utf-8")
    flat = _flatten_parser(parser_src)
    sample_lua_literal = json.dumps(SAMPLE_LUA)
    payload = (
        "-- === lua_symbols.lua (flattened) ===\n"
        + flat + "\n\n"
        + "-- === smoke driver ===\n"
        + "local __sample = " + sample_lua_literal + "\n"
        + "local __syms = parse(__sample)\n"
        + "return game:GetService('HttpService'):JSONEncode(__syms)\n"
    )
    (HERE / "_debug_payload.lua").write_text(payload, encoding="utf-8")
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bridge", default=str(DEFAULT_BRIDGE))
    ap.add_argument("--mcp-command", default=DEFAULT_MCP_COMMAND)
    ap.add_argument("--mcp-args", default=DEFAULT_MCP_ARGS)
    ap.add_argument("--working-dir", default=str(PROJECT_ROOT))
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    backend = MCPBackend(
        bridge_script=str(DEFAULT_BRIDGE),
        command=f"{sys.executable} -u",
        mcp_command=args.mcp_command,
        mcp_args=args.mcp_args,
        working_dir=args.working_dir,
        preflight=True,
        auto_switch=True,
        ready_timeout=120.0,
        call_timeout=180.0,
        studio_timeout=60.0,
    )

    try:
        backend.open()
        print(f"[ok] bridge alive: {backend.is_alive()}")
        print()

        # Inline test: flatten parser + drive with sample, return JSON.
        print("Inline test: flattened lua_symbols.lua + sample")
        payload = _build_payload()
        print(f"  payload size: {len(payload)} chars")
        try:
            r = backend.execute(payload)
            print(f"  raw result: {r[:500]!r}")
            if len(r) > 500:
                print(f"  ... ({len(r) - 500} more)")
            print()
            try:
                syms = json.loads(r)
            except Exception as e:
                print(f"[FAIL] result not JSON: {e}")
                return 1
            print(f"  parsed {len(syms)} symbols:")
            for s in syms:
                print(f"    {s.get('qualname')}  [{s.get('kind')}]  "
                      f"L{s.get('line_start')}-L{s.get('line_end')}  "
                      f"sig={s.get('signature')!r}")
            expected = {"M.hello", "M:method", "helper", "M.assigned", "anon"}
            found = {s.get("qualname") for s in syms}
            if found == expected:
                print()
                print(f"[OK] all 5 expected symbols found (inline works)")
                return 0
            print()
            print(f"[FAIL] expected {expected}, got {found}")
            return 1
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
            print("  -> inspect toolkit/_debug_payload.lua")
            return 1
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
