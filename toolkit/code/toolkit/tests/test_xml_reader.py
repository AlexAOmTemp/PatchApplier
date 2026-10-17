"""Tests for toolkit.xml.reader.

Two layers:

  - unit: synthetic byte strings — every contract point from §7.
  - integration: five real files from RimWorld/Data and
    RimWorld/PatchApplier/AnotherXML (see docs/XML_FIXTURES.md §2).
    Skipped silently if the RimWorld root is absent (CI).

Run: python toolkit/code/toolkit/tests/test_xml_reader.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.xml.reader import (
    MAX_DEPTH,
    XmlError,
    detect_encoding,
    detect_line_ending,
    element_source,
    is_mixed_content,
    iter_elements,
    parse,
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

    def expect_raises(self, label, fn, code=None, exc=None):
        try:
            fn()
        except Exception as e:
            if exc is not None and not isinstance(e, exc):
                print(FAIL + ' ' + label
                      + f' -- wrong exc {type(e).__name__}, expected {exc.__name__}')
                self.failed += 1
                return
            if isinstance(e, XmlError) and code is not None and e.code != code:
                print(FAIL + ' ' + label + f' -- code={e.code}, expected {code}')
                self.failed += 1
                return
            print(PASS + ' ' + label + f' ({type(e).__name__})')
            self.passed += 1
        else:
            print(FAIL + ' ' + label + ' -- no exception')
            self.failed += 1


t = T()

# --- encoding --------------------------------------------------------------

enc, bom = detect_encoding(b'<?xml version="1.0" encoding="utf-8"?><a/>')
t.expect('enc: declared utf-8', enc == 'utf-8' and bom == b'', repr((enc, bom)))

enc, bom = detect_encoding(b'<?xml version="1.0" encoding="UTF-16"?><a/>')
t.expect('enc: declared utf-16 lowercased', enc == 'utf-16' and bom == b'')

enc, bom = detect_encoding(b'\xef\xbb\xbf<a/>')
t.expect('enc: utf-8 BOM', enc == 'utf-8' and bom == b'\xef\xbb\xbf')

enc, bom = detect_encoding(b'\xff\xfe<\x00a\x00/\x00>\x00')
t.expect('enc: utf-16-le BOM', enc == 'utf-16-le' and bom == b'\xff\xfe')

enc, bom = detect_encoding(b'<a/>')
t.expect('enc: default utf-8', enc == 'utf-8')

# --- line endings ----------------------------------------------------------

t.expect('eol: LF', detect_line_ending(b'<a/>\n<b/>\n') == '\n')
t.expect('eol: CRLF', detect_line_ending(b'<a/>\r\n<b/>\r\n') == '\r\n')
t.expect('eol: mixed but CRLF dominant',
         detect_line_ending(b'<a/>\r\n<b/>\n<c/>\r\n') == '\r\n')

# --- basic parse -----------------------------------------------------------

d = parse(b'<root><a x="1">hello</a></root>')
t.expect('parse: root tag', d.root.tag == 'root')
t.expect('parse: one child', len(d.root.children) == 1)
child = d.root.children[0]
t.expect('child tag', child.tag == 'a')
t.expect('child attrib', child.attrib == {'x': '1'}, repr(child.attrib))
t.expect('child text', child.text == 'hello', repr(child.text))
t.expect('child parent', child.parent is d.root)

# --- byte offsets ----------------------------------------------------------

d = parse(b'<root><a>hi</a></root>')
child = d.root.children[0]
t.expect('slice: child',
         d.source_bytes[child.start:child.end] == b'<a>hi</a>',
         repr(d.source_bytes[child.start:child.end]))
t.expect('slice: root',
         d.source_bytes[d.root.start:d.root.end] == b'<root><a>hi</a></root>',
         repr(d.source_bytes[d.root.start:d.root.end]))

d = parse(b'<x/>')
t.expect('slice: self-closing',
         d.source_bytes[d.root.start:d.root.end] == b'<x/>',
         repr(d.source_bytes[d.root.start:d.root.end]))

# Element with attributes: slice includes attribute bytes.
d = parse(b'<x a="1" b="2"/>')
t.expect('slice: attrs',
         d.source_bytes[d.root.start:d.root.end] == b'<x a="1" b="2"/>',
         repr(d.source_bytes[d.root.start:d.root.end]))

# --- attribute order -------------------------------------------------------

d = parse(b'<x z="1" a="2" m="3"/>')
t.expect('attrib order preserved',
         list(d.root.attrib.keys()) == ['z', 'a', 'm'],
         repr(list(d.root.attrib.keys())))

# --- BOM preserved, offset base -------------------------------------------

raw = b'\xef\xbb\xbf<root><a>x</a></root>'
d = parse(raw)
t.expect('BOM: detected', d.bom == b'\xef\xbb\xbf')
t.expect('BOM: encoding utf-8', d.encoding == 'utf-8')
t.expect('BOM: root slice has no BOM',
         d.source_bytes[d.root.start:d.root.end] == b'<root><a>x</a></root>',
         repr(d.source_bytes[d.root.start:d.root.end]))

# --- CRLF preserved in slices ---------------------------------------------

raw = b'<root>\r\n  <a>x</a>\r\n</root>'
d = parse(raw)
t.expect('CRLF: detected', d.line_ending == '\r\n')
t.expect('CRLF: slice keeps it',
         d.source_bytes[d.root.start:d.root.end] == raw,
         repr(d.source_bytes[d.root.start:d.root.end]))

# --- CDATA -----------------------------------------------------------------

raw = b'<a><![CDATA[hello & <world>]]></a>'
d = parse(raw)
t.expect('CDATA: text raw', d.root.text == 'hello & <world>', repr(d.root.text))
t.expect('CDATA: slice',
         element_source(d, d.root) == raw,
         repr(element_source(d, d.root)))

# --- mixed content ---------------------------------------------------------

raw = b'<a>x<b>y</b>z</a>'
d = parse(raw)
root = d.root
b = root.children[0]
t.expect('mixed: text', root.text == 'x', repr(root.text))
t.expect('mixed: b.text', b.text == 'y', repr(b.text))
t.expect('mixed: b.tail', b.tail == 'z', repr(b.tail))
t.expect('mixed: is_mixed_content', is_mixed_content(root))

# Structural whitespace — NOT mixed.
raw = b'<a>\n  <b/>\n  <c/>\n</a>'
d = parse(raw)
t.expect('structural whitespace: not mixed',
         not is_mixed_content(d.root),
         f'text={d.root.text!r}, tails={[c.tail for c in d.root.children]!r}')

# Text leaf — not mixed (no children).
raw = b'<a>hello</a>'
t.expect('text leaf: not mixed', not is_mixed_content(parse(raw).root))

# --- iter_elements ---------------------------------------------------------

d = parse(b'<a><b><c/></b><d/></a>')
tags = [el.tag for el in iter_elements(d.root)]
t.expect('iter_elements pre-order', tags == ['a', 'b', 'c', 'd'], repr(tags))

# --- errors ----------------------------------------------------------------

t.expect_raises('malformed', lambda: parse(b'<a><b></a>'), code='syntax_error')
t.expect_raises('empty input', lambda: parse(b''), code='syntax_error')
t.expect_raises('not bytes', lambda: parse('<a/>'), exc=Exception)  # TypeError

# --- DTD / entities --------------------------------------------------------

d = parse(b'<!DOCTYPE root><root><a>x</a></root>')
t.expect('DTD allowed (no entities)', d.has_doctype and not d.has_entities)

d = parse(b'<!DOCTYPE root [ <!ENTITY foo "bar"> ]><root>&foo;</root>')
t.expect('DTD with entity flagged', d.has_doctype and d.has_entities)

# --- depth limit -----------------------------------------------------------

# Build 102-deep nested elements.
deep = b'<a>' * (MAX_DEPTH + 2) + b'</a>' * (MAX_DEPTH + 2)
t.expect_raises('depth > MAX_DEPTH', lambda: parse(deep), code='depth_too_deep')

# --- integration: real RimWorld files -------------------------------------

RW = Path('D:/Programs/UnityAiDevSystem/RimWorld')

def _slice_selfcheck(label, rel):
    """Parse a real file, verify every element's slice parses back to itself.

    This is the strongest single property we can assert without a full
    writer: if the reader's byte spans are wrong, re-parsing the slice
    will either fail or yield a different root tag.
    """
    p = RW / rel
    if not p.is_file():
        print(PASS + f' {label}: skipped (file absent)')
        t.passed += 1
        return
    try:
        d = parse(p.read_bytes())
    except Exception as e:
        print(FAIL + f' {label}: parse failed -- {type(e).__name__}: {e}')
        t.failed += 1
        return
    for el in iter_elements(d.root):
        sl = element_source(d, el)
        try:
            d2 = parse(sl)
        except Exception as e:
            print(FAIL + f' {label}: slice of <{el.tag}> unparseable: {e}')
            t.failed += 1
            return
        if d2.root.tag != el.tag:
            print(FAIL + f' {label}: slice of <{el.tag}> reparsed as <{d2.root.tag}>')
            t.failed += 1
            return
    print(PASS + f' {label}: all slices reparse cleanly')
    t.passed += 1

_slice_selfcheck('Roofs.xml (BOM+CRLF)', 'Data/Anomaly/Defs/Misc/Roofs.xml')
_slice_selfcheck('Abilities.xml (Abstract+concrete)', 'Data/Anomaly/Defs/AbilityDefs/Abilities.xml')
_slice_selfcheck('About.xml (CDATA+li)', 'Mods/3014915404/About/About.xml')
_slice_selfcheck('Cyberpunk.xml (colon in attr)',
                 'PatchApplier/AnotherXML/Cyberpunk.xml')
_slice_selfcheck('Scyrim.xml (space in attr+self-closing)',
                 'PatchApplier/AnotherXML/Scyrim.xml')
_slice_selfcheck('Patch file (10+ Operation siblings)',
                 'Mods/1123043922/1.0/Patches/Patch_GeneticRimPatchReplaceToNeutroglycerin_SparklingWorlds.xml')

# --- summary --------------------------------------------------------------

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
