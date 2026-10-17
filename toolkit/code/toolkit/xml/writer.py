"""Span-based XML writer for the XML toolset.

Strategy: work on ONE element at a time. Take the byte span from the
reader (`el.start:el.end`), decode it into text with `doc.encoding`
(handles UTF-16 cleanly because the decode is per-span), apply the edit
in text space, re-encode with `doc.encoding`, splice back into
`doc.source_bytes`.

Consequences of this approach (all covered by tests):

  - BOM is untouched (it lives in `source_bytes[:root.start]`).
  - CRLF is untouched (inside spans we don't change; new content uses
    `doc.line_ending` explicitly when a line break is needed).
  - Attribute order is preserved (we splice attrs by position, not
    rebuild the open tag).
  - CDATA in other elements is untouched.
  - Order of untouched bytes is a byte-for-byte identity.

For first pass we support:

  - `replace_text(doc, el, new_text)` — replace the leaf text of `el`.
    Preserves `<![CDATA[...]]>` wrapping if the original had it.
    Refuses elements with children (`has_children`).
  - `set_attr(doc, el, name, value)` — set or update an attribute.
    Existing attrs keep position, new ones append before `>`.
  - `remove_attr(doc, el, name)` — drop one attribute.

Not in first pass (Step 3): `append_child`, `insert_sibling`, indentation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .reader import XmlDocument, XmlElement, is_mixed_content, parse


class WriteError(ValueError):
    """Raised when a write operation is refused."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --- escaping --------------------------------------------------------------

_TEXT_ESCAPES = (
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
)

_ATTR_ESCAPES = _TEXT_ESCAPES + (("\"", "&quot;"),)


def escape_text(text: str) -> str:
    for a, b in _TEXT_ESCAPES:
        text = text.replace(a, b)
    return text


def escape_attr(text: str) -> str:
    for a, b in _ATTR_ESCAPES:
        text = text.replace(a, b)
    return text


# --- open-tag parsing -----------------------------------------------------

@dataclass
class _OpenTag:
    """Byte-accurate positions of an open tag inside `el_str`.

    All offsets are character offsets into the decoded `el_str` (NOT bytes,
    and NOT file offsets). The caller maps back to file offsets via el.start.
    """
    text: str              # decoded span el.start:el.end, doc.encoding
    tag_name_end: int      # end of '<TagName'
    gt_pos: int            # '<' of the closing '>' or '/>'
    self_closing: bool
    attrs: list[tuple[str, int, int]]  # (name, name_start, value_start) in text


def _parse_open_tag(el_str: str) -> _OpenTag:
    """Parse the opening tag from the front of a decoded element span.

    Handles: `<a>`, `<a/>`, `<a x="1">`, `<a x='1' y="2">`. CDATA, comments,
    and children are not touched because we stop at the first unquoted `>`.
    """
    if not el_str.startswith("<"):
        raise WriteError("bad_span", f"element span does not start with '<': {el_str[:20]!r}")
    n = len(el_str)
    i = 1
    while i < n and not el_str[i].isspace() and el_str[i] not in "/>":
        i += 1
    tag_name_end = i

    attrs: list[tuple[str, int, int]] = []
    while i < n:
        # skip whitespace
        while i < n and el_str[i].isspace():
            i += 1
        if i >= n:
            raise WriteError("bad_span", "unexpected end in open tag")
        if el_str[i] == ">":
            return _OpenTag(el_str, tag_name_end, i, False, attrs)
        if el_str.startswith("/>", i):
            return _OpenTag(el_str, tag_name_end, i, True, attrs)
        # attribute name
        name_start = i
        while i < n and el_str[i] not in "= \t\r\n/>":
            i += 1
        name = el_str[name_start:i]
        if not name:
            raise WriteError("bad_span", f"empty attr name at {i} in {el_str[:60]!r}")
        # skip whitespace before '='
        while i < n and el_str[i].isspace():
            i += 1
        if i >= n or el_str[i] != "=":
            raise WriteError("bad_span", f"missing '=' after attr {name!r}")
        i += 1
        while i < n and el_str[i].isspace():
            i += 1
        if i >= n or el_str[i] not in "\"'":
            raise WriteError("bad_span", f"unquoted value for attr {name!r}")
        quote = el_str[i]
        i += 1
        value_start = i
        while i < n and el_str[i] != quote:
            i += 1
        if i >= n:
            raise WriteError("bad_span", f"unclosed quote for attr {name!r}")
        i += 1  # skip closing quote
        attrs.append((name, name_start, value_start))
    raise WriteError("bad_span", "unexpected end in open tag")


# --- splice helpers --------------------------------------------------------

def _splice(doc: XmlDocument, el: XmlElement, new_el_str: str) -> bytes:
    """Replace el.start:el.end with new_el_str encoded as doc.encoding."""
    new_bytes = new_el_str.encode(doc.encoding)
    return doc.source_bytes[:el.start] + new_bytes + doc.source_bytes[el.end:]


def _decode_span(doc: XmlDocument, el: XmlElement) -> str:
    return doc.source_bytes[el.start:el.end].decode(doc.encoding)


def _find_close_tag_start(el_str: str, open_tag: _OpenTag) -> int:
    """Character index of the '<' that starts the closing tag, or -1 for self-closing."""
    if open_tag.self_closing:
        return -1
    # The last '<' that starts '</'.
    idx = el_str.rfind("</")
    if idx < 0:
        raise WriteError("bad_span", "no closing tag found in element span")
    return idx


# --- write ops -------------------------------------------------------------

# --- indentation helpers --------------------------------------------------

def _leading_ws(s: str) -> str:
    """Leading whitespace (spaces/tabs) of `s`."""
    n = 0
    while n < len(s) and s[n] in " \t":
        n += 1
    return s[:n]


def _common_ws_prefix(a: str, b: str) -> str:
    """Longest common prefix of whitespace (spaces/tabs) of two strings."""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i] or a[i] not in " \t":
            return a[:i]
    return a[:n]


def _reindent_fragment(
    fragment: str, child_indent: str, first_line_indent: str | None = None,
) -> str:
    """Strip common leading whitespace from `fragment` lines, then prefix
    each with `child_indent`. Empty lines stay empty (no trailing whitespace).

    `first_line_indent`: if not None, the first non-empty line uses this
    prefix instead of `child_indent`. Used by replace_element, where the
    splice point already supplies the leading indent before the first line.
    """
    lines = fragment.split("\n")
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return child_indent
    common = _leading_ws(non_empty[0])
    for ln in non_empty[1:]:
        common = _common_ws_prefix(common, _leading_ws(ln))
    n = len(common)
    out: list[str] = []
    seen_non_empty = False
    for ln in lines:
        if not ln.strip():
            out.append("")
            continue
        if not seen_non_empty and first_line_indent is not None:
            out.append(first_line_indent + ln[n:])
        else:
            out.append(child_indent + ln[n:])
        seen_non_empty = True
    return "\n".join(out)


def _line_indent(doc: XmlDocument, el: XmlElement) -> str:
    """Leading whitespace of the line on which `el.start` sits."""
    line_start = doc.source_bytes.rfind(b"\n", 0, el.start) + 1
    try:
        raw = doc.source_bytes[line_start:el.start].decode(doc.encoding)
    except UnicodeDecodeError:
        return ""
    return raw if raw.strip() == "" else ""


def replace_text(doc: XmlDocument, el: XmlElement, new_text: str) -> bytes:
    """Replace `el`'s leaf text with `new_text`. Returns new source bytes.

    Rules:
      - `el` must have no element children (`has_children` error otherwise).
      - If the element was self-closing, it is expanded to a pair:
            `<a/>`   -> `<a>new_text</a>`
      - If the original text was wrapped in `<![CDATA[...]]>`, the wrapper
        is preserved. Otherwise new_text is escaped (&, <, >).
      - Structural whitespace (only spaces/tabs/newlines) in the original
        text is preserved around the replacement? No — the whole text between
        the open and close tag is replaced by `new_text`. If the caller wants
        to preserve surrounding whitespace, they include it in new_text.
    """
    if el.children:
        raise WriteError(
            "has_children",
            f"<{el.tag}> has {len(el.children)} child element(s); "
            f"use xml_replace or xml_modify on a leaf",
        )

    el_str = _decode_span(doc, el)
    open_tag = _parse_open_tag(el_str)

    # Build the new element.
    if open_tag.self_closing:
        # `<a attr="v"/>` -> `<a attr="v">new_text</a>`
        head = el_str[:open_tag.gt_pos]
        tail_tag = f"</{el.tag}>"
        return _splice(doc, el, head + ">" + _wrap_new_text(el_str, new_text) + tail_tag)

    close_start = _find_close_tag_start(el_str, open_tag)
    between = el_str[open_tag.gt_pos + 1:close_start]
    # Detect CDATA wrap. Trusts that reader gave a leaf element (no children),
    # so `between` is text and/or a single CDATA section.
    had_cdata = between.lstrip().startswith("<![CDATA[") and between.rstrip().endswith("]]>")
    if had_cdata:
        wrapped = f"<![CDATA[{new_text}]]>"
    else:
        wrapped = escape_text(new_text)
    head = el_str[:open_tag.gt_pos + 1]
    tail = el_str[close_start:]
    return _splice(doc, el, head + wrapped + tail)


def _wrap_new_text(_el_str: str, new_text: str) -> str:
    """For self-closing expansion: if text contains chars that need CDATA,
    still escape. Caller can't tell us it was CDATA (it wasn't)."""
    return escape_text(new_text)


def apply_renames(text: str, renames: dict[str, str]) -> str:
    """Plain text.replace() for each key, longest first. See apply_renames_report."""
    out, _missed = apply_renames_report(text, renames)
    return out


def apply_renames_report(
    text: str, renames: dict[str, str],
) -> tuple[str, list[str]]:
    """Apply renames longest-first; return (text, keys that matched nothing).

    Order matters: replacing `TM_WoodGolem` before `TM_WoodGolemLS` would
    turn `TM_WoodGolemLS` into `TM_BoneGolemLS` (correct), but if the user
    meant `TM_WoodGolemLS` -> something different, the short key would
    eat the prefix first. Longest-first avoids that cascade.

    Not regex, not word-boundary: the caller is expected to pass exact
    identifiers as they appear in the source. This is deliberate — an
    over-eager `\\bWood\\b` would rename unrelated text in `<description>`.

    Returns missed keys so the caller can warn: a rename key that never
    matched means either the source didn't have it, or a longer key ate
    the occurrence first.
    """
    if not renames:
        return text, []
    items = sorted(renames.items(), key=lambda kv: -len(kv[0]))
    missed: list[str] = []
    for src, dst in items:
        if src not in text:
            missed.append(src)
            continue
        text = text.replace(src, dst)
    return text, missed


def set_annotation(doc: XmlDocument, el: XmlElement, text: str) -> bytes:
    """Insert or replace `<summary>` comment as the first child of `el`.

    Comment format: `<!-- summary: <text> -->`, one line, at the child
    indentation of `el`. If a summary comment already exists as the first
    non-whitespace inside `el`, only its value is replaced.

    Refuses self-closing parent — use xml_append for that case, or
    set_text on a text leaf.
    """
    el_str = _decode_span(doc, el)
    open_tag = _parse_open_tag(el_str)
    if open_tag.self_closing:
        raise WriteError(
            "empty_element",
            f"<{el.tag}> is self-closing; set_annotation needs children context",
        )
    close_start = _find_close_tag_start(el_str, open_tag)
    if close_start < 0:
        raise WriteError("bad_span", "no closing tag found")

    between = el_str[open_tag.gt_pos + 1:close_start]
    eol = doc.line_ending
    parent_indent = _line_indent(doc, el)
    child_indent = (
        _line_indent(doc, el.children[0]) if el.children
        else parent_indent + "  "
    )

    # Look for an existing comment at first non-ws.
    i = 0
    while i < len(between) and between[i] in " \t\r\n":
        i += 1
    if between[i:i + 4] == "<!--":
        end_m = between.find("-->", i)
        if end_m < 0:
            raise WriteError("bad_span", "unclosed comment")
        body = between[i + 4:end_m].strip()
        if body.startswith("summary:"):
            new_comment = f"<!-- summary: {text} -->"
            new_between = between[:i] + new_comment + between[end_m + 3:]
            new_el_str = (
                el_str[:open_tag.gt_pos + 1] + new_between + el_str[close_start:]
            )
            return _splice(doc, el, new_el_str)

    # No existing summary: insert as first child.
    new_comment = f"<!-- summary: {text} -->"
    if not between.strip():
        new_between = eol + child_indent + new_comment + eol + parent_indent
    else:
        content_start = 0
        while content_start < len(between) and between[content_start] in " \t\r\n":
            content_start += 1
        rest = between[content_start:]
        new_between = (
            eol + child_indent + new_comment + eol + child_indent + rest
        )

    new_el_str = el_str[:open_tag.gt_pos + 1] + new_between + el_str[close_start:]
    return _splice(doc, el, new_el_str)


def delete_element(doc: XmlDocument, el: XmlElement) -> bytes:
    """Delete `el` and its surrounding line (if the element is the only
    non-whitespace on that line). Otherwise, delete only the element span
    and collapse any trailing blank line that would be left.

    Invariants checked by caller: element must not be the document root
    (the caller uses xml_replace for that case, or refuses).
    """
    start = el.start
    end = el.end

    # If the line containing start is whitespace-only before start, and
    # whitespace-only after end (up to the next newline), delete the whole
    # line including the newline. This is the common case for pretty-printed
    # files: `<a/>\n` on its own line.
    line_start = doc.source_bytes.rfind(b"\n", 0, start) + 1
    line_end = doc.source_bytes.find(b"\n", end)
    if line_end < 0:
        line_end = len(doc.source_bytes)
    else:
        line_end += 1  # include the newline
    before = doc.source_bytes[line_start:start]
    after = doc.source_bytes[end:line_end]
    if before.strip() == b"" and after.strip() in (b"", b"\r"):
        return doc.source_bytes[:line_start] + doc.source_bytes[line_end:]

    # Fallback: delete just the span, plus one adjacent whitespace rune
    # on either side if present, to avoid `>\n\n<` artifacts.
    return doc.source_bytes[:start] + doc.source_bytes[end:]


def replace_element(
    doc: XmlDocument, el: XmlElement, fragment: str,
) -> bytes:
    """Replace `el` with `fragment`. Fragment is reindented to el's line.

    Fragment must be one well-formed element. Structural whitespace of the
    original (indent before `<` on its own line) is preserved by using the
    same rules as append_child.
    """
    try:
        parse(fragment.encode("utf-8"))
    except Exception as e:
        raise WriteError("bad_fragment", f"fragment is not well-formed XML: {e}")

    # Reindent fragment to match el's line-indent. First line keeps no
    # additional prefix — the splice point already has the old element's
    # leading indent before `el.start`.
    el_indent = _line_indent(doc, el)
    reindented = _reindent_fragment(fragment, el_indent, first_line_indent="")

    # Splice in the reindented fragment bytes (encoding doc.encoding).
    new_bytes = reindented.encode(doc.encoding)
    return doc.source_bytes[:el.start] + new_bytes + doc.source_bytes[el.end:]


def insert_sibling(
    doc: XmlDocument, parent_el: XmlElement, target: XmlElement,
    fragment: str, position: str,
) -> bytes:
    """Insert `fragment` as a sibling of `target` (before or after).

    `parent_el` must be the direct parent of `target`. Reindent: each line
    of the fragment gets `target`'s line-indent (via the same helper as
    append_child). Position 'before' inserts at target.start with target's
    indent; 'after' inserts at target.end with a preceding EOL.

    Mixed content of parent_el must already be ruled out by the caller.
    """
    try:
        parse(fragment.encode("utf-8"))
    except Exception as e:
        raise WriteError("bad_fragment", f"fragment is not well-formed XML: {e}")

    indent = _line_indent(doc, target)
    reindented = _reindent_fragment(fragment, indent, first_line_indent="")
    eol = doc.line_ending

    if position == "before":
        # Splice at the start of target's line, prefixed with target's indent.
        ins = (indent + reindented + eol).encode(doc.encoding)
        return doc.source_bytes[:target.start] + ins + doc.source_bytes[target.start:]

    # position == "after": insert after target.end, prefixed with eol + indent.
    ins = (eol + indent + reindented).encode(doc.encoding)
    return doc.source_bytes[:target.end] + ins + doc.source_bytes[target.end:]


def append_child(doc: XmlDocument, parent_el: XmlElement, fragment: str) -> bytes:
    """Append `fragment` (one well-formed element) as the last child of
    `parent_el`. Reindents to match existing children. Refuses mixed content.

    Layout rules:
      - Parent already has children: insert `eol + child_indent + frag` right
        after the last non-whitespace char of the between-content; the existing
        trailing whitespace (which prefixes the close tag) is preserved.
      - Parent between-content is whitespace-only / empty: rebuild it as
        `eol + child_indent + frag + eol + parent_indent`.
      - Self-closing parent `<a/>`: expand to `<a>...child...</a>`.

    CDATA / comments in the fragment survive: we only shift leading whitespace
    per line by a common prefix, never touching content bytes.
    """
    # Validate the fragment.
    try:
        parse(fragment.encode("utf-8"))
    except Exception as e:
        raise WriteError("bad_fragment", f"fragment is not well-formed XML: {e}")

    # Mixed-content guard.
    if parent_el.children and is_mixed_content(parent_el):
        raise WriteError(
            "mixed_content_unsupported",
            f"<{parent_el.tag}> has mixed content; appending is unsafe",
        )
    elif parent_el.text and parent_el.text.strip():
        raise WriteError(
            "mixed_content_unsupported",
            f"<{parent_el.tag}> is a text leaf; append would create mixed content",
        )

    el_str = _decode_span(doc, parent_el)
    open_tag = _parse_open_tag(el_str)

    # Parent's own line-indent.
    parent_indent = _line_indent(doc, parent_el)

    # Child-indent: mirror the first existing child; else parent_indent + 2 spaces.
    child_indent = ""
    if parent_el.children:
        child_indent = _line_indent(doc, parent_el.children[0])
    if not child_indent:
        child_indent = parent_indent + "  "

    reindented = _reindent_fragment(fragment, child_indent)
    eol = doc.line_ending

    if open_tag.self_closing:
        head = el_str[:open_tag.gt_pos]
        tail_tag = f"</{parent_el.tag}>"
        new_el_str = (
            head + ">" + eol + reindented + eol + parent_indent + tail_tag
        )
        return _splice(doc, parent_el, new_el_str)

    close_start = _find_close_tag_start(el_str, open_tag)
    between = el_str[open_tag.gt_pos + 1:close_start]

    # Find last non-whitespace position in between.
    i = len(between) - 1
    while i >= 0 and between[i] in " \t\r\n":
        i -= 1

    if i < 0:
        # Empty or whitespace-only between: rebuild clean.
        new_between = eol + reindented + eol + parent_indent
    else:
        # Insert after last non-ws, before the existing trailing whitespace.
        new_between = between[:i + 1] + eol + reindented + between[i + 1:]

    new_el_str = (
        el_str[:open_tag.gt_pos + 1] + new_between + el_str[close_start:]
    )
    return _splice(doc, parent_el, new_el_str)


def set_attr(doc: XmlDocument, el: XmlElement, name: str, value: str) -> bytes:
    """Set or update one attribute on `el`.

    - Existing attr: value replaced in place, name position and quote style kept.
    - New attr: appended just before `>` (or `/>`), space-separated. Always `"`.
    - If name has `:` (namespace prefix), it is treated as literal text — no
      normalization (see XML_TOOLSET §13).
    """
    if not name or "=" in name or any(c.isspace() for c in name):
        raise WriteError("bad_attr_name", f"invalid attr name: {name!r}")

    el_str = _decode_span(doc, el)
    open_tag = _parse_open_tag(el_str)

    for attr_name, name_start, value_start in open_tag.attrs:
        if attr_name != name:
            continue
        # Find the closing quote to bound the value.
        quote = el_str[value_start - 1]  # the char before value_start
        value_end = el_str.find(quote, value_start)
        if value_end < 0:
            raise WriteError("bad_span", f"unclosed quote for attr {name!r}")
        new_val = escape_attr(value)
        new_el_str = (
            el_str[:value_start] + new_val + el_str[value_end:]
        )
        return _splice(doc, el, new_el_str)

    # New attribute. Insert before `>`.
    new_attr = f' {name}="{escape_attr(value)}"'
    pos = open_tag.gt_pos
    new_el_str = el_str[:pos] + new_attr + el_str[pos:]
    return _splice(doc, el, new_el_str)


def remove_attr(doc: XmlDocument, el: XmlElement, name: str) -> bytes:
    """Remove one attribute from `el`. Idempotent-friendly: missing attr -> `attr_not_found`."""
    el_str = _decode_span(doc, el)
    open_tag = _parse_open_tag(el_str)

    for i, (attr_name, name_start, value_start) in enumerate(open_tag.attrs):
        if attr_name != name:
            continue
        quote = el_str[value_start - 1]
        value_end = el_str.find(quote, value_start)
        if value_end < 0:
            raise WriteError("bad_span", f"unclosed quote for attr {name!r}")
        # Find the start of the whitespace immediately preceding the attr name.
        pre = name_start
        while pre > 0 and el_str[pre - 1].isspace():
            pre -= 1
        post = value_end + 1
        new_el_str = el_str[:pre] + el_str[post:]
        return _splice(doc, el, new_el_str)

    raise WriteError("attr_not_found", f"no attr {name!r} on <{el.tag}>")
