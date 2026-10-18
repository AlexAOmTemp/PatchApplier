"""Smoke-test llmscope parse/match/serialize — no backend needed."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from toolkit.config import llmscope


def main() -> int:
    text = """
# file-level comment
Source            # engine, not our mod
Mods/*            # other mods
!Mods/1201382956  # our target mod
tests             # pytest suite
*.g.cs            # generated code
"""
    rules = llmscope.parse(text)
    assert len(rules) == 5, rules
    assert rules[0].glob == "Source" and rules[0].reason == "engine, not our mod"
    assert not rules[0].negated
    assert rules[2].negated and rules[2].glob == "Mods/1201382956"

    scope = llmscope.Scope(rules)
    cases = [
        ("Source/Foo.cs", True),
        ("Source/a/b/c.cs", True),
        ("Mods", False),
        ("Mods/other/x.cs", True),
        ("Mods/other/deep/x.cs", True),
        ("Mods/1201382956/x.cs", False),
        ("Mods/1201382956/Defs/y.xml", False),
        ("tests/test_x.py", True),
        ("a/b/test_util.py", False),
        ("foo.g.cs", True),
        ("a/b/foo.g.cs", True),
        ("src/main.py", False),
    ]
    fail = 0
    for path, expect in cases:
        got = scope.is_hidden(path)
        ok = got == expect
        if not ok:
            fail += 1
        print(f"[{'OK' if ok else 'FAIL'}] {path} -> {got} (want {expect})")

    paths = ["Source/x.cs", "Mods/other/y.cs", "Mods/1201382956/z.cs", "src/main.py"]
    visible, hidden = scope.partition(paths)
    assert visible == ["Mods/1201382956/z.cs", "src/main.py"], visible
    assert hidden == {"Source": 1, "Mods/*": 1}, hidden
    print(f"[OK] partition: visible={len(visible)} hidden={hidden}")

    rt = llmscope.parse(llmscope.serialize(scope))
    assert rt == rules, (rt, rules)
    print("[OK] serialize roundtrip")

    try:
        llmscope.parse("Source\n")
        print("[FAIL] rule without reason accepted")
        fail += 1
    except llmscope.ScopeParseError:
        print("[OK] rule without reason rejected")

    print(f"\n{'all checks passed' if fail == 0 else f'{fail} failure(s)'}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
