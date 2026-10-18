"""Exempt-on-explicit-path semantics.

Rule: path=X bypasses rules matching X itself (or X/*), but rules on
X/sub stay active unless X/sub is itself the named path.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from toolkit.config import llmscope


def show(title, paths, pattern_text, path_prefix):
    scope = llmscope.Scope(llmscope.parse(pattern_text))
    ex = scope.exemptions_for(path_prefix)
    visible, hidden = scope.partition(paths, exempt=ex)
    print(f"\n[{title}]  path={path_prefix}")
    print(f"  exempt: {sorted(ex)}")
    print(f"  visible: {visible}")
    print(f"  hidden: {hidden}")
    return visible, hidden


RULES = """
tests          # hide all tests
tests/slow     # hide slow subdir
other          # hide other dir
"""

paths = [
    "tests/fast/test_a.py",
    "tests/slow/test_b.py",
    "tests/__init__.py",
    "other/x.py",
    "src/main.py",
]

# 1. path=tests -> shows non-slow tests, slow still hidden, other hidden
vis, hid = show("path=tests", paths, RULES, "tests")
assert "tests/__init__.py" in vis, vis
assert "tests/fast/test_a.py" in vis, vis
assert "tests/slow/test_b.py" not in vis, vis
assert hid == {"tests/slow": 1, "other": 1}, hid

# 2. path=tests/slow -> slow also shown
vis, hid = show("path=tests/slow", paths, RULES, "tests/slow")
assert "tests/slow/test_b.py" in vis, vis
assert hid == {"other": 1}, hid

# 3. path=other -> other shown, tests still hidden
vis, hid = show("path=other", paths, RULES, "other")
assert "other/x.py" in vis, vis
assert "tests/__init__.py" not in vis, vis
assert hid == {"tests": 2, "tests/slow": 1}, hid

# 4. no path -> no exemptions
scope = llmscope.Scope(llmscope.parse(RULES))
ex = scope.exemptions_for("")
assert ex == set(), ex

# 5. path=src (not hidden) -> no exemptions for src
vis, hid = show("path=src", paths, RULES, "src")
assert "src/main.py" in vis, vis

print("\n[OK] exempt-on-explicit-path works")
