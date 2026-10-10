"""Tests for Lua symbol tools (list/read/replace)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

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
            print(f'{PASS} {label}')
            self.passed += 1
        else:
            print(f'{FAIL} {label}' + (f' -- {detail}' if detail else ''))
            self.failed += 1


def _run(root, patches, policy=None):
    backend = FilesystemBackend(root)
    fmt = Format.load('default')
    with Session(backend, fmt=fmt, tools=TOOL_MAP,
                 policy=policy or Policy()) as s:
        return s.apply_patches(patches)


SEED = (
    '-- Sample Lua module\n'
    'local M = {}\n'
    '\n'
    'function M.hello(name)\n'
    '    return "hello " .. name\n'
    'end\n'
    '\n'
    'function M:method(x)\n'
    '    return self.value + x\n'
    'end\n'
    '\n'
    'local function helper(a, b)\n'
    '    return a + b\n'
    'end\n'
    '\n'
    'M.assigned = function(y)\n'
    '    return y * 2\n'
    'end\n'
    '\n'
    'local anon = function(z)\n'
    '    return z\n'
    'end\n'
    '\n'
    'return M\n'
)


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / 'sample.lua'
        p.write_text(SEED, encoding='utf-8')

        print('== list_symbols_lua ==')
        r = _run(root, [{'action': 'list_symbols_lua',
                         'arguments': {'file_path': 'sample.lua'}}])[0]
        t.expect('ok', r.status == 'ok', f'{r.status}: {r.message}')
        for qn in ('M.hello', 'M:method', 'helper', 'M.assigned', 'anon'):
            t.expect(f'has {qn}', qn in r.message)
        t.expect('kind [function]', '[function]' in r.message)
        t.expect('kind [method]', '[method]' in r.message)
        t.expect('kind [local_function]', '[local_function]' in r.message)
        t.expect('kind [assigned]', '[assigned]' in r.message)

        print()
        print('== read_symbol_lua: M.hello ==')
        r = _run(root, [{'action': 'read_symbol_lua',
                         'arguments': {'file_path': 'sample.lua',
                                       'qualname': 'M.hello'}}])[0]
        t.expect('ok', r.status == 'ok', f'{r.status}: {r.message}')
        t.expect('body has function M.hello',
                 'function M.hello' in r.message)
        t.expect('body has return', 'return' in r.message)
        t.expect('no helper', 'local function helper' not in r.message)
        t.expect('no M:method', 'function M:method' not in r.message)

        print()
        print('== read_symbol_lua: M:method ==')
        r = _run(root, [{'action': 'read_symbol_lua',
                         'arguments': {'file_path': 'sample.lua',
                                       'qualname': 'M:method'}}])[0]
        t.expect('ok', r.status == 'ok', f'{r.status}: {r.message}')
        t.expect('body has function M:method',
                 'function M:method' in r.message)

        print()
        print('== read_symbol_lua: local_function helper ==')
        r = _run(root, [{'action': 'read_symbol_lua',
                         'arguments': {'file_path': 'sample.lua',
                                       'qualname': 'helper'}}])[0]
        t.expect('ok', r.status == 'ok', f'{r.status}: {r.message}')
        t.expect('body has local function helper',
                 'local function helper' in r.message)

        print()
        print('== read_symbol_lua: not found ==')
        r = _run(root, [{'action': 'read_symbol_lua',
                         'arguments': {'file_path': 'sample.lua',
                                       'qualname': 'nope'}}])[0]
        t.expect('error', r.status == 'error')
        t.expect('error_code not_found', r.error_code == 'not_found')

        print()
        print('== replace_function_lua ==')
        new_hello = (
            'function M.hello(name)\n'
            '    return "hi " .. name\n'
            'end'
        )
        r = _run(root, [{'action': 'replace_function_lua',
                         'arguments': {'file_path': 'sample.lua',
                                       'qualname': 'M.hello',
                                       'new_code': new_hello}}])[0]
        t.expect('ok', r.status == 'ok', f'{r.status}: {r.message}')
        t.expect('delta present', r.delta is not None)
        content = p.read_text(encoding='utf-8')
        t.expect('new body present', '"hi "' in content)
        t.expect('old body gone', '"hello "' not in content)
        t.expect('M:method intact', 'function M:method' in content)
        t.expect('helper intact', 'local function helper' in content)
        t.expect('M.assigned intact', 'M.assigned = function' in content)

        print()
        print('== replace_function_lua: bad new_code rejected ==')
        before = p.read_text(encoding='utf-8')
        r = _run(root, [{'action': 'replace_function_lua',
                         'arguments': {
                             'file_path': 'sample.lua',
                             'qualname': 'M.hello',
                             'new_code': 'function M.hello( -- unterminated',
                         }}])[0]
        t.expect('error', r.status == 'error')
        t.expect('error_code result_*',
                 r.error_code in ('result_parse_error',
                                  'result_missing_symbol'),
                 r.error_code)
        after = p.read_text(encoding='utf-8')
        t.expect('file unchanged', before == after)

        print()
        print('== replace_function_lua: empty rejected ==')
        r = _run(root, [{'action': 'replace_function_lua',
                         'arguments': {'file_path': 'sample.lua',
                                       'qualname': 'M.hello',
                                       'new_code': ''}}])[0]
        t.expect('error', r.status == 'error')
        t.expect('error_code empty_input', r.error_code == 'empty_input')

        print()
        print('== filter blocks replace_function_lua ==')
        policy = Policy.uniform(mode='white', paths=['sub'])
        r = _run(root, [{'action': 'replace_function_lua',
                         'arguments': {
                             'file_path': 'sample.lua',
                             'qualname': 'M.hello',
                             'new_code': 'function M.hello() return nil end',
                         }}], policy)[0]
        t.expect('blocked', r.status == 'blocked', r.status)

        print()
        print('== replace_function_lua: M:method ==')
        new_method = (
            'function M:method(x)\n'
            '    return self.value - x\n'
            'end'
        )
        r = _run(root, [{'action': 'replace_function_lua',
                         'arguments': {'file_path': 'sample.lua',
                                       'qualname': 'M:method',
                                       'new_code': new_method}}])[0]
        t.expect('ok', r.status == 'ok', f'{r.status}: {r.message}')
        content = p.read_text(encoding='utf-8')
        t.expect('method body updated', 'self.value - x' in content)

    print()
    if t.failed:
        print(f'=== ======: {t.passed} ok, {t.failed} failed ===')
        return 1
    print(f'=== ======: {t.passed} ok ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
