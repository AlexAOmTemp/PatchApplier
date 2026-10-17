"""Live tests for Roblox tools against a real MCP bridge.

Not part of run_all.py: requires a running Roblox Studio + bridge,
and will SKIP (exit 0) when the MCP backend is not available.

Run manually:
    python toolkit/code/toolkit/tests/test_live_studio.py

Scenario uses a throwaway ModuleScript under ReplicatedStorage.Shared.
Every step cleans up after itself; a failed run leaves __live_test__
in place (delete it manually if needed).
"""
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))


PASS = "[OK]  "
FAIL = "[FAIL]"
SANDBOX = "ReplicatedStorage.Shared.__live_test__"

SOURCE = """-- Live test module
local M = {}

function M.hello(name)
	return 'hi ' .. name
end

return M
"""


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def expect(self, label, cond, detail=""):
        if cond:
            print(f"{PASS} {label}")
            self.passed += 1
        else:
            print(f"{FAIL} {label}" + (f" -- {detail}" if detail else ""))
            self.failed += 1


def _make_session():
    """Build a Session identical to the GUI's composite session (fs + mcp)."""
    from toolkit.backends import MultiDomainBackend, RootDirBackend, MCPBackend
    from toolkit.config import loader as _cfg
    from toolkit.core import Session
    from toolkit.formats import Format
    from toolkit.tools import TOOL_MAP
    from toolkit.tools.index import install_index_paths

    cfg = _cfg.load()
    install_index_paths(cfg)
    fmt = Format.load(cfg.get("format_preset", "default"), cfg.get("format") or None)

    wd = Path(cfg.get("project_dir") or PROJECT_ROOT)
    fs = RootDirBackend(wd)
    mcp_cfg = cfg.get("mcp") or {}
    native = mcp_cfg.get("native_tools") or {}
    bridge = mcp_cfg.get("bridge_script") or str(_cfg.default_bridge_script())

    mcp = MCPBackend(
        bridge_script=bridge,
        command=mcp_cfg.get("command", "python -u"),
        mcp_command=mcp_cfg.get("mcp_command", "cmd.exe"),
        mcp_args=mcp_cfg.get("mcp_args", ""),
        working_dir=wd,
        preflight=mcp_cfg.get("preflight", True),
        auto_switch=mcp_cfg.get("auto_switch", True),
        ready_timeout=float(mcp_cfg.get("ready_timeout", 120.0)),
        call_timeout=float(mcp_cfg.get("call_timeout", 180.0)),
        studio_timeout=float(mcp_cfg.get("studio_timeout", 60.0)),
        max_retries=int(mcp_cfg.get("max_retries", 6)),
        retry_delay=float(mcp_cfg.get("retry_delay", 1.0)),
        native_tools_enabled=bool(native.get("enabled", True)),
        native_tools_allow=native.get("allow") or None,
    )
    backend = MultiDomainBackend([("fs", fs), ("mcp", mcp)])
    return Session(backend, fmt=fmt, tools=TOOL_MAP)


def _skip(reason: str) -> int:
    print(f"=== SKIPPED: {reason} ===")
    return 0


def _run_body(t, apply):
    print()
    print("== create_file (ModuleScript with trailing return M) ==")
    r = apply([{"action": "create_file",
                "arguments": {"file_path": SANDBOX,
                              "file_content": SOURCE,
                              "class_name": "ModuleScript"}}])[0]
    t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")

    r = apply([{"action": "read_file",
                "arguments": {"file_path": SANDBOX}}])[0]
    t.expect("read matches created", r.status == "ok" and "return M" in r.message,
             r.message[:200])

    print()
    print("== list_symbols ==")
    r = apply([{"action": "list_symbols",
                "arguments": {"file_path": SANDBOX}}])[0]
    t.expect("has M.hello", r.status == "ok" and "M.hello" in r.message, r.message)

    print()
    print("== insert_symbol end: must land BEFORE trailing return M ==")
    r = apply([{"action": "insert_symbol",
                "arguments": {"file_path": SANDBOX,
                              "new_code": "function M.bye()\n\treturn 'bye'\nend\n",
                              "position": "end"}}])[0]
    t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
    r = apply([{"action": "read_file",
                "arguments": {"file_path": SANDBOX}}])[0]
    body = r.message
    idx_bye = body.find("function M.bye")
    idx_ret = body.rfind("return M")
    t.expect("bye present", idx_bye != -1, body)
    t.expect("bye before return M", -1 < idx_bye < idx_ret, body)

    print()
    print("== replace_symbol ==")
    r = apply([{"action": "replace_symbol",
                "arguments": {"file_path": SANDBOX,
                              "qualname": "M.hello",
                              "new_code": "function M.hello(name)\n\treturn 'hello ' .. name\nend\n"}}])[0]
    t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")

    print()
    print("== delete_symbol ==")
    r = apply([{"action": "delete_symbol",
                "arguments": {"file_path": SANDBOX,
                              "qualname": "M.bye"}}])[0]
    t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")

    print()
    print("== rebuild_lua_code_index ==")
    r = apply([{"action": "rebuild_lua_code_index", "arguments": {}}])[0]
    t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
    # The diff may be empty if the module was already indexed with the
    # same content (hash match). Verify by reading the index itself.
    idx = apply([{"action": "get_index",
                  "arguments": {"kind": "lua", "max_bytes": 20000}}])[0]
    t.expect("module present", SANDBOX in idx.message, idx.message[:300])


EXTRA_SOURCE = (
    "-- Live test module\n"
    "local M = {}\n"
    "\n"
    "-- ANCHOR_START\n"
    "-- ANCHOR_END\n"
    "\n"
    "function M.hello(name)\n"
    "\treturn 'hi ' .. name\n"
    "end\n"
    "\n"
    "return M\n"
)


def _run_extra(t, apply):
    """Cover tools not exercised by _run_body: text edits and more."""
    SB = "ReplicatedStorage.Shared.__live_extra__"
    apply([{"action": "delete_file", "arguments": {"file_path": SB}}])

    print()
    print("== create_file: class_name=Script ==")
    r = apply([{"action": "create_file",
                "arguments": {"file_path": SB,
                              "file_content": EXTRA_SOURCE,
                              "class_name": "Script"}}])[0]
    t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")

    print()
    print("== replace_in_file: simple text edit ==")
    r = apply([{"action": "replace_in_file",
                "arguments": {"file_path": SB,
                              "search": "return 'hi ' .. name",
                              "replace": "return 'hello ' .. name"}}])[0]
    t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
    body = apply([{"action": "read_file", "arguments": {"file_path": SB}}])[0].message
    t.expect("edit applied", "'hello '" in body, body[:300])

    print()
    print("== replace_between: between anchors ==")
    r = apply([{"action": "replace_between",
                "arguments": {"file_path": SB,
                              "start_anchor": "-- ANCHOR_START",
                              "end_anchor": "-- ANCHOR_END",
                              "new_content": "-- ANCHOR_START\nlocal inserted = 1\n-- ANCHOR_END"}}])[0]
    t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
    body = apply([{"action": "read_file", "arguments": {"file_path": SB}}])[0].message
    t.expect("inserted present", "local inserted = 1" in body, body[:300])

    print()
    print("== insert_at_anchor: before ==")
    r = apply([{"action": "insert_at_anchor",
                "arguments": {"file_path": SB,
                              "anchor": "-- ANCHOR_START",
                              "position": "before",
                              "new_content": "-- PRE_ANCHOR"}}])[0]
    t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
    body = apply([{"action": "read_file", "arguments": {"file_path": SB}}])[0].message
    idx_pre = body.find("-- PRE_ANCHOR")
    idx_start = body.find("-- ANCHOR_START")
    t.expect("pre before anchor", -1 < idx_pre < idx_start, body[:300])

    print()
    print("== replace_range: by line numbers ==")
    msg = apply([{"action": "read_file", "arguments": {"file_path": SB}}])[0].message
    # strip header (first line is `path` or `path Lx-Ly`); data lines follow
    body_lines = msg.splitlines()[1:]
    ret_idx = next((i for i, ln in enumerate(body_lines) if ln.strip() == "return M"), None)
    t.expect("found return M", ret_idx is not None, msg[:300])
    if ret_idx is not None:
        r = apply([{"action": "replace_range",
                    "arguments": {"file_path": SB,
                                  "start_line": ret_idx + 1,
                                  "end_line": ret_idx + 1,
                                  "new_content": "return M",
                                  "expected_first_line": "return M"}}])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")

    print()
    print("== insert_symbol: reorder via move_symbol ==")
    r = apply([{"action": "insert_symbol",
                "arguments": {"file_path": SB,
                              "new_code": "function M.bye()\n\treturn 'bye'\nend\n",
                              "position": "end"}}])[0]
    t.expect("insert ok", r.status == "ok", f"{r.status}: {r.message}")
    r = apply([{"action": "move_symbol",
                "arguments": {"file_path": SB,
                              "qualname": "M.bye",
                              "position": "before",
                              "anchor": "M.hello"}}])[0]
    t.expect("move ok", r.status == "ok", f"{r.status}: {r.message}")
    body = apply([{"action": "read_file", "arguments": {"file_path": SB}}])[0].message
    idx_bye = body.find("function M.bye")
    idx_hello = body.find("function M.hello")
    t.expect("bye before hello", -1 < idx_bye < idx_hello, body[:400])

    print()
    print("== copy_unit: Lua symbol to same file? (skip if unsupported) ==")
    # copy_unit works source->target; try Lua->Lua with a new target file.
    SB2 = "ReplicatedStorage.Shared.__live_extra_copy__"
    apply([{"action": "delete_file", "arguments": {"file_path": SB2}}])
    apply([{"action": "create_file",
            "arguments": {"file_path": SB2,
                          "file_content": "-- target\nlocal T = {}\nreturn T\n",
                          "class_name": "ModuleScript"}}])
    r = apply([{"action": "copy_unit",
                "arguments": {"source_file": SB,
                              "target_file": SB2,
                              "selector": {"qualname": "M.hello"},
                              "position": "end"}}])[0]
    t.expect("copy_unit Lua", r.status == "ok", f"{r.status}: {r.error_code}: {r.message}")
    apply([{"action": "delete_file", "arguments": {"file_path": SB2}}])

    print()
    print("== cleanup ==")
    apply([{"action": "delete_file", "arguments": {"file_path": SB}}])
    r = apply([{"action": "file_exists", "arguments": {"file_path": SB}}])[0]
    t.expect("sandbox gone", "false" in r.message.lower(), r.message)


def main():
    t = T()

    print("== preflight: is MCP available? ==")
    try:
        s = _make_session()
        s.__enter__()
    except Exception as e:
        return _skip(f"session failed: {e}")

    def apply(patches):
        return s.apply_patches(patches)

    rc = 0
    try:
        state = s.backend.backend_state("mcp")
        if state != "ready":
            rc = _skip(f"mcp backend not ready: {state}")
        else:
            print("    mcp backend ready")
            apply([{"action": "delete_file",
                    "arguments": {"file_path": SANDBOX}}])
            _run_body(t, apply)
            _run_extra(t, apply)
            print()
            print("== cleanup: delete_file ==")
            # Soft delete: file may already be absent (nothing to clean up).
            apply([{"action": "delete_file",
                    "arguments": {"file_path": SANDBOX}}])
            r = apply([{"action": "file_exists",
                        "arguments": {"file_path": SANDBOX}}])[0]
            t.expect("sandbox gone", "false" in r.message.lower(), r.message)
    finally:
        try:
            s.__exit__(None, None, None)
        except Exception:
            pass

    if rc:
        return rc
    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
