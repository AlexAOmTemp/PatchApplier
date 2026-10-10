"""DEPRECATED — bulk Lua indexing moved to `indexers.lua_runner`.

The Python-side bulk path (walk DataModel via `read_many`, parse every
script locally with `formats.lua`) was replaced by a Lua-side driver
that runs inside Studio (`lua/code_index_regen.lua`). This module is
kept as a compatibility shim so existing imports from `toolkit.indexers`
keep working. New code should import `build_lua_index` / `LuaIndexResult`
from `indexers.lua_runner` directly.
"""
from __future__ import annotations

from .lua_runner import build_lua_index, LuaIndexResult


# Backwards-compatible names.
build_lua_code_index = build_lua_index
LuaCodeIndexResult = LuaIndexResult


__all__ = ["build_lua_code_index", "LuaCodeIndexResult"]
