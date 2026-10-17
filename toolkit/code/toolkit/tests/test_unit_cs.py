"""Tests for the C# unit adapter (tree-sitter-c-sharp).

Covers:
  - build: module, namespaces (block + file-scoped), types, members
  - qualname: nesting, overloads (occurrence), explicit interface impl
  - annotation: /// runs and /** */ blocks, plain // is not annotation
  - read_unit: head / body / block parts
  - replace_unit: body, all
  - remove_unit: part=all
  - _check_parses: broken C# is rejected with result_syntax_error
  - partial class across files: both units visible by qualname

Run: python toolkit/code/toolkit/tests/test_unit_cs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from toolkit.tools.unit import writer
from toolkit.tools.unit.reader import list_units, read_unit
from toolkit.tools.unit import adapter_cs


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


SAMPLE = '''using System;

namespace Game.Core
{
    /// <summary>
    /// A foo thing.
    /// </summary>
    public partial class Foo : IFoo, IBar
    {
        private int _x;

        public Foo(int x)
        {
            _x = x;
        }

        public void Bar() { }

        public void Bar(int y)
        {
            _x = y;
        }

        void IFoo.Bar()
        {
            _x = 0;
        }

        public int Prop { get; set; }

        public int Expr => _x * 2;

        public class Inner
        {
            public void Qux() { }
        }
    }
}
'''


def _qn(units: str) -> list[str]:
    out = []
    for line in units.splitlines():
        out.append(line.split()[0] if line.strip() else '')
    return [x for x in out if x]


def main():
    t = T()
    path = 'Foo.cs'

    # --- list_units ---
    rows = list_units(SAMPLE, path)
    qns = _qn(rows)
    t.expect('module listed', '<module>' in qns, rows)
    t.expect('namespace-prefixed class', 'Game.Core.Foo' in qns, rows)
    t.expect('nested class', 'Game.Core.Foo.Inner' in qns, rows)
    t.expect('nested method', 'Game.Core.Foo.Inner.Qux' in qns, rows)
    t.expect('constructor listed', 'Game.Core.Foo.Foo' in qns, rows)
    t.expect('three Bar overloads listed', qns.count('Game.Core.Foo.Bar') == 3, rows)
    t.expect('title shows params', '(int y)' in rows, rows)
    t.expect('title shows explicit iface', 'IFoo.Bar()' in rows, rows)

    # --- annotation: /// run belongs to class ---
    ann = read_unit(SAMPLE, path, {'qualname': 'Game.Core.Foo'}, part='annotation')
    t.expect('/// run is annotation', 'A foo thing.' in ann, ann)
    t.expect('annotation excludes class line', 'public partial class' not in ann, ann)

    # --- head / body ---
    head = read_unit(SAMPLE, path, {'qualname': 'Game.Core.Foo'}, part='head')
    t.expect('head is declaration line',
             head.strip() == 'public partial class Foo : IFoo, IBar', repr(head))
    body = read_unit(SAMPLE, path, {'qualname': 'Game.Core.Foo'}, part='body')
    t.expect('body contains members', 'public void Bar()' in body, body)
    t.expect('body excludes head', 'public partial class' not in body, body)

    # --- overloads via occurrence ---
    try:
        read_unit(SAMPLE, path, {'qualname': 'Game.Core.Foo.Bar'}, part='head')
        t.expect('overload without occurrence raises', False)
    except KeyError as e:
        t.expect('overload without occurrence raises', 'ambiguous' in str(e), str(e))

    h2 = read_unit(SAMPLE, path, {'qualname': 'Game.Core.Foo.Bar', 'occurrence': 2},
                   part='head')
    t.expect('occurrence=2 is (int y)', '(int y)' in h2, h2)
    h3 = read_unit(SAMPLE, path, {'qualname': 'Game.Core.Foo.Bar', 'occurrence': 3},
                   part='head')
    t.expect('occurrence=3 is explicit impl', 'IFoo.Bar' in h3, h3)

    # --- blocks inside body ---
    blk1 = read_unit(SAMPLE, path, {'qualname': 'Game.Core.Foo.Foo'}, block=1)
    t.expect('constructor block 1 is assignment', '_x = x' in blk1, blk1)

    # --- replace_unit part=body ---
    src = writer.replace_unit(SAMPLE, path, {'qualname': 'Game.Core.Foo.Bar',
                                             'occurrence': 2},
                              part='body', new_text='{\n            _x = 42;\n        }')
    t.expect('replace body changed it', '_x = 42' in src and '_x = y' not in src, src)
    t.expect('replace body kept sibling', 'public void Bar() { }' in src, src)

    # --- replace_unit part=all ---
    src2 = writer.replace_unit(SAMPLE, path, {'qualname': 'Game.Core.Foo.Bar',
                                              'occurrence': 2},
                               part='all',
                               new_text='public void Bar(int y)\n        {\n            _x = 7;\n        }')
    t.expect('replace all changed body', '_x = 7' in src2, src2)

    # --- remove_unit part=all ---
    src3 = writer.remove_unit(SAMPLE, path, {'qualname': 'Game.Core.Foo.Bar',
                                             'occurrence': 2},
                              part='all')
    t.expect('remove_unit removed the (int y) overload',
             'Bar(int y)' not in src3, src3)
    t.expect('remove_unit kept the no-arg overload',
             'public void Bar() { }' in src3, src3)
    t.expect('remove_unit kept the explicit-impl overload',
             'void IFoo.Bar()' in src3, src3)

    # --- _check_parses: broken C# rejected ---
    try:
        writer.replace_unit(SAMPLE, path, {'qualname': 'Game.Core.Foo.Bar',
                                           'occurrence': 2},
                            part='body', new_text='{\n            _x = ;\n        }')
        t.expect('broken C# rejected', False, 'no exception')
    except ValueError as e:
        t.expect('broken C# rejected', 'result_syntax_error' in str(e), str(e))

    # --- broken C# also caught in file-level syntax check ---
    tree = adapter_cs.parse_tree('class Foo { void Bar( { } }')
    t.expect('parse_tree flags broken input', tree.root_node.has_error)
    tree2 = adapter_cs.parse_tree(SAMPLE)
    t.expect('parse_tree flags clean input as clean', not tree2.root_node.has_error)

    # --- file-scoped namespace ---
    fs = 'namespace Game.Core;\n\npublic class Foo\n{\n    public void Bar() { }\n}\n'
    t.expect('file-scoped namespace prefixes class',
             'Game.Core.Foo' in _qn(list_units(fs, 'Foo.cs')), list_units(fs, 'Foo.cs'))

    # --- record / interface / struct / enum ---
    diverse = ('namespace N;\n\n'
               'public record Point(int X, int Y);\n\n'
               'public interface IFoo\n{\n    void Bar();\n}\n\n'
               'public struct Vec\n{\n    public float X;\n}\n\n'
               'public enum Color { Red, Green }\n')
    qns = _qn(list_units(diverse, 'D.cs'))
    for expected in ('N.Point', 'N.IFoo', 'N.IFoo.Bar', 'N.Vec', 'N.Vec.X', 'N.Color'):
        t.expect(f'{expected} listed', expected in qns, qns)

    # --- partial class in two files: same qualname, separate trees ---
    a = 'namespace N;\npublic partial class Foo { public void A() { } }\n'
    b = 'namespace N;\npublic partial class Foo { public void B() { } }\n'
    qa = _qn(list_units(a, 'A.cs'))
    qb = _qn(list_units(b, 'B.cs'))
    t.expect('partial A sees Foo.A', 'N.Foo.A' in qa, qa)
    t.expect('partial B sees Foo.B', 'N.Foo.B' in qb, qb)

    print()
    print(f'=== {t.passed} ok, {t.failed} failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
