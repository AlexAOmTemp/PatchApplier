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

import bisect
import threading

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


_TLS = threading.local()


class _Point:
    __slots__ = ("row", "column")

    def __init__(self, row, column=0):
        self.row = row
        self.column = column


class _Snap:
    """Pure-Python snapshot of one tree-sitter node.

    Holding tree-sitter Node objects across a recursive walk is unsafe:
    on large files some Node references become dangling and the next
    attribute read raises an access violation (0xC0000005). Taking a full
    snapshot right after parse() makes the rest of the adapter independent
    of tree-sitter lifetimes.

    The node's source text is NOT copied — only byte offsets are kept.
    On RimWorld (3551 files, 13k nodes each) materializing text for every
    node tripled the index time. Callers that need text go through
    ``_text(node)``, which slices the source bytes by offset.
    """
    __slots__ = ("type", "start_byte", "end_byte", "_sp_row", "_ep_row",
                 "is_named", "children", "_src")

    def __init__(self, type_, start_byte, end_byte, sp_row, ep_row,
                 is_named, src):
        self.type = type_
        self.start_byte = start_byte
        self.end_byte = end_byte
        self._sp_row = sp_row
        self._ep_row = ep_row
        self.is_named = is_named
        self._src = src
        self.children: list["_Snap"] = []

    @property
    def text(self):
        return self._src[self.start_byte:self.end_byte].decode(
            "utf-8", "replace")

    @property
    def start_point(self):
        return _Point(self._sp_row)

    @property
    def end_point(self):
        return _Point(self._ep_row)


def _snapshot(ts_root, src: bytes) -> _Snap:
    """Iterative snapshot — no recursion, no Point access.

    Recursion on deep trees overflows the C stack. Reading
    start_point / end_point off tree-sitter Nodes segfaults on some
    Windows builds (0xC0000005). Both are avoided: iteration for
    structure, bisect over a line-start index for row numbers.
    """
    line_starts = [0]
    for i, b in enumerate(src):
        if b == 0x0A:
            line_starts.append(i + 1)

    def make_snap(ts_node):
        start, end = ts_node.start_byte, ts_node.end_byte
        sp_row = bisect.bisect_right(line_starts, start) - 1
        ep_row = bisect.bisect_right(line_starts, end) - 1
        return _Snap(ts_node.type, start, end, sp_row, ep_row,
                     ts_node.is_named, src)

    root_snap = make_snap(ts_root)
    stack = [(ts_root, root_snap)]
    while stack:
        ts_node, snap = stack.pop()
        for ch in ts_node.children:
            csnap = make_snap(ch)
            snap.children.append(csnap)
            stack.append((ch, csnap))
    return root_snap


def _parser():
    """One Parser per thread — tree-sitter Parser is not thread-safe.

    The Language object is stored on the same thread-local and kept alive
    for the lifetime of the thread. A temporary Language(...) can be
    garbage-collected while the Parser still refers to its grammar
    tables, which crashes on the next node access (0xC0000005).
    """
    p = getattr(_TLS, "parser", None)
    if p is None:
        from tree_sitter import Language, Parser
        import tree_sitter_c_sharp as _tscs
        _TLS.lang = Language(_tscs.language())   # keep alive
        p = Parser(_TLS.lang)
        _TLS.parser = p
    return p


def parse_tree(source: str):
    """Parse and return the raw tree-sitter tree (for syntax checks).

    The encoded bytes are stored on the thread-local and kept alive for
    the whole build pass. Node.text reads from the original source
    buffer; letting it be garbage-collected is a use-after-free that
    segfaults (Windows: 0xC0000005). ``_text`` slices these bytes by
    ``start_byte``/``end_byte`` instead of going through ``Node.text``.

    Last parsed (source, tree) is cached per thread: indexers call
    parse_tree(text) for the has_error check and then build(text) right
    after, and the second call would otherwise re-parse the same file.
    """
    src = source.encode("utf-8")
    cached_src = getattr(_TLS, "src", None)
    if cached_src == src:
        return _TLS.tree
    _TLS.src = src
    _TLS.tree = _parser().parse(src)
    return _TLS.tree


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
    snap = _snapshot(tree.root_node, _TLS.src)
    lines = source.splitlines()
    n = len(lines) or 1
    return _build_module(snap, lines, n)


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
    if isinstance(node, _Snap):
        return node.text
    src = getattr(_TLS, "src", b"")
    if src:
        return src[node.start_byte:node.end_byte].decode("utf-8", "replace")
    return node.text.decode("utf-8", "replace")

def extract_usings(source: str) -> list[str]:
    """All `using` / `using static` / alias directives, as written."""
    tree = parse_tree(source)
    out: list[str] = []
    for ch in tree.root_node.children:
        if ch.type == "using_directive":
            out.append(_text(ch))
    return out
