"""Tests for the C# indexer and the rebuild_csharp_index tool."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.backends import RootDirBackend
from toolkit.core import Session
from toolkit.formats import Format
from toolkit.indexers.csharp import build_csharp_index
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


CS = '''using System;
using System.Collections.Generic;

namespace Game.Core
{
    /// <summary>Player.</summary>
    public partial class Player
    {
        private int _hp;

        public void Damage(int amount)
        {
            _hp -= amount;
        }

        public class Inventory
        {
            public void Add(string item) { }
        }
    }
}
'''

BAD = 'class Broken { void M( { } }\n'


def _run(root: Path, patches):
    backend = RootDirBackend(root)
    fmt = Format.load('default')
    with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:
        return s.apply_patches(patches)


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'Player.cs').write_text(CS, encoding='utf-8')
        (root / 'Broken.cs').write_text(BAD, encoding='utf-8')
        (root / 'obj').mkdir()
        (root / 'obj' / 'Gen.cs').write_text('class Gen { }\n', encoding='utf-8')

        r = build_csharp_index(RootDirBackend(root))
        t.expect('broken .cs skipped', r.modules_count == 1, r.modules_count)
        t.expect('obj/ skipped',
                 [m.path for m in r.modules] == ['Player.cs'],
                 [m.path for m in r.modules])

        m = r.modules[0]
        t.expect('usings captured', len(m.imports) == 2, m.imports)
        qns = [s.qualname for s in m.symbols]
        for qn in ('Game.Core.Player', 'Game.Core.Player.Damage',
                   'Game.Core.Player.Inventory',
                   'Game.Core.Player.Inventory.Add'):
            t.expect(f'{qn} in index', qn in qns, qns)

        t.expect('render has header', '## Player.cs' in r.text)
        man = json.loads(r.manifest_json)
        t.expect('manifest is list', isinstance(man, list) and len(man) == 1)
        t.expect('manifest has symbol',
                 'Game.Core.Player.Damage' in
                 [s['qualname'] for s in man[0]['symbols']])

    # --- tool: rebuild_csharp_index writes both files ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'Player.cs').write_text(CS, encoding='utf-8')
        r = _run(root, [{'action': 'rebuild_csharp_index', 'arguments': {}}])[0]
        t.expect('tool ok', r.status == 'ok',
                 f'{r.status}/{r.error_code}: {r.message}')
        t.expect('index written', (root / 'CODE_INDEX_CS.md').exists())
        t.expect('manifest written',
                 (root / 'CODE_INDEX_CS.manifest.json').exists())
        t.expect('message has version', '[v1]' in r.message, r.message)

    # --- find_symbol with kind=csharp ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'Player.cs').write_text(CS, encoding='utf-8')
        _run(root, [{'action': 'rebuild_csharp_index', 'arguments': {}}])
        r = _run(root, [{'action': 'find_symbol', 'arguments': {
            'query': 'Damage', 'kind': 'csharp',
            'manifest_path': 'CODE_INDEX_CS.manifest.json',
        }}])[0]
        t.expect('find_symbol(csharp) ok', r.status == 'ok', r.message)
        t.expect('find_symbol finds Damage', 'Damage' in r.message, r.message)

    # --- incremental: reuse unchanged, re-parse the changed one ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / 'A.cs').write_text(
            'namespace N { public class A { public void M() { } } }',
            encoding='utf-8')
        (root / 'B.cs').write_text(
            'namespace N { public class B { public void M() { } } }',
            encoding='utf-8')

        backend = RootDirBackend(root)
        r1 = build_csharp_index(backend)
        t.expect('incremental: cold build', r1.modules_count == 2, r1.modules_count)

        import json as _json
        prev = _json.loads(r1.manifest_json)

        # No-op: pass the manifest, expect identical text
        r2 = build_csharp_index(backend, prev_manifest=prev)
        t.expect('incremental: no-op output identical',
                 r2.text == r1.text)
        t.expect('incremental: no-op keeps module count',
                 r2.modules_count == r1.modules_count)

        # A module reconstructed from manifest has no source but keeps lines/symbols
        m0 = next(m for m in r2.modules if m.path == 'A.cs')
        t.expect('incremental: cached module has no source', m0.source == '')
        t.expect('incremental: cached module keeps lines', m0.lines > 0, m0.lines)
        t.expect('incremental: cached module keeps symbols',
                 any(s.qualname.endswith('.M') for s in m0.symbols),
                 [s.qualname for s in m0.symbols])
        t.expect('incremental: cached module keeps hash', m0.source_hash != 0,
                 m0.source_hash)

        # Change A.cs only; drop its manifest entry so the tool must re-parse it
        (root / 'A.cs').write_text(
            'namespace N { public class A { public void M() { } public void N2() { } } }',
            encoding='utf-8')
        prev_modified = [e for e in prev if e['path'] != 'A.cs']
        r3 = build_csharp_index(backend, prev_manifest=prev_modified)
        t.expect('incremental: re-parsed file has new symbol',
                 any(s.qualname.endswith('.N2')
                     for m in r3.modules if m.path == 'A.cs'
                     for s in m.symbols))
        mb = next(m for m in r3.modules if m.path == 'B.cs')
        t.expect('incremental: untouched B still cached (no source)',
                 mb.source == '')

    print()
    print(f'=== {t.passed} ok, {t.failed} failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
