"""Backwards-compatible re-exports for Python symbol tools.

Real implementations live in `toolkit.tools.symbols.python` (tools) and
`toolkit.tools.symbols._ast` (AST helpers). This module is kept so that
older patches and imports referencing `toolkit.tools.code` keep working.
New code should import from `toolkit.tools.symbols`.
"""
from .symbols.python import (
    ListSymbolsTool, ReadSymbolTool,
    ReplaceSymbolTool, ReplaceSymbolBodyTool,
    ReplaceSymbolSignatureTool, DeleteSymbolTool, InsertSymbolTool,
    MoveSymbolTool, ReplaceStatementTool,
)

# Backwards-compatible aliases (pre-rename patches).
ReplaceFunctionTool = ReplaceSymbolTool
ReplaceFunctionBodyTool = ReplaceSymbolBodyTool

__all__ = [
    "ListSymbolsTool", "ReadSymbolTool",
    "ReplaceSymbolTool", "ReplaceSymbolBodyTool",
    "ReplaceSymbolSignatureTool", "DeleteSymbolTool", "InsertSymbolTool",
    "MoveSymbolTool", "ReplaceStatementTool",
    "ReplaceFunctionTool", "ReplaceFunctionBodyTool",
]
