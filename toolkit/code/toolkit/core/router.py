"""Rebuild router: which index rebuilds to run after a patch.

Pure function; no backend, no GUI, no CLI. Takes the applied patches and
their Results, returns a list of (label, patch) to append. This is the
single place where the policy 'what touched what -> which index' lives.
"""
from __future__ import annotations

from .models import Result
from .paths import is_mcp_path


# Native MCP tools that only read. Everything else (unknown native,
# execute_luau, multi_edit, generative, insert_asset, ...) is treated as
# capable of mutating the DataModel and triggers a Lua rebuild.
NATIVE_READ_ONLY = frozenset({
    "inspect_instance",
    "search_game_tree",
    "script_read",
    "script_search",
    "script_grep",
    "get_console_output",
    "get_studio_state",
    "list_roblox_studios",
    "search_asset",
    "http_get",
    "skill",
    "store_image",
    "wait_job_finished",
})


def _classify_path(path: str) -> str | None:
    """Map a single path to a rebuild domain.

    'docs' / 'code' (Python) / 'csharp' / 'lua' / None.
    """
    if not path:
        return None
    if is_mcp_path(path):
        return "lua"
    low = path.lower()
    if low.endswith(".md"):
        return "docs"
    if low.endswith(".py"):
        return "code"
    if low.endswith(".cs"):
        return "csharp"
    return None


def _paths_of(tool_cls: type, args: dict) -> list[str]:
    """Collect every path-valued argument declared by the tool."""
    out: list[str] = []
    for key in getattr(tool_cls, "path_args", []) or []:
        v = args.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    for key in getattr(tool_cls, "path_list_args", []) or []:
        v = args.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str) and item:
                    out.append(item)
    return out


def plan_rebuilds(
    user_patches: list[dict],
    user_results: list[Result],
    tool_map: dict[str, type],
    *,
    config: dict,
    supports_fs: bool,
    supports_mcp: bool,
) -> list[tuple[str, dict]]:
    """Return [(label, rebuild_patch)] for domains touched by successful writes.

    Rules:
      * empty user_patches -> []
      * only Result.status == 'ok' contributes
      * only op == 'write' tools (and non-read-only natives) contribute
      * write with no declared path_args -> all enabled domains
      * write with path_args -> classified by extension / is_mcp_path
      * docs/code need supports_fs; lua needs supports_mcp
      * per-domain config flag: index_docs / index_python / index_csharp / index_lua

    Deterministic order of output: docs, code, csharp, lua.
    """
    if not user_patches:
        return []

    want_docs = bool(config.get("index_docs", True)) and supports_fs
    want_code = bool(config.get("index_python", True)) and supports_fs
    want_cs   = bool(config.get("index_csharp", True)) and supports_fs
    want_lua  = bool(config.get("index_lua", True)) and supports_mcp

    touched: set[str] = set()

    for patch, result in zip(user_patches, user_results):
        if result is None or result.status != "ok":
            continue
        action = patch.get("action") or ""
        args = patch.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}

        tool_cls = tool_map.get(action)
        if tool_cls is None:
            # Native MCP tool. Only an explicit read-only whitelist is safe;
            # anything else may mutate the DataModel.
            if action not in NATIVE_READ_ONLY:
                touched.add("lua")
            continue

        op = getattr(tool_cls, "op", "write")
        if op != "write":
            continue

        paths = _paths_of(tool_cls, args)
        if not paths:
            # Opaque writer (e.g. run_python): might have touched anything.
            touched.update({"docs", "code", "csharp", "lua"})
            continue

        for p in paths:
            domain = _classify_path(p)
            if domain:
                touched.add(domain)

    out: list[tuple[str, dict]] = []
    if "docs" in touched and want_docs:
        out.append(("rebuild_index (docs)",
                    {"action": "rebuild_index", "arguments": {}}))
    if "code" in touched and want_code:
        out.append(("rebuild_code_index (Python)",
                    {"action": "rebuild_code_index", "arguments": {}}))
    if "csharp" in touched and want_cs:
        out.append(("rebuild_csharp_index (C#)",
                    {"action": "rebuild_csharp_index", "arguments": {}}))
    if "lua" in touched and want_lua:
        out.append(("rebuild_lua_code_index (Roblox)",
                    {"action": "rebuild_lua_code_index", "arguments": {}}))
    return out
