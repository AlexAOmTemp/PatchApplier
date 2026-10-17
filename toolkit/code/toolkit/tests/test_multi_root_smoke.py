'''End-to-end multi-root smoke: 2+ roots, rebuild_index / rebuild_code_index.

Creates a temp project with two roots (`alpha` and `beta`), runs both
rebuilders through Session, and checks that the produced indexes contain
files from both roots, with `<basename>/<rel>` paths.

This is the live check that `test_workspace_backend.py` covers only in
isolation (list/read/filter). Here the whole pipeline runs: Workspace →
MultiRootFsBackend → Session → RebuildIndexTool → INDEX.md.

Run: python toolkit/code/toolkit/tests/test_multi_root_smoke.py
'''
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.config import workspace as ws_mod
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


def _run(session, patches):
    return session.apply_patches(patches)


def main():
    t = T()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # --- two roots ---
        alpha = root / 'alpha'
        beta = root / 'beta'
        alpha.mkdir(); beta.mkdir()
        (alpha / 'a.py').write_text('def alpha_fn():\n    return 1\n', encoding='utf-8')
        (beta / 'b.py').write_text('def beta_fn():\n    return 2\n', encoding='utf-8')
        (alpha / 'a.md').write_text('# Alpha\n\n## 1. One\n<!-- summary: a -->\n\nbody a\n', encoding='utf-8')
        (beta / 'b.md').write_text('# Beta\n\n## 1. One\n<!-- summary: b -->\n\nbody b\n', encoding='utf-8')

        # --- project state dir with workspace.json ---
        project = root / 'project'
        state = project / '.patch_applier'
        state.mkdir(parents=True)
        w = ws_mod.Workspace(id='test', name='multi')
        ws_mod.add_root(w, str(alpha))
        ws_mod.add_root(w, str(beta))
        if not ws_mod.save(w, state):
            print('[FAIL] could not save workspace')
            return 1

        # --- open workspace backend ---
        wb = MultiRootFsBackend(w, state)
        wb.open()
        try:
            # sanity: list across roots
            files = wb.list('')
            t.expect('list includes alpha/a.py',
                     'alpha/a.py' in files, str(files))
            t.expect('list includes beta/b.py',
                     'beta/b.py' in files, str(files))
            t.expect('list includes alpha/a.md',
                     'alpha/a.md' in files, str(files))
            t.expect('list includes beta/b.md',
                     'beta/b.md' in files, str(files))

            # --- Session with tools ---
            fmt = Format.load('default')
            with Session(wb, fmt=fmt, tools=TOOL_MAP) as s:
                # --- rebuild docs index ---
                print()
                print('== rebuild_index (docs) ==')
                r = _run(s, [{
                    'action': 'rebuild_index',
                    'arguments': {'output': '.patch_applier/INDEX.md'},
                }])[0]
                t.expect('rebuild_index ok', r.status == 'ok',
                         f'{r.status}: {r.message}')
                idx_text = (state / 'INDEX.md').read_text(encoding='utf-8')
                t.expect('INDEX has alpha/a.md',
                         'alpha/a.md' in idx_text)
                t.expect('INDEX has beta/b.md',
                         'beta/b.md' in idx_text)
                t.expect('INDEX does NOT have bare a.md without prefix',
                         '## alpha/a.md' in idx_text and '## beta/b.md' in idx_text)

                # --- rebuild code index ---
                print()
                print('== rebuild_code_index ==')
                r = _run(s, [{
                    'action': 'rebuild_code_index',
                    'arguments': {
                        'output': '.patch_applier/CODE_INDEX.md',
                        'manifest_output': '.patch_applier/CODE_INDEX.manifest.json',
                    },
                }])[0]
                t.expect('rebuild_code_index ok', r.status == 'ok',
                         f'{r.status}: {r.message}')
                ci_text = (state / 'CODE_INDEX.md').read_text(encoding='utf-8')
                t.expect('CODE_INDEX has alpha/a.py',
                         'alpha/a.py' in ci_text)
                t.expect('CODE_INDEX has beta/b.py',
                         'beta/b.py' in ci_text)
                # --- symbol visibility: alpha_fn from alpha, beta_fn from beta
                t.expect('alpha_fn symbol', 'alpha_fn' in ci_text)
                t.expect('beta_fn symbol', 'beta_fn' in ci_text)

                # --- filter: turn off a root, rebuild, ensure it disappears ---
                print()
                print('== disable beta → beta gone from index ==')
                w.roots['beta'].overrides['.'] = ws_mod.PathPolicy(
                    index_docs=False, index_py=False)
                r = _run(s, [{
                    'action': 'rebuild_index',
                    'arguments': {'output': '.patch_applier/INDEX.md'},
                }])[0]
                t.expect('rebuild after disable ok', r.status == 'ok', r.message)
                idx_text2 = (state / 'INDEX.md').read_text(encoding='utf-8')
                t.expect('beta gone from INDEX',
                         'beta/b.md' not in idx_text2, idx_text2[:200])
                t.expect('alpha still in INDEX',
                         'alpha/a.md' in idx_text2)
        finally:
            wb.close()

    print()
    print('=== ' + str(t.passed) + ' ok, ' + str(t.failed) + ' failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
