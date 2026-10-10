"""Unit model — dataclasses.

See MODEL.md for the specification. Pure data; adapters build these from
the existing parsers, and reader.py resolves addresses against them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class UnitKind(str, Enum):
    MODULE = "module"
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    SECTION = "section"


@dataclass
class Part:
    """One of the three named parts of a unit, with line bounds
    (1-based, inclusive). `None` means the part is absent (e.g. no
    annotation).
    """
    start: int | None = None
    end: int | None = None

    def is_present(self) -> bool:
        return self.start is not None and self.end is not None


@dataclass
class Block:
    """A numbered element inside a parent unit's body.

    Blocks are the *only* representation of children in this model — there
    is no separate `children` list. When a block is itself a unit (a
    method inside a class, a subsection inside a section), `unit` points
    to it; otherwise the block is plain text bounded by `start` and `end`.
    """
    index: int                       # 1-based, top-to-bottom in parent body
    start: int                       # 1-based, inclusive
    end: int                         # 1-based, inclusive
    unit: "Unit | None" = None       # set when the block is a child unit
    # Nested blocks — theoretically possible, rarely needed. Kept off the
    # hot path; adapters leave this empty for now.
    blocks: list["Block"] = field(default_factory=list)


@dataclass
class Unit:
    """A single addressable entity: module, function, method, class,
    section. Lines are 1-based inclusive.
    """
    kind: UnitKind
    name: str                        # last component ("apply", "3.1")
    qualname: str                    # full address ("Foo.bar", "<module>", "3.1")
    line_start: int                  # first line of the unit (incl. decorators / heading)
    line_end: int                    # last line of the unit
    head: Part = field(default_factory=Part)
    annotation: Part = field(default_factory=Part)
    body: Part = field(default_factory=Part)
    blocks: list[Block] = field(default_factory=list)
    # Set by the adapter when several units share the same address; the
    # first (top-most) has occurrence=1, the next 2, etc.
    occurrence: int = 1

    def full_range(self) -> tuple[int, int]:
        return self.line_start, self.line_end

    def children(self) -> list["Unit"]:
        """Convenience: the units among this unit's blocks, top to bottom.

        This is a derived view, not stored state. Blocks are the source of
        truth; a method in a class is a block with `unit` set.
        """
        return [b.unit for b in self.blocks if b.unit is not None]
