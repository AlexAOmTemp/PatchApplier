"""Tests for toolkit.core.patchparse.parse_patches.

Two contracts:
  1. Every accepted shape parses to the same actions list.
  2. Malformed fragments become diagnostics, siblings survive.
  3. `id` is required; missing / duplicate produce diagnostics.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[2]))  # .../toolkit/code

from toolkit.core.patchparse import parse_patches  # noqa: E402


def _acts(text):
    return [a["action"] for a in parse_patches(text).actions]


def _diags(text):
    return parse_patches(text).diagnostics


class ShapesTest(unittest.TestCase):
    def test_single_object(self):
        self.assertEqual(_acts('{"id": 1, "action": "a"}'), ["a"])

    def test_single_array(self):
        self.assertEqual(
            _acts('[{"id": 1, "action": "a"}, {"id": 2, "action": "b"}]'),
            ["a", "b"],
        )

    def test_several_arrays(self):
        text = '[{"id": 1, "action": "a"}]\n[{"id": 2, "action": "b"}]'
        self.assertEqual(_acts(text), ["a", "b"])

    def test_arrays_with_commas(self):
        text = '[{"id": 1, "action": "a"}],\n[{"id": 2, "action": "b"}]'
        self.assertEqual(_acts(text), ["a", "b"])

    def test_jsonl(self):
        text = '{"id": 1, "action": "a"}\n{"id": 2, "action": "b"}'
        self.assertEqual(_acts(text), ["a", "b"])

    def test_code_fence(self):
        text = '```json\n[{"id": 1, "action": "a"}]\n```'
        self.assertEqual(_acts(text), ["a"])

    def test_empty(self):
        self.assertEqual(_acts(""), [])
        self.assertEqual(_acts("   \n  "), [])


class BracketMistakesTest(unittest.TestCase):
    def test_double_brackets_around_single_action(self):
        self.assertEqual(_acts('[[{"id": 1, "action": "a"}]]'), ["a"])

    def test_double_brackets_around_patch(self):
        self.assertEqual(
            _acts('[[{"id": 1, "action": "a"}, {"id": 2, "action": "b"}]]'),
            ["a", "b"],
        )

    def test_double_brackets_several_docs(self):
        text = '[[{"id": 1, "action": "a"}]]\n[[{"id": 2, "action": "b"}]]'
        self.assertEqual(_acts(text), ["a", "b"])

    def test_extra_closing_bracket_between(self):
        # `]]` between groups is harmless noise; both actions recover.
        text = '[{"id": 1, "action": "a"}]]\n[{"id": 2, "action": "b"}]'
        res = parse_patches(text)
        self.assertEqual([a["action"] for a in res.actions], ["a", "b"])
        self.assertEqual(res.diagnostics, [])

    def test_leading_stray_closing_bracket(self):
        # A leading `]` is noise; the action still recovers.
        text = '][{"id": 1, "action": "a"}]'
        res = parse_patches(text)
        self.assertEqual([a["action"] for a in res.actions], ["a"])
        self.assertEqual(res.diagnostics, [])


class IdTest(unittest.TestCase):
    def test_missing_id(self):
        res = parse_patches('[{"action": "a"}]')
        self.assertEqual(res.actions, [])
        self.assertEqual(len(res.diagnostics), 1)
        self.assertEqual(res.diagnostics[0].kind, "missing_id")

    def test_id_null_is_valid(self):
        # id value is not validated — null is a valid label.
        res = parse_patches('[{"id": null, "action": "a"}]')
        self.assertEqual([a["action"] for a in res.actions], ["a"])

    def test_id_zero_is_valid(self):
        res = parse_patches('[{"id": 0, "action": "a"}]')
        self.assertEqual([a["action"] for a in res.actions], ["a"])

    def test_id_string_is_valid(self):
        res = parse_patches('[{"id": "read-config", "action": "a"}]')
        self.assertEqual([a["action"] for a in res.actions], ["a"])

    def test_duplicate_id_warns_but_applies_both(self):
        text = '[{"id": 1, "action": "a"}, {"id": 1, "action": "b"}]'
        res = parse_patches(text)
        self.assertEqual([a["action"] for a in res.actions], ["a", "b"])
        self.assertEqual(len(res.diagnostics), 1)
        self.assertEqual(res.diagnostics[0].kind, "duplicate_id")


class SyntaxErrorsTest(unittest.TestCase):
    def test_broken_middle_group(self):
        text = (
            '[{"id": 1, "action": "a"}]\n'
            '[{"id": 2, "arguments": {"x": 1 "y": 2}}]\n'
            '[{"id": 3, "action": "c"}]'
        )
        res = parse_patches(text)
        self.assertEqual([a["action"] for a in res.actions], ["a", "c"])
        self.assertEqual(len(res.diagnostics), 1)
        self.assertEqual(res.diagnostics[0].kind, "syntax")

    def test_broken_first_group(self):
        text = (
            '[{"id": 1, "action": "a" "extra": 1}]\n'
            '[{"id": 2, "action": "b"}]'
        )
        res = parse_patches(text)
        self.assertEqual([a["action"] for a in res.actions], ["b"])
        self.assertTrue(any(d.kind == "syntax" for d in res.diagnostics))

    def test_broken_last_group(self):
        text = (
            '[{"id": 1, "action": "a"}]\n'
            '[{"id": 2, "action": "b" "extra": 1}]'
        )
        res = parse_patches(text)
        self.assertEqual([a["action"] for a in res.actions], ["a"])
        self.assertTrue(any(d.kind == "syntax" for d in res.diagnostics))

    def test_diagnostic_has_position(self):
        text = '[{"id": 1, "action": "a"}]\n[{"id": 2, "x": 1 "y": 2}]'
        res = parse_patches(text)
        d = res.diagnostics[0]
        self.assertEqual(d.kind, "syntax")
        self.assertGreaterEqual(d.line, 1)
        self.assertGreaterEqual(d.column, 1)
        self.assertTrue(d.fragment)


if __name__ == "__main__":
    unittest.main()
