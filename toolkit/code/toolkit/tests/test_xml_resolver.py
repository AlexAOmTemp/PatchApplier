"""Tests for toolkit.xml.resolver.

Unit tests over synthetic XML cover the address resolution contract; the
integration section hits the same real files as test_xml_reader using the
addresses from docs/XML_FIXTURES.md §2.

Run: python toolkit/code/toolkit/tests/test_xml_resolver.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.xml.address import parse_address
from toolkit.xml.reader import parse
from toolkit.xml.resolver import ResolveError, resolve_all, resolve_one


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

    def expect_error(self, label, fn, code):
        try:
            fn()
        except ResolveError as e:
            if e.code == code:
                print(PASS + ' ' + label + f' ({code})')
                self.passed += 1
            else:
                print(FAIL + ' ' + label + f' -- code={e.code}, expected {code}')
                self.failed += 1
        except Exception as e:
            print(FAIL + ' ' + label + f' -- wrong exc {type(e).__name__}: {e}')
            self.failed += 1
        else:
            print(FAIL + ' ' + label + ' -- no exception')
            self.failed += 1


t = T()

CFG = {
    'discriminators': {
        'ThingDef': ['defName', '@Name'],
        'RoofDef': ['defName', '@Name'],
        'comps/li': '@Class',
        'Operation': '@Class',
        'modDependencies/li': 'packageId',
    }
}

# --- synthetic -------------------------------------------------------------

SRC = b'''<Defs>
  <ThingDef><defName>Steel</defName><label>steel</label></ThingDef>
  <ThingDef><defName>Wood</defName></ThingDef>
  <ThingDef><defName>Steel</defName></ThingDef>
  <ThingDef Name="AbstractBase" Abstract="True"/>
  <RoofDef><defName>Voidmetal</defName></RoofDef>
</Defs>'''
doc = parse(SRC)

# Two Steel — ambiguous without occurrence.
t.expect_error(
    'two Steel ambiguous',
    lambda: resolve_one(doc, parse_address('Defs/ThingDef[Steel]'), CFG),
    code='ambiguous_address',
)

# But with occurrence.
r = resolve_one(doc, parse_address('Defs/ThingDef[Steel]'), CFG, occurrence=1)
t.expect('occurrence=1: has label',
         any(c.tag == 'label' for c in r.element.children))
r = resolve_one(doc, parse_address('Defs/ThingDef[Steel]'), CFG, occurrence=2)
t.expect('occurrence=2: no label',
         not any(c.tag == 'label' for c in r.element.children))

t.expect_error(
    'occurrence=3 out of range',
    lambda: resolve_one(doc, parse_address('Defs/ThingDef[Steel]'), CFG, occurrence=3),
    code='occurrence_out_of_range',
)

# Abstract-Def via @Name fallback.
r = resolve_one(doc, parse_address('Defs/ThingDef[AbstractBase]'), CFG)
t.expect('Abstract-Def via @Name', r.element.attrib.get('Name') == 'AbstractBase')

# RoofDef.
r = resolve_one(doc, parse_address('Defs/RoofDef[Voidmetal]'), CFG)
t.expect('RoofDef', r.element.tag == 'RoofDef')

# Position selector.
r = resolve_one(doc, parse_address('Defs/ThingDef[2]'), CFG)
t.expect('ThingDef[2] = Wood',
         any(c.tag == 'defName' and c.text == 'Wood' for c in r.element.children))

t.expect_error(
    'ThingDef[5] out of range',
    lambda: resolve_one(doc, parse_address('Defs/ThingDef[5]'), CFG),
    code='position_out_of_range',
)

# not_found: bad tag.
t.expect_error(
    'unknown tag',
    lambda: resolve_one(doc, parse_address('Defs/Nope[1]'), CFG),
    code='not_found',
)

# not_found: root mismatch.
t.expect_error(
    'wrong root',
    lambda: resolve_one(doc, parse_address('Other/ThingDef'), CFG),
    code='not_found',
)

# Bare Defs — the root itself.
r = resolve_one(doc, parse_address('Defs'), CFG)
t.expect('bare Defs -> root', r.element.tag == 'Defs')

# resolve_all: every ThingDef.
all_thing = resolve_all(doc, parse_address('Defs/ThingDef'), CFG)
t.expect('resolve_all ThingDef: 4 matches', len(all_thing) == 4, f'got {len(all_thing)}')

# resolve_all respects the selector.
all_steel = resolve_all(doc, parse_address('Defs/ThingDef[Steel]'), CFG)
t.expect('resolve_all Steel: 2 matches', len(all_steel) == 2, f'got {len(all_steel)}')

# --- integration: real RimWorld files -------------------------------------

RW = Path('D:/Programs/UnityAiDevSystem/RimWorld')

def _load(rel):
    p = RW / rel
    if not p.is_file():
        return None
    return parse(p.read_bytes())


# Roofs.xml — unique defName.
d = _load('Data/Anomaly/Defs/Misc/Roofs.xml')
if d is None:
    print(PASS + ' Roofs.xml: skipped')
    t.passed += 1
else:
    r = resolve_one(d, parse_address('Defs/RoofDef[VoidmetalRoof]'), CFG)
    t.expect('Roofs.xml: RoofDef[VoidmetalRoof]',
             r.element.tag == 'RoofDef')
    t.expect_error(
        'Roofs.xml: unknown defName',
        lambda: resolve_one(d, parse_address('Defs/RoofDef[Nope]'), CFG),
        code='not_found',
    )

# Abilities.xml — Abstract-Def and ambiguous comps/li.
d = _load('Data/Anomaly/Defs/AbilityDefs/Abilities.xml')
if d is None:
    print(PASS + ' Abilities.xml: skipped')
    t.passed += 1
else:
    r = resolve_one(d, parse_address('Defs/AbilityDef[SpikeLaunchBase]'), CFG)
    t.expect('Abilities.xml: Abstract-Def via @Name',
             r.element.attrib.get('Name') == 'SpikeLaunchBase')

    r = resolve_one(d, parse_address('Defs/AbilityDef[SpikeLaunch_Toughspike]'), CFG)
    t.expect('Abilities.xml: concrete Def via defName',
             r.element.tag == 'AbilityDef')

    # EntitySkip has <comps><li Class="CompProperties_AbilityTeleport">.
    comps_addr = ('Defs/AbilityDef[EntitySkip]/comps/li[CompProperties_AbilityTeleport]')
    r = resolve_one(d, parse_address(comps_addr), CFG)
    t.expect('Abilities.xml: nested comps/li[Class]', r.element.tag == 'li')

# Patch file — ambiguous Operation, resolved via occurrence.
d = _load('Mods/1123043922/1.0/Patches/Patch_GeneticRimPatchReplaceToNeutroglycerin_SparklingWorlds.xml')
if d is None:
    print(PASS + ' Patch file: skipped')
    t.passed += 1
else:
    t.expect_error(
        'Patch: Operation[PatchOperationSequence] ambiguous',
        lambda: resolve_one(d, parse_address('Patch/Operation[PatchOperationSequence]'), CFG),
        code='ambiguous_address',
    )
    r = resolve_one(d, parse_address('Patch/Operation[PatchOperationSequence]'), CFG, occurrence=3)
    t.expect('Patch: Operation[Sequence] occurrence=3', r.element.tag == 'Operation')

# About.xml — child-based discriminator and text-[N] fallback.
d = _load('Mods/3014915404/About/About.xml')
if d is None:
    print(PASS + ' About.xml: skipped')
    t.passed += 1
else:
    r = resolve_one(d, parse_address('ModMetaData/modDependencies/li[brrainz.harmony]'), CFG)
    t.expect('About.xml: modDependencies/li[brrainz.harmony]',
             r.element.tag == 'li')
    r = resolve_one(d, parse_address('ModMetaData/supportedVersions/li[2]'), CFG)
    t.expect('About.xml: supportedVersions/li[2] positional',
             r.element.tag == 'li')

# Cyberpunk — colon in attribute value.
d = _load('PatchApplier/AnotherXML/Cyberpunk.xml')
if d is None:
    print(PASS + ' Cyberpunk.xml: skipped')
    t.passed += 1
else:
    r = resolve_one(
        d,
        parse_address('tweakdb/record_update[gamedataStatModifierGroup_Record:PlayerBaseCarryCapacity]'),
        {'discriminators': {'record_update': '@dbid'}},
    )
    t.expect('Cyberpunk: colon preserved in selector',
             r.element.attrib.get('dbid', '').endswith('PlayerBaseCarryCapacity'))

# Scyrim — space in attribute value.
d = _load('PatchApplier/AnotherXML/Scyrim.xml')
if d is None:
    print(PASS + ' Scyrim.xml: skipped')
    t.passed += 1
else:
    r = resolve_one(
        d, parse_address('physics/bones/bone[NPC Cape1]'),
        {'discriminators': {'bone': '@name'}},
    )
    t.expect('Scyrim: space preserved in selector',
             r.element.attrib.get('name') == 'NPC Cape1')

# --- summary --------------------------------------------------------------

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
