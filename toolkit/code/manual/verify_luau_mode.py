"""Smoke: get_status renders luau mode correctly (mcp vs rojo)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

from toolkit.tools.status import GetStatusTool  # noqa: E402


def _check(label, ok):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return ok


def main():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        for mode in ("mcp", "rojo"):
            print(f"== luau_mode={mode} ==")
            GetStatusTool.set_context(
                project_name="p", backend="composite",
                luau_mode=mode,
                backends_enabled={"filesystem", "mcp"},
            )
            r = GetStatusTool().execute(backend=None, fmt=None,
                                        sections=["session", "policy"])
            ok &= _check("ok", r.status == "ok")
            ok &= _check(f"luau: {mode}", f"luau:     {mode}" in r.message)
            if mode == "mcp":
                ok &= _check("MCP scope includes Luau",
                             "Roblox scene + Luau code" in r.message)
            else:
                ok &= _check("MCP scope is scene only",
                             "scope:    Roblox scene" in r.message)
                ok &= _check("no '+ Luau code' when rojo",
                             "+ Luau code" not in r.message)

    print()
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
