"""Tests for build_starter_text extras (roblox / xml).

Run: python toolkit/code/toolkit/tests/test_starter_text.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.runner.presenters.main import build_starter_text


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


t = T()

with tempfile.TemporaryDirectory() as td:
    docs = Path(td).resolve() / 'docs'
    docs.mkdir()
    (docs / 'RobloxCodeRules.md').write_text('ROBLOX RULES', encoding='utf-8')
    (docs / 'MCPBridgeRules.md').write_text('MCP BRIDGE RULES', encoding='utf-8')
    (docs / 'XML_START.md').write_text('XML TOOLS', encoding='utf-8')
    rstate = Path(td).resolve() / 'runtime'
    rstate.mkdir()

    def read_text(lang):
        return 'BASE TEXT', 'ru'

    def build(**kwargs):
        return build_starter_text(
            lang='ru', session=None,
            docs_dir=docs, runtime_state_dir=rstate,
            read_text_fn=read_text, **kwargs,
        )

    # --- no extras ---
    text, used, suffix = build(include_roblox=False, include_xml=False)
    t.expect('base: used=ru', used == 'ru')
    t.expect('base: no roblox', 'ROBLOX RULES' not in text)
    t.expect('base: no xml', 'XML TOOLS' not in text)
    t.expect('base: suffix empty', suffix == '', suffix)
    t.expect('base: has base', 'BASE TEXT' in text)

    # --- roblox only ---
    text, _, suffix = build(include_roblox=True, include_xml=False)
    t.expect('roblox: has roblox', 'ROBLOX RULES' in text)
    t.expect('roblox: has mcp', 'MCP BRIDGE RULES' in text)
    t.expect('roblox: no xml', 'XML TOOLS' not in text)
    t.expect('roblox: suffix', suffix == '+roblox', suffix)

    # --- xml only ---
    text, _, suffix = build(include_roblox=False, include_xml=True)
    t.expect('xml: has xml', 'XML TOOLS' in text)
    t.expect('xml: no roblox', 'ROBLOX RULES' not in text)
    t.expect('xml: suffix', suffix == '+xml', suffix)

    # --- both ---
    text, _, suffix = build(include_roblox=True, include_xml=True)
    t.expect('both: has roblox', 'ROBLOX RULES' in text)
    t.expect('both: has xml', 'XML TOOLS' in text)
    t.expect('both: suffix', suffix == '+roblox+xml', suffix)

    # --- xml default off ---
    text, _, _ = build(include_roblox=False)
    t.expect('xml default off', 'XML TOOLS' not in text)

    # --- missing file handled ---
    (docs / 'XML_START.md').unlink()
    text, _, _ = build(include_roblox=False, include_xml=True)
    t.expect('xml missing: not found note',
             'XML_START.md not found' in text, text[:300])
    t.expect('xml missing: no crash', True)

print()
print(f"=== {t.passed} passed, {t.failed} failed ===")
sys.exit(0 if t.failed == 0 else 1)
