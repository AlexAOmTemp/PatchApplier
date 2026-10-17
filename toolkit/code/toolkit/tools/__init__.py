"""Tools registry. Runners import TOOL_MAP and pass it to Session.

Deprecated tools (removed from TOOL_MAP 2026-10-11, see DECISIONS §2.1):

- Symbol tools (list_symbols / read_symbol / replace_symbol* / replace_statement /
  delete_symbol / insert_symbol / move_symbol / replace_function* / list_symbols_lua /
  read_symbol_lua / replace_function_lua) — superseded by the unit model.
- Section tools (replace_section / set_summary / verify_section) — superseded by
  replace_unit / set_annotation.

Class definitions remain in `tools/write.py`, `tools/code.py`, `tools/lua_code.py`,
`tools/symbols/*`, `tools/unit/tool.py`. To reactivate one, add its import and a
TOOL_MAP entry back.

`set_annotation` (removed from TOOL_MAP): use `replace_unit(part="annotation")` to replace, `create_unit(part="annotation")` to create.
"""

from .read import (
    ReadFileTool, FileExistsTool, FileStatTool, ListFilesTool, GrepTool,
    SurveyDirTool,
)
from .tree import TreeTool
from .write import (
    ReplaceInFileTool, ReplaceRangeTool, ReplaceBetweenTool,
    InsertAtAnchorTool,
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
from .find_symbol import FindSymbolTool
from .symbol_graph import SymbolGraphTool
from .grep_mcp import GrepMcpTool
from .grep_replace_mcp import GrepReplaceMcpTool
from .grep_replace import GrepReplaceTool
from .find_usages import FindUsagesTool
from .copy import CopyUnitTool
from .shell import RunPythonTool
from .verify import VerifySyntaxTool
from .unit.tool import (
    ReadUnitTool, ListUnitsTool,
    ReplaceUnitTool, RemoveUnitTool, CreateUnitTool, InsertBlockTool,
)


TOOL_MAP: dict[str, type] = {
    "read_file": ReadFileTool,
    "file_exists": FileExistsTool,
    "file_stat": FileStatTool,
    "list_files": ListFilesTool,
    "survey_dir": SurveyDirTool,
    "tree": TreeTool,
    "grep": GrepTool,
    "grep_mcp": GrepMcpTool,
    "grep_replace": GrepReplaceTool,
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
    "verify_syntax": VerifySyntaxTool,
    "read_unit": ReadUnitTool,
    "list_units": ListUnitsTool,
    "replace_unit": ReplaceUnitTool,
    "remove_unit": RemoveUnitTool,
    "create_unit": CreateUnitTool,
    "insert_block": InsertBlockTool,
}

__all__ = [
    "TOOL_MAP",
    "ReadFileTool", "FileExistsTool", "FileStatTool", "ListFilesTool", "GrepTool",
    "SurveyDirTool", "TreeTool",
    "ReplaceInFileTool", "ReplaceRangeTool", "ReplaceBetweenTool",
    "InsertAtAnchorTool",
    "CreateFileTool", "OverwriteFileTool", "DeleteFileTool", "MoveFileTool",
    "CopyFileTool",
    "RebuildIndexTool", "RebuildCodeIndexTool", "RebuildLuaCodeIndexTool",
    "GetIndexTool", "GetStatusTool",
    "FindSymbolTool",
    "FindUsagesTool",
    "SymbolGraphTool",
    "GrepMcpTool",
    "GrepReplaceMcpTool",
    "GrepReplaceTool",
    "CopyUnitTool",
    "RunPythonTool",
    "VerifySyntaxTool",
    "ReadUnitTool", "ListUnitsTool",
    "ReplaceUnitTool", "RemoveUnitTool", "CreateUnitTool", "InsertBlockTool",
]
