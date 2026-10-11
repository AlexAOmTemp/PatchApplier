'''Tests for stricter content checks and unit-model edges.

Covers:
  - create_file / overwrite_file: content_syntax_error for .py/.json
  - replace_unit: empty_input_use_delete_block for part=all + empty text
  - replace_unit: part=own_body on markdown with subsections
  - get_status: roots line when workspace roots are supplied

Run: python toolkit/code/toolkit/tests/test_strictness.py
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

    # --- create_file: .py syntax error ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        r = _run(root, [{'action': 'create_file', 'arguments': {
            'file_path': 'bad.py', 'file_content': 'def foo(:\n    pass\n'
        }}])[0]
        t.expect('create .py syntax error rejected',
                 r.status == 'error' and r.error_code == 'content_syntax_error',
                 f'{r.status}/{r.error_code}')
        t.expect('file not created', not (root / 'bad.py').exists())

    # --- create_file: .py OK ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        r = _run(root, [{'action': 'create_file', 'arguments': {
            'file_path': 'good.py', 'file_content': 'x = 1\n'
        }}])[0]
        t.expect('create .py valid OK', r.status == 'ok', r.message)

    # --- create_file: .json bad ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        r = _run(root, [{'action': 'create_file', 'arguments': {
            'file_path': 'bad.json', 'file_content': '{ not json'
        }}])[0]
        t.expect('create .json syntax error rejected',
                 r.status == 'error' and r.error_code == 'content_syntax_error',
                 f'{r.status}/{r.error_code}')

    # --- create_file: .md not checked ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        r = _run(root, [{'action': 'create_file', 'arguments': {
            'file_path': 'x.md', 'file_content': '# not checked {\n'
        }}])[0]
        t.expect('create .md not checked', r.status == 'ok', r.message)

    # --- overwrite_file: .py syntax error ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'a.py').write_text('x = 1\n', encoding='utf-8')
        r = _run(root, [{'action': 'overwrite_file', 'arguments': {
            'file_path': 'a.py', 'file_content': 'def foo(:\n'
        }}])[0]
        t.expect('overwrite .py syntax error rejected',
                 r.status == 'error' and r.error_code == 'content_syntax_error',
                 f'{r.status}/{r.error_code}')
        t.expect('original preserved',
                 (root / 'a.py').read_text(encoding='utf-8') == 'x = 1\n')

    # --- scope: required / conflict ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'a.py').write_text('def foo():\n    return 1\n', encoding='utf-8')

        # Neither part nor block
        r = _run(root, [{'action': 'replace_unit', 'arguments': {
            'file_path': 'a.py',
            'address': {'qualname': 'foo'},
            'new_text': 'x',
        }}])[0]
        t.expect('scope_required when no part/block',
                 r.status == 'error' and r.error_code == 'scope_required',
                 f'{r.status}/{r.error_code}')

        # Both part and block
        r = _run(root, [{'action': 'replace_unit', 'arguments': {
            'file_path': 'a.py',
            'address': {'qualname': 'foo'},
            'part': 'body',
            'block': 1,
            'new_text': 'x',
        }}])[0]
        t.expect('scope_conflict when both part and block',
                 r.status == 'error' and r.error_code == 'scope_conflict',
                 f'{r.status}/{r.error_code}')

        # block= works through replace_unit
        r = _run(root, [{'action': 'replace_unit', 'arguments': {
            'file_path': 'a.py',
            'address': {'qualname': 'foo'},
            'block': 1,
            'new_text': 'return 42',
        }}])[0]
        t.expect('replace_unit(block=1) works', r.status == 'ok', r.message)
        body = (root / 'a.py').read_text(encoding='utf-8')
        t.expect('block replaced', 'return 42' in body and 'return 1' not in body)

        # block= with empty new_text = delete that block. Function must
        # have more than one block, or we end up with `def f():` and no body.
        (root / 'b.py').write_text(
            'def f():\n    a = 1\n    b = 2\n', encoding='utf-8')
        r = _run(root, [{'action': 'replace_unit', 'arguments': {
            'file_path': 'b.py',
            'address': {'qualname': 'f'},
            'block': 1,
            'new_text': '',
        }}])[0]
        t.expect('replace_unit(block=, empty) deletes', r.status == 'ok',
                 f'{r.status}/{r.error_code}')
        if r.status == 'ok':
            body = (root / 'b.py').read_text(encoding='utf-8')
            t.expect('first block gone', 'a = 1' not in body, repr(body))
            t.expect('second block kept', 'b = 2' in body, repr(body))

    # --- section_title resolution ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        md = (
            '# Doc\n\n'
            '## 1. Alpha section\n'
            '<!-- summary: a -->\n\n'
            'Body a.\n\n'
            '## 2. Beta section\n'
            '<!-- summary: b -->\n\n'
            'Body b.\n'
        )
        (root / 'doc.md').write_text(md, encoding='utf-8')
        r = _run(root, [{'action': 'read_unit', 'arguments': {
            'file_path': 'doc.md',
            'address': {'section_title': 'Alpha'},
            'part': 'annotation',
        }}])[0]
        t.expect('section_title by human text works',
                 r.status == 'ok' and 'a' in r.message, r.message)

        r = _run(root, [{'action': 'read_unit', 'arguments': {
            'file_path': 'doc.md',
            'address': {'section_title': 'Beta'},
            'part': 'annotation',
        }}])[0]
        t.expect('section_title finds second by title',
                 r.status == 'ok' and 'b' in r.message, r.message)

        # not_found with hint
        r = _run(root, [{'action': 'read_unit', 'arguments': {
            'file_path': 'doc.md',
            'address': {'section_title': 'Gamma'},
            'part': 'annotation',
        }}])[0]
        t.expect('unknown section_title -> not_found',
                 r.status == 'error' and r.error_code == 'not_found',
                 f'{r.status}/{r.error_code}')
        t.expect('hint mentions list_units',
                 'list_units' in r.message, r.message)

        # qualname not found -> hint
        r = _run(root, [{'action': 'read_unit', 'arguments': {
            'file_path': 'doc.md',
            'address': {'qualname': 'nosuch'},
        }}])[0]
        t.expect('unknown qualname -> not_found',
                 r.status == 'error' and r.error_code == 'not_found')
        t.expect('qualname hint mentions list_units',
                 'list_units' in r.message, r.message)

        # section_number still works
        r = _run(root, [{'action': 'read_unit', 'arguments': {
            'file_path': 'doc.md',
            'address': {'section_number': '2'},
            'part': 'annotation',
        }}])[0]
        t.expect('section_number still works',
                 r.status == 'ok' and 'b' in r.message, r.message)

    # --- replace_unit: empty + part=all ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'a.py').write_text('def foo():\n    pass\n', encoding='utf-8')
        r = _run(root, [{'action': 'replace_unit', 'arguments': {
            'file_path': 'a.py',
            'address': {'qualname': 'foo'},
            'part': 'all',
            'new_text': '',
        }}])[0]
        t.expect('empty part=all rejected with dedicated code',
                 r.status == 'error'
                 and r.error_code == 'empty_input_use_delete_block',
                 f'{r.status}/{r.error_code}')

    # --- replace_unit: own_body on markdown ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        md = (
            '# Doc\n\n'
            '## 1. First\n'
            '<!-- summary: first -->\n\n'
            'Prose part one.\n'
            'More prose.\n\n'
            '### 1.1 Sub\n'
            '<!-- summary: sub -->\n\n'
            'Sub body.\n'
        )
        (root / 'doc.md').write_text(md, encoding='utf-8')
        # read own_body: should get `Prose part one.` and `More prose.`
        # but not `Sub body.`
        r = _run(root, [{'action': 'read_unit', 'arguments': {
            'file_path': 'doc.md',
            'address': {'section_number': '1'},
            'part': 'own_body',
        }}])[0]
        t.expect('read own_body ok', r.status == 'ok', r.message)
        t.expect('own_body has prose', 'Prose part one.' in r.message, r.message)
        t.expect('own_body has second prose line', 'More prose.' in r.message)
        t.expect('own_body excludes subsection',
                 'Sub body.' not in r.message, r.message)
        t.expect('own_body excludes subsection header',
                 '### 1.1' not in r.message, r.message)

        # replace own_body: swap prose, keep subsection
        r = _run(root, [{'action': 'replace_unit', 'arguments': {
            'file_path': 'doc.md',
            'address': {'section_number': '1'},
            'part': 'own_body',
            'new_text': 'New prose.\n',
        }}])[0]
        t.expect('replace own_body ok', r.status == 'ok', r.message)
        body = (root / 'doc.md').read_text(encoding='utf-8')
        t.expect('new prose written', 'New prose.' in body, repr(body))
        t.expect('old prose gone', 'Prose part one.' not in body, repr(body))
        t.expect('subsection preserved', '### 1.1 Sub' in body, repr(body))
        t.expect('subsection body preserved', 'Sub body.' in body, repr(body))

    # --- get_status: roots line ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'x.py').write_text('x = 1\n', encoding='utf-8')
        from toolkit.tools.status import GetStatusTool
        orig = dict(GetStatusTool._context)
        try:
            GetStatusTool.set_context(
                project_name='proj',
                backend='filesystem',
                roots=['toolkit', 'docs'],
                backends_enabled={'filesystem'},
            )
            r = _run(root, [{'action': 'get_status',
                             'arguments': {'sections': 'session'}}])[0]
            t.expect('get_status ok', r.status == 'ok', r.message)
            t.expect('roots line present',
                     'roots:' in r.message and 'toolkit, docs' in r.message,
                     r.message)
        finally:
            GetStatusTool._context = orig

    print()
    print('=== ' + str(t.passed) + ' ok, ' + str(t.failed) + ' failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
