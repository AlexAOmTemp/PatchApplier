'''Tests for config/workspace.py — the multi-root Workspace model.

Covers: unique basename enforcement, nesting rejection, reserved-name
collision, JSON round-trip, add_root validation, save/load, per-path
policy overrides. No Session, no backend — pure model + disk I/O.

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
        p = w.policy_for('src', '')
        t.expect('default policy for src all-True',
                 p.read and p.write and p.index_docs and p.index_py and p.index_lua)

        # --- basename collision ---
        ws.add_root(w, str(root / 'a' / 'toolkit'))
        t.expect('toolkit accepted once', 'toolkit' in w.roots)
        t.raises('second toolkit rejected',
                 lambda: ws.add_root(w, str(root / 'b' / 'toolkit')))

        # --- nesting ---
        t.raises('nesting (child under existing) rejected',
                 lambda: ws.add_root(w, str(root / 'src' / 'inner')))

        # --- reserved Roblox service ---
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
        t.raises('key must match path basename',
                 lambda: ws.validate(bad))

        # --- per-path policy in overrides ---
        r_src = w.roots['src']
        r_src.overrides['.'] = ws.PathPolicy(write=False, index_py=False)
        r_src.overrides['docs/generated'] = ws.PathPolicy(read=False)
        pol_root = w.policy_for('src', '')
        pol_gen = w.policy_for('src', 'docs/generated/x.md')
        pol_nested = w.policy_for('src', 'docs/generated')
        t.expect('root default write=False', pol_root.write is False)
        t.expect('root default read=True', pol_root.read is True)
        t.expect('root default index_py=False', pol_root.index_py is False)
        t.expect('override subpath read=False', pol_gen.read is False)
        t.expect('override inherits to child', pol_nested.read is False)
        # A PathPolicy override is a *complete* replacement, not a partial
        # merge with the root default. `docs/generated` sets read=False and
        # leaves the other four flags at PathPolicy() defaults (all True),
        # independent of the root default (write=False).
        t.expect('override is complete (write stays True, not inherited)',
                 pol_gen.write is True, str(pol_gen.write))

        # --- round-trip ---
        w.format = {'preset': 'default'}
        w.mcp = {'native_tools': {'enabled': True}}
        as_dict = ws.to_dict(w)
        w2 = ws.from_dict(as_dict)
        t.expect('round-trip id', w2.id == w.id)
        t.expect('round-trip name', w2.name == w.name)
        t.expect('round-trip roots',
                 set(w2.roots.keys()) == set(w.roots.keys()))
        t.expect('round-trip override preserved',
                 'docs/generated' in w2.roots['src'].overrides)
        t.expect('round-trip default write=False',
                 w2.policy_for('src', '').write is False)
        t.expect('round-trip format', w2.format == w.format)
        t.expect('round-trip mcp', w2.mcp == w.mcp)

        # --- from_dict of bare root (no overrides) -> all-True ---
        partial = {
            'id': 'abc', 'name': 'p',
            'roots': {'src': {'path': str(root / 'src')}},
        }
        w3 = ws.from_dict(partial)
        t.expect('from_dict empty overrides -> all True',
                 w3.policy_for('src', '').read is True)

        # --- save / load to state dir ---
        state = root / 'state'
        ok = ws.save(w, state)
        t.expect('save returns True', ok is True)
        t.expect('workspace.json written',
                 (state / 'workspace.json').is_file())
        w4 = ws.load(state)
        t.expect('load returns Workspace', w4 is not None)
        t.expect('loaded id matches', w4 is not None and w4.id == w.id)
        t.expect('loaded default write=False kept',
                 w4 is not None and w4.policy_for('src', '').write is False)

        # --- load from empty dir ---
        empty = root / 'empty-state'
        empty.mkdir()
        t.expect('load from empty dir returns None', ws.load(empty) is None)

        # --- save refuses invalid workspace ---
        bad2 = ws.Workspace(id='y', name='y')
        bad2.roots['a'] = ws.Root(path=str(root / 'src'))
        ok = ws.save(bad2, state)
        t.expect('save invalid returns False', ok is False)

    print()
    print('=== ' + str(t.passed) + ' ok, ' + str(t.failed) + ' failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
