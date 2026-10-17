"""C# adapter — build a Unit tree from source via tree-sitter-c-sharp.

Grammar is tree-sitter-c-sharp (derived from Roslyn); syntax only —
no semantic model, no overload resolution, no type info.

Model mapping:
    compilation_unit                   -> <module>
    namespace_declaration              -> transparent (qualname prefix)
    file_scoped_namespace_declaration  -> prefix for following siblings
    class/struct/interface/enum/record -> CLASS unit (nesting allowed)
    method/constructor/property/field  -> METHOD unit (leaf or with blocks)

Annotation: a run of `///` line comments, or a `/** ... */` block
comment, immediately above a declaration (no blank line in between).
`//` and `/* */` are plain comments, not annotation.

Known limitation (shared with the Python adapter): a single-line
declaration like `public enum Color { Red }` yields head = empty and
body = the whole line. Editing `part="body"` on such a unit replaces
the whole line — read before you write.
"""
from __future__ import annotations

from .model import Block, Part, Unit, UnitKind


_TYPE_DECLS = {
    "class_declaration": UnitKind.CLASS,
    "struct_declaration": UnitKind.CLASS,
    "interface_declaration": UnitKind.CLASS,
    "enum_declaration": UnitKind.CLASS,
    "record_declaration": UnitKind.CLASS,
}

_MEMBER_DECLS = frozenset({
    "method_declaration",
    "constructor_declaration",
    "destructor_declaration",
    "operator_declaration",
    "conversion_operator_declaration",
    "property_declaration",
    "indexer_declaration",
    "event_declaration",
    "event_field_declaration",
    "delegate_declaration",
    "field_declaration",
})

_BODY_CHILD_TYPES = (
    "declaration_list",
    "block",
    "arrow_expression_clause",
    "accessor_list",
    "enum_member_declaration_list",
)


_LANG = None
_PARSER = None


def _parser():
    global _LANG, _PARSER
    if _PARSER is None:
        from tree_sitter import Language, Parser
        import tree_sitter_c_sharp as _tscs
        _LANG = Language(_tscs.language())
        _PARSER = Parser(_LANG)
    return _PARSER


def parse_tree(source: str):
    """Parse and return the raw tree-sitter tree (for syntax checks)."""
    return _parser().parse(source.encode("utf-8"))


def has_qualname(root: Unit, qualname: str) -> bool:
    stack = [root]
    while stack:
        u = stack.pop()
        if u.qualname == qualname:
            return True
        for b in u.blocks:
            if b.unit is not None:
                stack.append(b.unit)
    return False


def build(source: str, path: str = "") -> Unit:
    tree = parse_tree(source)
    lines = source.splitlines()
    n = len(lines) or 1
    return _build_module(tree.root_node, lines, n)


# --- module ---------------------------------------------------------------


def _build_module(root, lines, n: int) -> Unit:
    items = _flatten_top(root)
    ann = _module_annotation(root)

    blocks = []
    for i, (node, prefix, docs) in enumerate(items, start=1):
        u = _build_decl(node, prefix, docs)
        if u is not None:
            blocks.append(Block(index=i, start=u.line_start,
                                end=u.line_end, unit=u))

    if items:
        first_line = items[0][0].start_point.row + 1
    else:
        first_line = None

    if first_line is None:
        head = Part(1, n) if n >= 1 else Part()
        body = Part()
    else:
        head_end = first_line - 1
        head = Part(1, head_end) if head_end >= 1 else Part()
        body = Part(first_line, n)

    return Unit(
        kind=UnitKind.MODULE, name="<module>", qualname="<module>",
        line_start=1, line_end=n,
        head=head, annotation=ann, body=body, blocks=blocks,
    )


def _flatten_top(container, prefix: str = "", out=None):
    if out is None:
        out = []
    pending: list = []
    for ch in container.children:
        if ch.type == "comment":
            pending = _extend_doc_run(pending, ch)
            continue
        if ch.type == "namespace_declaration":
            ns = _namespace_name(ch)
            body = _child(ch, "declaration_list")
            if body is not None and ns:
                _flatten_top(body, prefix + ns + ".", out)
            pending = []
            continue
        if ch.type == "file_scoped_namespace_declaration":
            ns = _namespace_name(ch)
            if ns:
                prefix = prefix + ns + "."
            pending = []
            continue
        if _is_decl(ch):
            out.append((ch, prefix, pending[:]))
        pending = []
    return out


def _namespace_name(node) -> str:
    for ch in node.children:
        if ch.type in ("qualified_name", "identifier"):
            return _text(ch)
    return ""


# --- declarations ---------------------------------------------------------


def _build_decl(node, prefix: str, docs: list):
    name = _decl_name(node)
    if not name:
        return None
    qn = (prefix + name) if prefix else name
    is_type = node.type in _TYPE_DECLS
    kind = UnitKind.CLASS if is_type else UnitKind.METHOD

    ann = _part_from_docs(docs)
    head, body = _split_bounds(node)

    if is_type:
        blocks = _build_members(_child(node, "declaration_list"), qn)
    else:
        blk = _child(node, "block")
        if blk is not None:
            blocks = _build_statements(blk)
        else:
            acc = _child(node, "accessor_list")
            blocks = _build_accessors(acc) if acc is not None else []

    return Unit(
        kind=kind, name=name, qualname=qn, title=_decl_title(node, name),
        line_start=node.start_point.row + 1,
        line_end=node.end_point.row + 1,
        head=head, annotation=ann, body=body, blocks=blocks,
    )


def _decl_name(node):
    for ch in node.children:
        if ch.type == "identifier":
            return _text(ch)
    vd = _child(node, "variable_declaration")
    if vd is not None:
        vdec = _child(vd, "variable_declarator")
        if vdec is not None:
            for ch in vdec.children:
                if ch.type == "identifier":
                    return _text(ch)
    return None


def _decl_title(node, name: str) -> str:
    eis = _child(node, "explicit_interface_specifier")
    pl = _child(node, "parameter_list")
    pl_text = _text(pl) if pl is not None else ""
    if eis is not None:
        return _text(eis) + name + pl_text
    return pl_text


def _split_bounds(node):
    start_line = node.start_point.row + 1
    end_line = node.end_point.row + 1
    body_node = None
    for ch in node.children:
        if ch.type in _BODY_CHILD_TYPES:
            body_node = ch
            break
    if body_node is None:
        return Part(start_line, end_line), Part()
    body_start = body_node.start_point.row + 1
    body_end = body_node.end_point.row + 1
    head_end = body_start - 1
    head = Part(start_line, head_end) if head_end >= start_line else Part()
    return head, Part(body_start, body_end)


def _build_members(dl, parent_qn: str):
    if dl is None:
        return []
    blocks = []
    pending: list = []
    idx = 1
    for ch in dl.children:
        if ch.type == "comment":
            pending = _extend_doc_run(pending, ch)
            continue
        if _is_decl(ch):
            u = _build_decl(ch, parent_qn + ".", pending[:])
            if u is not None:
                blocks.append(Block(index=idx, start=u.line_start,
                                    end=u.line_end, unit=u))
                idx += 1
        pending = []
    return blocks


def _build_statements(blk):
    blocks = []
    idx = 1
    for ch in blk.children:
        if not ch.is_named or ch.type == "comment":
            continue
        blocks.append(Block(index=idx,
                            start=ch.start_point.row + 1,
                            end=ch.end_point.row + 1))
        idx += 1
    return blocks


def _build_accessors(acc):
    blocks = []
    idx = 1
    for ch in acc.children:
        if ch.type == "accessor_declaration":
            blocks.append(Block(index=idx,
                                start=ch.start_point.row + 1,
                                end=ch.end_point.row + 1))
            idx += 1
    return blocks


# --- annotations ----------------------------------------------------------


def _extend_doc_run(pending: list, ch):
    text = _text(ch)
    if not (text.startswith("///") or text.startswith("/**")):
        return []
    if pending and ch.start_point.row != pending[-1].end_point.row + 1:
        return [ch]
    return pending + [ch]


def _part_from_docs(docs) -> Part:
    if not docs:
        return Part()
    return Part(docs[0].start_point.row + 1, docs[-1].end_point.row + 1)


def _module_annotation(root) -> Part:
    pending: list = []
    for ch in root.children:
        if ch.type == "comment":
            new = _extend_doc_run(pending, ch)
            if not new:
                return _part_from_docs(pending)
            pending = new
            continue
        break
    return _part_from_docs(pending)


# --- helpers --------------------------------------------------------------


def _is_decl(node) -> bool:
    return node.type in _TYPE_DECLS or node.type in _MEMBER_DECLS


def _child(node, typ):
    for ch in node.children:
        if ch.type == typ:
            return ch
    return None


def _text(node) -> str:
    return node.text.decode("utf-8", "replace")

def extract_usings(source: str) -> list[str]:
    """All `using` / `using static` / alias directives, as written."""
    tree = parse_tree(source)
    out: list[str] = []
    for ch in tree.root_node.children:
        if ch.type == "using_directive":
            out.append(_text(ch))
    return out
