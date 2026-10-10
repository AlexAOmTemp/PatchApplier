"""Manual smoke: grep_replace_mcp against a real Roblox Studio.

Verifies the two-pass replace tool end-to-end:
  1. setup: create a ModuleScript with known content
  2. grep_mcp: sanity that the pattern is present
  3. grep_replace_mcp (dry_run): counts without writing
  4. read back: unchanged
  5. grep_replace_mcp (apply): writes
  6. read back: replaced
  7. grep_replace_mcp (mappings, dry_run): counts without writing
  8. grep_replace_mcp (mappings, apply): writes
  9. read back: replaced
 10. overflow gate: max_replacements=1 with >1 expected -> __OVERFLOW__
 11. no_matches: unknown pattern -> error_code=no_matches
 12. cleanup: destroy test folder

Usage (from MCPBridge dir):
    python toolkit/code/manual/verify_grep_replace_mcp.py

Requires:
    - Roblox Studio open with the target project
    - Roblox MCP server installed (bridge.py spawns it)

Nothing outside the test folder is touched. The test folder is removed
in the finally block regardless of outcome.
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

FOLDER_PATH = "ReplicatedStorage.__pa_grep_replace_test__"
MODULE_PATH = FOLDER_PATH + ".Fixture"

CONTENT_INITIAL = (
    "local QuestService = {}\n"
    "QuestService.completedQuests = {}\n"
    "function QuestService.GetCompletedQuests(player)\n"
    "    return QuestService.completedQuests[player]\n"
    "end\n"
    "function QuestService.SetQuestCompleted(player, id)\n"
    "    QuestService.completedQuests[player] = id\n"
    "end\n"
    "return QuestService\n"
)

CONTENT_SINGLE = (
    "local MissionService = {}\n"
    "MissionService.completedQuests = {}\n"
    "function MissionService.GetCompletedQuests(player)\n"
    "    return MissionService.completedQuests[player]\n"
    "end\n"
    "function MissionService.SetQuestCompleted(player, id)\n"
    "    MissionService.completedQuests[player] = id\n"
    "end\n"
    "return MissionService\n"
)

CONTENT_MAPPINGS = (
    "local MissionService = {}\n"
    "MissionService.completedMissions = {}\n"
    "function MissionService.GetCompletedMissions(player)\n"
    "    return MissionService.completedMissions[player]\n"
    "end\n"
    "function MissionService.SetMissionCompleted(player, id)\n"
    "    MissionService.completedMissions[player] = id\n"
    "end\n"
    "return MissionService\n"
)

SETUP_CODE = (
    "local rs = game:GetService('ReplicatedStorage')\n"
    f"local folder = rs:FindFirstChild('__pa_grep_replace_test__')\n"
    "if folder then folder:Destroy() end\n"
    "folder = Instance.new('Folder')\n"
    "folder.Name = '__pa_grep_replace_test__'\n"
    "folder.Parent = rs\n"
    "local mod = Instance.new('ModuleScript')\n"
    "mod.Name = 'Fixture'\n"
    "mod.Source = ..."
    "mod.Parent = folder\n"
    "return 'setup-ok'"
)

CLEANUP_CODE = (
    "local rs = game:GetService('ReplicatedStorage')\n"
    f"local folder = rs:FindFirstChild('__pa_grep_replace_test__')\n"
    "if folder then folder:Destroy() return 'cleaned' end\n"
    "return 'already-gone'"
)


def _step(msg: str) -> None:
    print()
    print("=" * 60)
    print(msg)
    print("=" * 60)


def _check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    suffix = f"  ({detail})" if detail and not ok else ""
    print(f"  {mark}  {label}{suffix}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bridge", default=str(DEFAULT_BRIDGE))
    ap.add_argument("--mcp-command", default=DEFAULT_MCP_COMMAND)
    ap.add_argument("--mcp-args", default=DEFAULT_MCP_ARGS)
    ap.add_argument("--working-dir", default=str(PROJECT_ROOT))
    ap.add_argument("--ready-timeout", type=float, default=120.0)
    ap.add_argument("--call-timeout", type=float, default=180.0)
    ap.add_argument("--studio-timeout", type=float, default=60.0)
    ap.add_argument("--yes", action="store_true",
                    help="skip interactive confirmation")
    args = ap.parse_args()

    bridge = Path(args.bridge)
    if not bridge.is_file():
        print(f"[error] bridge not found: {bridge}")
        return 2

    if not args.yes:
        print("This smoke test will:")
        print(f"  - create folder {FOLDER_PATH}")
        print(f"  - create ModuleScript {MODULE_PATH} with known content")
        print("  - run grep_replace_mcp in dry_run and apply modes")
        print("  - run grep_replace_mcp in mappings mode")
        print("  - verify overflow / no_matches error codes")
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
    try:
        _step("Opening bridge...")
        backend.open()
        print(f"[ok] bridge alive: {backend.is_alive()}")

        _step("Setup")
        code = SETUP_CODE.replace("...", repr(CONTENT_INITIAL))
        r = backend.execute(code)
        print(f"  setup result: {r!r}")
        if not _check("setup returned 'setup-ok'", r == "setup-ok", r):
            failures += 1
        if not _check("module exists", backend.exists(MODULE_PATH)):
            failures += 1

        _step("grep_mcp sanity")
        raw = backend.grep_mcp(FOLDER_PATH, "QuestService", fixed_strings=True)
        if not _check("grep_mcp found QuestService", "QuestService" in raw):
            failures += 1
            print(f"  raw: {raw!r}")

        _step("grep_replace_mcp dry_run: QuestService -> MissionService")
        raw = backend.grep_replace_mcp(
            FOLDER_PATH,
            pattern="QuestService",
            replacement="MissionService",
            fixed_strings=True,
            word_boundary=True,
            max_replacements=1000,
            dry_run=True,
        )
        print(f"  raw: {raw!r}")
        ok_dry = _check("dry_run returned CHANGED", "CHANGED\t" in raw)
        ok_dry &= _check("dry_run reported applied=false",
                         "applied=false" in raw)
        if not ok_dry:
            failures += 1
        got = backend.read(MODULE_PATH)
        if not _check("dry_run did not modify .Source", got == CONTENT_INITIAL):
            failures += 1

        _step("grep_replace_mcp apply: QuestService -> MissionService")
        raw = backend.grep_replace_mcp(
            FOLDER_PATH,
            pattern="QuestService",
            replacement="MissionService",
            fixed_strings=True,
            word_boundary=True,
            max_replacements=1000,
            dry_run=False,
        )
        print(f"  raw: {raw!r}")
        if not _check("apply reported applied=true", "applied=true" in raw):
            failures += 1
        got = backend.read(MODULE_PATH)
        if not _check("apply wrote expected content", got == CONTENT_SINGLE,
                      f"len={len(got)} expected={len(CONTENT_SINGLE)}"):
            failures += 1
            print(f"  got: {got!r}")

        _step("grep_replace_mcp mappings dry_run")
        raw = backend.grep_replace_mcp(
            FOLDER_PATH,
            mappings=[
                ("completedQuests", "completedMissions"),
                ("GetCompletedQuests", "GetCompletedMissions"),
                ("SetQuestCompleted", "SetMissionCompleted"),
            ],
            fixed_strings=True,
            word_boundary=True,
            max_replacements=1000,
            dry_run=True,
        )
        print(f"  raw: {raw!r}")
        if not _check("mappings dry_run returned CHANGED", "CHANGED\t" in raw):
            failures += 1
        if not _check("mappings dry_run reported applied=false",
                      "applied=false" in raw):
            failures += 1
        got = backend.read(MODULE_PATH)
        if not _check("mappings dry_run did not modify", got == CONTENT_SINGLE):
            failures += 1

        _step("grep_replace_mcp mappings apply")
        raw = backend.grep_replace_mcp(
            FOLDER_PATH,
            mappings=[
                ("completedQuests", "completedMissions"),
                ("GetCompletedQuests", "GetCompletedMissions"),
                ("SetQuestCompleted", "SetMissionCompleted"),
            ],
            fixed_strings=True,
            word_boundary=True,
            max_replacements=1000,
            dry_run=False,
        )
        print(f"  raw: {raw!r}")
        if not _check("mappings apply reported applied=true",
                      "applied=true" in raw):
            failures += 1
        got = backend.read(MODULE_PATH)
        if not _check("mappings apply wrote expected content",
                      got == CONTENT_MAPPINGS,
                      f"len={len(got)} expected={len(CONTENT_MAPPINGS)}"):
            failures += 1
            print(f"  got: {got!r}")

        _step("overflow gate: max_replacements=1")
        backend.write(MODULE_PATH, CONTENT_INITIAL)
        raw = backend.grep_replace_mcp(
            FOLDER_PATH,
            pattern="QuestService",
            replacement="MissionService",
            fixed_strings=True,
            word_boundary=True,
            max_replacements=1,
            dry_run=False,
        )
        print(f"  raw: {raw!r}")
        if not _check("overflow returned __OVERFLOW__",
                      raw.startswith("__OVERFLOW__\t")):
            failures += 1
        got = backend.read(MODULE_PATH)
        if not _check("overflow did not modify .Source", got == CONTENT_INITIAL):
            failures += 1

        _step("no_matches: unknown pattern")
        raw = backend.grep_replace_mcp(
            FOLDER_PATH,
            pattern="ThisPatternDoesNotExistAnywhere",
            replacement="x",
            fixed_strings=True,
            max_replacements=1000,
            dry_run=True,
        )
        print(f"  raw: {raw!r}")
        if not _check("no_matches returned __EMPTY__", raw == "__EMPTY__"):
            failures += 1

    except Exception as e:
        _step(f"FATAL: {type(e).__name__}")
        print(e)
        traceback.print_exc()
        failures += 1
    finally:
        _step("Cleanup")
        try:
            backend.execute(CLEANUP_CODE)
            print("  cleanup executed")
        except Exception as e:
            print(f"  [warn] cleanup failed: {type(e).__name__}: {e}")
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
