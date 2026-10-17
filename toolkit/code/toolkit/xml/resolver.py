"""Address resolution against an `XmlElement` tree.

Pure function: no I/O, no expat. Takes the tree from `reader.parse` and the
segments from `address.parse_address`, returns the element(s) that match.

Rules (docs/XML_TOOLSET.md §3):

  - First segment matches the **root** element's tag; a mismatch is
    `not_found`.
  - Intermediate segments must be unambiguous: exactly one child matches
    the tag, or a Position/Discriminator selector narrows to one. If two
    or more candidates survive, it's `ambiguous_address`. `occurrence`
    applies only to the **last** segment.
  - Last segment: same rule, but `occurrence=N` (1-based) picks the N-th
    candidate when there are several. Without `occurrence`, several
    candidates raise `ambiguous_address` carrying their line positions.
  - `PositionSelector(N)` is 1-based; out-of-range is `position_out_of_range`.
  - `DiscriminatorSelector(value)` matches against the segment's resolved
    discriminator chain (see `discriminator.py`).

`resolve_all` is the same walk with no uniqueness requirement on the
final segment — the caller (`xml_find`) wants every match.
"""
from __future__ import annotations

from dataclasses import dataclass

from .address import (
    DiscriminatorSelector,
    PositionSelector,
    Segment,
)
from .discriminator import chain_for, match_value
from .reader import XmlDocument, XmlElement


class ResolveError(Exception):
    """Raised when an address cannot be resolved to exactly one element
    (or, for resolve_all, to at least one)."""

    def __init__(self, code: str, message: str,
                 candidates: list[XmlElement] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.candidates = candidates or []


@dataclass
class Resolved:
    """One resolved element plus the tag path that reached it."""
    element: XmlElement
    tag_path: list[str]  # includes the root tag and el's own tag


def _line_of(doc: XmlDocument, el: XmlElement) -> int:
    """1-based line number for an element's start offset."""
    return doc.source_bytes.count(b"\n", 0, el.start) + 1


def _describe(doc: XmlDocument, el: XmlElement) -> str:
    return f"<{el.tag}> L{_line_of(doc, el)}–L{_line_of(doc, XmlElement(tag=el.tag, start=el.end, end=el.end))}"


def _candidates_for(
    doc: XmlDocument,
    parent: XmlElement,
    seg: Segment,
    tag_path: list[str],
    xml_cfg: dict | None,
) -> list[XmlElement]:
    """All children of `parent` matching the segment's tag+selector."""
    by_tag = [ch for ch in parent.children if ch.tag == seg.tag]
    if not by_tag:
        raise ResolveError(
            "not_found",
            f"no <{seg.tag}> child under <{parent.tag}>",
        )
    if seg.selector is None:
        return by_tag
    if isinstance(seg.selector, PositionSelector):
        n = seg.selector.n
        if n < 1 or n > len(by_tag):
            raise ResolveError(
                "position_out_of_range",
                f"<{seg.tag}>[{n}] out of range: only {len(by_tag)} children "
                f"with that tag under <{parent.tag}>",
            )
        return [by_tag[n - 1]]
    # DiscriminatorSelector
    chain = chain_for(tag_path + [seg.tag], xml_cfg)
    want = seg.selector.value
    out: list[XmlElement] = []
    for ch in by_tag:
        got = match_value(ch, chain)
        if got is not None and got == want:
            out.append(ch)
    if not out:
        chain_desc = ', '.join(
            (f'@{l.name}' if l.kind == 'attr' else l.name if l.kind == 'child' else '<text>')
            for l in chain
        )
        raise ResolveError(
            "not_found",
            f"{len(by_tag)} <{seg.tag}> under <{parent.tag}>, none matches "
            f"[{want}] (tried: {chain_desc})",
        )
    return out


def resolve_one(
    doc: XmlDocument,
    segments: list[Segment],
    xml_cfg: dict | None = None,
    occurrence: int | None = None,
) -> Resolved:
    """Resolve to exactly one element. Raises `ResolveError` otherwise."""
    if not segments:
        raise ResolveError("empty_address", "empty address")
    if occurrence is not None and occurrence < 1:
        raise ResolveError(
            "bad_occurrence", f"occurrence must be >= 1, got {occurrence}"
        )

    # First segment: must match root.
    first = segments[0]
    if first.tag != doc.root.tag:
        raise ResolveError(
            "not_found",
            f"root is <{doc.root.tag}>, address starts with <{first.tag}>",
        )

    current = doc.root
    tag_path = [doc.root.tag]
    last_segment_index = len(segments) - 1

    for idx, seg in enumerate(segments[1:], start=1):
        matches = _candidates_for(doc, current, seg, tag_path, xml_cfg)
        is_last = idx == last_segment_index

        if not matches:
            raise ResolveError(
                "not_found",
                f"no <{seg.tag}> child under <{current.tag}> "
                f"(seg #{idx})",
            )

        if is_last:
            if len(matches) == 1 and occurrence is None:
                return Resolved(matches[0], tag_path + [seg.tag])
            if occurrence is not None:
                if occurrence > len(matches):
                    raise ResolveError(
                        "occurrence_out_of_range",
                        f"occurrence={occurrence} but only {len(matches)} "
                        f"candidates for <{seg.tag}>",
                        candidates=matches,
                    )
                return Resolved(matches[occurrence - 1], tag_path + [seg.tag])
            # Multiple matches, no occurrence.
            detail = "; ".join(_describe(doc, m) for m in matches[:8])
            if len(matches) > 8:
                detail += f"; … {len(matches) - 8} more"
            raise ResolveError(
                "ambiguous_address",
                f"<{seg.tag}> matches {len(matches)} candidates: {detail}",
                candidates=matches,
            )

        # Intermediate segment.
        if len(matches) > 1:
            detail = "; ".join(_describe(doc, m) for m in matches[:8])
            if len(matches) > 8:
                detail += f"; … {len(matches) - 8} more"
            raise ResolveError(
                "ambiguous_address",
                f"intermediate <{seg.tag}> matches {len(matches)} candidates "
                f"(add a selector in the address): {detail}",
                candidates=matches,
            )
        current = matches[0]
        tag_path.append(seg.tag)

    # Only one segment: the root itself.
    return Resolved(doc.root, tag_path)


def resolve_all(
    doc: XmlDocument,
    segments: list[Segment],
    xml_cfg: dict | None = None,
) -> list[Resolved]:
    """Resolve to every match of the last segment; no occurrence requirement.

    No unique requirement on the last segment. Intermediate segments still
    require uniqueness. A selector on the last segment still narrows.
    """
    if not segments:
        raise ResolveError("empty_address", "empty address")
    first = segments[0]
    if first.tag != doc.root.tag:
        raise ResolveError(
            "not_found",
            f"root is <{doc.root.tag}>, address starts with <{first.tag}>",
        )
    if len(segments) == 1:
        return [Resolved(doc.root, [doc.root.tag])]

    current = doc.root
    tag_path = [doc.root.tag]
    last_segment_index = len(segments) - 1

    for idx, seg in enumerate(segments[1:], start=1):
        matches = _candidates_for(doc, current, seg, tag_path, xml_cfg)
        if not matches:
            raise ResolveError(
                "not_found",
                f"no <{seg.tag}> child under <{current.tag}> (seg #{idx})",
            )
        is_last = idx == last_segment_index
        if is_last:
            new_tag_path = tag_path + [seg.tag]
            return [Resolved(m, new_tag_path) for m in matches]
        if len(matches) > 1:
            detail = "; ".join(_describe(doc, m) for m in matches[:8])
            raise ResolveError(
                "ambiguous_address",
                f"intermediate <{seg.tag}> matches {len(matches)} candidates "
                f"(add a selector): {detail}",
                candidates=matches,
            )
        current = matches[0]
        tag_path.append(seg.tag)

    return [Resolved(current, tag_path)]
