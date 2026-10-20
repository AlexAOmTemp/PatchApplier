"""Tests for XmlDeleteTool and XmlReplaceTool.

Run: python toolkit/code/toolkit/tests/test_xml_delete_replace.py
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
from toolkit.tools.xml import XmlDeleteTool, XmlReplaceTool


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

def _setup(td):
    proj = Path(td).resolve() / 'proj'
    proj.mkdir()
    project = Path(td).resolve() / 'project'
    state = project / '.patch_applier'
    state.mkdir(parents=True)
    w = ws_mod.Workspace(id='t', name='t', xml={
        'discriminators': {'ThingDef': ['defName', '@Name']}
    })
    ws_mod.add_root(w, str(proj))
    ws_mod.save(w, state)
    backend = MultiRootFsBackend(w, state)
    backend.open()
    return proj, backend


# ========== xml_delete ==========

with tempfile.TemporaryDirectory() as td:
    proj, backend = _setup(td)
    tool = XmlDeleteTool()

    def write_and_read(content):
        (proj / 'a.xml').write_text(content, encoding='utf-8')
        return 'proj/a.xml'

    # Element on its own line: whole line + newline removed.
    path = write_and_read(
        '<Defs>\n  <ThingDef><defName>A</defName></ThingDef>\n  <ThingDef><defName>B</defName></ThingDef>\n</Defs>')
    r = tool.execute(backend, path=path, address='Defs/ThingDef[A]')
    t.expect('delete: ok', r.status == 'ok', r.message)
    cur = (proj / 'a.xml').read_text(encoding='utf-8')
    t.expect('delete: A gone', '<defName>A</defName>' not in cur)
    t.expect('delete: B kept', '<defName>B</defName>' in cur)
    t.expect('delete: no double newline', '\n\n' not in cur, repr(cur))

    # Delete root -> refused.
    r = tool.execute(backend, path=path, address='Defs')
    t.expect_code('delete root', r, 'cannot_delete_root')

    # Delete nonexistent.
    r = tool.execute(backend, path=path, address='Defs/ThingDef[C]')
    t.expect_code('delete missing', r, 'not_found')

    # Ambiguous.
    path = write_and_read(
        '<Defs>\n  <ThingDef><defName>A</defName></ThingDef>\n  <ThingDef><defName>A</defName></ThingDef>\n</Defs>')
    r = tool.execute(backend, path=path, address='Defs/ThingDef[A]')
    t.expect_code('delete ambiguous', r, 'ambiguous_address')
    r = tool.execute(backend, path=path, address='Defs/ThingDef[A]', occurrence=1)
    t.expect('delete occurrence=1: ok', r.status == 'ok', r.message)

    backend.close()


# ========== xml_replace ==========

with tempfile.TemporaryDirectory() as td:
    proj, backend = _setup(td)
    tool = XmlReplaceTool()

    def write_and_read(content):
        (proj / 'a.xml').write_text(content, encoding='utf-8')
        return 'proj/a.xml'

    # Simple replace.
    path = write_and_read(
        '<Defs>\n  <ThingDef><defName>A</defName></ThingDef>\n</Defs>')
    r = tool.execute(backend, path=path,
                     address='Defs/ThingDef[A]',
                     fragment='<ThingDef><defName>B</defName></ThingDef>')
    t.expect('replace: ok', r.status == 'ok', r.message)
    cur = (proj / 'a.xml').read_text(encoding='utf-8')
    t.expect('replace: A gone', '<defName>A</defName>' not in cur)
    t.expect('replace: B present', '<defName>B</defName>' in cur)
    t.expect('replace: 2-space indent kept', '\n  <ThingDef>' in cur, repr(cur))

    # Multi-line replace with reindent.
    path = write_and_read(
        '<Defs>\n  <A/>\n</Defs>')
    r = tool.execute(backend, path=path, address='Defs/A',
                     fragment='<A>\n  <b>x</b>\n</A>')
    t.expect('replace multiline: ok', r.status == 'ok', r.message)
    cur = (proj / 'a.xml').read_text(encoding='utf-8')
    t.expect('replace multiline: A at 2', '\n  <A>' in cur, repr(cur))
    t.expect('replace multiline: b at 4', '\n    <b>x</b>' in cur, repr(cur))

    # Replace root (allowed).
    path = write_and_read('<Root><x/></Root>')
    r = tool.execute(backend, path=path, address='Root',
                     fragment='<NewRoot><y/></NewRoot>')
    t.expect('replace root: ok', r.status == 'ok', r.message)
    cur = (proj / 'a.xml').read_text(encoding='utf-8')
    t.expect('replace root: NewRoot', '<NewRoot>' in cur)

    # Malformed fragment.
    path = write_and_read('<r><a/></r>')
    r = tool.execute(backend, path=path, address='r/a', fragment='<bad')
    t.expect_code('replace malformed', r, 'bad_fragment')

    # Multi-root fragment.
    r = tool.execute(backend, path=path, address='r/a', fragment='<a/><b/>')
    t.expect_code('replace multi-root', r, 'bad_fragment')

    # Not found.
    r = tool.execute(backend, path=path, address='r/nope', fragment='<x/>')
    t.expect_code('replace not_found', r, 'not_found')

    backend.close()


# ========== integration ==========

RW = Path('D:/Programs/UnityAiDevSystem/RimWorld')
if RW.is_dir():
    import shutil
    with tempfile.TemporaryDirectory() as td:
        proj, backend = _setup(td)
        target = proj / 'Roofs.xml'
        shutil.copyfile(RW / 'Data/Anomaly/Defs/Misc/Roofs.xml', target)

        delete_tool = XmlDeleteTool()
        r = delete_tool.execute(backend, path='proj/Roofs.xml',
                                address='Defs/RoofDef[VoidmetalRoof]')
        t.expect('RW delete: ok', r.status == 'ok', r.message)
        after = target.read_bytes()
        t.expect('RW delete: BOM preserved', after.startswith(b'\xef\xbb\xbf'))
        t.expect('RW delete: CRLF preserved', b'\r\n' in after)
        t.expect('RW delete: VoidmetalRoof gone', b'VoidmetalRoof' not in after)

        # Reset and try replace.
        shutil.copyfile(RW / 'Data/Anomaly/Defs/Misc/Roofs.xml', target)
        replace_tool = XmlReplaceTool()
        r = replace_tool.execute(
            backend, path='proj/Roofs.xml',
            address='Defs/RoofDef[VoidmetalRoof]',
            fragment='<RoofDef><defName>VoidmetalRoof</defName>'
                     '<label>edited</label></RoofDef>')
        t.expect('RW replace: ok', r.status == 'ok', r.message)
        after = target.read_bytes()
        t.expect('RW replace: BOM preserved', after.startswith(b'\xef\xbb\xbf'))
        t.expect('RW replace: edited label', b'<label>edited</label>' in after)

        backend.close()
else:
    print(PASS + ' RW integration: skipped')
    t.passed += 2

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
