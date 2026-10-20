"""Tests for toolkit.tools.xml.XmlModifyTool.

Run: python toolkit/code/toolkit/tests/test_xml_modify.py
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
from toolkit.tools.xml import XmlModifyTool


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
        '<?xml version="1.0"?>'
        '<Defs>'
        '<ThingDef x="1"><defName>Steel</defName></ThingDef>'
        '<ThingDef><defName>Wood</defName><label>wood</label></ThingDef>'
        '<Leaf>old</Leaf>'
        '<Empty/>'
        '<Mixed>x<b>y</b>z</Mixed>'
        '</Defs>',
        encoding='utf-8')

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
    tool = XmlModifyTool()

    path = 'proj/a.xml'

    def read():
        return (proj / 'a.xml').read_text(encoding='utf-8')

    # --- set_attr existing --------------------------------------------------
    r = tool.execute(backend, path=path, address='Defs/ThingDef[Steel]',
                     ops=[{'op': 'set_attr', 'name': 'x', 'value': 'NEW'}])
    t.expect('set_attr existing: ok', r.status == 'ok', r.message)
    t.expect('set_attr existing: in file', 'x="NEW"' in read())

    # --- set_attr new -------------------------------------------------------
    r = tool.execute(backend, path=path, address='Defs/ThingDef[Wood]',
                     ops=[{'op': 'set_attr', 'name': 'y', 'value': '2'}])
    t.expect('set_attr new: ok', r.status == 'ok', r.message)
    t.expect('set_attr new: in file', 'y="2"' in read())

    # --- remove_attr --------------------------------------------------------
    r = tool.execute(backend, path=path, address='Defs/ThingDef[Steel]',
                     ops=[{'op': 'remove_attr', 'name': 'x'}])
    t.expect('remove_attr: ok', r.status == 'ok', r.message)
    t.expect('remove_attr: gone from file', 'x="NEW"' not in read())

    # --- set_text -----------------------------------------------------------
    r = tool.execute(backend, path=path, address='Defs/Leaf',
                     ops=[{'op': 'set_text', 'value': 'A & B'}])
    t.expect('set_text: ok', r.status == 'ok', r.message)
    t.expect('set_text: escaped', '<Leaf>A &amp; B</Leaf>' in read())

    # --- set_text on Empty (self-closing) ----------------------------------
    r = tool.execute(backend, path=path, address='Defs/Empty',
                     ops=[{'op': 'set_text', 'value': 'v'}])
    t.expect('set_text empty: ok', r.status == 'ok', r.message)
    t.expect('set_text empty: expanded', '<Empty>v</Empty>' in read())

    # --- set_text on mixed-content -----------------------------------------
    before = read()
    r = tool.execute(backend, path=path, address='Defs/Mixed',
                     ops=[{'op': 'set_text', 'value': 'X'}])
    t.expect_code('set_text mixed', r, 'mixed_content_unsupported')
    t.expect('mixed: file untouched', read() == before)

    # --- set_text on element with children ---------------------------------
    before = read()
    r = tool.execute(backend, path=path, address='Defs/ThingDef[Wood]',
                     ops=[{'op': 'set_text', 'value': 'X'}])
    t.expect_code('set_text on children', r, 'has_children')
    t.expect('children: file untouched', read() == before)

    # --- atomic: two ops, second fails ------------------------------------
    before = read()
    r = tool.execute(backend, path=path, address='Defs/ThingDef[Wood]',
                     ops=[
                         {'op': 'set_attr', 'name': 'ok_attr', 'value': 'v'},
                         {'op': 'remove_attr', 'name': 'missing'},
                     ])
    t.expect_code('atomic second fails', r, 'attr_not_found')
    t.expect('atomic: no partial write (ok_attr absent)',
             'ok_attr' not in read())

    # --- multiple ops all succeed -----------------------------------------
    r = tool.execute(backend, path=path, address='Defs/ThingDef[Wood]',
                     ops=[
                         {'op': 'set_attr', 'name': 'a', 'value': '1'},
                         {'op': 'set_attr', 'name': 'b', 'value': '2'},
                     ])
    t.expect('multi-ops: ok', r.status == 'ok', r.message)
    cur = read()
    t.expect('multi-ops: a', 'a="1"' in cur)
    t.expect('multi-ops: b', 'b="2"' in cur)

    # --- bad_op: unknown kind ---------------------------------------------
    r = tool.execute(backend, path=path, address='Defs/Leaf',
                     ops=[{'op': 'nuke'}])
    t.expect_code('unknown op kind', r, 'bad_op')

    # --- bad_op: missing field -------------------------------------------
    r = tool.execute(backend, path=path, address='Defs/Leaf',
                     ops=[{'op': 'set_attr'}])
    t.expect_code('missing name', r, 'bad_op')

    r = tool.execute(backend, path=path, address='Defs/Leaf',
                     ops=[{'op': 'set_attr', 'name': 'x'}])
    t.expect_code('missing value', r, 'bad_op')

    # --- empty ops -------------------------------------------------------
    r = tool.execute(backend, path=path, address='Defs/Leaf', ops=[])
    t.expect_code('empty ops', r, 'bad_input')

    # --- bad address -----------------------------------------------------
    r = tool.execute(backend, path=path, address='Defs/Leaf[',
                     ops=[{'op': 'set_text', 'value': 'v'}])
    t.expect_code('bad address', r, 'bad_address')

    # --- not found -------------------------------------------------------
    r = tool.execute(backend, path=path, address='Defs/Nope',
                     ops=[{'op': 'set_text', 'value': 'v'}])
    t.expect_code('not found', r, 'not_found')

    # --- missing file ----------------------------------------------------
    r = tool.execute(backend, path='proj/missing.xml', address='x',
                     ops=[{'op': 'set_text', 'value': 'v'}])
    t.expect_code('missing file', r, 'not_found')

    # --- set_annotation: insert as first child -------------------------
    (proj / 'a.xml').write_text(
        '<Defs>\n  <ThingDef>\n    <defName>Steel</defName>\n  </ThingDef>\n</Defs>',
        encoding='utf-8')
    r = tool.execute(backend, path=path, address='Defs/ThingDef[Steel]',
                     ops=[{'op': 'set_annotation', 'value': 'metal from steel'}])
    t.expect('set_annotation: ok', r.status == 'ok', r.message)
    cur = read()
    t.expect('set_annotation: inserted', '<!-- summary: metal from steel -->' in cur, cur)
    t.expect('set_annotation: before defName',
             cur.index('<!-- summary') < cur.index('<defName>Steel'), cur)
    t.expect('set_annotation: 4-space indent',
             '\n    <!-- summary: metal from steel -->' in cur, cur)

    # --- set_annotation: replace existing -------------------------------
    (proj / 'a.xml').write_text(
        '<Defs>\n  <ThingDef>\n    <!-- summary: old text -->\n    <defName>Steel</defName>\n  </ThingDef>\n</Defs>',
        encoding='utf-8')
    r = tool.execute(backend, path=path, address='Defs/ThingDef[Steel]',
                     ops=[{'op': 'set_annotation', 'value': 'new text'}])
    t.expect('set_annotation replace: ok', r.status == 'ok', r.message)
    cur = read()
    t.expect('set_annotation replace: new present', '<!-- summary: new text -->' in cur, cur)
    t.expect('set_annotation replace: old gone', 'old text' not in cur)
    t.expect('set_annotation replace: no duplicate',
             cur.count('<!-- summary') == 1, cur)

    # --- set_annotation: empty parent -----------------------------------
    (proj / 'a.xml').write_text('<Defs>\n  <A></A>\n</Defs>', encoding='utf-8')
    r = tool.execute(backend, path=path, address='Defs/A',
                     ops=[{'op': 'set_annotation', 'value': 'ann'}])
    t.expect('set_annotation empty: ok', r.status == 'ok', r.message)
    cur = read()
    t.expect('set_annotation empty: present', '<!-- summary: ann -->' in cur, cur)

    # --- set_annotation on self-closing ---------------------------------
    (proj / 'a.xml').write_text('<Defs>\n  <A/>\n</Defs>', encoding='utf-8')
    r = tool.execute(backend, path=path, address='Defs/A',
                     ops=[{'op': 'set_annotation', 'value': 'ann'}])
    t.expect_code('set_annotation self-closing', r, 'empty_element')

    backend.close()

# --- integration: real RimWorld file -----------------------------------------

RW = Path('D:/Programs/UnityAiDevSystem/RimWorld')
if RW.is_dir():
    import shutil
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        project = tmp / 'project'
        state = project / '.patch_applier'
        state.mkdir(parents=True)
        # Copy the real file so we do not modify RimWorld.
        target = project / 'Roofs.xml'
        shutil.copyfile(
            RW / 'Data/Anomaly/Defs/Misc/Roofs.xml', target,
        )
        w = ws_mod.Workspace(id='rw', name='rw', xml={
            'discriminators': {'RoofDef': ['defName', '@Name']}
        })
        ws_mod.add_root(w, str(project))
        ws_mod.save(w, state)
        backend = MultiRootFsBackend(w, state)
        backend.open()
        tool = XmlModifyTool()

        before = target.read_bytes()
        r = tool.execute(backend, path='project/Roofs.xml',
                         address='Defs/RoofDef[VoidmetalRoof]',
                         ops=[{'op': 'set_attr', 'name': 'test_attr', 'value': 'v'}])
        t.expect('RW Roofs: ok', r.status == 'ok', r.message)
        after = target.read_bytes()
        t.expect('RW Roofs: BOM preserved', after.startswith(b'\xef\xbb\xbf'))
        t.expect('RW Roofs: CRLF count unchanged',
                 after.count(b'\r\n') == before.count(b'\r\n'))
        t.expect('RW Roofs: attr inserted', b'test_attr="v"' in after)
        t.expect('RW Roofs: rest untouched (idempotent prefix)',
                 after.replace(b' test_attr="v"', b'') == before)

        backend.close()
else:
    print(PASS + ' RimWorld integration: skipped')
    t.passed += 1

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
