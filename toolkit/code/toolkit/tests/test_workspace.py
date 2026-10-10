'''Tests for config/workspace.py — the multi-root Workspace model.

Covers: unique basename enforcement, nesting rejection, reserved-name
collision, JSON round-trip, add_root validation, save/load. No Session,
no backend — pure model + disk I/O.

Run: python toolkit/code/toolkit/tests/test_workspace.py
'''
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.config import workspace as ws


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

    def raises(self, label, fn, kind=ValueError):
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
        (root / 'a' / 'toolkit').mkdir(parents=True)
        (root / 'b' / 'toolkit').mkdir(parents=True)
        (root / 'src').mkdir()
        (root / 'src' / 'inner').mkdir()

        # --- identity ---
        w = ws.Workspace(id=ws.new_id(), name='t')
        t.expect('new_id is 12 hex',
                 len(w.id) == 12 and all(c in '0123456789abcdef' for c in w.id),
                 w.id)

        # --- add_root: basic ---
        name = ws.add_root(w, str(root / 'src'))
        t.expect('add_root returns basename', name == 'src', name)
        t.expect('roots has src', 'src' in w.roots)
        t.expect('policy default for src',
                 w.policy['src'].read and w.policy['src'].write
                 and w.policy['src'].index_docs
                 and w.policy['src'].index_py
                 and w.policy['src'].index_lua)

        # --- basename collision ---
        ws.add_root(w, str(root / 'a' / 'toolkit'))
        t.expect('toolkit accepted once', 'toolkit' in w.roots)
        t.raises('second toolkit rejected',
                 lambda: ws.add_root(w, str(root / 'b' / 'toolkit')))

        # --- nesting ---
        t.raises('nesting (child under existing) rejected',
                 lambda: ws.add_root(w, str(root / 'src' / 'inner')))

        # --- reserved Roblox service ---
        # Only fires if core.paths exposes ROBLOX_SERVICES. Probe for one
        # of the common names, create a dir with that basename, try to add.
        probe_svc = None
        try:
            from toolkit.core.paths import ROBLOX_SERVICES
            for cand in ('ReplicatedStorage', 'ServerScriptService', 'Workspace'):
                if cand in ROBLOX_SERVICES:
                    probe_svc = cand
                    break
        except Exception:
            probe_svc = None
        if probe_svc:
            (root / probe_svc).mkdir(exist_ok=True)
            t.raises('reserved Roblox service name rejected',
                     lambda: ws.add_root(w, str(root / probe_svc)))
        else:
            print('  (skip: ROBLOX_SERVICES not importable)')

        # --- validate: name does not match basename ---
        bad = ws.Workspace(id='x', name='x')
        bad.roots['notmatching'] = ws.Root(path=str(root / 'src'))
        bad.policy['notmatching'] = ws.RootPolicy()
        t.raises('key must match path basename',
                 lambda: ws.validate(bad))

        # --- round-trip ---
        w.policy['src'].write = False
        w.policy['src'].index_py = False
        w.format = {'preset': 'default'}
        w.mcp = {'native_tools': {'enabled': True}}
        as_dict = ws.to_dict(w)
        w2 = ws.from_dict(as_dict)
        t.expect('round-trip id', w2.id == w.id)
        t.expect('round-trip name', w2.name == w.name)
        t.expect('round-trip roots',
                 set(w2.roots.keys()) == set(w.roots.keys()))
        t.expect('round-trip policy flags',
                 w2.policy['src'].write is False
                 and w2.policy['src'].index_py is False
                 and w2.policy['src'].read is True
                 and w2.policy['src'].index_lua is True)
        t.expect('round-trip format', w2.format == w.format)
        t.expect('round-trip mcp', w2.mcp == w.mcp)

        # --- from_dict fills missing policy ---
        partial = {
            'id': 'abc', 'name': 'p',
            'roots': {'src': {'path': str(root / 'src')}},
        }
        w3 = ws.from_dict(partial)
        t.expect('from_dict fills missing policy',
                 'src' in w3.policy and w3.policy['src'].read)

        # --- save / load to state dir ---
        state = root / 'state'
        ok = ws.save(w, state)
        t.expect('save returns True', ok is True)
        t.expect('workspace.json written',
                 (state / 'workspace.json').is_file())
        w4 = ws.load(state)
        t.expect('load returns Workspace', w4 is not None)
        t.expect('loaded id matches', w4 is not None and w4.id == w.id)
        t.expect('loaded policy write=False kept',
                 w4 is not None and w4.policy['src'].write is False)

        # --- load from empty dir ---
        empty = root / 'empty-state'
        empty.mkdir()
        t.expect('load from empty dir returns None', ws.load(empty) is None)

        # --- save refuses invalid workspace ---
        bad2 = ws.Workspace(id='y', name='y')
        bad2.roots['a'] = ws.Root(path=str(root / 'src'))
        bad2.policy['a'] = ws.RootPolicy()
        ok = ws.save(bad2, state)
        t.expect('save invalid returns False', ok is False)

    print()
    print('=== ' + str(t.passed) + ' ok, ' + str(t.failed) + ' failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
