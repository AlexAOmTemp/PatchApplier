"""Unit model prototype: read-only access to a unified tree of units.

A test bed for the model described in MODEL.md. Not part of the toolkit
runtime; lives in `manual/` until the model is validated.
"""
from .model import Unit, Block, UnitKind
from .reader import read_unit, list_units, dump_tree

__all__ = ["Unit", "Block", "UnitKind", "read_unit", "list_units", "dump_tree"]
