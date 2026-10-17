"""Address parser for the XML toolset.

Grammar (docs/XML_TOOLSET.md §3):

    address   := segment ("/" segment)*
    segment   := tagname selector?
    selector  := "[" (index | value) "]"
    index     := ASCII digits only (1-based)
    value     := escaped-string
    tagname   := any char except / [ ]

Escaping inside values: \\[  \\]  \\/  \\\\.

Resolution of the discriminator NAME (which attribute or child element to
compare the value against) is NOT this module's job — that lives in
`discriminator.py` (config + fallback chain). This module only tokenises
the address into segments and selectors.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union


class AddressError(ValueError):
    """Raised on malformed XML address syntax."""


@dataclass(frozen=True)
class PositionSelector:
    """`[N]` where N is all ASCII digits — 1-based positional selector."""
    n: int


@dataclass(frozen=True)
class DiscriminatorSelector:
    """`[value]` — resolved against the segment's discriminator (config or fallback)."""
    value: str


Selector = Union[PositionSelector, DiscriminatorSelector]


@dataclass(frozen=True)
class Segment:
    tag: str
    selector: Selector | None = None


_DIGITS = frozenset("0123456789")
_TAG_STOP = frozenset("/[]")


def _read_char(text: str, i: int) -> tuple[str, int]:
    """Read one logical character at `i`, processing backslash escapes."""
    if i >= len(text):
        raise AddressError(f"unexpected end of address at position {i}")
    c = text[i]
    if c == "\\":
        if i + 1 >= len(text):
            raise AddressError(f"trailing backslash at position {i}")
        return text[i + 1], i + 2
    return c, i + 1


def parse_address(text: str) -> list[Segment]:
    """Parse an XML address into segments.

    Examples:
        "Defs"                                  -> [Segment("Defs")]
        "Defs/ThingDef[Steel]"                  -> [Segment("Defs"), Segment("ThingDef", D("Steel"))]
        "Patch/Operation[3]"                    -> [Segment("Patch"), Segment("Operation", P(3))]
        "tweakdb/record_update[a:b]"            -> value "a:b" (" : " not special)
        "physics/bones/bone[NPC Cape1]"         -> value "NPC Cape1" (space not special)
        "Defs/RoofDef[Weird\\]Name]"            -> value "Weird]Name"
    """
    if not text:
        raise AddressError("empty address")
    segments: list[Segment] = []
    n = len(text)
    i = 0
    while i < n:
        # --- tag name: any char except / [ ] ---
        tag_chars: list[str] = []
        while i < n and text[i] not in _TAG_STOP:
            c, i = _read_char(text, i)
            tag_chars.append(c)
        if not tag_chars:
            raise AddressError(f"empty tag name at position {i} in {text!r}")
        tag = "".join(tag_chars)

        # --- optional selector ---
        selector: Selector | None = None
        if i < n and text[i] == "[":
            i += 1  # consume '['
            sel_chars: list[str] = []
            while i < n and text[i] != "]":
                c, i = _read_char(text, i)
                sel_chars.append(c)
            if i >= n:
                raise AddressError(f"unclosed '[' in {text!r}")
            i += 1  # consume ']'
            sel_raw = "".join(sel_chars)
            if not sel_raw:
                raise AddressError(f"empty selector in {text!r}")
            if all(c in _DIGITS for c in sel_raw):
                pos = int(sel_raw)
                if pos < 1:
                    raise AddressError(
                        f"position selector must be >= 1, got {pos} in {text!r}"
                    )
                selector = PositionSelector(pos)
            else:
                selector = DiscriminatorSelector(sel_raw)
        segments.append(Segment(tag, selector))

        # --- separator ---
        if i < n:
            if text[i] != "/":
                raise AddressError(
                    f"expected '/' at position {i} in {text!r}, got {text[i]!r}"
                )
            i += 1
            if i >= n:
                raise AddressError(f"trailing '/' in {text!r}")
    return segments
