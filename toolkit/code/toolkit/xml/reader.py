"""Expat-based XML reader for the XML toolset.

Why expat, not ElementTree/lxml: we need **byte offsets** for every element
so writer can edit by span and preserve everything else (BOM, CRLF, CDATA,
attribute order). ElementTree gives positions only as (line, col); lxml is
an external dependency and loses attribute order on write.

Contract (docs/XML_TOOLSET.md §7):

  - `parse(data)` takes raw bytes; detects encoding from BOM or
    `<?xml encoding="..."?>`.
  - Every `XmlElement` carries `start`/`end` byte offsets into the original
    `data`. `data[el.start:el.end]` is exactly the source slice of the
    element, including its open and close tags.
  - Attribute order is preserved (expat's `ordered_attributes`).
  - Text and tail follow ElementTree convention: `text` is the direct text
    before the first child, `tail` is the direct text after the close tag
    (visible to the parent). Mixed content is representable, not hidden.
  - `xml:space="preserve"` and DTD-with-entities are rejected upstream by
    the tools, not here — the reader just reports what it saw.

Safety (§7.8):

  - External entities disabled (`ExternalEntityRefHandler` returns 0).
  - Parameter entities disabled (`XML_PARAM_ENTITY_PARSING_NEVER`).
  - Hard limits on input size, element count, and nesting depth.
  - DTD is allowed; DTD with **entity declarations** is flagged via
    `XmlDocument.has_entities`, tools refuse it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from xml.parsers import expat


# Hard limits — see §7.8. Not user-tunable in v1; raise in code if a real
# project hits them.
MAX_BYTES = 50 * 1024 * 1024
MAX_ELEMENTS = 1_000_000
MAX_DEPTH = 100


class XmlError(ValueError):
    """Base class for all XML errors raised by this module."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class XmlElement:
    """One XML element with its exact byte span in the source.

    `start` is the offset of the `<` that opens the element. `end` is the
    offset just past the `>` that closes it (either of `/>` or `</tag>`).
    For self-closing elements, `end - start` includes the `/` before `>`.
    """
    tag: str
    attrib: dict[str, str] = field(default_factory=dict)
    text: str = ""
    tail: str = ""
    children: list["XmlElement"] = field(default_factory=list)
    start: int = 0
    end: int = 0
    parent: "XmlElement | None" = field(default=None, repr=False, compare=False)


@dataclass
class XmlDocument:
    """Parsed XML document with metadata needed by the writer."""
    root: XmlElement
    encoding: str
    bom: bytes
    line_ending: str          # "\\n" or "\\r\\n" — dominant in the file
    source_bytes: bytes
    has_doctype: bool = False
    has_entities: bool = False  # DTD <!ENTITY ...> seen


# --- encoding --------------------------------------------------------------

_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)


def detect_encoding(data: bytes) -> tuple[str, bytes]:
    """Return (encoding, bom). BOM empty if absent.

    Detection order: BOM first (authoritative per XML spec), then the
    `encoding="..."` attribute of `<?xml ...?>` declaration, then utf-8.
    """
    for bom, enc in _BOMS:
        if data.startswith(bom):
            return enc, bom
    # <?xml version="1.0" encoding="..."?>
    head = data[:200]
    if head.startswith(b"<?xml"):
        end = head.find(b"?>")
        if end > 0:
            decl = head[:end]
            for enc_attr in (b'encoding="', b"encoding='"):
                i = decl.find(enc_attr)
                if i >= 0:
                    i += len(enc_attr)
                    quote = enc_attr[-1:-0] or (b'"' if b'"' in enc_attr else b"'")
                    quote = decl[i - 1:i]
                    j = decl.find(quote, i)
                    if j > i:
                        try:
                            return decl[i:j].decode("ascii").lower(), b""
                        except UnicodeDecodeError:
                            pass
    return "utf-8", b""


def detect_line_ending(data: bytes) -> str:
    """Return the dominant line ending in the first 8 KiB of data."""
    head = data[:8192]
    crlf = head.count(b"\r\n")
    bare_lf = head.count(b"\n") - crlf
    if crlf > bare_lf:
        return "\r\n"
    return "\n"


# --- parse -----------------------------------------------------------------

def parse(data: bytes) -> XmlDocument:
    """Parse XML bytes. Raises `XmlError` on any failure.

    The returned tree carries byte offsets into `data`.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(f"parse expects bytes, got {type(data).__name__}")
    data = bytes(data)
    if len(data) > MAX_BYTES:
        raise XmlError("file_too_large",
                       f"input is {len(data)} bytes, limit is {MAX_BYTES}")

    encoding, bom = detect_encoding(data)

    parser = expat.ParserCreate(encoding=encoding)
    parser.ordered_attributes = True
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.ExternalEntityRefHandler = lambda *a: 0  # reject external

    # Per-parse state.
    state = {
        "root": None,               # XmlElement
        "stack": [],                # list[XmlElement]
        "element_count": 0,
        "has_doctype": False,
        "has_entities": False,
        "error": None,
    }

    def start_element(name: str, attrs: Any) -> None:
        if state["error"] is not None:
            return
        state["element_count"] += 1
        if state["element_count"] > MAX_ELEMENTS:
            state["error"] = XmlError(
                "too_many_elements",
                f"element count exceeds {MAX_ELEMENTS}",
            )
            return
        if len(state["stack"]) >= MAX_DEPTH:
            state["error"] = XmlError(
                "depth_too_deep",
                f"nesting depth exceeds {MAX_DEPTH} at <{name}>",
            )
            return

        # ordered_attributes=True delivers a flat list: [k1, v1, k2, v2, ...]
        attrib: dict[str, str] = {}
        if isinstance(attrs, list):
            for i in range(0, len(attrs), 2):
                attrib[attrs[i]] = attrs[i + 1]
        elif isinstance(attrs, dict):
            attrib = dict(attrs)

        el = XmlElement(tag=name, attrib=attrib, start=parser.CurrentByteIndex)
        if state["stack"]:
            parent = state["stack"][-1]
            el.parent = parent
            parent.children.append(el)
        else:
            state["root"] = el
        state["stack"].append(el)

    def end_element(name: str) -> None:
        if state["error"] is not None:
            return
        el = state["stack"].pop()
        i = parser.CurrentByteIndex
        # Expat reports CurrentByteIndex at the '<' of the close tag for
        # non-self-closing elements, and just past the '/>' for self-closing
        # ones (observed, not documented). We want `end` to point just past
        # the '>' in both cases, so advance for the non-self-closing form.
        if i + 1 < len(data) and data[i:i + 2] == b"</":
            j = data.find(b">", i)
            el.end = j + 1 if j > 0 else i
        else:
            el.end = i

    def char_data(text: str) -> None:
        if state["error"] is not None:
            return
        stack = state["stack"]
        if not stack:
            return  # text outside root — expat already rejects this
        cur = stack[-1]
        if cur.children:
            cur.children[-1].tail += text
        else:
            cur.text += text

    def start_doctype(name: str, sysid: Any, pubid: Any, has_internal: int) -> None:
        state["has_doctype"] = True

    def entity_decl(*_a: Any) -> None:
        state["has_entities"] = True

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = char_data
    parser.StartDoctypeDeclHandler = start_doctype
    parser.EntityDeclHandler = entity_decl
    # CDATA is delivered through CharacterDataHandler too — nothing extra needed.

    try:
        parser.Parse(data, True)
    except expat.ExpatError as e:
        raise XmlError("syntax_error", f"expat: {e}") from None

    if state["error"] is not None:
        raise state["error"]
    if state["root"] is None:
        raise XmlError("syntax_error", "no root element")

    return XmlDocument(
        root=state["root"],
        encoding=encoding,
        bom=bom,
        line_ending=detect_line_ending(data),
        source_bytes=data,
        has_doctype=state["has_doctype"],
        has_entities=state["has_entities"],
    )


# --- tree helpers ----------------------------------------------------------

def iter_elements(el: XmlElement):
    """Pre-order iterator over `el` and all descendants."""
    yield el
    for ch in el.children:
        yield from iter_elements(ch)


def is_mixed_content(el: XmlElement) -> bool:
    """True iff `el` has at least one child AND non-whitespace text
    anywhere between its open and close tags.

    Structural whitespace between children (`\\n  `) does NOT count.
    Text node directly under an element with children, containing any
    non-whitespace char, DOES count. Same for the tail of any child.
    """
    if not el.children:
        return False
    if el.text and el.text.strip():
        return True
    for ch in el.children:
        if ch.tail and ch.tail.strip():
            return True
    return False


def element_source(doc: XmlDocument, el: XmlElement) -> bytes:
    """Exact byte slice of `el` in the original file."""
    return doc.source_bytes[el.start:el.end]
