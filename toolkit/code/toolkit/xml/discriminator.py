"""Discriminator resolution for XML address selectors.

`address.py` tokenises `[value]` into a `DiscriminatorSelector` — it does not
know **which** attribute or child element to compare the value against. That
is this module's job.

Resolution chain per segment comes from one of two places, in this order:

  1. `workspace.xml.discriminators` config. Key is a tag name or a path
     suffix (`comps/li`, `modDependencies/li`). Longest suffix wins.
  2. DEFAULT_CHAIN if the config has no entry for the path.

A configured value is:

  - a string            -> [parse_spec(string)]
  - a list of strings   -> [parse_spec(s) for s in list]
  - null / absent       -> DEFAULT_CHAIN (behaves identically to no entry)

`parse_spec` maps a spec to a `Lookup`:

  - `"@Name"`  -> Lookup(kind="attr",  name="Name")
  - `"defName"`-> Lookup(kind="child", name="defName")
  - `""`       -> Lookup(kind="text",  name="")  (own text)

See docs/XML_FIXTURES.md §4 for the default table and docs/XML_TOOLSET.md §4.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal


LookupKind = Literal["child", "attr", "text"]


@dataclass(frozen=True)
class Lookup:
    """How to extract a discriminator value from one element."""
    kind: LookupKind
    name: str  # "" when kind == "text"


# When the config has no entry for this segment, try these in order. The
# last entry (`text`) handles bare `<li>1.4</li>` and `<li>Metallic</li>`.
DEFAULT_CHAIN: tuple[Lookup, ...] = (
    Lookup("child", "defName"),
    Lookup("attr", "Name"),
    Lookup("attr", "name"),
    Lookup("attr", "id"),
    Lookup("attr", "key"),
    Lookup("child", "artifactId"),
    Lookup("text", ""),
)


def parse_spec(spec: str) -> Lookup:
    """Turn one config spec string into a Lookup.

    Empty string is the explicit way to say "own text of the element".
    """
    if not isinstance(spec, str):
        raise TypeError(f"discriminator spec must be str, got {type(spec).__name__}")
    if spec == "":
        return Lookup("text", "")
    if spec.startswith("@"):
        name = spec[1:]
        if not name:
            raise ValueError("empty attribute name after '@'")
        return Lookup("attr", name)
    return Lookup("child", spec)


def _specs_to_chain(spec: Any) -> list[Lookup]:
    """Normalise a config value (str | list | None) into a chain of Lookups."""
    if spec is None:
        return list(DEFAULT_CHAIN)
    if isinstance(spec, str):
        return [parse_spec(spec)]
    if isinstance(spec, (list, tuple)):
        out: list[Lookup] = []
        for s in spec:
            out.append(parse_spec(s))
        if not out:
            return list(DEFAULT_CHAIN)
        return out
    raise TypeError(f"discriminator value must be str | list | None, got {type(spec).__name__}")


def _config_dict(xml_cfg: dict | None) -> dict:
    """Extract `discriminators` from `workspace.xml`. Tolerates shape errors."""
    if not isinstance(xml_cfg, dict):
        return {}
    disc = xml_cfg.get("discriminators")
    return disc if isinstance(disc, dict) else {}


def _suffix_keys(tag_path: Iterable[str]) -> list[str]:
    """From `['A','B','C']`, yield 'A/B/C', 'B/C', 'C'.

    Longest suffix first, tag last. This mirrors XML_TOOLSET §4
    (path.endswith(key) — longest match wins).
    """
    parts = list(tag_path)
    out: list[str] = []
    for i in range(len(parts)):
        out.append("/".join(parts[i:]))
    return out


def chain_for(tag_path: list[str], xml_cfg: dict | None) -> list[Lookup]:
    """Resolve the discriminator chain for the last segment of `tag_path`.

    `tag_path` is the list of tag names leading to this segment, NOT
    including the segment's own selector. e.g. for address
    `ModMetaData/modDependencies/li[brrainz.harmony]`, call with
    `['ModMetaData', 'modDependencies', 'li']`.
    """
    if not tag_path:
        return list(DEFAULT_CHAIN)
    cfg = _config_dict(xml_cfg)
    if cfg:
        for key in _suffix_keys(tag_path):
            if key in cfg:
                return _specs_to_chain(cfg[key])
    return list(DEFAULT_CHAIN)


def extract_value(element: Any, lookup: Lookup) -> str | None:
    """Extract the discriminator value from one expat-derived element.

    `element` is anything with `.tag`, `.attrib`, `.text` (own direct text
    before first child), `.children`. This shape is produced by
    `toolkit.xml.reader`. Plain dicts are also accepted for tests:
    `{"tag": ..., "attrib": {...}, "text": ..., "children": [...]}`.

    Returns None if the spec doesn't match (no such attr, no such child,
    empty text). Never raises on missing data.
    """
    if lookup.kind == "attr":
        attrib = getattr(element, "attrib", None)
        if attrib is None and isinstance(element, dict):
            attrib = element.get("attrib") or {}
        if not attrib:
            return None
        v = attrib.get(lookup.name)
        return v if isinstance(v, str) else None
    if lookup.kind == "child":
        children = getattr(element, "children", None)
        if children is None and isinstance(element, dict):
            children = element.get("children") or []
        for ch in children or ():
            ch_tag = getattr(ch, "tag", None) or (
                ch.get("tag") if isinstance(ch, dict) else None
            )
            if ch_tag != lookup.name:
                continue
            ch_text = getattr(ch, "text", None)
            if ch_text is None and isinstance(ch, dict):
                ch_text = ch.get("text")
            if isinstance(ch_text, str):
                return ch_text
        return None
    # kind == "text"
    text = getattr(element, "text", None)
    if text is None and isinstance(element, dict):
        text = element.get("text")
    return text if isinstance(text, str) else None


def match_value(element: Any, chain: list[Lookup]) -> str | None:
    """First non-None value from `chain`. None if no lookup finds a value."""
    for lookup in chain:
        v = extract_value(element, lookup)
        if v is not None and v != "":
            return v
    return None
