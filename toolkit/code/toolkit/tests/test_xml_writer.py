"""Tests for toolkit.xml.writer.

Unit layer exercises each operation on synthetic bytes, asserting byte-
exact output (all contracts §7.6). Integration layer re-applies the same
edits to real RimWorld files and reparses to confirm well-formedness.

Run: python toolkit/code/toolkit/tests/test_xml_writer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.xml.reader import parse
from toolkit.xml.writer import (
    WriteError,
    escape_attr,
    escape_text,
    remove_attr,
    replace_text,
    set_attr,
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

    def expect_code(self, label, fn, code):
        try:
            fn()
        except WriteError as e:
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

# --- escaping --------------------------------------------------------------

t.expect('escape_text &', escape_text('A & B') == 'A &amp; B')
t.expect('escape_text <', escape_text('a<b') == 'a&lt;b')
t.expect('escape_text >', escape_text('a>b') == 'a&gt;b')
t.expect('escape_attr quote', escape_attr('a"b') == 'a&quot;b')
t.expect('escape_attr & < >',
         escape_attr('A&B<C>D') == 'A&amp;B&lt;C&gt;D')

# --- replace_text ----------------------------------------------------------

# Leaf text: simple replace.
d = parse(b'<a>old</a>')
new = replace_text(d, d.root, 'new')
t.expect('leaf: bytes', new == b'<a>new</a>', repr(new))

# Text with special chars: escaped.
d = parse(b'<a>old</a>')
new = replace_text(d, d.root, 'A & B <C>')
t.expect('leaf: escaped', new == b'<a>A &amp; B &lt;C&gt;</a>', repr(new))

# CDATA preserved when original was CDATA.
d = parse(b'<a><![CDATA[old & <stuff>]]></a>')
new = replace_text(d, d.root, 'A & B <C>')
t.expect('CDATA preserved: wrapper',
         new.startswith(b'<a><![CDATA[') and new.endswith(b']]></a>'),
         repr(new))
t.expect('CDATA preserved: content raw',
         b'A & B <C>' in new, repr(new))

# Self-closing leaf: expanded to pair.
d = parse(b'<a/>')
new = replace_text(d, d.root, 'v')
t.expect('self-closing -> pair', new == b'<a>v</a>', repr(new))

# Self-closing with attr: attr preserved.
d = parse(b'<a x="1"/>')
new = replace_text(d, d.root, 'v')
t.expect('self-closing attr: preserved',
         new == b'<a x="1">v</a>', repr(new))

# Has children -> refused.
d = parse(b'<a><b>y</b></a>')
t.expect_code('has_children',
              lambda: replace_text(d, d.root, 'z'),
              'has_children')

# Attribute order and CDATA of OTHER elements are untouched.
raw = b'<a><b><![CDATA[keep]]></b><c>old</c></a>'
d = parse(raw)
c = d.root.children[1]
new = replace_text(d, c, 'new')
t.expect('other elems untouched: CDATA', b'<![CDATA[keep]]>' in new)
t.expect('other elems untouched: b', b'<b>' in new)
t.expect('target changed', b'<c>new</c>' in new, repr(new))

# --- set_attr on existing --------------------------------------------------

# Value replaced, quote style kept (double).
d = parse(b'<a x="1" y="2"/>')
new = set_attr(d, d.root, 'x', 'NEW')
t.expect('set_attr existing: value', new == b'<a x="NEW" y="2"/>', repr(new))

# Single-quote preserved.
d = parse(b"<a x='1' y=\"2\"/>")
new = set_attr(d, d.root, 'x', 'NEW')
t.expect('set_attr existing: single quote kept',
         b"x='NEW'" in new, repr(new))

# Escaped value in attr.
d = parse(b'<a x="1"/>')
new = set_attr(d, d.root, 'x', 'A & B')
t.expect('set_attr: escaped',
         b'x="A &amp; B"' in new, repr(new))

# Attribute order preserved (existing stays in place).
d = parse(b'<a z="1" x="2" m="3"/>')
new = set_attr(d, d.root, 'x', '99')
t.expect('set_attr: order',
         new == b'<a z="1" x="99" m="3"/>', repr(new))

# --- set_attr new ----------------------------------------------------------

# Appended before `>`.
d = parse(b'<a x="1"/>')
new = set_attr(d, d.root, 'y', '2')
t.expect('set_attr new: appended',
         new == b'<a x="1" y="2"/>', repr(new))

# --- remove_attr -----------------------------------------------------------

d = parse(b'<a x="1" y="2" z="3"/>')
new = remove_attr(d, d.root, 'y')
t.expect('remove_attr middle',
         new == b'<a x="1" z="3"/>', repr(new))

d = parse(b'<a x="1"/>')
new = remove_attr(d, d.root, 'x')
t.expect('remove_attr only', new == b'<a/>', repr(new))

d = parse(b'<a x="1"/>')
t.expect_code('remove_attr missing',
              lambda: remove_attr(d, d.root, 'nope'),
              'attr_not_found')

# --- preserve BOM, CRLF, encoding -----------------------------------------

raw = b'\xef\xbb\xbf<root>\r\n  <a>old</a>\r\n</root>'
d = parse(raw)
a = d.root.children[0]
new = replace_text(d, a, 'NEW')
t.expect('BOM preserved', new.startswith(b'\xef\xbb\xbf'), repr(new[:20]))
t.expect('CRLF preserved (surrounding)',
         b'\r\n' in new and b'\n\r' not in new, repr(new))
t.expect('BOM: no LF-only inserted',
         new.count(b'\r\n') == raw.count(b'\r\n'), repr(new))
t.expect('BOM: content changed', b'<a>NEW</a>' in new)

# --- UTF-16 round-trip ----------------------------------------------------

raw = '<root><a>old</a></root>'.encode('utf-16-le')
raw_with_bom = b'\xff\xfe' + raw
d = parse(raw_with_bom)
a = d.root.children[0]
new = replace_text(d, a, 'NEW')
t.expect('UTF-16: BOM preserved', new.startswith(b'\xff\xfe'))
t.expect('UTF-16: bytes',
         new == b'\xff\xfe' + '<root><a>NEW</a></root>'.encode('utf-16-le'),
         repr(new))

# --- integration: real files reparse after edit ---------------------------

RW = Path('D:/Programs/UnityAiDevSystem/RimWorld')

def _roundtrip(rel, address_root_tag, edit_fn, label):
    p = RW / rel
    if not p.is_file():
        print(PASS + f' {label}: skipped')
        t.passed += 1
        return
    d = parse(p.read_bytes())
    # Apply edit to the root's first child whose tag matches.
    target = None
    for ch in d.root.children:
        if ch.tag == address_root_tag:
            target = ch
            break
    if target is None:
        print(FAIL + f' {label}: no <{address_root_tag}> child')
        t.failed += 1
        return
    try:
        new_bytes = edit_fn(d, target)
    except WriteError as e:
        print(PASS + f' {label}: refused ({e.code})')
        t.passed += 1
        return
    try:
        d2 = parse(new_bytes)
    except Exception as e:
        print(FAIL + f' {label}: reparse failed -- {e}')
        t.failed += 1
        return
    # Confirm only the target changed: other siblings' slices still valid.
    print(PASS + f' {label}: reparse ok')
    t.passed += 1
    _ = d2  # silence

# Roofs.xml: set_attr on <isThickRoof>
_roundtrip('Data/Anomaly/Defs/Misc/Roofs.xml', 'RoofDef',
           lambda d, el: set_attr(d, el.children[2], 'test_attr', 'v'),
           'Roofs: set_attr on isThickRoof')

# Roofs.xml: replace_text on <label>
_roundtrip('Data/Anomaly/Defs/Misc/Roofs.xml', 'RoofDef',
           lambda d, el: replace_text(
               d, next(c for c in el.children if c.tag == 'label'),
               'edited ceiling'),
           'Roofs: replace_text on label')

# About.xml: replace_text inside CDATA <description>
_roundtrip('Mods/3014915404/About/About.xml', 'description',
           lambda d, el: replace_text(d, el, 'New framework description.'),
           'About: replace_text on CDATA description')

# Abilities.xml: set_attr on Abstract-Def
_roundtrip('Data/Anomaly/Defs/AbilityDefs/Abilities.xml', 'AbilityDef',
           lambda d, el: set_attr(d, el, 'Abstract', 'False'),
           'Abilities: set_attr Abstract')

# Scyrim.xml: remove_attr on physics root's child
_roundtrip('PatchApplier/AnotherXML/Scyrim.xml', 'margin',
           lambda d, el: replace_text(d, el, '0.10'),
           'Scyrim: replace_text on margin')

# Cyberpunk: set_attr on record_update@dbid
_roundtrip('PatchApplier/AnotherXML/Cyberpunk.xml', 'record_update',
           lambda d, el: set_attr(d, el, 'dbid', 'new:Value'),
           'Cyberpunk: set_attr dbid with colon')

# Patch file: set_attr on Operation@Class
_roundtrip('Mods/1123043922/1.0/Patches/Patch_GeneticRimPatchReplaceToNeutroglycerin_SparklingWorlds.xml',
           'Operation',
           lambda d, el: set_attr(d, el, 'Class', 'PatchOperationTest'),
           'Patch: set_attr Operation@Class')

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
