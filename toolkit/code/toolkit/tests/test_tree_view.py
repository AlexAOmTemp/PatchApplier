'''Smoke test for runner/gui/tree_view.PolicyTree (Tk widget).

Creates a hidden Tk root, builds the widget over a fake Root, renders
a few rows, simulates click cycles on cells, checks that overrides
change as documented. Not a substitute for a visual check, but catches
the common breakages: missing imports, broken state transitions,
render crashes.

Requires a display. Skipped silently if Tk cannot start.

Run: python toolkit/code/toolkit/tests/test_tree_view.py
'''
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

PASS = '[OK]  '
FAIL = '[FAIL]'
SKIP = '[SKIP]'


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
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
    except Exception as e:
        print(SKIP + ' Tk not available: ' + type(e).__name__ + ': ' + str(e))
        return 0

    t = T()

    from toolkit.config.workspace import Root
    from toolkit.runner.gui.tree_view import PolicyTree

    r = Root(path='/fake/root')
    frame = tk.Frame(root)
    w = PolicyTree(frame, r)

    paths = [
        ('code', False),
        ('code/bridge', False),
        ('docs', False),
        ('docs/generated', True),
    ]
    try:
        w.render(paths, show_hidden=False)
        t.expect('render ok (hidden filtered)', True)
    except Exception as e:
        t.expect('render ok (hidden filtered)', False, repr(e))

    t.expect('overrides starts empty', w.overrides() == {})

    w._cycle('code', 'read')
    p = w.overrides().get('code')
    t.expect('override created for code', p is not None)
    t.expect('read inverted from effective (True -> False)',
             p is not None and p.read is False)
    t.expect('other flags stayed at effective (write=True)',
             p is not None and p.write is True)

    w._cycle('code', 'read')
    p = w.overrides().get('code')
    t.expect('read flipped back to True',
             p is not None and p.read is True)

    w._cycle('code', 'write')
    p = w.overrides().get('code')
    t.expect('write now False', p is not None and p.write is False)
    t.expect('read unaffected', p is not None and p.read is True)

    w._cycle('code/bridge', 'index_py')
    pb = w.overrides().get('code/bridge')
    t.expect('nested override created', pb is not None)
    t.expect('nested index_py inverted (True -> False)',
             pb is not None and pb.index_py is False)

    try:
        w.render(paths, show_hidden=True)
        t.expect('render with show_hidden ok', True)
    except Exception as e:
        t.expect('render with show_hidden ok', False, repr(e))

    root.destroy()

    print()
    print('=== ' + str(t.passed) + ' ok, ' + str(t.failed) + ' failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
