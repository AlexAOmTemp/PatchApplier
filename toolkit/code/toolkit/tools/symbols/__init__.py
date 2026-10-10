"""Symbol tools — structure-aware operations on named units of a file.

Currently Python only. The public API mirrors `toolkit.tools.code` (which
re-exports from here) so external callers may use either import path.
"""
from .python import (
    ListSymbolsTool, ReadSymbolTool,
    ReplaceSymbolTool, ReplaceSymbolBodyTool,
    ReplaceSymbolSignatureTool, DeleteSymbolTool, InsertSymbolTool,
    MoveSymbolTool,
)

ReplaceFunctionTool = ReplaceSymbolTool
ReplaceFunctionBodyTool = ReplaceSymbolBodyTool

__all__ = [
    "ListSymbolsTool", "ReadSymbolTool",
    "ReplaceSymbolTool", "ReplaceSymbolBodyTool",
    "ReplaceSymbolSignatureTool", "DeleteSymbolTool", "InsertSymbolTool",
    "MoveSymbolTool",
    "ReplaceFunctionTool", "ReplaceFunctionBodyTool",
]
