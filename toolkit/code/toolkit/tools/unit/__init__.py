"""Unit tools — cross-format read + write via the unified node model.

See `toolkit/docs/DECISIONS.md` §2.1 and `manual/unit_proto/MODEL.md`
for the model.

`ReplaceBlockTool` / `DeleteBlockTool` / `SetAnnotationTool` (defined in
`tool.py`) are folded into `replace_unit(...)` and removed from TOOL_MAP.
Definitions stay in `tool.py` for reference.

Annotation setting is `replace_unit(part="annotation")` — `writer.set_annotation`
is the underlying implementation and applies the per-format wrapper.
"""
from .tool import (
    ReadUnitTool, ListUnitsTool,
    ReplaceUnitTool, InsertBlockTool,
)

__all__ = [
    "ReadUnitTool", "ListUnitsTool",
    "ReplaceUnitTool", "InsertBlockTool",
]
