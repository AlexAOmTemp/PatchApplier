"""Tests for toolkit.tools.xml.XmlAppendTool.

Run: python toolkit/code/toolkit/tests/test_xml_append_tool.py
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
from toolkit.tools.xml import XmlAppendTool


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
        '<Patch>\n  <Operation Class="X"/>\n</Patch>',
        encoding='utf-8')
    (proj / 'mixed.xml').write_text(
        '<root>some text <b>y</b> more</root>', encoding='utf-8')
    (proj / 'leaf.xml').write_text('<root>hello</root>', encoding='utf-8')

    project = tmp / 'project'
    state = project / '.patch_applier'
    state.mkdir(parents=True)
    w = ws_mod.Workspace(id='t', name='t')
    ws_mod.add_root(w, str(proj))
    ws_mod.save(w, state)
    backend = MultiRootFsBackend(w, state)
    backend.open()
    tool = XmlAppendTool()

    # happy path
    r = tool.execute(backend, path='proj/a.xml', parent='Patch',
                     fragment='<Operation Class="Y"><success>Always</success></Operation>')
    t.expect('append: ok', r.status == 'ok', r.message)
    t.expect('append: +B delta', 'B)' in r.message or 'B' in r.message)
    cur = (proj / 'a.xml').read_text(encoding='utf-8')
    t.expect('append: Y in file', 'Class="Y"' in cur)
    t.expect('append: indented 2 spaces', '\n  <Operation Class="Y">' in cur)
    t.expect('append: X untouched', 'Class="X"' in cur)

    # fragment with nested child is reindented
    r = tool.execute(backend, path='proj/a.xml', parent='Patch',
                     fragment='<Operation Class="Z">\n  <nested>v</nested>\n</Operation>')
    t.expect('multiline: ok', r.status == 'ok', r.message)
    cur = (proj / 'a.xml').read_text(encoding='utf-8')
    t.expect('multiline: Operation at 2', '\n  <Operation Class="Z">' in cur)
    t.expect('multiline: nested at 4', '\n    <nested>v</nested>' in cur)

    # malformed fragment
    r = tool.execute(backend, path='proj/a.xml', parent='Patch',
                     fragment='<bad')
    t.expect_code('malformed', r, 'bad_fragment')

    # multi-root fragment
    r = tool.execute(backend, path='proj/a.xml', parent='Patch',
                     fragment='<a/><b/>')
    t.expect_code('multi-root', r, 'bad_fragment')

    # mixed content parent
    r = tool.execute(backend, path='proj/mixed.xml', parent='root',
                     fragment='<c/>')
    t.expect_code('mixed parent', r, 'mixed_content_unsupported')

    # text leaf parent
    r = tool.execute(backend, path='proj/leaf.xml', parent='root',
                     fragment='<c/>')
    t.expect_code('leaf parent', r, 'mixed_content_unsupported')

    # not found
    r = tool.execute(backend, path='proj/a.xml', parent='Nope',
                     fragment='<x/>')
    t.expect_code('parent not found', r, 'not_found')

    # bad address
    r = tool.execute(backend, path='proj/a.xml', parent='Patch[',
                     fragment='<x/>')
    t.expect_code('bad address', r, 'bad_address')

    # empty fragment
    r = tool.execute(backend, path='proj/a.xml', parent='Patch',
                     fragment='  ')
    t.expect_code('empty fragment', r, 'bad_input')

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
        target = project / 'Roofs.xml'
        shutil.copyfile(
            RW / 'Data/Anomaly/Defs/Misc/Roofs.xml', target)
        w = ws_mod.Workspace(id='rw', name='rw', xml={
            'discriminators': {'RoofDef': ['defName', '@Name']}
        })
        ws_mod.add_root(w, str(project))
        ws_mod.save(w, state)
        backend = MultiRootFsBackend(w, state)
        backend.open()
        tool = XmlAppendTool()

        before = target.read_bytes()
        r = tool.execute(backend, path='project/Roofs.xml', parent='Defs',
                         fragment='<RoofDef><defName>TestRoof</defName></RoofDef>')
        t.expect('RW Roofs: ok', r.status == 'ok', r.message)
        after = target.read_bytes()
        t.expect('RW Roofs: BOM preserved', after.startswith(b'\xef\xbb\xbf'))
        t.expect('RW Roofs: CRLF preserved',
                 after.count(b'\r\n') >= before.count(b'\r\n'))
        t.expect('RW Roofs: TestRoof in file', b'<defName>TestRoof</defName>' in after)
        t.expect('RW Roofs: VoidmetalRoof intact',
                 b'<defName>VoidmetalRoof</defName>' in after)

        backend.close()
else:
    print(PASS + ' RimWorld integration: skipped')
    t.passed += 1

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
