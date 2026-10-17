"""Tests for toolkit.tools.xml.XmlReadTool.

Drives the tool through a real MultiRootFsBackend over a tmp project so
we exercise the same resolve_physical / filter_check pipeline the live
runtime uses. Then integration on real RimWorld files via a real
workspace rooted at RimWorld/.

Run: python toolkit/code/toolkit/tests/test_xml_tool.py
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
from toolkit.tools.xml import XmlReadTool


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
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Defs>\n'
        '  <ThingDef><defName>Steel</defName><label>steel</label></ThingDef>\n'
        '  <ThingDef><defName>Wood</defName></ThingDef>\n'
        '  <ThingDef><defName>Steel</defName></ThingDef>\n'
        '</Defs>\n',
        encoding='utf-8',
    )
    # BOM+CRLF file.
    (proj / 'bom.xml').write_bytes(
        b'\xef\xbb\xbf<root>\r\n  <a>x</a>\r\n</root>'
    )
    # Mixed content.
    (proj / 'mixed.xml').write_text('<a>x<b>y</b>z</a>', encoding='utf-8')

    project = tmp / 'project'
    state = project / '.patch_applier'
    state.mkdir(parents=True)

    w = ws_mod.Workspace(id='test', name='xml')
    ws_mod.add_root(w, str(proj))
    ws_mod.save(w, state)

    backend = MultiRootFsBackend(w, state)
    backend.open()

    tool = XmlReadTool()

    # --- happy path ------------------------------------------------------
    r = tool.execute(backend, file_path='proj/a.xml', address='Defs/ThingDef[Wood]')
    t.expect('read Wood: status ok', r.status == 'ok', r.message)
    t.expect('read Wood: includes defName', '<defName>Wood</defName>' in r.message)
    t.expect('read Wood: excludes Steel', 'Steel' not in r.message)
    t.expect('read Wood: header tag', '<ThingDef>' in r.message)

    # Ambiguous without occurrence.
    r = tool.execute(backend, file_path='proj/a.xml', address='Defs/ThingDef[Steel]')
    t.expect_code('ambiguous Steel', r, 'ambiguous_address')
    # Header on L1, <Defs> on L2, so the two Steel ThingDefs are L3 and L5.
    t.expect('ambiguous: message lists L3 and L5',
             'L3' in r.message and 'L5' in r.message, r.message)

    # occurrence picks one.
    r = tool.execute(backend, file_path='proj/a.xml',
                     address='Defs/ThingDef[Steel]', occurrence=1)
    t.expect('occurrence=1 ok', r.status == 'ok')
    t.expect('occurrence=1 has label', '<label>steel</label>' in r.message)

    r = tool.execute(backend, file_path='proj/a.xml',
                     address='Defs/ThingDef[Steel]', occurrence=2)
    t.expect('occurrence=2 ok', r.status == 'ok')
    t.expect('occurrence=2 no label', '<label>' not in r.message)

    # occurrence out of range.
    r = tool.execute(backend, file_path='proj/a.xml',
                     address='Defs/ThingDef[Steel]', occurrence=3)
    t.expect_code('occurrence out of range', r, 'occurrence_out_of_range')

    # Position selector.
    r = tool.execute(backend, file_path='proj/a.xml', address='Defs/ThingDef[2]')
    t.expect('position selector', r.status == 'ok' and 'Wood' in r.message, r.message)

    # --- BOM+CRLF --------------------------------------------------------
    r = tool.execute(backend, file_path='proj/bom.xml', address='root/a')
    t.expect('BOM: status ok', r.status == 'ok', r.message)
    t.expect('BOM: text includes a', '<a>x</a>' in r.message)
    # Slice of <a> shouldn't start with BOM.
    t.expect('BOM: slice clean of BOM', '\ufeff' not in r.message)

    # --- mixed content: read works, modify would refuse (not this tool) ---
    r = tool.execute(backend, file_path='proj/mixed.xml', address='a')
    t.expect('mixed: read ok', r.status == 'ok', r.message)
    t.expect('mixed: text shows both texts', 'x' in r.message and 'z' in r.message)

    # --- errors ----------------------------------------------------------
    r = tool.execute(backend, file_path='proj/a.xml', address='Defs/Nope[1]')
    t.expect_code('not_found tag', r, 'not_found')

    r = tool.execute(backend, file_path='proj/a.xml', address='Nope')
    t.expect_code('wrong root', r, 'not_found')

    r = tool.execute(backend, file_path='proj/a.xml', address='')
    t.expect_code('empty address', r, 'bad_input')

    r = tool.execute(backend, file_path='proj/a.xml', address='Defs/RoofDef[')
    t.expect_code('bad address', r, 'bad_address')

    r = tool.execute(backend, file_path='proj/missing.xml', address='root')
    t.expect_code('missing file', r, 'not_found')

    backend.close()

# --- integration: real RimWorld file ----------------------------------------

RW = Path('D:/Programs/UnityAiDevSystem/RimWorld')
if RW.is_dir():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        project = tmp / 'project'
        state = project / '.patch_applier'
        state.mkdir(parents=True)
        w = ws_mod.Workspace(id='rw', name='rw', xml={
            'discriminators': {
                'RoofDef': ['defName', '@Name'],
                'Operation': '@Class',
            }
        })
        ws_mod.add_root(w, str(RW))
        ws_mod.save(w, state)
        backend = MultiRootFsBackend(w, state)
        backend.open()
        tool = XmlReadTool()

        r = tool.execute(backend, file_path='RimWorld/Data/Anomaly/Defs/Misc/Roofs.xml',
                         address='Defs/RoofDef[VoidmetalRoof]')
        t.expect('RW Roofs: ok', r.status == 'ok', r.message)
        t.expect('RW Roofs: content', '<label>void metal ceiling</label>' in r.message)

        r = tool.execute(backend,
                         file_path='RimWorld/PatchApplier/AnotherXML/Cyberpunk.xml',
                         address='tweakdb/record_update[gamedataStatModifierGroup_Record:PlayerBaseCarryCapacity]')
        # Discriminator not configured for record_update here → falls back.
        # Fallback chain on <record_update> won't find dbid → not_found.
        t.expect_code('RW Cyberpunk w/o cfg: not_found', r, 'not_found')

        backend.close()
else:
    print(PASS + ' RimWorld integration: skipped (root absent)')
    t.passed += 1

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
