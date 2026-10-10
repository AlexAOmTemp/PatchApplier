'''Regression tests for unit-model line bounds (off-by-one audit).

Covers:
  - md: replace_unit part=body must not eat the next section heading
  - md: sibling sections must not overlap in line ranges
  - py: module head must not include the first def's decorator line
  - py: unit head.end < body.start (no head/body overlap)
  - py: decorated method in class must not overlap sibling method
  - lua: sibling top-level functions must not overlap

Run: python toolkit/code/toolkit/tests/test_unit_bounds.py
'''
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.tools.unit import reader
from toolkit.tools.unit.adapter_md import build as build_md
from toolkit.tools.unit.adapter_py import build as build_py
from toolkit.tools.unit.adapter_lua import build as build_lua


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


def siblings_disjoint(root):
    '''Sibling units (children of same parent) must not share line ranges.'''
    problems = []

    def walk(u):
        units = [b.unit for b in u.blocks if b.unit is not None]
        units.sort(key=lambda x: x.line_start)
        for a, b in zip(units, units[1:]):
            if a.line_end >= b.line_start:
                problems.append((a.qualname, a.line_end, b.qualname, b.line_start))
        for c in units:
            walk(c)

    walk(root)
    return problems


def head_body_disjoint(root):
    '''For every unit: head.end must be < body.start (when both present).'''
    problems = []

    def walk(u):
        if u.head.is_present() and u.body.is_present():
            if u.head.end >= u.body.start:
                problems.append((u.qualname, u.head.end, u.body.start))
        for b in u.blocks:
            if b.unit is not None:
                walk(b.unit)

    walk(root)
    return problems


def module_head_vs_first_block(root):
    '''Module: head must end strictly before the first block's start.
    Decorator of the first def/class belongs to the block, not to head.'''
    if not root.blocks:
        return None
    first = root.blocks[0]
    if not root.head.is_present():
        return None
    if root.head.end >= first.start:
        return (root.head.end, first.start)
    return None


MD = [
    '# Index', '',
    '## 1. First', '<!-- summary: first -->', 'Body one.', '',
    '## 2. Second', '<!-- summary: second -->', 'Body two.', '',
    '## 3. Third', '<!-- summary: third -->', 'Body three.', '',
]
MD_SAMPLE = chr(10).join(MD)

# Line numbers (1-based) for PY_DEC_SAMPLE:
#   1: import os
#   2: (blank)
#   3: CONST = 1
#   4: (blank)
#   5: (blank)
#   6: @staticmethod
#   7: def f():
#   8:     return 1
#   9: (blank)
#  10: (blank)
#  11: def g():
#  12:     return 2
PY_DEC = [
    'import os', '',
    'CONST = 1', '', '',
    '@staticmethod',
    'def f():',
    '    return 1', '', '',
    'def g():',
    '    return 2', '',
]
PY_DEC_SAMPLE = chr(10).join(PY_DEC)

PY_CLS = [
    'class C:',
    '    @staticmethod',
    '    def f():',
    '        return 1',
    '',
    '    def g(self):',
    '        return 2',
    '',
]
PY_CLS_SAMPLE = chr(10).join(PY_CLS)

LUA = [
    'local M = {}', '',
    'function M.a()', '    return 1', 'end', '',
    'function M.b()', '    return 2', 'end', '',
    'return M', '',
]
LUA_SAMPLE = chr(10).join(LUA)


def main():
    t = T()

    # --- md ---
    root = build_md(MD_SAMPLE, 'doc.md')
    probs = siblings_disjoint(root)
    t.expect('md: no sibling overlap', not probs, str(probs))
    probs = head_body_disjoint(root)
    t.expect('md: no head/body overlap', not probs, str(probs))
    sec2 = next(u for u in reader._iter_units(root) if u.qualname == '2')
    sec3 = next(u for u in reader._iter_units(root) if u.qualname == '3')
    body_text = reader._slice(MD_SAMPLE, sec2.body)
    t.expect('md: sec2 body excludes ## 3', '## 3' not in body_text,
             repr(body_text))
    t.expect('md: sec2 body has Body two.', 'Body two.' in body_text)
    t.expect('md: sec2.line_end < sec3.line_start',
             sec2.line_end < sec3.line_start,
             str(sec2.line_end) + ' vs ' + str(sec3.line_start))

    # --- py: decorated first def ---
    root = build_py(PY_DEC_SAMPLE, 'a.py')
    probs = siblings_disjoint(root)
    t.expect('py: no sibling overlap (decorated first def)',
             not probs, str(probs))
    probs = head_body_disjoint(root)
    t.expect('py: no head/body overlap (decorated first def)',
             not probs, str(probs))
    # Module head must end before the first def's decorator line (line 6).
    mhb = module_head_vs_first_block(root)
    t.expect('py: module head does not include @staticmethod',
             mhb is None, str(mhb))
    # First block must start exactly at the decorator line (line 6).
    first_block_start = root.blocks[0].start
    t.expect('py: first block starts at decorator line',
             first_block_start == 6, str(first_block_start))
    # f.head includes decorator AND def line (this is correct by design).
    f = next(u for u in reader._iter_units(root) if u.qualname == 'f')
    head_text = reader._slice(PY_DEC_SAMPLE, f.head)
    t.expect('py: f.head has decorator and def (by design)',
             '@staticmethod' in head_text and 'def f():' in head_text,
             repr(head_text))
    # f.body excludes decorator and def line.
    body_text = reader._slice(PY_DEC_SAMPLE, f.body)
    t.expect('py: f.body excludes decorator',
             '@staticmethod' not in body_text, repr(body_text))
    t.expect('py: f.body excludes def line',
             'def f():' not in body_text, repr(body_text))

    # --- py: decorated method in class ---
    root = build_py(PY_CLS_SAMPLE, 'b.py')
    probs = siblings_disjoint(root)
    t.expect('py class: no sibling overlap (decorated method)',
             not probs, str(probs))
    probs = head_body_disjoint(root)
    t.expect('py class: no head/body overlap (decorated method)',
             not probs, str(probs))

    # --- lua ---
    root = build_lua(LUA_SAMPLE, 'm.lua')
    probs = siblings_disjoint(root)
    t.expect('lua: no sibling overlap (two funcs)', not probs, str(probs))
    probs = head_body_disjoint(root)
    t.expect('lua: no head/body overlap', not probs, str(probs))

    print()
    print('=== ' + str(t.passed) + ' ok, ' + str(t.failed) + ' failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
