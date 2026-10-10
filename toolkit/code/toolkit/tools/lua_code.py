"""Backwards-compatible re-exports for Lua symbol tools.

The real implementations live in `toolkit.tools.symbols.python`, which
dispatches to `toolkit.tools.symbols.lua` when `file_path` ends with
.lua/.luau. This module keeps the historical `_lua`-suffixed action names
(`list_symbols_lua`, `read_symbol_lua`, `replace_function_lua`) available
for old patches. New patches should prefer the unified names
(`list_symbols`, `read_symbol`, `replace_symbol`) — they handle Lua
files transparently.
"""
from .symbols.python import (
    ListSymbolsTool as ListSymbolsLuaTool,
    ReadSymbolTool as ReadSymbolLuaTool,
    ReplaceSymbolTool as ReplaceFunctionLuaTool,
)

__all__ = [
    "ListSymbolsLuaTool",
    "ReadSymbolLuaTool",
    "ReplaceFunctionLuaTool",
]
