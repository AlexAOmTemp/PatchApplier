"""Indexers: doc index (render + diff), code index."""

from .doc import build_index, BuildResult
from .code import build_code_index, CodeIndexResult
from .lua_code import build_lua_code_index, LuaCodeIndexResult
from .diff import (
    DiffResult, CodeDiffResult,
    diff_index, diff_code_index,
    diff_structures,
    parse_index_text, parse_code_index_text,
)

__all__ = [
    "build_index", "BuildResult",
    "build_code_index", "CodeIndexResult",
    "build_lua_code_index", "LuaCodeIndexResult",
    "DiffResult", "CodeDiffResult",
    "diff_index", "diff_code_index",
    "diff_structures",
    "parse_index_text", "parse_code_index_text",
]
