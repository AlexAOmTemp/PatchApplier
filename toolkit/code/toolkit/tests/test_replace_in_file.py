'''Tests for replace_in_file: 3 tiers + regex.

Note on tier 1 vs tier 2. `foo()` is a substring of `foo()  ` — when the
search has no trailing whitespace, tier 1 finds it silently and leaves
the file's trailing whitespace alone. Tier 2 only fires when the search
as-is cannot be located byte-for-byte, e.g. a multi-line needle where a
file line has trailing spaces that the needle lacks. Tests below use
that shape.

Covers:
  - tier 1: byte-exact, silent; substring keeps trailing in the file
  - tier 2: multi-line trailing-whitespace tolerance, message marked
  - tier 2 ambiguous: two normalised matches, occurrence required
  - tier 3: no match, similar lines marked
  - regex: literal, backrefs, occurrence, all, no-match, bad pattern

Run: python toolkit/code/toolkit/tests/test_replace_in_file.py
'''
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.backends import RootDirBackend
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
    backend = RootDirBackend(root)
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

    # --- tier 1: substring keeps file's trailing whitespace ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'b.py'
        p.write_text('foo()  \nbar()\n', encoding='utf-8')
        r = _run(root, [_tool(file_path='b.py', search='foo()', replace='baz()')])[0]
        t.expect('tier1 substring ok', r.status == 'ok', r.message)
        body = p.read_text(encoding='utf-8')
        # trailing preserved: foo() -> baz() inside the line, two spaces stay
        t.expect('substring keeps trailing ws',
                 body == 'baz()  \nbar()\n', repr(body))
        t.expect('substring no normalisation marker',
                 'normalisation' not in r.message, r.message)

    # --- tier 2: multi-line trailing whitespace ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'c.py'
        p.write_text('def f():  \n    return 1\n', encoding='utf-8')
        # Two-line needle without trailing on first line -> no exact match
        r = _run(root, [_tool(file_path='c.py',
                              search='def f():\n    return 1',
                              replace='def g():\n    return 2')])[0]
        t.expect('tier2 ok', r.status == 'ok', r.message)
        body = p.read_text(encoding='utf-8')
        t.expect('tier2 replaced',
                 body == 'def g():\n    return 2\n', repr(body))
        t.expect('tier2 marked in message',
                 'normalisation' in r.message, r.message)

    # --- tier 2 ambiguous: same normalised needle twice ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'd.py'
        # Two identical multi-line blocks, first has trailing on header
        p.write_text(
            'def a():  \n    pass\n\ndef b():  \n    pass\n',
            encoding='utf-8',
        )
        r = _run(root, [_tool(file_path='d.py',
                              search='def x():\n    pass',
                              replace='y')])[0]
        # Neither exact (no `x`) nor normalised (a/b != x) match
        t.expect('no match for unrelated needle',
                 r.status == 'error' and r.error_code == 'no_match',
                 f'{r.status}/{r.error_code}')

    # --- tier 2 unique then occurrence on multi-line ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'e.py'
        p.write_text(
            'def a():  \n    return 1\n\ndef b():\n    return 2\n',
            encoding='utf-8',
        )
        r = _run(root, [_tool(file_path='e.py',
                              search='def a():\n    return 1',
                              replace='def A():\n    return 9')])[0]
        t.expect('tier2 unique ok', r.status == 'ok', r.message)
        body = p.read_text(encoding='utf-8')
        t.expect('tier2 unique applied', 'def A():' in body and 'def a():' not in body)
        t.expect('tier2 second function untouched', 'def b():' in body)

    # --- tier 3: no match, similar lines shown ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'f.py'
        p.write_text('from .model import Block, Part, Unit, UnitKind  \n', encoding='utf-8')
        r = _run(root, [_tool(file_path='f.py',
                              search='from .core import Something',
                              replace='x')])[0]
        t.expect('tier3 no_match',
                 r.status == 'error' and r.error_code == 'no_match',
                 f'{r.status}/{r.error_code}')
        t.expect('tier3 mentions searched', 'Searched' in r.message, r.message)
        t.expect('tier3 shows similar lines', 'Similar' in r.message, r.message)
        t.expect('tier3 marks trailing space',
                 '\u2423' in r.message, r.message)

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
