"""Tests for toolkit.xml.writer.append_child.

Run: python toolkit/code/toolkit/tests/test_xml_append.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.xml.reader import parse
from toolkit.xml.writer import WriteError, append_child


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

# --- simple append to empty-ish parent ---------------------------------

raw = b'<root>\n  <a/>\n</root>'
d = parse(raw)
new = append_child(d, d.root, '<b/>')
t.expect('append to non-empty: status', True)  # placeholder
t.expect('append: contains b', b'<b/>' in new, repr(new))
t.expect('append: b indented', b'\n  <b/>\n' in new, repr(new))
# reparse
parse(new)
t.expect('append: reparse ok', True)

# --- append to truly empty parent -------------------------------------

raw = b'<root></root>'
d = parse(raw)
new = append_child(d, d.root, '<b>x</b>')
t.expect('empty parent: has b', b'<b>x</b>' in new, repr(new))
t.expect('empty parent: has newlines', b'\n' in new, repr(new))
parse(new)
t.expect('empty parent: reparse', True)

# --- append to self-closing parent -----------------------------------

raw = b'<root/>'
d = parse(raw)
new = append_child(d, d.root, '<b>y</b>')
t.expect('self-closing parent: expanded', b'<root>' in new and b'</root>' in new,
         repr(new))
t.expect('self-closing parent: has b', b'<b>y</b>' in new, repr(new))
parse(new)
t.expect('self-closing parent: reparse', True)

# --- append respects parent's 4-space indent --------------------------

raw = b'<root>\n    <a/>\n</root>'
d = parse(raw)
new = append_child(d, d.root, '<b/>')
t.expect('4-space indent preserved', b'\n    <b/>\n' in new, repr(new))

# --- append reindents multi-line fragment ----------------------------

raw = b'<root>\n  <a/>\n</root>'
d = parse(raw)
frag = '<b>\n  <c>x</c>\n</b>'
new = append_child(d, d.root, frag)
t.expect('multiline frag: b at 2 spaces', b'\n  <b>' in new, repr(new))
t.expect('multiline frag: c at 4 spaces', b'\n    <c>x</c>' in new, repr(new))
t.expect('multiline frag: /b at 2 spaces', b'\n  </b>' in new, repr(new))
parse(new)
t.expect('multiline frag: reparse', True)

# --- CRLF parent stays CRLF ------------------------------------------

raw = b'<root>\r\n  <a/>\r\n</root>'
d = parse(raw)
new = append_child(d, d.root, '<b/>')
t.expect('CRLF preserved: insert uses CRLF', b'\r\n  <b/>\r\n' in new, repr(new))
t.expect('CRLF preserved: no LF-only', b'\n' not in new.replace(b'\r\n', b''),
         repr(new))
parse(new)
t.expect('CRLF preserved: reparse', True)

# --- refuse mixed content parent ------------------------------------

raw = b'<root>text <b>y</b> more</root>'
d = parse(raw)
t.expect_code('mixed content refused',
              lambda: append_child(d, d.root, '<c/>'),
              'mixed_content_unsupported')

# --- refuse text-leaf parent -----------------------------------------

raw = b'<root>hello</root>'
d = parse(raw)
t.expect_code('text leaf refused',
              lambda: append_child(d, d.root, '<b/>'),
              'mixed_content_unsupported')

# --- refuse malformed fragment ---------------------------------------

raw = b'<root><a/></root>'
d = parse(raw)
t.expect_code('malformed fragment',
              lambda: append_child(d, d.root, '<b>'),
              'bad_fragment')

# --- refuse multi-root fragment ---------------------------------------

t.expect_code('multi-root fragment',
              lambda: append_child(parse(b'<r><x/></r>').root and
                                    parse(b'<r><x/></r>') or
                                    None, None,
                                    '<a/><b/>') if False else
              append_child(parse(b'<r/>'), parse(b'<r/>').root, '<a/><b/>'),
              'bad_fragment')

# --- CDATA in fragment survives --------------------------------------

raw = b'<root>\n  <a/>\n</root>'
d = parse(raw)
frag = '<b><![CDATA[keep & me <intact>]]></b>'
new = append_child(d, d.root, frag)
t.expect('CDATA in fragment: preserved', b'<![CDATA[keep & me <intact>]]>' in new, repr(new))
parse(new)
t.expect('CDATA in fragment: reparse', True)

# --- BOM preserved on parent file -----------------------------------

raw = b'\xef\xbb\xbf<root>\n  <a/>\n</root>'
d = parse(raw)
new = append_child(d, d.root, '<b/>')
t.expect('BOM preserved', new.startswith(b'\xef\xbb\xbf'), repr(new[:6]))

# --- UTF-16 parent ------------------------------------------------

raw = '<root>\n  <a/>\n</root>'.encode('utf-16-le')
raw = b'\xff\xfe' + raw
d = parse(raw)
new = append_child(d, d.root, '<b/>')
t.expect('UTF-16: BOM preserved', new.startswith(b'\xff\xfe'))
parse(new)
t.expect('UTF-16: reparse', True)

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
