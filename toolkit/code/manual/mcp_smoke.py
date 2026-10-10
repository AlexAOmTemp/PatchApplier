"""Manual end-to-end test of MCPBackend against a real Roblox Studio.

Usage (from MCPBridge dir):
    python toolkit/manual_mcp_smoke.py

Requires:
    - Roblox Studio open with the target project
    - Roblox MCP server installed (bridge.py spawns it)

The script will:
    1. Spawn bridge.py (which itself spawns the Roblox MCP server)
    2. Wait for "Мост готов"
    3. Do a few read-only calls via execute_luau
    4. Print results and close

Nothing is written to Studio — read-only smoke test.
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
from toolkit.core import FilterSpec


DEFAULT_BRIDGE = PROJECT_ROOT / "bridge.py"
DEFAULT_MCP_COMMAND = "cmd.exe"
DEFAULT_MCP_ARGS = r"/c cd /d %LOCALAPPDATA%\Roblox && .\mcp.bat"


TEST_PATHS = [
    "ReplicatedStorage.Shared.Domain.ItemFormula",
    "ServerScriptService.Services.CraftService",
    "ReplicatedStorage.Shared.Domain.MathUtils",
]


def _step(msg: str) -> None:
    print()
    print("=" * 60)
    print(msg)
    print("=" * 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bridge", default=str(DEFAULT_BRIDGE),
                    help="path to bridge.py")
    ap.add_argument("--mcp-command", default=DEFAULT_MCP_COMMAND,
                    help="executable to launch MCP server")
    ap.add_argument("--mcp-args", default=DEFAULT_MCP_ARGS,
                    help="arguments for the MCP server")
    ap.add_argument("--working-dir", default=str(PROJECT_ROOT),
                    help="where bridge stores patch.json/outputs.json")
    ap.add_argument("--ready-timeout", type=float, default=120.0)
    ap.add_argument("--call-timeout", type=float, default=180.0)
    ap.add_argument("--studio-timeout", type=float, default=60.0)
    args = ap.parse_args()

    bridge = Path(args.bridge)
    if not bridge.is_file():
        print(f"[error] bridge not found: {bridge}")
        return 2

    _step(f"Bridge: {bridge}")
    _step(f"MCP: {args.mcp_command} {args.mcp_args}")
    _step(f"Working dir: {args.working_dir}")

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

    try:
        _step("Opening bridge...")
        backend.open()
        print(f"[ok] bridge alive: {backend.is_alive()}")

        for path in TEST_PATHS:
            _step(f"exists({path})")
            try:
                exists = backend.exists(path)
                print(f"  exists -> {exists}")
            except Exception as e:
                print(f"  [error] {type(e).__name__}: {e}")

        for path in TEST_PATHS:
            _step(f"read({path})")
            try:
                src = backend.read(path)
                n = len(src)
                preview = src[:200].replace("\n", "\\n")
                print(f"  len={n}")
                print(f"  preview: {preview}")
                if n > 200:
                    print(f"  ... ({n - 200} more chars)")
            except Exception as e:
                print(f"  [error] {type(e).__name__}: {e}")
                traceback.print_exc()

        _step("stat on known paths")
        for path in TEST_PATHS:
            try:
                st = backend.stat(path)
                print(f"  {path}: size={st.size_bytes} lines={st.lines} is_file={st.is_file}")
            except Exception as e:
                print(f"  {path}: [error] {type(e).__name__}: {e}")

        _step("list under ReplicatedStorage.Shared.Domain")
        try:
            lst = backend.list("ReplicatedStorage.Shared.Domain")
            print(f"  found {len(lst)} modules (first 10 shown)")
            for p in lst[:10]:
                print(f"    {p}")
        except Exception as e:
            print(f"  [error] {type(e).__name__}: {e}")

        _step("filter_check sanity")
        spec = FilterSpec(overrides={"ReplicatedStorage": True})
        err = backend.filter_check("ReplicatedStorage.Foo", spec)
        print(f"  allow ReplicatedStorage -> {err}")
        spec2 = FilterSpec(overrides={"ReplicatedStorage": False})
        err2 = backend.filter_check("ReplicatedStorage.Foo", spec2)
        print(f"  deny ReplicatedStorage -> {err2}")

    except Exception as e:
        _step(f"FATAL: {type(e).__name__}")
        print(e)
        traceback.print_exc()
        return 1
    finally:
        _step("Closing bridge...")
        backend.close()
        print(f"[ok] closed, alive={backend.is_alive()}")

    print()
    print("=== DONE ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
