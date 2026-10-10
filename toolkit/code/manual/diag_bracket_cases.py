"""Diagnostic: how does parse_patches handle bracket mistakes?"""
from __future__ import annotations
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # toolkit/code

from toolkit.core.patchparse import parse_patches  # noqa: E402


CASES = [
    ("normal single array",
     '[{"action": "a"}, {"action": "b"}]'),

    ("normal groups",
     '[{"action": "a"}]\n[{"action": "b"}]'),

    ("groups with commas",
     '[{"action": "a"}],\n[{"action": "b"}]'),

    ("[[ ]] around whole patch",
     '[[{"action": "a"}]]'),

    ("[[ ]] around one group (middle)",
     '[{"action": "a"}]\n[[{"action": "b"}]]\n[{"action": "c"}]'),

    ("extra ]] between groups",
     '[{"action": "a"}]]\n[{"action": "b"}]'),

    ("extra ]] at end",
     '[{"action": "a"}]]'),

    ("] instead of [ on ALL groups",
     ']{"action": "a"}\n]{"action": "b"}'),

    ("] instead of [ on middle group",
     '[{"action": "a"}]\n]{"action": "b"}\n[{"action": "c"}]'),

    ("[ instead of ] on close",
     '[{"action": "a"}]\n[{"action": "b"}[\n[{"action": "c"}]'),

    ("{} instead of [] on ALL groups",
     '{{"action": "a"}}\n{{"action": "b"}}'),

    ("{} around single action, no []",
     '{"action": "a"}\n{"action": "b"}'),

    ("broken middle group",
     '[{"action": "a"}]\n[{"action": "b" "c": 1}]\n[{"action": "d"}]'),
]


def _describe(result):
    if not result:
        return "[]"
    parts = []
    for item in result:
        a = item.get("action", "?")
        if a == "__parse_error__":
            parts.append(f"<err:g={item['arguments'].get('group')}>")
        else:
            parts.append(a)
    return "[" + ", ".join(parts) + "]"


def main():
    for label, text in CASES:
        try:
            result = parse_patches(text)
            print(f"{label:42s} -> {_describe(result)}")
        except Exception as e:
            print(f"{label:42s} -> EXCEPTION {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
