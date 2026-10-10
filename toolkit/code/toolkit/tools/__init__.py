"""Tools registry. Runners import TOOL_MAP and pass it to Session."""

from .read import (
    ReadFileTool, FileExistsTool, FileStatTool, ListFilesTool, GrepTool,
)
from .write import (
    ReplaceInFileTool, ReplaceRangeTool, ReplaceBetweenTool,
    InsertAtAnchorTool, ReplaceSectionTool, SetSummaryTool,
    VerifySectionTool,
)
from .fileops import (
    CreateFileTool, OverwriteFileTool, DeleteFileTool, MoveFileTool,
    CopyFileTool,
)
from .index import (
    RebuildIndexTool, RebuildCodeIndexTool, RebuildLuaCodeIndexTool,
    GetIndexTool,
)
from .status import GetStatusTool
from .code import (
    ListSymbolsTool, ReadSymbolTool,
    ReplaceSymbolTool, ReplaceSymbolBodyTool,
    ReplaceSymbolSignatureTool, DeleteSymbolTool, InsertSymbolTool,
    MoveSymbolTool, ReplaceStatementTool,
)
from .find_symbol import FindSymbolTool
from .symbol_graph import SymbolGraphTool
from .grep_mcp import GrepMcpTool
from .grep_replace_mcp import GrepReplaceMcpTool
from .find_usages import FindUsagesTool
from .copy import CopyUnitTool
from .lua_code import (
    ListSymbolsLuaTool, ReadSymbolLuaTool, ReplaceFunctionLuaTool,
)
from .shell import RunPythonTool
from .unit import (
    ReadUnitTool, ListUnitsTool, SetAnnotationTool,
    ReplaceUnitTool, ReplaceBlockTool, DeleteBlockTool, InsertBlockTool,
)


TOOL_MAP: dict[str, type] = {
    "read_file": ReadFileTool,
    "file_exists": FileExistsTool,
    "file_stat": FileStatTool,
    "list_files": ListFilesTool,
    "grep": GrepTool,
    "grep_mcp": GrepMcpTool,
    "grep_replace_mcp": GrepReplaceMcpTool,
    # Legacy alias — old name kept for pre-rename patches.
    "grep_lua": GrepMcpTool,
    "replace_in_file": ReplaceInFileTool,
    "replace_range": ReplaceRangeTool,
    "replace_between": ReplaceBetweenTool,
    "insert_at_anchor": InsertAtAnchorTool,
    "replace_section": ReplaceSectionTool,
    "set_summary": SetSummaryTool,
    "verify_section": VerifySectionTool,
    "create_file": CreateFileTool,
    "overwrite_file": OverwriteFileTool,
    "delete_file": DeleteFileTool,
    "move_file": MoveFileTool,
    "copy_file": CopyFileTool,
    "copy_unit": CopyUnitTool,
    "rebuild_index": RebuildIndexTool,
    "rebuild_code_index": RebuildCodeIndexTool,
    "rebuild_lua_code_index": RebuildLuaCodeIndexTool,
    "get_index": GetIndexTool,
    "get_status": GetStatusTool,
    "list_symbols": ListSymbolsTool,
    "read_symbol": ReadSymbolTool,
    "replace_symbol": ReplaceSymbolTool,
    "replace_symbol_body": ReplaceSymbolBodyTool,
    "replace_symbol_signature": ReplaceSymbolSignatureTool,
    "replace_statement": ReplaceStatementTool,
    "delete_symbol": DeleteSymbolTool,
    "insert_symbol": InsertSymbolTool,
    "move_symbol": MoveSymbolTool,
    # Backwards-compatible aliases (pre-rename patches).
    "replace_function": ReplaceSymbolTool,
    "replace_function_body": ReplaceSymbolBodyTool,
    "find_symbol": FindSymbolTool,
    "find_usages": FindUsagesTool,
    "symbol_graph": SymbolGraphTool,
    "list_symbols_lua": ListSymbolsLuaTool,
    "read_symbol_lua": ReadSymbolLuaTool,
    "replace_function_lua": ReplaceFunctionLuaTool,
    "run_python": RunPythonTool,
    # Unit model — cross-format read (DECISIONS §2.1).
    "read_unit": ReadUnitTool,
    "list_units": ListUnitsTool,
    "set_annotation": SetAnnotationTool,
    "replace_unit": ReplaceUnitTool,
    "replace_block": ReplaceBlockTool,
    "delete_block": DeleteBlockTool,
    "insert_block": InsertBlockTool,
}

__all__ = [
    "TOOL_MAP",
    "ReadFileTool", "FileExistsTool", "FileStatTool", "ListFilesTool", "GrepTool",
    "ReplaceInFileTool", "ReplaceRangeTool", "ReplaceBetweenTool",
    "InsertAtAnchorTool", "ReplaceSectionTool", "SetSummaryTool",
    "VerifySectionTool",
    "CreateFileTool", "OverwriteFileTool", "DeleteFileTool", "MoveFileTool",
    "CopyFileTool",
    "RebuildIndexTool", "RebuildCodeIndexTool", "RebuildLuaCodeIndexTool",
    "GetIndexTool", "GetStatusTool",
    "ListSymbolsTool", "ReadSymbolTool",
    "ReplaceSymbolTool", "ReplaceSymbolBodyTool",
    "ReplaceSymbolSignatureTool", "DeleteSymbolTool", "InsertSymbolTool",
    "MoveSymbolTool", "ReplaceStatementTool",
    "FindSymbolTool",
    "FindUsagesTool",
    "SymbolGraphTool",
    "GrepMcpTool",
    "GrepReplaceMcpTool",
    "CopyUnitTool",
    "ListSymbolsLuaTool", "ReadSymbolLuaTool", "ReplaceFunctionLuaTool",
    "RunPythonTool",
    "ReadUnitTool", "ListUnitsTool", "SetAnnotationTool",
    "ReplaceUnitTool", "ReplaceBlockTool", "DeleteBlockTool", "InsertBlockTool",
]
