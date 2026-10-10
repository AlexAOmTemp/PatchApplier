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

    # --- active_flags: hide Id/Ip/Il ---
    w2 = PolicyTree(frame, r, active_flags={'read', 'write'})
    try:
        w2.render(paths, show_hidden=False)
        t.expect('render with 2 flags ok', True)
    except Exception as e:
        t.expect('render with 2 flags ok', False, repr(e))
    # id column should be absent from row_widgets
    code_widgets = w2._row_widgets.get('code', {})
    t.expect('Id cell absent when index_docs off', 'index_docs' not in code_widgets,
             str(list(code_widgets.keys())))
    t.expect('R cell present', 'read' in code_widgets)
    t.expect('W cell present', 'write' in code_widgets)

    # switch flags on the fly
    w2.set_active_flags({'read', 'write', 'index_docs'})
    w2.render(paths, show_hidden=False)
    code_widgets = w2._row_widgets.get('code', {})
    t.expect('Id cell present after enable', 'index_docs' in code_widgets)
    t.expect('Ip still absent', 'index_py' not in code_widgets)

    # overrides survive re-render
    w2._cycle('code', 'index_docs')
    t.expect('override set on index_docs',
             'code' in w2.overrides() and w2.overrides()['code'].index_docs is False)
    w2.set_active_flags({'read', 'write'})
    w2.render(paths, show_hidden=False)
    w2.set_active_flags({'read', 'write', 'index_docs'})
    w2.render(paths, show_hidden=False)
    t.expect('override survived hide+show cycle',
             w2.overrides()['code'].index_docs is False)

    root.destroy()

    print()
    print('=== ' + str(t.passed) + ' ok, ' + str(t.failed) + ' failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
