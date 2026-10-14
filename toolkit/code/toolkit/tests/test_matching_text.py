"""Tests for toolkit.matching.text — the shared write-side matcher.

Mirrors `replace_in_file` tier semantics: tier 1 byte-exact tried first;
if any exact match exists, only those are returned. Tier 2 (trailing-
whitespace tolerance) fires only when tier 1 finds nothing.

Covers:
  - tier 1: byte-exact, exact positions, non-overlapping
  - tier 1 wins: if any exact match exists, tier 2 does not fire
  - tier 2: trailing-whitespace tolerance on multi-line needles
  - tier 2: disabled by normalize_trailing=False
  - leading whitespace is NOT normalised
  - empty needle -> no matches
  - find_text returns the first match only
  - similar_lines returns ranked candidates; mark_invisible shows markers

Run: python toolkit/code/toolkit/tests/test_matching_text.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.matching.text import (
    TextMatch,
    find_all_text,
    find_text,
    mark_invisible,
    similar_lines,
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


t = T()

# --- tier 1: exact ---------------------------------------------------------
m = find_all_text('hello world', 'world')
t.expect('exact: one match', len(m) == 1, repr(m))
t.expect('exact: span', m[0].start == 6 and m[0].end == 11, repr(m[0]))
t.expect('exact: normalization=none', m[0].normalization == 'none')
t.expect('exact: is_exact', m[0].is_exact)

# --- tier 1: multiple exact, non-overlapping -------------------------------
m = find_all_text('aaaa', 'aa')
t.expect('exact: two non-overlapping', len(m) == 2, repr(m))
t.expect('exact: positions',
         m[0].start == 0 and m[1].start == 2, repr(m))

# --- tier 1: no exact, needle not present ----------------------------------
m = find_all_text('hello world', 'xyz')
t.expect('exact miss: empty list', m == [], repr(m))

# --- tier 1 substring semantics -------------------------------------------
# 'foo()' is a substring of 'foo()  ' — byte-exact matching finds both.
# Trailing whitespace in the file is kept, not normalised.
m = find_all_text('foo()\nfoo()  \nbar()\n', 'foo()')
t.expect('substring: both occurrences match', len(m) == 2, repr(m))
t.expect('substring: all normalization=none',
         all(x.normalization == 'none' for x in m), repr(m))
t.expect('substring: spans',
         m[0].start == 0 and m[0].end == 5
         and m[1].start == 6 and m[1].end == 11, repr(m))

# --- tier 2: multi-line needle, first file line has trailing ws ------------
# needle: 'def f():\n    return 1' (no trailing ws)
# file:   'def f():  \n    return 1\n' (two trailing spaces)
# tier 1 cannot find it byte-exact; tier 2 matches after rstrip.
m = find_all_text('def f():  \n    return 1\n',
                  'def f():\n    return 1')
t.expect('tier2 multi: one match', len(m) == 1, repr(m))
t.expect('tier2 multi: normalization=trailing',
         m[0].normalization == 'trailing', repr(m[0]))
t.expect('tier2 multi: start=0', m[0].start == 0, repr(m[0]))
t.expect('tier2 multi: is_exact False',
         m[0].is_exact is False)

# --- tier 2: two multi-line blocks, occurrence selection -------------------
m = find_all_text(
    'def a():  \n    return 1\n\ndef b():  \n    return 2\n',
    'def a():\n    return 1')
t.expect('tier2 first-of-two: one match', len(m) == 1, repr(m))
t.expect('tier2 first-of-two: start=0', m[0].start == 0, repr(m[0]))

# --- tier 2: disabled ------------------------------------------------------
m = find_all_text('def f():  \n    return 1\n',
                  'def f():\n    return 1',
                  normalize_trailing=False)
t.expect('tier2 disabled: no match', m == [], repr(m))

# --- leading whitespace is NOT normalised ----------------------------------
# needle indent differs from file indent -> no match even at tier 2
m = find_all_text('def f():\n    return 1\n',
                  'def f():\n  return 1')
t.expect('leading ws preserved: no match', m == [], repr(m))

# --- empty needle ----------------------------------------------------------
m = find_all_text('abc', '')
t.expect('empty needle: no matches', m == [], repr(m))

# --- find_text returns first only ------------------------------------------
m = find_text('aaa', 'aa')
t.expect('find_text: first match only',
         m is not None and m.start == 0, repr(m))
t.expect('find_text: returns None on miss',
         find_text('abc', 'xyz') is None)

# --- similar_lines ---------------------------------------------------------
sim = similar_lines('from .model import Block\nfrom .foo import Bar\n',
                    'from .core import Something')
t.expect('similar_lines: at least one candidate', len(sim) >= 1, repr(sim))
t.expect('similar_lines: sorted desc by ratio',
         all(sim[i][2] >= sim[i+1][2] for i in range(len(sim)-1)),
         repr(sim))

# --- mark_invisible --------------------------------------------------------
t.expect('mark_invisible: trailing space -> \u2423',
         '\u2423' in mark_invisible('foo  '))
t.expect('mark_invisible: tab anywhere -> \u21e5',
         '\u21e5' in mark_invisible('\tfoo'))

# --- TextMatch.is_exact ----------------------------------------------------
t.expect('TextMatch exact', TextMatch(0, 1, 'none').is_exact)
t.expect('TextMatch not exact',
         TextMatch(0, 1, 'trailing').is_exact is False)


print()
print(f'=== {t.passed} ok, {t.failed} failed ===')
sys.exit(1 if t.failed else 0)
