'''Tests for runner/gui/tree.py — pure tree logic.

Covers: empty input, single-level, nesting, missing intermediates,
duplicate prefixes, hidden filtering (branch removal), flatten invert.

Run: python toolkit/code/toolkit/tests/test_tree.py
'''
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.runner.gui.tree import build_tree, filter_hidden, flatten


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


def main():
    t = T()

    # --- empty ---
    t.expect('empty input -> empty output',
             build_tree([]) == [])

    # --- single level ---
    tree = build_tree([('code', False), ('docs', False)])
    t.expect('two top-level nodes', len(tree) == 2)
    t.expect('first is code', tree[0]['name'] == 'code')
    t.expect('second is docs', tree[1]['name'] == 'docs')
    t.expect('both have empty children',
             tree[0]['children'] == [] and tree[1]['children'] == [])

    # --- nesting ---
    tree = build_tree([
        ('code', False),
        ('code/bridge', False),
        ('code/toolkit', False),
        ('code/toolkit/backends', False),
        ('docs', False),
    ])
    t.expect('code node has 2 children', len(tree[0]['children']) == 2)
    t.expect('code/bridge child', tree[0]['children'][0]['name'] == 'bridge')
    t.expect('code/toolkit child', tree[0]['children'][1]['name'] == 'toolkit')
    t.expect('code/toolkit has backends',
             tree[0]['children'][1]['children'][0]['name'] == 'backends')
    t.expect('docs has no children', tree[1]['children'] == [])

    # --- missing intermediate: a/b/c alone -> chain a -> b -> c ---
    tree = build_tree([('a/b/c', False)])
    t.expect('auto-create a', len(tree) == 1 and tree[0]['name'] == 'a')
    t.expect('auto-create a/b', tree[0]['children'][0]['name'] == 'b')
    t.expect('auto-create a/b/c',
             tree[0]['children'][0]['children'][0]['name'] == 'c')

    # --- duplicate prefix merge ---
    tree = build_tree([('code', False), ('code', False)])
    t.expect('duplicate prefix merged, not added twice', len(tree) == 1)
    t.expect('merged node is code', tree[0]['name'] == 'code')

    # --- order preserved ---
    tree = build_tree([('zeta', False), ('alpha', False), ('mike', False)])
    t.expect('order preserved (not alphabetical)',
             [n['name'] for n in tree] == ['zeta', 'alpha', 'mike'])

    # --- backslash normalisation ---
    tree = build_tree([('a\\b\\c', False)])
    t.expect('backslash path splits correctly',
             tree[0]['name'] == 'a' and tree[0]['children'][0]['name'] == 'b')

    # --- leading/trailing slashes ignored ---
    tree = build_tree([('/code/', False)])
    t.expect('leading/trailing slashes ignored',
             tree[0]['name'] == 'code')

    # --- empty segments ignored ---
    tree = build_tree([('a//b', False)])
    t.expect('double slash ignored',
             tree[0]['name'] == 'a' and tree[0]['children'][0]['name'] == 'b')

    # --- filter_hidden ---
    tree = build_tree([
        ('code', False),
        ('.git', True),
        ('.git/objects', True),
        ('docs', False),
        ('docs/generated', True),
        ('docs/generated/sub', True),
    ])
    filtered = filter_hidden(tree)
    names = [n['name'] for n in filtered]
    t.expect('filter removes .git', '.git' not in names)
    t.expect('filter keeps code', 'code' in names)
    t.expect('filter keeps docs', 'docs' in names)
    docs_node = next(n for n in filtered if n['name'] == 'docs')
    t.expect('docs/generated removed',
             'generated' not in [c['name'] for c in docs_node['children']])

    # --- filter_hidden on non-hidden subtree ---
    tree = build_tree([
        ('a', False),
        ('a/keep', False),
        ('a/drop', True),
    ])
    filtered = filter_hidden(tree)
    a_children = [c['name'] for c in filtered[0]['children']]
    t.expect('drop removed from a', 'drop' not in a_children)
    t.expect('keep still under a', 'keep' in a_children)

    # --- flatten inverts build_tree ---
    source = [('code', False), ('code/toolkit', False), ('docs', False)]
    tree = build_tree(source)
    flat = flatten(tree)
    t.expect('flatten matches input', flat == source,
             str(flat) + ' vs ' + str(source))

    print()
    print('=== ' + str(t.passed) + ' ok, ' + str(t.failed) + ' failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
