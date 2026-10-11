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
    "find_symbol": FindSymbolTool,
    "find_usages": FindUsagesTool,
    "symbol_graph": SymbolGraphTool,
    "run_python": RunPythonTool,
    # Unit model — cross-format read/write (DECISIONS §2.1).
    # `replace_block` / `delete_block` removed 2026-10-11 — folded into
    # `replace_unit(block=...)`. See DECISIONS §2.1.
    "read_unit": ReadUnitTool,
    "list_units": ListUnitsTool,
    "set_annotation": SetAnnotationTool,
    "replace_unit": ReplaceUnitTool,
    "insert_block": InsertBlockTool,
}

# Deprecated 2026-10-11 (see DECISIONS §2.1). Removed from the map, files
# remain in the tree for reference: replace_section / set_summary /
# verify_section (superseded by unit model), list_symbols / read_symbol /
# replace_symbol* / replace_statement / delete_symbol / insert_symbol /
# move_symbol / replace_function* (Python symbol tools), list_symbols_lua /
# read_symbol_lua / replace_function_lua (Lua symbol tools).

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
