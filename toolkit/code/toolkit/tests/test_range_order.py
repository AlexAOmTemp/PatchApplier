"""Tests for replace_range ordering rules in Patcher.apply.

Covers:
  - two replace_ranges bottom-up -> both ok
  - two replace_ranges top-down  -> second rejected (range_order)
  - replace_range after replace_in_file on the same file
        -> rejected (range_after_write)
  - replace_range after replace_unit on the same file
        -> rejected (range_after_write)
  - replace_unit after replace_range on the same file
        -> allowed (writes after ranges are content-anchored)

Run: python toolkit/code/toolkit/tests/test_range_order.py
"""
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


SAMPLE = 'line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\n'
t = T()


# --- 1. two replace_ranges, bottom-up --------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / 'a.txt').write_text(SAMPLE, encoding='utf-8')
    r = _run(root, [
        {'action': 'replace_range', 'arguments': {
            'file_path': 'a.txt', 'start_line': 7, 'end_line': 8,
            'new_content': 'NEWBOTTOM\n'}},
        {'action': 'replace_range', 'arguments': {
            'file_path': 'a.txt', 'start_line': 1, 'end_line': 2,
            'new_content': 'NEWTOP\n'}},
    ])
    t.expect('bottom-up: first ok', r[0].status == 'ok',
             f'{r[0].status}/{r[0].error_code}')
    t.expect('bottom-up: second ok', r[1].status == 'ok',
             f'{r[1].status}/{r[1].error_code}')
    out = (root / 'a.txt').read_text(encoding='utf-8')
    t.expect('both edits present',
             'NEWBOTTOM' in out and 'NEWTOP' in out,
             repr(out))


# --- 2. two replace_ranges, top-down ---------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / 'a.txt').write_text(SAMPLE, encoding='utf-8')
    r = _run(root, [
        {'action': 'replace_range', 'arguments': {
            'file_path': 'a.txt', 'start_line': 1, 'end_line': 2,
            'new_content': 'NEWTOP\n'}},
        {'action': 'replace_range', 'arguments': {
            'file_path': 'a.txt', 'start_line': 7, 'end_line': 8,
            'new_content': 'NEWBOTTOM\n'}},
    ])
    t.expect('top-down: first ok', r[0].status == 'ok',
             f'{r[0].status}/{r[0].error_code}')
    t.expect('top-down: second rejected as range_order',
             r[1].status == 'error' and r[1].error_code == 'range_order',
             f'{r[1].status}/{r[1].error_code}')


# --- 3. replace_range after replace_in_file --------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / 'a.txt').write_text(SAMPLE, encoding='utf-8')
    r = _run(root, [
        {'action': 'replace_in_file', 'arguments': {
            'file_path': 'a.txt', 'search': 'line3', 'replace': 'LINE3',
            'search_repr': False}},
        {'action': 'replace_range', 'arguments': {
            'file_path': 'a.txt', 'start_line': 7, 'end_line': 8,
            'new_content': 'NEW\n'}},
    ])
    t.expect('replace_in_file ok', r[0].status == 'ok',
             f'{r[0].status}/{r[0].error_code}')
    t.expect('replace_range after replace_in_file -> range_after_write',
             r[1].status == 'error'
             and r[1].error_code == 'range_after_write',
             f'{r[1].status}/{r[1].error_code}')


# --- 4. replace_range after replace_unit on the same file ------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / 'a.py').write_text(
        'def foo():\n    return 1\n\n\ndef bar():\n    return 2\n',
        encoding='utf-8')
    r = _run(root, [
        {'action': 'replace_unit', 'arguments': {
            'file_path': 'a.py',
            'address': {'qualname': 'foo'},
            'part': 'body',
            'new_text': '    return 42\n'}},
        {'action': 'replace_range', 'arguments': {
            'file_path': 'a.py', 'start_line': 5, 'end_line': 6,
            'new_content': 'def bar():\n    return 99\n'}},
    ])
    t.expect('replace_unit ok', r[0].status == 'ok',
             f'{r[0].status}/{r[0].error_code}')
    t.expect('replace_range after replace_unit -> range_after_write',
             r[1].status == 'error'
             and r[1].error_code == 'range_after_write',
             f'{r[1].status}/{r[1].error_code}')


# --- 5. replace_unit after replace_range: allowed --------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / 'a.py').write_text(
        'def foo():\n    return 1\n\n\ndef bar():\n    return 2\n',
        encoding='utf-8')
    r = _run(root, [
        {'action': 'replace_range', 'arguments': {
            'file_path': 'a.py', 'start_line': 5, 'end_line': 6,
            'new_content': 'def bar():\n    return 99\n'}},
        {'action': 'replace_unit', 'arguments': {
            'file_path': 'a.py',
            'address': {'qualname': 'foo'},
            'part': 'body',
            'new_text': '    return 42\n'}},
    ])
    t.expect('replace_range first: ok', r[0].status == 'ok',
             f'{r[0].status}/{r[0].error_code}')
    t.expect('replace_unit after replace_range: allowed',
             r[1].status == 'ok',
             f'{r[1].status}/{r[1].error_code}')


print(f'\n=== {t.passed} ok, {t.failed} failed ===')
sys.exit(1 if t.failed else 0)
