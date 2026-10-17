"""Tests for XmlCopyTool and XmlMoveTool.

Run: python toolkit/code/toolkit/tests/test_xml_copy_move.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.config import workspace as ws_mod
from toolkit.tools.xml import XmlCopyTool, XmlMoveTool


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
    proj.mkdir()
    (proj / 'src.xml').write_text(
        '<Defs>\n'
        '  <ThingDef>\n'
        '    <defName>TM_WoodGolem</defName>\n'
        '    <label>wood golem</label>\n'
        '  </ThingDef>\n'
        '  <ThingDef>\n'
        '    <defName>TM_StoneGolem</defName>\n'
        '    <label>stone golem</label>\n'
        '  </ThingDef>\n'
        '</Defs>', encoding='utf-8')
    (proj / 'dst.xml').write_text(
        '<Defs>\n'
        '  <ThingDef>\n'
        '    <defName>TM_Existing</defName>\n'
        '  </ThingDef>\n'
        '</Defs>', encoding='utf-8')

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

    copy_t = XmlCopyTool()
    move_t = XmlMoveTool()

    # --- copy without renames -----------------------------------------
    r = copy_t.execute(
        backend, source_file='proj/src.xml',
        source_address='Defs/ThingDef[TM_WoodGolem]',
        target_file='proj/dst.xml', position='end', target_parent='Defs')
    t.expect('copy: ok', r.status == 'ok', r.message)
    dst = (proj / 'dst.xml').read_text(encoding='utf-8')
    t.expect('copy: has Wood', 'TM_WoodGolem' in dst, dst)
    t.expect('copy: has Existing', 'TM_Existing' in dst)
    t.expect('copy: src untouched',
             'TM_WoodGolem' in (proj / 'src.xml').read_text(encoding='utf-8'))

    # --- copy with renames --------------------------------------------
    (proj / 'dst.xml').write_text(
        '<Defs>\n</Defs>', encoding='utf-8')
    r = copy_t.execute(
        backend, source_file='proj/src.xml',
        source_address='Defs/ThingDef[TM_WoodGolem]',
        target_file='proj/dst.xml', position='end', target_parent='Defs',
        renames={'TM_WoodGolem': 'TM_BoneGolem',
                 'wood golem': 'bone golem'})
    t.expect('copy renames: ok', r.status == 'ok', r.message)
    dst = (proj / 'dst.xml').read_text(encoding='utf-8')
    t.expect('copy renames: TM_BoneGolem', 'TM_BoneGolem' in dst, dst)
    t.expect('copy renames: bone golem', 'bone golem' in dst, dst)
    t.expect('copy renames: no TM_Wood', 'TM_WoodGolem' not in dst, dst)

    # --- copy: replace position ---------------------------------------
    (proj / 'dst.xml').write_text(
        '<Defs>\n  <ThingDef>\n    <defName>TM_Old</defName>\n  </ThingDef>\n</Defs>',
        encoding='utf-8')
    r = copy_t.execute(
        backend, source_file='proj/src.xml',
        source_address='Defs/ThingDef[TM_WoodGolem]',
        target_file='proj/dst.xml', position='replace',
        target_address='Defs/ThingDef[TM_Old]',
        renames={'TM_WoodGolem': 'TM_BoneGolem'})
    t.expect('copy replace: ok', r.status == 'ok', r.message)
    dst = (proj / 'dst.xml').read_text(encoding='utf-8')
    t.expect('copy replace: TM_BoneGolem present', 'TM_BoneGolem' in dst)
    t.expect('copy replace: TM_Old gone', 'TM_Old' not in dst)

    # --- copy: bad_position -------------------------------------------
    r = copy_t.execute(
        backend, source_file='proj/src.xml',
        source_address='Defs/ThingDef[TM_WoodGolem]',
        target_file='proj/dst.xml', position='before',
        target_address='Defs/ThingDef[TM_Old]')
    t.expect_code('copy bad_position', r, 'bad_position')

    # --- copy: bad rename fragment ------------------------------------
    r = copy_t.execute(
        backend, source_file='proj/src.xml',
        source_address='Defs/ThingDef[TM_WoodGolem]',
        target_file='proj/dst.xml', position='end', target_parent='Defs',
        renames={'TM_WoodGolem': '<broken>'})
    t.expect_code('copy rename breaks well-formed', r, 'bad_fragment')

    # --- move: same file → refuse -------------------------------------
    r = move_t.execute(
        backend, source_file='proj/src.xml',
        source_address='Defs/ThingDef[TM_WoodGolem]',
        target_file='proj/src.xml', position='end', target_parent='Defs')
    t.expect_code('move same file', r, 'same_file_move_unsupported')

    # --- move: cross file ---------------------------------------------
    (proj / 'src.xml').write_text(
        '<Defs>\n  <ThingDef><defName>TM_WoodGolem</defName></ThingDef>\n</Defs>',
        encoding='utf-8')
    (proj / 'dst.xml').write_text('<Defs>\n</Defs>', encoding='utf-8')
    r = move_t.execute(
        backend, source_file='proj/src.xml',
        source_address='Defs/ThingDef[TM_WoodGolem]',
        target_file='proj/dst.xml', position='end', target_parent='Defs',
        renames={'TM_WoodGolem': 'TM_BoneGolem'})
    t.expect('move: ok', r.status == 'ok', r.message)
    t.expect('move: source deleted (msg)', '(source deleted)' in r.message, r.message)
    src = (proj / 'src.xml').read_text(encoding='utf-8')
    dst = (proj / 'dst.xml').read_text(encoding='utf-8')
    t.expect('move: src empty Defs', 'TM_WoodGolem' not in src, src)
    t.expect('move: dst has TM_BoneGolem', 'TM_BoneGolem' in dst, dst)

    backend.close()


# --- integration: real RWoM -------------------------------------

RW = Path('D:/Programs/UnityAiDevSystem/RimWorld')
if (RW / 'PatchApplier/RWoM-main/v1.5/Defs/GolemDefs/Golem_Race_Base.xml').is_file():
    import shutil
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        project = tmp / 'project'
        state = project / '.patch_applier'
        state.mkdir(parents=True)
        shutil.copyfile(
            RW / 'PatchApplier/RWoM-main/v1.5/Defs/GolemDefs/Golem_Race_Base.xml',
            project / 'Golem_Race_Base.xml')
        (project / 'Additions.xml').write_text(
            '<Defs>\n</Defs>', encoding='utf-8')
        w = ws_mod.Workspace(id='rw', name='rw', xml={
            'discriminators': {'ThingDef': ['defName', '@Name']}
        })
        ws_mod.add_root(w, str(project))
        ws_mod.save(w, state)
        backend = MultiRootFsBackend(w, state)
        backend.open()
        tool = XmlCopyTool()

        r = tool.execute(
            backend,
            source_file='project/Golem_Race_Base.xml',
            source_address='Defs/ThingDef[TM_WoodGolem]',
            target_file='project/Additions.xml', position='end',
            target_parent='Defs',
            renames={'TM_WoodGolem': 'TM_BoneGolem',
                     'wood golem': 'bone golem',
                     'TM_Wood_Manipulator': 'TM_Bone_Manipulator',
                     'TM_Wood_Base': 'TM_Bone_Base',
                     'TM_WoodGolemLS': 'TM_BoneGolemLS',
                     'WoodLog': 'BoneLog'})
        t.expect('RW copy: ok', r.status == 'ok', r.message)
        cur = (project / 'Additions.xml').read_text(encoding='utf-8')
        t.expect('RW copy: TM_BoneGolem', 'TM_BoneGolem' in cur)
        t.expect('RW copy: bone golem label', 'bone golem' in cur)
        t.expect('RW copy: TM_Bone_Manipulator', 'TM_Bone_Manipulator' in cur)
        t.expect('RW copy: TM_BoneGolemLS (longest-first)', 'TM_BoneGolemLS' in cur)
        t.expect('RW copy: no TM_Wood', 'TM_Wood' not in cur, cur[:300])

        backend.close()
else:
    print(PASS + ' RWoM integration: skipped')
    t.passed += 1

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
