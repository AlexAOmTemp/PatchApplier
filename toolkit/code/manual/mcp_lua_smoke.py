"""End-to-end smoke of Lua symbol tools against real Roblox code.

Reads ItemFormula from ReplicatedStorage, parses its symbols, reads one
function via read_symbol_lua, then clones the module to ServerStorage,
applies replace_function_lua on the copy, verifies, and cleans up.

Nothing in the actual project is mutated -- all writes go to a temporary
copy under ServerStorage.MCPBridgeTest.

Usage (from MCPBridge dir):
    python toolkit/manual_mcp_lua_smoke.py --yes

Requires Roblox Studio open with the target project.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import MCPBackend
from toolkit.formats.lua import parse_lua_symbols
from toolkit.tools.lua_code import (
    ListSymbolsLuaTool, ReadSymbolLuaTool, ReplaceFunctionLuaTool,
)


DEFAULT_BRIDGE = PROJECT_ROOT / "bridge.py"
DEFAULT_MCP_COMMAND = "cmd.exe"
DEFAULT_MCP_ARGS = r"/c cd /d %LOCALAPPDATA%\Roblox && .\mcp.bat"

SOURCE_MODULE = "ReplicatedStorage.Shared.Domain.ItemFormula"
TEST_FOLDER = "ServerStorage.MCPBridgeTest"
COPY_MODULE = "ServerStorage.MCPBridgeTest.ItemFormulaCopy"

MARKER = "-- SMOKE_TEST_MARKER_REPLACED"

SETUP_CODE = '''\
local ServerStorage = game:GetService('ServerStorage')
local folder = ServerStorage:FindFirstChild('MCPBridgeTest')
if not folder then
    folder = Instance.new('Folder')
    folder.Name = 'MCPBridgeTest'
    folder.Parent = ServerStorage
end
return 'setup-ok'
'''

CLONE_CODE = '''\
local ServerStorage = game:GetService('ServerStorage')
local folder = ServerStorage:FindFirstChild('MCPBridgeTest')
if not folder then return 'no-folder' end
local existing = folder:FindFirstChild('ItemFormulaCopy')
if existing then existing:Destroy() end
local src = game.ReplicatedStorage.Shared.Domain.ItemFormula
if not src then return 'no-source' end
local copy = src:Clone()
copy.Name = 'ItemFormulaCopy'
copy.Parent = folder
return 'clone-ok'
'''

TEARDOWN_CODE = '''\
local ServerStorage = game:GetService('ServerStorage')
local folder = ServerStorage:FindFirstChild('MCPBridgeTest')
if folder then folder:Destroy() end
return 'teardown-ok'
'''


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
        print(f"This smoke test will:")
        print(f"  - read {SOURCE_MODULE} (read-only)")
        print(f"  - parse its Lua symbols")
        print(f"  - clone it to {COPY_MODULE}")
        print(f"  - replace one function in the copy")
        print(f"  - delete the copy and {TEST_FOLDER}")
        print()
        print("Nothing in the original project is mutated.")
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
    setup_done = False
    try:
        _step("Opening bridge...")
        backend.open()
        print(f"[ok] bridge alive: {backend.is_alive()}")

        _step(f"Read source: {SOURCE_MODULE}")
        source = backend.read(SOURCE_MODULE)
        print(f"  source length: {len(source)} chars")
        if not _expect("source is non-empty", len(source) > 0):
            failures += 1

        _step("Parse Lua symbols")
        syms = parse_lua_symbols(source)
        print(f"  found {len(syms)} symbols")
        for s in syms[:15]:
            print(f"    {s.qualname}  [{s.kind}]  L{s.line_start}-L{s.line_end}")
        if len(syms) > 15:
            print(f"    ... and {len(syms) - 15} more")
        if not _expect("at least 3 symbols", len(syms) >= 3,
                       f"got {len(syms)}"):
            failures += 1
        if not _expect("every symbol has non-zero span",
                       all(s.line_end >= s.line_start for s in syms)):
            failures += 1

        if not syms:
            print()
            print("Aborting further steps: no symbols parsed.")
            raise RuntimeError("parser found no symbols")

        first = syms[0]
        _step(f"read_symbol_lua: {first.qualname}")
        rd_tool = ReadSymbolLuaTool()
        r = rd_tool.execute(
            backend=backend, fmt=None,
            file_path=SOURCE_MODULE, qualname=first.qualname,
        )
        print(f"  status: {r.status}")
        print(f"  message preview: {r.message[:200]}")
        if not _expect("read_symbol_lua ok", r.status == "ok"):
            failures += 1
        if r.status == "ok":
            body = r.message
            if not _expect("body contains function decl",
                           first.signature.split("(")[0] in body,
                           first.signature[:60]):
                failures += 1
            if not _expect("body smaller than full source",
                           len(body) < len(source)):
                failures += 1

        _step("Setup test folder")
        backend.execute(SETUP_CODE)
        setup_done = True

        _step(f"Clone source to {COPY_MODULE}")
        cl = backend.execute(CLONE_CODE)
        print(f"  clone result: {cl!r}")
        if not _expect("clone returned 'clone-ok'", cl == "clone-ok", cl):
            failures += 1
        if not _expect("copy exists", backend.exists(COPY_MODULE)):
            failures += 1
            raise RuntimeError("clone failed")

        _step("read copy")
        copy_src = backend.read(COPY_MODULE)
        if not _expect("copy content matches source", copy_src == source,
                       f"copy {len(copy_src)} vs source {len(source)}"):
            failures += 1

        _step(f"replace_function_lua on copy: {first.qualname}")
        new_body = (
            f"{first.signature}\n"
            f"    {MARKER}\n"
            f"    return nil\n"
            f"end"
        )
        rep_tool = ReplaceFunctionLuaTool()
        r2 = rep_tool.execute(
            backend=backend, fmt=None,
            file_path=COPY_MODULE, qualname=first.qualname,
            new_code=new_body,
        )
        print(f"  status: {r2.status}")
        print(f"  message: {r2.message[:200]}")
        if not _expect("replace_function_lua ok", r2.status == "ok",
                       r2.message[:200]):
            failures += 1
        if not _expect("delta present", r2.delta is not None):
            failures += 1

        _step("verify copy after replace")
        copy_after = backend.read(COPY_MODULE)
        if not _expect("marker present in copy",
                       MARKER in copy_after):
            failures += 1
        if not _expect("copy changed size",
                       len(copy_after) != len(copy_src)):
            failures += 1
        # Check that other symbols survived
        syms_after = parse_lua_symbols(copy_after)
        survivor_count = len([s for s in syms_after if s.qualname != first.qualname])
        other_count = len([s for s in syms if s.qualname != first.qualname])
        if not _expect(f"other {other_count} symbols survived",
                       survivor_count == other_count,
                       f"before={other_count}, after={survivor_count}"):
            failures += 1

        _step("Confirm original module untouched")
        orig_after = backend.read(SOURCE_MODULE)
        if not _expect("original source unchanged", orig_after == source,
                       f"orig {len(orig_after)} vs snapshot {len(source)}"):
            failures += 1

    except Exception as e:
        _step(f"FATAL: {type(e).__name__}")
        print(e)
        traceback.print_exc()
        failures += 1
    finally:
        if setup_done:
            _step("Teardown")
            try:
                backend.execute(TEARDOWN_CODE)
                print("  [ok] test folder destroyed")
            except Exception as e:
                print(f"  [warn] teardown failed: {type(e).__name__}: {e}")
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
