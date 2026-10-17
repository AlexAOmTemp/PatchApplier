"""Tests for toolkit.xml.address — the XML address tokeniser.

Covers:
  - single segment, multi-segment
  - positional selector (ASCII digits only, 1-based)
  - value selector (everything else), preserving : / space
  - escaping: \\[ \\] \\/ \\\\
  - error cases: empty, trailing slash, leading slash, unclosed [, empty [], trailing text, position 0
  - disambiguation: '2' is positional, '1.5' is value, '-1' is value

Run: python toolkit/code/toolkit/tests/test_xml_address.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.xml.address import (
    AddressError,
    DiscriminatorSelector,
    PositionSelector,
    Segment,
    parse_address,
)


PASS = '[OK]  '
FAIL = '[FAIL]'


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def expect(self, label, cond, detail=''):
        if cond:
            print(PASS + ' ' + label)
            self.passed += 1
        else:
            print(FAIL + ' ' + label + (' -- ' + detail if detail else ''))
            self.failed += 1

    def expect_raises(self, label, fn, exc=AddressError):
        try:
            fn()
        except exc as e:
            print(PASS + ' ' + label + f' ({type(e).__name__})')
            self.passed += 1
        except Exception as e:
            print(FAIL + ' ' + label + f' -- wrong exc {type(e).__name__}: {e}')
            self.failed += 1
        else:
            print(FAIL + ' ' + label + ' -- no exception')
            self.failed += 1


t = T()

# --- basic parsing ---------------------------------------------------------

segs = parse_address("Defs")
t.expect('single segment: count', len(segs) == 1, repr(segs))
t.expect('single segment: tag', segs[0].tag == 'Defs', repr(segs[0]))
t.expect('single segment: no selector', segs[0].selector is None, repr(segs[0]))

segs = parse_address("Defs/ThingDef[Steel]/statBases/MarketValue")
t.expect('4 segments', len(segs) == 4, repr(segs))
t.expect('seg0 Defs', segs[0].tag == 'Defs' and segs[0].selector is None)
t.expect('seg1 ThingDef+value',
         segs[1].tag == 'ThingDef'
         and isinstance(segs[1].selector, DiscriminatorSelector)
         and segs[1].selector.value == 'Steel')
t.expect('seg2 statBases', segs[2].tag == 'statBases' and segs[2].selector is None)
t.expect('seg3 MarketValue', segs[3].tag == 'MarketValue' and segs[3].selector is None)

# --- positional vs value ---------------------------------------------------

segs = parse_address("Patch/Operation[3]")
t.expect('position 3',
         isinstance(segs[1].selector, PositionSelector)
         and segs[1].selector.n == 3, repr(segs[1]))

segs = parse_address("Defs/ThingDef[1]")
t.expect('position 1',
         isinstance(segs[1].selector, PositionSelector)
         and segs[1].selector.n == 1)

segs = parse_address("ModMetaData/supportedVersions/li[1.5]")
t.expect('1.5 is value (has dot)',
         isinstance(segs[2].selector, DiscriminatorSelector)
         and segs[2].selector.value == '1.5', repr(segs[2]))

segs = parse_address("Defs/AbilityDef[-1]")
t.expect('-1 is value (has minus)',
         isinstance(segs[1].selector, DiscriminatorSelector)
         and segs[1].selector.value == '-1', repr(segs[1]))

segs = parse_address("Defs/AbilityDef[01]")
t.expect('01 is positional (all digits)',
         isinstance(segs[1].selector, PositionSelector)
         and segs[1].selector.n == 1, repr(segs[1]))

# --- real-world samples ----------------------------------------------------

# Cyberpunk: ':' inside value is not special.
segs = parse_address(
    "tweakdb/record_update[gamedataStatModifierGroup_Record:PlayerBaseCarryCapacity]"
)
t.expect('Cyberpunk: colon preserved',
         isinstance(segs[1].selector, DiscriminatorSelector)
         and segs[1].selector.value
             == 'gamedataStatModifierGroup_Record:PlayerBaseCarryCapacity',
         repr(segs[1]))

# Skyrim: space inside value is not special.
segs = parse_address("physics/bones/bone[NPC Cape1]")
t.expect('Skyrim: space preserved',
         isinstance(segs[2].selector, DiscriminatorSelector)
         and segs[2].selector.value == 'NPC Cape1', repr(segs[2]))

# RimWorld Abstract-Def: value has no @ in address.
segs = parse_address("Defs/AbilityDef[SpikeLaunchBase]")
t.expect('RimWorld Abstract: plain value',
         isinstance(segs[1].selector, DiscriminatorSelector)
         and segs[1].selector.value == 'SpikeLaunchBase')

# --- escaping --------------------------------------------------------------

segs = parse_address("Defs/RoofDef[Weird\\]Name]")
t.expect('escape ]',
         isinstance(segs[1].selector, DiscriminatorSelector)
         and segs[1].selector.value == 'Weird]Name', repr(segs[1]))

segs = parse_address("Defs/RoofDef[Weird\\[Name]")
t.expect('escape [',
         isinstance(segs[1].selector, DiscriminatorSelector)
         and segs[1].selector.value == 'Weird[Name', repr(segs[1]))

segs = parse_address("Defs/RoofDef[Weird\\/Name]")
t.expect('escape /',
         isinstance(segs[1].selector, DiscriminatorSelector)
         and segs[1].selector.value == 'Weird/Name', repr(segs[1]))

# Escaped backslash: source '\\' (two chars) -> value '\\' (one char).
segs = parse_address("Defs/RoofDef[Weird\\\\Name]")
t.expect('escape \\',
         isinstance(segs[1].selector, DiscriminatorSelector)
         and segs[1].selector.value == 'Weird\\Name', repr(segs[1]))

# Escaped [ in tag name (not selector).
segs = parse_address("Defs/Weird\\[Tag")
t.expect('escape [ in tag name', segs[1].tag == 'Weird[Tag', repr(segs[1]))

# --- errors ----------------------------------------------------------------

t.expect_raises('empty address', lambda: parse_address(""))
t.expect_raises('leading slash', lambda: parse_address("/Defs"))
t.expect_raises('trailing slash', lambda: parse_address("Defs/"))
t.expect_raises('double slash', lambda: parse_address("Defs//ThingDef"))
t.expect_raises('unclosed [', lambda: parse_address("Defs/RoofDef[Steel"))
t.expect_raises('empty []', lambda: parse_address("Defs/RoofDef[]"))
t.expect_raises('text after selector', lambda: parse_address("Defs/RoofDef[Steel]extra"))
t.expect_raises('position 0', lambda: parse_address("Defs/RoofDef[0]"))

# --- summary --------------------------------------------------------------

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
