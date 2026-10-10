"""Python adapter — build a Unit tree from source + AST.

Uses `ast` directly (not `formats/code.py`) because the model needs
information the Symbol dataclass does not carry: precise line bounds for
head (before the first body statement), annotation (docstring), and
blocks (top-level statements in the body).
"""
from __future__ import annotations

import ast

from .model import Block, Part, Unit, UnitKind


def build(source: str, path: str = "") -> Unit:
    tree = ast.parse(source)
    return _build_module(tree, source, path)


def _is_def(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))


def _stmt_start(stmt: ast.stmt) -> int:
    """Start line of a statement, including decorators for def/class."""
    if _is_def(stmt) and stmt.decorator_list:
        return stmt.decorator_list[0].lineno
    return stmt.lineno


def _docstring_part(node: ast.AST, kind: str) -> Part:
    body = getattr(node, "body", None)
    if not body:
        return Part()
    first = body[0]
    if not isinstance(first, ast.Expr):
        return Part()
    val = first.value
    if not (isinstance(val, ast.Constant) and isinstance(val.value, str)):
        return Part()
    return Part(first.lineno, first.end_lineno or first.lineno)


def _build_module(tree: ast.Module, source: str, path: str) -> Unit:
    n = len(source.splitlines())
    if n == 0:
        return Unit(UnitKind.MODULE, "<module>", "<module>", 1, 1)

    ann = _docstring_part(tree, "module")
    first_def = next((s for s in tree.body if _is_def(s)), None)
    if first_def is None:
        head_end = n
        body_part = Part()
        body_first_line = None
    else:
        # Decorators belong to the def/class; use _stmt_start so head does
        # not swallow the decorator line and blocks do not start above body.
        body_first_line = _stmt_start(first_def)
        head_end = body_first_line - 1
        body_part = Part(body_first_line, n)

    head_start = 1
    if ann.is_present() and ann.start == 1:
        head_start = ann.end + 1
    head = Part(head_start, head_end) if head_end >= head_start else Part()

    blocks: list[Block] = []
    idx = 1
    for stmt in tree.body:
        if body_first_line is None or _stmt_start(stmt) < body_first_line:
            continue
        if ann.is_present() and stmt.lineno == ann.start:
            continue
        b_start = _stmt_start(stmt)
        b_end = stmt.end_lineno or b_start
        child = None
        if _is_def(stmt):
            child = _build_unit(stmt, parent_qn="<module>", parent_is_class=False)
        blocks.append(Block(index=idx, start=b_start, end=b_end, unit=child))
        idx += 1

    return Unit(
        kind=UnitKind.MODULE, name="<module>", qualname="<module>",
        line_start=1, line_end=n,
        head=head, annotation=ann, body=body_part, blocks=blocks,
    )


def _build_unit(node: ast.AST, parent_qn: str, parent_is_class: bool) -> Unit:
    if isinstance(node, ast.ClassDef):
        kind = UnitKind.CLASS
    elif parent_is_class:
        kind = UnitKind.METHOD
    else:
        kind = UnitKind.FUNCTION

    name = node.name
    qn = name if parent_qn == "<module>" else f"{parent_qn}.{name}"
    start = _stmt_start(node)
    end = node.end_lineno or node.lineno

    if not node.body:
        return Unit(kind, name, qn, start, end,
                    head=Part(start, end), annotation=Part(), body=Part())

    # _stmt_start, not .lineno: a decorated first body item has decorators
    # on earlier lines. Using .lineno would put head_end on the decorator
    # line — same line the first block starts on.
    body_first_line = _stmt_start(node.body[0])
    head_end = body_first_line - 1
    ann = _docstring_part(node, kind.value)
    body_start = (ann.end + 1) if ann.is_present() else (head_end + 1)
    body_part = Part(body_start, end) if end >= body_start else Part()

    blocks: list[Block] = []
    idx = 1
    for i, stmt in enumerate(node.body):
        if ann.is_present() and i == 0:
            continue
        b_start = _stmt_start(stmt)
        b_end = stmt.end_lineno or b_start
        child = None
        if _is_def(stmt):
            child = _build_unit(stmt, parent_qn=qn,
                                parent_is_class=(kind == UnitKind.CLASS))
        blocks.append(Block(index=idx, start=b_start, end=b_end, unit=child))
        idx += 1

    return Unit(
        kind=kind, name=name, qualname=qn,
        line_start=start, line_end=end,
        head=Part(start, head_end) if head_end >= start else Part(),
        annotation=ann, body=body_part, blocks=blocks,
    )
