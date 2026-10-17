"""Tests for toolkit.tools.xml.XmlFindTool.

Drives the tool over a real MultiRootFsBackend on tmp files, then
integration on real RimWorld/Data.

Run: python toolkit/code/toolkit/tests/test_xml_find.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.config import workspace as ws_mod
from toolkit.tools.xml import XmlFindTool


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

    def expect_code(self, label, r, code):
        if r.status == 'error' and r.error_code == code:
            print(PASS + ' ' + label + f' ({code})')
            self.passed += 1
        else:
            print(FAIL + ' ' + label
                  + f' -- status={r.status}, code={r.error_code}, msg={r.message[:120]}')
            self.failed += 1


t = T()

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td).resolve()
    proj = tmp / 'proj'
    (proj / 'Defs' / 'Walls').mkdir(parents=True)
    (proj / 'Defs' / 'Floors').mkdir(parents=True)
    (proj / 'Defs' / 'Walls' / 'Wall.xml').write_text(
        '<?xml version="1.0"?><Defs>'
        '<ThingDef ParentName="BlockBase"><defName>BlockWall</defName><label>wall</label></ThingDef>'
        '<ThingDef><defName>WoodWall</defName></ThingDef>'
        '</Defs>', encoding='utf-8')
    (proj / 'Defs' / 'Floors' / 'Floor.xml').write_text(
        '<?xml version="1.0"?><Defs>'
        '<ThingDef><defName>BlockFloor</defName></ThingDef>'
        '<RecipeDef><defName>MakeSteel</defName></RecipeDef>'
        '</Defs>', encoding='utf-8')
    # Bad XML — should be skipped, not crash.
    (proj / 'Defs' / 'Broken.xml').write_text('<Defs><bad', encoding='utf-8')

    project = tmp / 'project'
    state = project / '.patch_applier'
    state.mkdir(parents=True)
    w = ws_mod.Workspace(id='t', name='t', xml={
        'discriminators': {'ThingDef': ['defName', '@Name']}
    })
    ws_mod.add_root(w, str(proj))
    ws_mod.save(w, state)
    backend = MultiRootFsBackend(w, state)
    backend.open()
    tool = XmlFindTool()

    # No where — all ThingDef across tree.
    r = tool.execute(backend, path='proj/Defs', tag='ThingDef')
    t.expect('all ThingDef: ok', r.status == 'ok', r.message)
    t.expect('all ThingDef: BlockWall', 'BlockWall' in r.message)
    t.expect('all ThingDef: WoodWall', 'WoodWall' in r.message)
    t.expect('all ThingDef: BlockFloor', 'BlockFloor' in r.message)
    t.expect('all ThingDef: no MakeSteel', 'MakeSteel' not in r.message)
    t.expect('all ThingDef: 3 matches header',
             '3 matches' in r.message, r.message.splitlines()[0])

    # where glob on defName.
    r = tool.execute(backend, path='proj/Defs', tag='ThingDef',
                     where={'defName': '*Block*'})
    t.expect('glob Block: ok', r.status == 'ok')
    t.expect('glob Block: BlockWall', 'BlockWall' in r.message)
    t.expect('glob Block: BlockFloor', 'BlockFloor' in r.message)
    t.expect('glob Block: no WoodWall', 'WoodWall' not in r.message)

    # where exact string.
    r = tool.execute(backend, path='proj/Defs', tag='ThingDef',
                     where={'defName': 'WoodWall'})
    t.expect('exact WoodWall: ok', r.status == 'ok')
    t.expect('exact WoodWall: match', 'WoodWall' in r.message)
    t.expect('exact WoodWall: no BlockWall', 'BlockWall' not in r.message)

    # where on @attr.
    r = tool.execute(backend, path='proj/Defs', tag='ThingDef',
                     where={'@ParentName': '*'})
    t.expect('@attr present: ok', r.status == 'ok')
    t.expect('@attr present: BlockWall', 'BlockWall' in r.message)
    t.expect('@attr present: no WoodWall', 'WoodWall' not in r.message)

    # where multiple criteria (AND).
    r = tool.execute(backend, path='proj/Defs', tag='ThingDef',
                     where={'defName': '*Block*', '@ParentName': 'BlockBase'})
    t.expect('AND: BlockWall only',
             'BlockWall' in r.message and 'BlockFloor' not in r.message,
             r.message)

    # No match.
    r = tool.execute(backend, path='proj/Defs', tag='ThingDef',
                     where={'defName': 'Nope'})
    t.expect('no match: ok', r.status == 'ok', r.message)
    t.expect('no match: message', 'no matches' in r.message)

    # Unparseable file skipped, not fatal.
    r = tool.execute(backend, path='proj/Defs', tag='ThingDef')
    t.expect('broken file skipped', r.status == 'ok')

    # --- errors ----------------------------------------------------------
    r = tool.execute(backend, path='', tag='ThingDef')
    t.expect_code('empty path', r, 'bad_input')

    r = tool.execute(backend, path='proj/Defs', tag='')
    t.expect_code('empty tag', r, 'bad_input')

    r = tool.execute(backend, path='proj/Defs', tag='ThingDef',
                     where={'defName': 123})
    t.expect_code('non-string where value', r, 'bad_input')

    r = tool.execute(backend, path='proj/Missing', tag='ThingDef')
    t.expect_code('missing path', r, 'not_found')

    r = tool.execute(backend, path='proj/Defs', tag='ThingDef', max_files=1)
    t.expect_code('too many files', r, 'too_many_files')
    t.expect('too_many suggests narrowing',
             'narrow path' in r.message or 'raise max_files' in r.message,
             r.message)

    backend.close()

# --- integration: real RimWorld --------------------------------------------

RW = Path('D:/Programs/UnityAiDevSystem/RimWorld')
if RW.is_dir():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        project = tmp / 'project'
        state = project / '.patch_applier'
        state.mkdir(parents=True)
        w = ws_mod.Workspace(id='rw', name='rw', xml={
            'discriminators': {
                'ThingDef': ['defName', '@Name'],
                'AbilityDef': ['defName', '@Name'],
                'RoofDef': ['defName', '@Name'],
            }
        })
        ws_mod.add_root(w, str(RW))
        ws_mod.save(w, state)
        backend = MultiRootFsBackend(w, state)
        backend.open()
        tool = XmlFindTool()

        # Narrow scope: one file.
        r = tool.execute(backend,
                         path='RimWorld/Data/Anomaly/Defs/Misc/Roofs.xml',
                         tag='RoofDef')
        t.expect('RW Roofs: ok', r.status == 'ok', r.message)
        t.expect('RW Roofs: VoidmetalRoof', 'VoidmetalRoof' in r.message)

        # Abilities dir: find AbilityDef with glob on defName.
        r = tool.execute(backend,
                         path='RimWorld/Data/Anomaly/Defs/AbilityDefs',
                         tag='AbilityDef',
                         where={'defName': '*Spike*'})
        t.expect('RW Spike: ok', r.status == 'ok', r.message)
        t.expect('RW Spike: found SpikeLaunch',
                 'SpikeLaunch' in r.message, r.message)

        backend.close()
else:
    print(PASS + ' RimWorld integration: skipped (root absent)')
    t.passed += 1

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
