"""Debug the Lua parser by loading it as a real ModuleScript in Studio.

Steps:
    1. Verify lua_symbols.lua is ASCII-only (catches hidden NBSP/curly quotes).
    2. Create ServerStorage.MCPBridgeTest.LuaSymbolsParser via multi_edit.
    3. require + parse a sample via execute_luau.
    4. Print result, cleanup.

If the file fails to parse, Studio reports the exact line number.
This bypasses every inline-code problem: real Studio parser, real errors.

Usage (from MCPBridge dir):
    python toolkit/manual_lua_parser_in_studio.py --yes
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

MODULE_PATH = "ServerStorage.MCPBridgeTest.LuaSymbolsParser"
PARENT_FOLDER = "ServerStorage.MCPBridgeTest"

SETUP_FOLDER = (
    "local ServerStorage = game:GetService('ServerStorage')\n"
    "local f = ServerStorage:FindFirstChild('MCPBridgeTest')\n"
    "if not f then f = Instance.new('Folder'); f.Name = 'MCPBridgeTest'; f.Parent = ServerStorage end\n"
    "local m = f:FindFirstChild('LuaSymbolsParser')\n"
    "if m then m:Destroy() end\n"
    "return 'setup-ok'"
)

CLEANUP = (
    "local ServerStorage = game:GetService('ServerStorage')\n"
    "local f = ServerStorage:FindFirstChild('MCPBridgeTest')\n"
    "if f then f:Destroy() end\n"
    "return 'cleanup-ok'"
)

SAMPLE_LUA = (
    "local M = {}\n"
    "function M.hello(name)\n"
    "    return \"hello \" .. name\n"
    "end\n"
    "return M\n"
)

RUN_TEST = (
    "local ok, P = pcall(function() return require(game.ServerStorage.MCPBridgeTest.LuaSymbolsParser) end)\n"
    "if not ok then return 'REQUIRE_FAIL: ' .. tostring(P) end\n"
    "local ok2, syms = pcall(function() return P.parse([==[\n"
    + SAMPLE_LUA
    + "\n]==]) end)\n"
    "if not ok2 then return 'PARSE_FAIL: ' .. tostring(syms) end\n"
    "return game:GetService('HttpService'):JSONEncode(syms)\n"
)


def _check_ascii(path):
    """Return list of (line, col, char_ord) for non-ASCII chars."""
    text = path.read_text(encoding="utf-8")
    issues = []
    for line_no, line in enumerate(text.split("\n"), start=1):
        for col, ch in enumerate(line, start=1):
            if ord(ch) > 127:
                issues.append((line_no, col, ord(ch), ch))
                if len(issues) >= 20:
                    return issues
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bridge", default=str(DEFAULT_BRIDGE))
    ap.add_argument("--mcp-command", default=DEFAULT_MCP_COMMAND)
    ap.add_argument("--mcp-args", default=DEFAULT_MCP_ARGS)
    ap.add_argument("--working-dir", default=str(PROJECT_ROOT))
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    if not LUA_PARSER.is_file():
        print(f"[error] parser not found: {LUA_PARSER}")
        return 2

    print(f"Parser file: {LUA_PARSER}")
    print(f"Size: {LUA_PARSER.stat().st_size} bytes")
    print()

    # Step 1: ASCII check.
    print("Step 1: ASCII purity check")
    issues = _check_ascii(LUA_PARSER)
    if issues:
        print(f"  [FAIL] {len(issues)} non-ASCII chars found:")
        for ln, col, code, ch in issues:
            print(f"    L{ln}:{col}  U+{code:04X}  {ch!r}")
        print("  --> fix these first, Studio refuses non-ASCII in some contexts")
        return 1
    print("  [ok] file is pure ASCII")
    print()

    parser_src = LUA_PARSER.read_text(encoding="utf-8")

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

        # Step 2: setup folder.
        print("Step 2: setup ServerStorage.MCPBridgeTest")
        r = backend.execute(SETUP_FOLDER)
        print(f"  -> {r!r}")
        print()

        # Step 3: create module via multi_edit.
        print("Step 3: create LuaSymbolsParser ModuleScript")
        try:
            edit_call = [{
                "tool": "multi_edit",
                "arguments": {
                    "file_path": MODULE_PATH,
                    "className": "ModuleScript",
                    "datamodel_type": "Edit",
                    "edits": [{"old_string": "", "new_string": parser_src}],
                },
            }]
            # Use _invoke_many to send the multi_edit call directly.
            entries = backend._invoke_many(edit_call)
            entry = entries[0] if entries else {}
            is_err = entry.get("is_error", False)
            texts = entry.get("result") or []
            preview = texts[0][:300] if texts else "(no result)"
            print(f"  is_error={is_err}")
            print(f"  result: {preview}")
            if is_err:
                print("  [FAIL] multi_edit rejected the module")
                print("  --> check Studio Output panel for the exact parse error")
                return 1
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
            return 1
        print()

        # Step 4: run test via require.
        print("Step 4: require + parse sample")
        try:
            r = backend.execute(RUN_TEST)
            print(f"  raw result: {r[:500]!r}")
            print()
            if r.startswith("REQUIRE_FAIL"):
                print("  [FAIL] require failed — check Studio Output for stacktrace")
                return 1
            if r.startswith("PARSE_FAIL"):
                print("  [FAIL] parse failed at runtime — check Studio Output")
                return 1
            try:
                syms = json.loads(r)
                print(f"  parsed {len(syms)} symbols:")
                for s in syms:
                    print(f"    {s.get('qualname')}  [{s.get('kind')}]  "
                          f"L{s.get('line_start')}-L{s.get('line_end')}")
                if len(syms) == 1 and syms[0].get("qualname") == "M.hello":
                    print()
                    print("[OK] parser works in Studio")
                    return 0
                print()
                print("[FAIL] unexpected symbols")
                return 1
            except Exception as e:
                print(f"  [FAIL] result not JSON: {e}")
                return 1
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
            return 1
        finally:
            print()
            print("Cleanup")
            try:
                r = backend.execute(CLEANUP)
                print(f"  -> {r!r}")
            except Exception as e:
                print(f"  cleanup error: {e}")
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
