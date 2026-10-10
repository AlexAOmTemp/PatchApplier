'''Tests for WorkspaceBackend (read-only skeleton, step 3).

Covers: path routing <basename>/<rel>, read/exists/stat/list, list("") ->
basenames, unknown root, write raises NotImplementedError, filter_check
(policy on full path + patchignore on rel). No Session, no composite.

Run: python toolkit/code/toolkit/tests/test_workspace_backend.py
'''
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.backends.workspace import WorkspaceBackend
from toolkit.config import workspace as ws_mod
from toolkit.core import FilterSpec


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

    def raises(self, label, fn, kind):
        try:
            fn()
        except kind as e:
            print(PASS + ' ' + label + ' (' + type(e).__name__ + ')')
            self.passed += 1
            return
        except Exception as e:
            print(FAIL + ' ' + label + ' -- wrong exc ' + repr(e))
            self.failed += 1
            return
        print(FAIL + ' ' + label + ' -- no exception')
        self.failed += 1


def main():
    t = T()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'alpha').mkdir()
        (root / 'beta').mkdir()
        (root / 'state').mkdir()
        (root / 'alpha' / 'hello.txt').write_text('hi alpha', encoding='utf-8')
        (root / 'alpha' / 'sub').mkdir()
        (root / 'alpha' / 'sub' / 'deep.txt').write_text('deep', encoding='utf-8')
        (root / 'beta' / 'hello.txt').write_text('hi beta', encoding='utf-8')

        w = ws_mod.Workspace(id='t', name='t')
        ws_mod.add_root(w, str(root / 'alpha'))
        ws_mod.add_root(w, str(root / 'beta'))

        wb = WorkspaceBackend(w, root / 'state')
        wb.open()

        # --- read ---
        t.expect('read alpha/hello.txt', wb.read('alpha/hello.txt') == 'hi alpha')
        t.expect('read beta/hello.txt', wb.read('beta/hello.txt') == 'hi beta')
        t.raises('read unknown root -> FileNotFoundError',
                 lambda: wb.read('gamma/x.txt'), FileNotFoundError)

        # --- exists ---
        t.expect('exists alpha/hello.txt', wb.exists('alpha/hello.txt') is True)
        t.expect('exists alpha/nope.txt', wb.exists('alpha/nope.txt') is False)
        t.expect('exists unknown root -> False', wb.exists('gamma/x.txt') is False)

        # --- list("") ---
        names = wb.list('')
        t.expect('list("") returns sorted basenames',
                 names == ['alpha', 'beta'], str(names))

        # --- list("alpha") ---
        files = wb.list('alpha')
        t.expect('list("alpha") prefixes with basename',
                 'alpha/hello.txt' in files, str(files))
        t.expect('list("alpha") includes nested',
                 'alpha/sub/deep.txt' in files, str(files))
        t.expect('list("alpha") excludes beta',
                 not any('beta' in f for f in files))

        # --- list("gamma") on unknown root ---
        t.expect('list unknown root -> empty', wb.list('gamma') == [])

        # --- stat ---
        st = wb.stat('alpha/hello.txt')
        t.expect('stat size', st.size_bytes == 8, str(st.size_bytes))
        t.expect('stat is_file', st.is_file is True)

        # --- write is not implemented ---
        t.raises('write raises NotImplementedError',
                 lambda: wb.write('alpha/new.txt', 'x'),
                 NotImplementedError)
        t.raises('delete raises NotImplementedError',
                 lambda: wb.delete('alpha/hello.txt'),
                 NotImplementedError)
        t.raises('move raises NotImplementedError',
                 lambda: wb.move('alpha/a.txt', 'alpha/b.txt'),
                 NotImplementedError)
        t.raises('copy raises NotImplementedError',
                 lambda: wb.copy('alpha/a.txt', 'beta/a.txt'),
                 NotImplementedError)

        # --- filter_check: policy on full <basename>/<rel> ---
        spec = FilterSpec(overrides={'alpha': False})
        t.expect('filter blocks alpha path',
                 wb.filter_check('alpha/hello.txt', spec) is not None)
        t.expect('filter allows beta path',
                 wb.filter_check('beta/hello.txt', spec) is None)

        # --- filter_check: unknown root ---
        t.expect('filter blocks unknown root',
                 wb.filter_check('gamma/x.txt', FilterSpec()) is not None)

        # --- filter_check: .patchignore from state_dir ---
        (root / 'state' / '.patchignore').write_text('secret\n',
                                                     encoding='utf-8')
        wb.reload_patterns()
        t.expect('filter blocks hidden via state .patchignore',
                 wb.filter_check('alpha/secret/x.txt', FilterSpec()) is not None,
                 'expected hidden')
        t.expect('filter allows non-hidden path',
                 wb.filter_check('alpha/hello.txt', FilterSpec()) is None)

        wb.close()

    print()
    print('=== ' + str(t.passed) + ' ok, ' + str(t.failed) + ' failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
