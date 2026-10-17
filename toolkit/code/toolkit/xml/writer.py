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

from .reader import XmlDocument, XmlElement


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
