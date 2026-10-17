"""XML subpackage: address parser, discriminator resolver, expat reader, span writer.

Separate from `formats/` on purpose — XML has its own model (see docs/XML_TOOLSET.md §1).
Address parser and discriminator resolver are dependency-free; reader and writer
need expat + byte spans.
"""
from .address import (
    AddressError,
    DiscriminatorSelector,
    PositionSelector,
    Segment,
    parse_address,
)
from .discriminator import (
    DEFAULT_CHAIN,
    Lookup,
    chain_for,
    extract_value,
    match_value,
    parse_spec,
)
from .writer import (
    WriteError,
    append_child,
    delete_element,
    escape_attr,
    escape_text,
    remove_attr,
    replace_element,
    replace_text,
    set_attr,
)

__all__ = [
    "AddressError",
    "DiscriminatorSelector",
    "PositionSelector",
    "Segment",
    "parse_address",
    "DEFAULT_CHAIN",
    "Lookup",
    "chain_for",
    "extract_value",
    "match_value",
    "parse_spec",
    "WriteError",
    "append_child",
    "delete_element",
    "escape_attr",
    "escape_text",
    "remove_attr",
    "replace_element",
    "replace_text",
    "set_attr",
]
