"""Smoke: grep_replace_mcp validation — every error_code in one pass.

Table-driven: each case provides arguments and an expected error_code.
Cases that can be validated Python-side never reach Studio; only the
three runtime cases (not_found / no_matches / too_many_replacements)
need a live bridge.

Usage (from MCPBridge dir):
    python toolkit/code/manual/verify_grep_replace_mcp_errors.py

Requires:
    - Roblox Studio open with the target project (for the runtime cases)

Nothing is written to Studio. The not_found / no_matches cases use paths
and patterns that cannot match anything.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent
CODE_ROOT = HERE.parent              # .../toolkit/code
PROJECT_ROOT = HERE.parents[2]       # MCPBridge root
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from toolkit.backends import MCPBackend  # noqa: E402


DEFAULT_BRIDGE = CODE_ROOT / "bridge" / "bridge.py"
DEFAULT_MCP_COMMAND = "cmd.exe"
DEFAULT_MCP_ARGS = r"/c cd /d %LOCALAPPDATA%\Roblox && .\mcp.bat"

VALID_DIR = "ReplicatedStorage.Shared.Modules"


def _step(msg: str) -> None:
    print()
    print("=" * 60)
    print(msg)
    print("=" * 60)


# Each case: (label, kwargs, expected_error_code)
# kwargs are passed to backend.grep_replace_mcp (after root).
VALIDATION_CASES = [
    # --- domain (checked in tool layer, but easiest to test here) ---
    # (validation of wrong_domain is done in GrepReplaceMcpTool.execute)
    # Those cases require calling the tool, not the backend. See TOOL_CASES.

    # --- pattern / mappings exclusivity (backend raises ValueError) ---
    ("both pattern and mappings",
     dict(pattern="x", mappings=[("a", "b")], fixed_strings=True),
     "bad_options"),  # backend raises ValueError
    ("neither pattern nor mappings",
     dict(fixed_strings=True),
     "bad_options"),

    # --- mappings constraints ---
    ("empty mappings list",
     dict(mappings=[], fixed_strings=True),
     "bad_options"),
    ("mappings without fixed_strings",
     dict(mappings=[("a", "b")], fixed_strings=False),
     "bad_options"),
    ("mappings with ignore_case",
     dict(mappings=[("a", "b")], fixed_strings=True, ignore_case=True),
     "bad_options"),

    # --- pattern constraints ---
    ("empty pattern",
     dict(pattern="", fixed_strings=True),
     "bad_options"),
    ("ignore_case without fixed_strings",
     dict(pattern="x", fixed_strings=False, ignore_case=True),
     "bad_options"),

    # --- numeric ---
    ("max_replacements = 0",
     dict(pattern="x", fixed_strings=True, max_replacements=0),
     "bad_options"),
    ("max_replacements negative",
     dict(pattern="x", fixed_strings=True, max_replacements=-5),
     "bad_options"),
]


# Tool-level cases (validation happens in GrepReplaceMcpTool.execute,
# before any backend call). Each: (label, arguments_dict, expected_error_code)
TOOL_CASES = [
    ("directory is empty",
     {"directory": "", "pattern": "x", "fixed_strings": True},
     "wrong_domain"),
    ("directory is an FS path",
     {"directory": "toolkit/code", "pattern": "x", "fixed_strings": True},
     "wrong_domain"),
    ("both pattern and mappings",
     {"directory": VALID_DIR, "pattern": "x",
      "mappings": [{"from": "a", "to": "b"}], "fixed_strings": True},
     "bad_input"),
    ("neither pattern nor mappings",
     {"directory": VALID_DIR, "fixed_strings": True},
     "bad_input"),
    ("empty pattern string",
     {"directory": VALID_DIR, "pattern": "", "fixed_strings": True},
     "bad_input"),
    ("empty mappings list",
     {"directory": VALID_DIR, "mappings": [], "fixed_strings": True},
     "empty_mappings"),
    ("mappings without fixed_strings",
     {"directory": VALID_DIR,
      "mappings": [{"from": "a", "to": "b"}], "fixed_strings": False},
     "patterns_in_mappings_not_supported"),
    ("mappings with ignore_case",
     {"directory": VALID_DIR,
      "mappings": [{"from": "a", "to": "b"}],
      "fixed_strings": True, "ignore_case": True},
     "bad_options"),
    ("ignore_case without fixed_strings",
     {"directory": VALID_DIR, "pattern": "x",
      "fixed_strings": False, "ignore_case": True},
     "bad_options"),
    ("max_replacements = 0",
     {"directory": VALID_DIR, "pattern": "x",
      "fixed_strings": True, "max_replacements": 0},
     "bad_options"),
    ("mapping not a dict",
     {"directory": VALID_DIR, "mappings": ["a"], "fixed_strings": True},
     "bad_mapping"),
    ("mapping.from not a string",
     {"directory": VALID_DIR,
      "mappings": [{"from": 1, "to": "b"}], "fixed_strings": True},
     "bad_mapping"),
    ("mapping.from empty",
     {"directory": VALID_DIR,
      "mappings": [{"from": "", "to": "b"}], "fixed_strings": True},
     "empty_mapping"),
    ("mapping.from == to",
     {"directory": VALID_DIR,
      "mappings": [{"from": "a", "to": "a"}], "fixed_strings": True},
     "noop_mapping"),
    ("duplicate mapping.from",
     {"directory": VALID_DIR,
      "mappings": [{"from": "a", "to": "b"}, {"from": "a", "to": "c"}],
      "fixed_strings": True},
     "duplicate_mapping"),
]


# Runtime cases (need live Studio).
RUNTIME_CASES = [
    ("directory does not exist",
     {"directory": "ReplicatedStorage.__no_such_thing__",
      "pattern": "x", "fixed_strings": True},
     "not_found"),
    ("pattern with no matches",
     {"directory": VALID_DIR,
      "pattern": "ThisPatternDoesNotExistAnywhere12345",
      "fixed_strings": True},
     "no_matches"),
    ("max_replacements too low",
     {"directory": "ReplicatedStorage.Shared.Modules.LuckFormula",
      "pattern": "LuckFormula", "fixed_strings": True,
      "max_replacements": 1},
     "too_many_replacements"),
]


def _check(label: str, got: str, expected: str) -> bool:
    mark = "PASS" if got == expected else "FAIL"
    print(f"  {mark}  {label}")
    print(f"        expected: {expected}")
    if got != expected:
        print(f"        got:      {got}")
    return got == expected


def _run_tool_case(tool, backend, fmt, arguments: dict) -> str:
    """Call tool.execute directly, return the resulting error_code (or '<ok>')."""
    r = tool.execute(backend=backend, fmt=fmt, **arguments)
    if r.status == "ok":
        return "<ok>"
    return r.error_code or "<no-code>"


def _run_backend_case(backend, root: str, kwargs: dict) -> str:
    """Call backend.grep_replace_mcp directly; ValueError -> 'bad_options'."""
    try:
        backend.grep_replace_mcp(root, **kwargs)
    except ValueError:
        return "bad_options"
    except Exception as e:
        return f"<{type(e).__name__}>"
    return "<ok>"


def main() -> int:
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
        print("This smoke test will:")
        print("  - open the bridge")
        print("  - run a series of invalid-input cases (nothing is written)")
        print("  - close the bridge")
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

    from toolkit.formats import Format  # noqa: E402
    from toolkit.tools.grep_replace_mcp import GrepReplaceMcpTool  # noqa: E402

    tool = GrepReplaceMcpTool()
    fmt = Format.load("default")
    failures = 0

    try:
        _step("Opening bridge...")
        backend.open()
        print(f"[ok] bridge alive: {backend.is_alive()}")

        _step("Tool-level validation (no backend call)")
        for label, arguments, expected in TOOL_CASES:
            got = _run_tool_case(tool, backend, fmt, arguments)
            if not _check(label, got, expected):
                failures += 1

        _step("Backend-level validation (ValueError -> bad_options)")
        for label, kwargs, expected in VALIDATION_CASES:
            got = _run_backend_case(backend, VALID_DIR, kwargs)
            if not _check(label, got, expected):
                failures += 1

        _step("Runtime cases (need live Studio)")
        for label, arguments, expected in RUNTIME_CASES:
            got = _run_tool_case(tool, backend, fmt, arguments)
            if not _check(label, got, expected):
                failures += 1

    except Exception as e:
        _step(f"FATAL: {type(e).__name__}")
        print(e)
        traceback.print_exc()
        failures += 1
    finally:
        _step("Closing bridge...")
        backend.close()
        print(f"[ok] closed, alive={backend.is_alive()}")

    print()
    if failures:
        print(f"=== {failures} FAILURE(S) ===")
        return 1
    print("=== ALL OK ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
