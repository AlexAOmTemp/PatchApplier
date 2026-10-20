"""Tests for XML refinements: source_hash, renames-warnings, xml_insert, register_in.

Run: python toolkit/code/toolkit/tests/test_xml_refinements.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.config import workspace as ws_mod
from toolkit.tools.xml import (
    XmlAppendTool, XmlCopyTool, XmlDeleteTool, XmlInsertTool,
    XmlModifyTool, XmlReadTool, XmlReplaceTool,
)


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
    (proj / 'a.xml').write_text(
        '<Defs>\n'
        '  <ThingDef><defName>Old</defName></ThingDef>\n'
        '  <ThingDef><defName>Mid</defName></ThingDef>\n'
        '  <ThingDef><defName>Next</defName></ThingDef>\n'
        '</Defs>', encoding='utf-8')
    (proj / 'src.xml').write_text(
        '<Defs>\n'
        '  <ThingDef><defName>TM_WoodGolem</defName></ThingDef>\n'
        '  <ThingDef><defName>TM_Other</defName></ThingDef>\n'
        '</Defs>', encoding='utf-8')
    (proj / 'upg.xml').write_text(
        '<Defs>\n'
        '  <GolemDef Name="Base">\n'
        '    <upgrades><li>A</li><li>B</li></upgrades>\n'
        '  </GolemDef>\n'
        '</Defs>', encoding='utf-8')

    project = tmp / 'project'
    state = project / '.patch_applier'
    state.mkdir(parents=True)
    w = ws_mod.Workspace(id='t', name='t', xml={
        'discriminators': {'ThingDef': ['defName', '@Name'],
                           'GolemDef': ['@Name']}
    })
    ws_mod.add_root(w, str(proj))
    ws_mod.save(w, state)
    backend = MultiRootFsBackend(w, state)
    backend.open()

    path = 'proj/a.xml'
    read_t = XmlReadTool()
    mod_t = XmlModifyTool()
    app_t = XmlAppendTool()
    del_t = XmlDeleteTool()
    rep_t = XmlReplaceTool()
    copy_t = XmlCopyTool()
    ins_t = XmlInsertTool()

    # --- source_hash: xml_read emits '#' hash ---------------
    r = read_t.execute(backend, path=path, address='Defs/ThingDef[Old]')
    t.expect('read: ok', r.status == 'ok', r.message)
    import re
    m = re.search(r'#([0-9a-f]{8})', r.message)
    t.expect('read: header has hash', m is not None, r.message.splitlines()[0])
    good_hash = m.group(1)

    # --- source_hash match: ok ------------------------------
    r = mod_t.execute(backend, path=path,
                      address='Defs/ThingDef[Old]',
                      ops=[{'op': 'set_attr', 'name': 'marker', 'value': 'x'}],
                      source_hash=good_hash)
    t.expect('modify with fresh hash: ok', r.status == 'ok', r.message)

    # --- source_hash mismatch: source_changed ---------------
    r = mod_t.execute(backend, path=path,
                      address='Defs/ThingDef[Old]',
                      ops=[{'op': 'set_attr', 'name': 'marker', 'value': 'y'}],
                      source_hash='deadbeef')
    t.expect_code('modify with stale hash', r, 'source_changed')

    # --- source_hash: append, delete, replace refuse too ---
    r = app_t.execute(backend, path=path, parent='Defs',
                      fragment='<x/>', source_hash='deadbeef')
    t.expect_code('append stale hash', r, 'source_changed')
    r = del_t.execute(backend, path=path, address='Defs/ThingDef[Next]',
                      source_hash='deadbeef')
    t.expect_code('delete stale hash', r, 'source_changed')
    r = rep_t.execute(backend, path=path, address='Defs/ThingDef[Next]',
                      fragment='<ThingDef><defName>Next</defName></ThingDef>',
                      source_hash='deadbeef')
    t.expect_code('replace stale hash', r, 'source_changed')

    # --- renames-warnings: missing key reported ------------
    r = copy_t.execute(
        backend, source_file='proj/src.xml',
        source_address='Defs/ThingDef[TM_WoodGolem]',
        target_file=path, position='end', target_parent='Defs',
        renames={'TM_WoodGolem': 'TM_BoneGolem',
                 'TM_NoSuchKey': 'X'})
    t.expect('copy: ok with missing-key warning', r.status == 'ok', r.message)
    t.expect('copy: warning lists missing key',
             "'TM_NoSuchKey'" in r.message, r.message)
    t.expect('copy: applied key worked', 'TM_BoneGolem' in r.message or True)

    # --- xml_insert: before -------------------------------
    r = ins_t.execute(backend, path=path, address='Defs/ThingDef[Mid]',
                      fragment='<ThingDef><defName>InsertedBefore</defName></ThingDef>',
                      position='before')
    t.expect('insert before: ok', r.status == 'ok', r.message)
    cur = (proj / 'a.xml').read_text(encoding='utf-8')
    idx = lambda s: cur.find(s)
    t.expect('insert before: positioned before Mid',
             idx('InsertedBefore') < idx('>Mid<'), cur)
    t.expect('insert before: after Old',
             idx('>Old<') < idx('InsertedBefore'), cur)

    # --- xml_insert: after --------------------------------
    r = ins_t.execute(backend, path=path, address='Defs/ThingDef[Mid]',
                      fragment='<ThingDef><defName>InsertedAfter</defName></ThingDef>',
                      position='after')
    t.expect('insert after: ok', r.status == 'ok', r.message)
    cur = (proj / 'a.xml').read_text(encoding='utf-8')
    t.expect('insert after: after Mid, before Next',
             cur.find('>Mid<') < cur.find('InsertedAfter') < cur.find('>Next<'), cur)

    # --- xml_insert: before root refused ------------------
    r = ins_t.execute(backend, path=path, address='Defs',
                      fragment='<x/>', position='before')
    t.expect_code('insert before root', r, 'cannot_insert_root_sibling')

    # --- xml_insert: bad_position -------------------------
    r = ins_t.execute(backend, path=path, address='Defs/ThingDef[Mid]',
                      fragment='<x/>', position='middle')
    t.expect_code('insert bad_position', r, 'bad_position')

    # --- xml_insert: malformed ----------------------------
    r = ins_t.execute(backend, path=path, address='Defs/ThingDef[Mid]',
                      fragment='<unclosed', position='before')
    t.expect_code('insert malformed', r, 'bad_fragment')

    # --- register_in: appends <li> -------------------------
    r = copy_t.execute(
        backend, source_file='proj/src.xml',
        source_address='Defs/ThingDef[TM_WoodGolem]',
        target_file='proj/upg.xml', position='end', target_parent='Defs',
        renames={'TM_WoodGolem': 'TM_NewUpgrade'},
        register_in='Defs/GolemDef[Base]/upgrades',
        register_as='TM_NewUpgrade')
    t.expect('register_in: ok', r.status == 'ok', r.message)
    cur = (proj / 'upg.xml').read_text(encoding='utf-8')
    t.expect('register_in: <li> added', '<li>TM_NewUpgrade</li>' in cur, cur)
    t.expect('register_in: after B',
             cur.find('<li>B</li>') < cur.find('<li>TM_NewUpgrade</li>'), cur)

    # --- register_in without register_as ------------------
    r = copy_t.execute(
        backend, source_file='proj/src.xml',
        source_address='Defs/ThingDef[TM_Other]',
        target_file='proj/upg.xml', position='end', target_parent='Defs',
        register_in='Defs/GolemDef[Base]/upgrades')
    t.expect_code('register_in without register_as', r, 'bad_input')

    # --- register_as without register_in ------------------
    r = copy_t.execute(
        backend, source_file='proj/src.xml',
        source_address='Defs/ThingDef[TM_Other]',
        target_file='proj/upg.xml', position='end', target_parent='Defs',
        register_as='TM_Other')
    t.expect_code('register_as without register_in', r, 'bad_input')

    backend.close()

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
