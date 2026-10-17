"""Tests for toolkit.tools.xml.XmlMapTool.

Run: python toolkit/code/toolkit/tests/test_xml_map.py
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
from toolkit.tools.xml import XmlMapTool


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
    (proj / 'Items' / 'Nested').mkdir(parents=True)
    (proj / 'Recipes').mkdir()
    (proj / 'top.xml').write_text(
        '<?xml version="1.0"?><Defs>'
        '<ThingDef><defName>TopThing</defName></ThingDef>'
        '</Defs>', encoding='utf-8')
    (proj / 'Items' / 'A.xml').write_text(
        '<?xml version="1.0"?><Defs>'
        '<ThingDef><defName>Steel</defName></ThingDef>'
        '<ThingDef><defName>Wood</defName></ThingDef>'
        '<RecipeDef><defName>R1</defName></RecipeDef>'
        '</Defs>', encoding='utf-8')
    (proj / 'Items' / 'B.xml').write_text(
        '<?xml version="1.0"?><Defs>'
        '<ThingDef><defName>Cloth</defName></ThingDef>'
        '</Defs>', encoding='utf-8')
    (proj / 'Items' / 'Nested' / 'C.xml').write_text(
        '<Defs><ThingDef><defName>NestedThing</defName></ThingDef></Defs>',
        encoding='utf-8')
    (proj / 'Recipes' / 'R.xml').write_text(
        '<Defs><RecipeDef><defName>CookMeal</defName></RecipeDef></Defs>',
        encoding='utf-8')
    (proj / 'Items' / 'Broken.xml').write_text('<Defs><bad', encoding='utf-8')

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
    tool = XmlMapTool()

    # Default: depth=2, max_tags=5.
    r = tool.execute(backend, path='proj')
    t.expect('ok', r.status == 'ok', r.message)
    t.expect('header has file count',
             '5 files' in r.message or '6 files' in r.message, r.message.splitlines()[0])
    t.expect('has root line',
             r.message.splitlines()[1].strip().startswith('.'), r.message.splitlines()[1])
    t.expect('has Items line', 'Items' in r.message)
    t.expect('has Recipes line', 'Recipes' in r.message)
    t.expect('Items: ThingDef count',
             'ThingDef(3:' in r.message or 'ThingDef(3' in r.message, r.message)
    t.expect('Items: sample names',
             'Steel' in r.message or 'Wood' in r.message or 'Cloth' in r.message)
    t.expect('unparseable skipped', '1 unparseable' in r.message, r.message)

    # depth=1: Nested collapses into Items.
    r = tool.execute(backend, path='proj', depth=1)
    t.expect('depth=1: no Nested line',
             'Items/Nested' not in r.message, r.message)
    t.expect('depth=1: Items still present', 'Items' in r.message)

    # depth=0: all in one bucket.
    r = tool.execute(backend, path='proj', depth=0)
    dir_lines = [ln for ln in r.message.splitlines()
                 if ln.startswith('  .') and not ln.startswith('  ...')]
    t.expect('depth=0: single dot line',
             len(dir_lines) == 1, r.message)

    # max_tags=1 limits shown tags.
    r = tool.execute(backend, path='proj', max_tags=1)
    t.expect('max_tags=1: +N more tags',
             'more tags' in r.message, r.message)

    # Empty dir has no .xml.
    (proj / 'Empty').mkdir()
    r = tool.execute(backend, path='proj/Empty')
    t.expect('empty dir: ok', r.status == 'ok', r.message)
    t.expect('empty dir: no xml message',
             'no .xml files' in r.message, r.message)

    # --- errors ----------------------------------------------------------
    r = tool.execute(backend, path='')
    t.expect_code('empty path', r, 'bad_input')

    r = tool.execute(backend, path='proj/top.xml')
    t.expect_code('file not dir', r, 'bad_input')

    r = tool.execute(backend, path='proj/Missing')
    t.expect_code('missing path', r, 'not_found')

    r = tool.execute(backend, path='proj', max_files=1)
    t.expect_code('too many files', r, 'too_many_files')
    t.expect('too_many suggests narrow',
             'narrow path' in r.message, r.message)

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
            }
        })
        ws_mod.add_root(w, str(RW))
        ws_mod.save(w, state)
        backend = MultiRootFsBackend(w, state)
        backend.open()
        tool = XmlMapTool()

        r = tool.execute(backend,
                         path='RimWorld/Data/Anomaly/Defs/AbilityDefs',
                         depth=1)
        t.expect('RW AbilityDefs: ok', r.status == 'ok', r.message)
        t.expect('RW AbilityDefs: AbilityDef present',
                 'AbilityDef' in r.message, r.message)

        backend.close()
else:
    print(PASS + ' RimWorld integration: skipped')
    t.passed += 1

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
