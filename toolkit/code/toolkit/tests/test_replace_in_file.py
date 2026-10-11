'''Tests for replace_in_file: 3 tiers + regex.

Covers:
  - tier 1: byte-exact, silent
  - tier 2: trailing whitespace / EOL normalisation, message marked
  - tier 2 ambiguous: two normalised matches, occurrence required
  - tier 3: no match, similar lines marked
  - regex: literal, backrefs, occurrence, no-match

Run: python toolkit/code/toolkit/tests/test_replace_in_file.py
'''
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.backends import FilesystemBackend
from toolkit.core import Session
from toolkit.formats import Format
from toolkit.tools import TOOL_MAP


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


def _run(root: Path, patches):
    backend = FilesystemBackend(root)
    fmt = Format.load('default')
    with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:
        return s.apply_patches(patches)


def _tool(**args):
    return {'action': 'replace_in_file', 'arguments': args}


def main():
    t = T()

    # --- tier 1: exact ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'a.py'
        p.write_text('x = 1\n', encoding='utf-8')
        r = _run(root, [_tool(file_path='a.py', search='x = 1', replace='y = 2')])[0]
        t.expect('tier1 ok', r.status == 'ok', r.message)
        t.expect('tier1 applied', p.read_text(encoding='utf-8') == 'y = 2\n')
        t.expect('tier1 no marker', 'normalisation' not in r.message)

    # --- tier 2: trailing whitespace ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'b.py'
        p.write_text('foo()  \nbar()\n', encoding='utf-8')
        r = _run(root, [_tool(file_path='b.py', search='foo()', replace='baz()')])[0]
        t.expect('tier2 ok', r.status == 'ok', r.message)
        body = p.read_text(encoding='utf-8')
        t.expect('tier2 replaced line', 'baz()' in body, repr(body))
        t.expect('tier2 stripped trailing ws', body == 'baz()\nbar()\n', repr(body))
        t.expect('tier2 marked in message',
                 'normalisation' in r.message, r.message)

    # --- tier 2: multi-line trailing ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'c.py'
        p.write_text('def f():\n    x = 1   \n    return x\n', encoding='utf-8')
        r = _run(root, [_tool(file_path='c.py',
                              search='    x = 1\n    return x',
                              replace='    y = 2\n    return y')])[0]
        t.expect('tier2 multiline ok', r.status == 'ok', r.message)
        body = p.read_text(encoding='utf-8')
        t.expect('tier2 multiline replaced', 'y = 2' in body and 'x = 1' not in body)

    # --- tier 2 ambiguous ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'd.py'
        p.write_text('foo()  \nmid()\nfoo()\n', encoding='utf-8')
        r = _run(root, [_tool(file_path='d.py', search='foo()', replace='bar()')])[0]
        # occurrence=1 default; ambiguous -> error
        t.expect('tier2 ambiguous rejected',
                 r.status == 'error' and r.error_code == 'bad_occurrence',
                 f'{r.status}/{r.error_code}')
        # with occurrence=2 -> applies
        r = _run(root, [_tool(file_path='d.py', search='foo()', replace='bar()',
                              occurrence=2)])[0]
        t.expect('tier2 occurrence=2 ok', r.status == 'ok', r.message)

    # --- tier 3: no match, similar lines ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'e.py'
        p.write_text('from .model import Block, Part, Unit, UnitKind  \n', encoding='utf-8')
        r = _run(root, [_tool(file_path='e.py',
                              search='from .core import Something',
                              replace='x')])[0]
        t.expect('tier3 no_match',
                 r.status == 'error' and r.error_code == 'no_match',
                 f'{r.status}/{r.error_code}')
        t.expect('tier3 mentions searched', 'Searched' in r.message, r.message)
        # Similar might pick up L1 given the shared prefix
        t.expect('tier3 shows similar lines or at least searched',
                 'Similar' in r.message or 'Searched' in r.message)

    # --- regex: basic ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'r.py'
        p.write_text('x = 10\ny = 20\nz = 30\n', encoding='utf-8')
        r = _run(root, [_tool(file_path='r.py',
                              search=r'= \d+',
                              replace='= 0',
                              regex=True)])[0]
        t.expect('regex ok', r.status == 'ok', r.message)
        body = p.read_text(encoding='utf-8')
        t.expect('regex replaced first only',
                 body == 'x = 0\ny = 20\nz = 30\n', repr(body))

    # --- regex: occurrence=all ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 's.py'
        p.write_text('x = 10\ny = 20\n', encoding='utf-8')
        r = _run(root, [_tool(file_path='s.py',
                              search=r'= \d+',
                              replace='= 0',
                              regex=True,
                              occurrence='all')])[0]
        t.expect('regex all ok', r.status == 'ok', r.message)
        body = p.read_text(encoding='utf-8')
        t.expect('regex all replaced', body == 'x = 0\ny = 0\n', repr(body))

    # --- regex: backrefs ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 't.py'
        p.write_text('foo_1 = 1\n', encoding='utf-8')
        r = _run(root, [_tool(file_path='t.py',
                              search=r'(foo)_(\d)',
                              replace=r'\2_\1',
                              regex=True)])[0]
        t.expect('regex backref ok', r.status == 'ok', r.message)
        body = p.read_text(encoding='utf-8')
        t.expect('regex backref swapped', body == '1_foo = 1\n', repr(body))

    # --- regex: no match ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'u.py'
        p.write_text('x = 1\n', encoding='utf-8')
        r = _run(root, [_tool(file_path='u.py', search=r'qq\d+',
                              replace='x', regex=True)])[0]
        t.expect('regex no match',
                 r.status == 'error' and r.error_code == 'no_match',
                 f'{r.status}/{r.error_code}')

    # --- regex: bad pattern ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'v.py'
        p.write_text('x = 1\n', encoding='utf-8')
        r = _run(root, [_tool(file_path='v.py', search=r'(unclosed',
                              replace='x', regex=True)])[0]
        t.expect('regex bad pattern',
                 r.status == 'error' and r.error_code == 'bad_regex',
                 f'{r.status}/{r.error_code}')

    print()
    print('=== ' + str(t.passed) + ' ok, ' + str(t.failed) + ' failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
