"""Tests for toolkit.xml.discriminator.

Covers:
  - parse_spec: @attr / child / own-text
  - chain_for: config lookup by exact tag, by suffix, by longest suffix
  - chain_for: null = DEFAULT_CHAIN, absent = DEFAULT_CHAIN, list = ordered
  - match_value on realistic dict elements (RoofDef, Abstract-Def, li-text)
  - DEFAULT_CHAIN own-text fallback for <li>1.4</li>

Run: python toolkit/code/toolkit/tests/test_xml_discriminator.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.xml.discriminator import (
    DEFAULT_CHAIN,
    Lookup,
    chain_for,
    extract_value,
    match_value,
    parse_spec,
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


t = T()

# --- parse_spec ------------------------------------------------------------

lu = parse_spec('@Name')
t.expect('parse @Name', lu.kind == 'attr' and lu.name == 'Name', repr(lu))

lu = parse_spec('defName')
t.expect('parse defName', lu.kind == 'child' and lu.name == 'defName', repr(lu))

lu = parse_spec('')
t.expect('parse "" -> text', lu.kind == 'text' and lu.name == '', repr(lu))

# --- chain_for ------------------------------------------------------------

cfg = {
    'discriminators': {
        'ThingDef': ['defName', '@Name'],
        'comps/li': '@Class',
        'modDependencies/li': 'packageId',
        'supportedVersions/li': None,
        'record_update': '@dbid',
        'bone': '@name',
    }
}

# Exact tag entry with list.
chain = chain_for(['Defs', 'ThingDef'], cfg)
t.expect('ThingDef: 2 lookups', len(chain) == 2, repr(chain))
t.expect('ThingDef[0]: child defName', chain[0] == Lookup('child', 'defName'))
t.expect('ThingDef[1]: attr Name', chain[1] == Lookup('attr', 'Name'))

# Suffix entry beats tag (no tag entry).
chain = chain_for(['Defs', 'ThingDef', 'comps', 'li'], cfg)
t.expect('comps/li: single attr',
         chain == [Lookup('attr', 'Class')], repr(chain))

# Suffix with child lookup.
chain = chain_for(['ModMetaData', 'modDependencies', 'li'], cfg)
t.expect('modDependencies/li: child packageId',
         chain == [Lookup('child', 'packageId')], repr(chain))

# null -> DEFAULT_CHAIN.
chain = chain_for(['ModMetaData', 'supportedVersions', 'li'], cfg)
t.expect('supportedVersions/li null -> DEFAULT_CHAIN',
         chain == list(DEFAULT_CHAIN), repr(chain))

# Absent -> DEFAULT_CHAIN.
chain = chain_for(['Defs', 'UnknownDef'], cfg)
t.expect('absent -> DEFAULT_CHAIN', chain == list(DEFAULT_CHAIN), repr(chain))

# No config dict -> DEFAULT_CHAIN.
chain = chain_for(['Defs', 'ThingDef'], {})
t.expect('empty cfg -> DEFAULT_CHAIN', chain == list(DEFAULT_CHAIN), repr(chain))
chain = chain_for(['Defs', 'ThingDef'], None)
t.expect('None cfg -> DEFAULT_CHAIN', chain == list(DEFAULT_CHAIN), repr(chain))

# Longest suffix wins when both are present.
cfg2 = {'discriminators': {'li': '@Class', 'comps/li': '@parent'}}
chain = chain_for(['a', 'comps', 'li'], cfg2)
t.expect('longest suffix wins',
         chain == [Lookup('attr', 'parent')], repr(chain))

# --- match_value on realistic elements ------------------------------------

def el(tag, attrib=None, text='', children=None):
    return {'tag': tag, 'attrib': attrib or {}, 'text': text, 'children': children or []}

# RimWorld RoofDef: <RoofDef><defName>VoidmetalRoof</defName>...</RoofDef>
roof = el('RoofDef', children=[el('defName', text='VoidmetalRoof')])
chain = chain_for(['Defs', 'RoofDef'], cfg)
t.expect('RoofDef value from defName',
         match_value(roof, chain) == 'VoidmetalRoof', repr(match_value(roof, chain)))

# Abstract-Def: <AbilityDef Name="SpikeLaunchBase" Abstract="True">.
abstract = el('AbilityDef', attrib={'Name': 'SpikeLaunchBase', 'Abstract': 'True'})
chain = chain_for(['Defs', 'AbilityDef'], cfg)
t.expect('Abstract-Def value from @Name',
         match_value(abstract, chain) == 'SpikeLaunchBase',
         repr(match_value(abstract, chain)))

# comps/li with @Class.
comp = el('li', attrib={'Class': 'CompProperties_ConsumeLeap'})
chain = chain_for(['Defs', 'ThingDef', 'comps', 'li'], cfg)
t.expect('comps/li value from @Class',
         match_value(comp, chain) == 'CompProperties_ConsumeLeap',
         repr(match_value(comp, chain)))

# modDependencies/li with child packageId.
dep = el('li', children=[el('packageId', text='brrainz.harmony')])
chain = chain_for(['ModMetaData', 'modDependencies', 'li'], cfg)
t.expect('modDependencies/li value from child packageId',
         match_value(dep, chain) == 'brrainz.harmony',
         repr(match_value(dep, chain)))

# <li>1.4</li> -> own text via DEFAULT_CHAIN.
text_li = el('li', text='1.4')
chain = chain_for(['ModMetaData', 'supportedVersions', 'li'], cfg)
t.expect('text <li>1.4</li> via own-text',
         match_value(text_li, chain) == '1.4',
         repr(match_value(text_li, chain)))

# Missing everything -> None.
empty = el('li')
t.expect('no discriminator -> None', match_value(empty, chain) is None)

# --- extract_value direct --------------------------------------------------

attr_el = el('x', attrib={'Name': 'n'})
t.expect('extract attr', extract_value(attr_el, Lookup('attr', 'Name')) == 'n')
t.expect('extract attr missing', extract_value(attr_el, Lookup('attr', 'Nope')) is None)

child_el = el('x', children=[el('a', text='v')])
t.expect('extract child', extract_value(child_el, Lookup('child', 'a')) == 'v')
t.expect('extract child missing', extract_value(child_el, Lookup('child', 'b')) is None)

text_el = el('x', text=' hello ')
t.expect('extract text', extract_value(text_el, Lookup('text', '')) == ' hello ')

# --- summary --------------------------------------------------------------

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
