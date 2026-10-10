"""Tests for toolkit.core.router.plan_rebuilds - the rebuild router."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.core.models import Result
from toolkit.core.router import plan_rebuilds


PASS = "[OK]  "
FAIL = "[FAIL]"


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def expect(self, label, cond, info=""):
        if cond:
            self.passed += 1
            print(f"{PASS} {label}")
        else:
            self.failed += 1
            print(f"{FAIL} {label}  {info}")


class ReadTool:
    name = "read_file"
    op = "read"
    path_args = ["file_path"]
    path_list_args = []


class WriteMdTool:
    name = "replace_between"
    op = "write"
    path_args = ["file_path"]
    path_list_args = []


class WritePyTool:
    name = "replace_symbol"
    op = "write"
    path_args = ["file_path"]
    path_list_args = []


class MoveTool:
    name = "move_symbol"
    op = "write"
    path_args = ["file_path", "target_file"]
    path_list_args = []


class RunPythonTool:
    name = "run_python"
    op = "write"
    path_args = []
    path_list_args = []


class IndexTool:
    name = "rebuild_index"
    op = "index"
    path_args = []
    path_list_args = []


TOOL_MAP = {
    "read_file": ReadTool,
    "replace_between": WriteMdTool,
    "replace_symbol": WritePyTool,
    "move_symbol": MoveTool,
    "run_python": RunPythonTool,
    "rebuild_index": IndexTool,
}


def _patch(action, **args):
    return {"action": action, "arguments": args}


def _ok(action=None):
    return Result(status="ok", message="", action=action)


def _err(action=None):
    return Result(status="error", message="", action=action)


def _actions(plan):
    return [p["action"] for _, p in plan]


CFG_ALL_ON = {"index_docs": True, "index_python": True, "index_lua": True}


def main():
    t = T()

    plan = plan_rebuilds([], [], TOOL_MAP,
                         config=CFG_ALL_ON,
                         supports_fs=True, supports_mcp=True)
    t.expect("empty patch -> no rebuilds", plan == [], plan)

    plan = plan_rebuilds(
        [_patch("read_file", file_path="docs/X.md")],
        [_ok("read_file")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("read tool -> no trigger", plan == [], _actions(plan))

    plan = plan_rebuilds(
        [_patch("replace_between", file_path="docs/X.md")],
        [_ok("replace_between")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("write .md -> docs only",
             _actions(plan) == ["rebuild_index"], _actions(plan))

    plan = plan_rebuilds(
        [_patch("replace_symbol", file_path="toolkit/x.py")],
        [_ok("replace_symbol")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("write .py -> code only",
             _actions(plan) == ["rebuild_code_index"], _actions(plan))

    plan = plan_rebuilds(
        [_patch("replace_symbol", file_path="ReplicatedStorage.Mod")],
        [_ok("replace_symbol")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("MCP path -> lua only",
             _actions(plan) == ["rebuild_lua_code_index"], _actions(plan))

    plan = plan_rebuilds(
        [_patch("run_python", script="tests/x.py")],
        [_ok("run_python")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("run_python -> all three",
             _actions(plan) == ["rebuild_index", "rebuild_code_index",
                                "rebuild_lua_code_index"],
             _actions(plan))

    plan = plan_rebuilds(
        [_patch("replace_symbol", file_path="x.py")],
        [_err("replace_symbol")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("failed write -> no trigger", plan == [], _actions(plan))

    plan = plan_rebuilds(
        [_patch("rebuild_index")],
        [_ok("rebuild_index")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("index tool -> no trigger", plan == [], _actions(plan))

    plan = plan_rebuilds(
        [_patch("replace_between", file_path="docs/X.md"),
         _patch("replace_symbol", file_path="x.py")],
        [_ok("replace_between"), _ok("replace_symbol")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("mixed .md + .py -> docs + code",
             _actions(plan) == ["rebuild_index", "rebuild_code_index"],
             _actions(plan))

    plan = plan_rebuilds(
        [_patch("replace_symbol", file_path="ReplicatedStorage.Mod")],
        [_ok("replace_symbol")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=False)
    t.expect("supports_mcp=False -> no lua", plan == [], _actions(plan))

    cfg = dict(CFG_ALL_ON)
    cfg["index_docs"] = False
    plan = plan_rebuilds(
        [_patch("replace_between", file_path="docs/X.md")],
        [_ok("replace_between")],
        TOOL_MAP,
        config=cfg, supports_fs=True, supports_mcp=True)
    t.expect("index_docs=False -> no docs", plan == [], _actions(plan))

    plan = plan_rebuilds(
        [{"action": "inspect_instance", "arguments": {"path": "Workspace.X"}}],
        [_ok("inspect_instance")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("native read-only -> no trigger", plan == [], _actions(plan))

    plan = plan_rebuilds(
        [{"action": "execute_luau", "arguments": {"code": "return 1"}}],
        [_ok("execute_luau")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("native writer -> lua only",
             _actions(plan) == ["rebuild_lua_code_index"], _actions(plan))

    plan = plan_rebuilds(
        [{"action": "some_new_native", "arguments": {}}],
        [_ok("some_new_native")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("unknown native -> lua (safe default)",
             _actions(plan) == ["rebuild_lua_code_index"], _actions(plan))

    plan = plan_rebuilds(
        [_patch("move_symbol", file_path="a.py", target_file="b.py")],
        [_ok("move_symbol")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("move .py -> .py -> code only",
             _actions(plan) == ["rebuild_code_index"], _actions(plan))

    plan = plan_rebuilds(
        [_patch("move_symbol", file_path="a.md", target_file="b.py")],
        [_ok("move_symbol")],
        TOOL_MAP,
        config=CFG_ALL_ON, supports_fs=True, supports_mcp=True)
    t.expect("move .md -> .py -> docs + code",
             _actions(plan) == ["rebuild_index", "rebuild_code_index"],
             _actions(plan))

    print()
    print(f"=== RESULT: passed={t.passed} failed={t.failed} ===")
    return 1 if t.failed else 0


if __name__ == "__main__":
    sys.exit(main())
