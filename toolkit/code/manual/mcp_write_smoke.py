"""Manual end-to-end test of MCPBackend write/delete/move with real Studio.

Creates a test ModuleScript under ServerStorage.MCPBridgeTest, exercises the
full write pipeline (write / read / stat / move / delete), verifies each step,
then cleans up. Nothing else in Studio is touched.

Usage (from MCPBridge dir):
    python toolkit/manual_mcp_write_smoke.py

With --yes to skip the confirmation prompt.

Requires:
    - Roblox Studio open with the target project
    - Roblox MCP server installed (bridge.py spawns it)
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


DEFAULT_BRIDGE = PROJECT_ROOT / "bridge.py"
DEFAULT_MCP_COMMAND = "cmd.exe"
DEFAULT_MCP_ARGS = r"/c cd /d %LOCALAPPDATA%\Roblox && .\mcp.bat"

FOLDER_PATH = "ServerStorage.MCPBridgeTest"
MODULE_PATH = "ServerStorage.MCPBridgeTest.ProbeModule"
MODULE_RENAMED = "ServerStorage.MCPBridgeTest.ProbeModuleRenamed"

SETUP_CODE = '''\
local ServerStorage = game:GetService('ServerStorage')
local folder = ServerStorage:FindFirstChild('MCPBridgeTest')
if not folder then
    folder = Instance.new('Folder')
    folder.Name = 'MCPBridgeTest'
    folder.Parent = ServerStorage
end
local mod = folder:FindFirstChild('ProbeModule')
if not mod then
    mod = Instance.new('ModuleScript')
    mod.Name = 'ProbeModule'
    mod.Parent = folder
end
return 'setup-ok'
'''

TEARDOWN_CODE = '''\
local ServerStorage = game:GetService('ServerStorage')
local folder = ServerStorage:FindFirstChild('MCPBridgeTest')
if folder then folder:Destroy() end
return 'teardown-ok'
'''

CONTENT_V1 = '''\
-- MCPBridge write-smoke v1
local M = {}

function M.hello()
    return "v1"
end

return M
'''

CONTENT_V2 = '''\
-- MCPBridge write-smoke v2
local M = {}

function M.hello()
    return "v2 -- updated"
end

function M.extra()
    return 42
end

return M
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
    ap.add_argument("--yes", action="store_true",
                    help="Skip interactive confirmation")
    args = ap.parse_args()

    bridge = Path(args.bridge)
    if not bridge.is_file():
        print(f"[error] bridge not found: {bridge}")
        return 2

    if not args.yes:
        print("This smoke test will:")
        print(f"  - create folder {FOLDER_PATH}")
        print(f"  - create ModuleScript {MODULE_PATH}")
        print(f"  - overwrite its .Source twice, rename it, then delete it")
        print(f"  - destroy folder {FOLDER_PATH}")
        print()
        print("Nothing else in Studio is touched.")
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

        _step("Setup")
        r = backend.execute(SETUP_CODE)
        setup_done = True
        print(f"  setup result: {r!r}")
        if not _expect("setup returned 'setup-ok'", r == "setup-ok", r):
            failures += 1
        if not _expect("module exists", backend.exists(MODULE_PATH)):
            failures += 1

        _step("write v1")
        backend.write(MODULE_PATH, CONTENT_V1)
        got = backend.read(MODULE_PATH)
        if not _expect("read matches v1", got == CONTENT_V1,
                       f"len={len(got)}, expected {len(CONTENT_V1)}"):
            failures += 1

        _step("stat")
        st = backend.stat(MODULE_PATH)
        print(f"  size={st.size_bytes} lines={st.lines} is_file={st.is_file}")
        if not _expect("stat size matches content",
                       st.size_bytes == len(CONTENT_V1.encode("utf-8")),
                       str(st)):
            failures += 1

        _step("write v2")
        backend.write(MODULE_PATH, CONTENT_V2)
        got2 = backend.read(MODULE_PATH)
        if not _expect("read matches v2", got2 == CONTENT_V2,
                       f"len={len(got2)}, expected {len(CONTENT_V2)}"):
            failures += 1
        if not _expect("v2 contains 'extra'", "extra" in got2):
            failures += 1

        _step(f"move -> {MODULE_RENAMED}")
        backend.move(MODULE_PATH, MODULE_RENAMED)
        if not _expect("old path gone", not backend.exists(MODULE_PATH)):
            failures += 1
        if not _expect("new path exists", backend.exists(MODULE_RENAMED)):
            failures += 1
        got3 = backend.read(MODULE_RENAMED)
        if not _expect("content preserved after move", got3 == CONTENT_V2):
            failures += 1

        _step("delete")
        backend.delete(MODULE_RENAMED)
        if not _expect("deleted path gone", not backend.exists(MODULE_RENAMED)):
            failures += 1

        _step("Verify no-op: re-delete raises FileNotFoundError")
        try:
            backend.delete(MODULE_RENAMED)
            _expect("delete twice raises", False)
            failures += 1
        except FileNotFoundError:
            _expect("delete twice raises FileNotFoundError", True)

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
