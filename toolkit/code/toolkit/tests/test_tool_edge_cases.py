'''Regression tests for tool edge cases (from TOOL_PRACTICE.md §8).

Covers:
  - insert_at_anchor: auto-\n between anchor and content (line-gluing guard)
  - insert_at_anchor: no double-\n when boundary already present
  - replace_between: anchor EOL normalisation (LF anchor in CRLF file)

Run: python toolkit/code/toolkit/tests/test_tool_edge_cases.py
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


def main():
    t = T()

    # --- insert_at_anchor: line-gluing guard ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'a.py'
        p.write_text('from .model import Foo\nfrom .bar import Baz\n', encoding='utf-8')
        r = _run(root, [{
            'action': 'insert_at_anchor',
            'arguments': {
                'file_path': 'a.py',
                'anchor': 'from .model import Foo',
                'position': 'after',
                'new_content': 'from .extra import Qux',
            },
        }])[0]
        t.expect('insert ok (no explicit \\n)', r.status == 'ok', r.message)
        body = p.read_text(encoding='utf-8')
        t.expect('newline inserted between anchor and content',
                 'Foo\nfrom .extra import Qux\n' in body, repr(body))
        t.expect('second import line intact',
                 'from .bar import Baz' in body)

    # --- insert_at_anchor: no double \n when already present ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'b.py'
        p.write_text('X = 1\n\nY = 2\n', encoding='utf-8')
        r = _run(root, [{
            'action': 'insert_at_anchor',
            'arguments': {
                'file_path': 'b.py',
                'anchor': 'X = 1',
                'position': 'after',
                'new_content': '\nZ = 3',
            },
        }])[0]
        t.expect('insert ok (\n in content)', r.status == 'ok', r.message)
        body = p.read_text(encoding='utf-8')
        t.expect('no double newline',
                 'X = 1\nZ = 3\n' in body, repr(body))

    # --- insert_at_anchor: before, end-of-line boundary ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'c.py'
        p.write_text('A = 1\nB = 2\n', encoding='utf-8')
        r = _run(root, [{
            'action': 'insert_at_anchor',
            'arguments': {
                'file_path': 'c.py',
                'anchor': 'B = 2',
                'position': 'before',
                'new_content': 'M = 9',
            },
        }])[0]
        t.expect('insert before ok', r.status == 'ok', r.message)
        body = p.read_text(encoding='utf-8')
        t.expect('before: newline added after content',
                 'M = 9\nB = 2' in body, repr(body))

    # --- replace_between: LF anchor in CRLF file ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'd.py'
        p.write_bytes(b'A = 1\r\nB = 2\r\nC = 3\r\n')
        r = _run(root, [{
            'action': 'replace_between',
            'arguments': {
                'file_path': 'd.py',
                'start_anchor': 'A = 1',
                'end_anchor': 'C = 3',
                'new_content': 'X = 9',
            },
        }])[0]
        t.expect('replace_between ok', r.status == 'ok', r.message)
        body = p.read_bytes()
        t.expect('block replaced',
                 b'X = 9' in body and b'B = 2' not in body, repr(body))

    # --- replace_between: LF anchor with \n inside, in CRLF file ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'e.py'
        p.write_bytes(b'# start\r\nA = 1\r\nB = 2\r\n# end\r\n')
        # anchor with embedded \n written as LF (the normal case)
        r = _run(root, [{
            'action': 'replace_between',
            'arguments': {
                'file_path': 'e.py',
                'start_anchor': '# start\nA = 1',
                'end_anchor': '# end',
                'new_content': '# replaced\n',
            },
        }])[0]
        t.expect('multi-line LF anchor matches CRLF file',
                 r.status == 'ok', r.message)
        body = p.read_bytes()
        t.expect('block replaced',
                 b'# replaced' in body and b'A = 1' not in body, repr(body))

    print()
    print('=== ' + str(t.passed) + ' ok, ' + str(t.failed) + ' failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
