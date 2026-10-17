'''Regression: working_dir is gone from RootDirBackend.

After the multi-root prep refactor:
  - RootDirBackend stores its root as private `_root` (Path), not as a
    public `working_dir` attribute.
  - MultiDomainBackend.working_dir is a property that probes
    `_root -> working_dir` on the FS sub-backend, returns None when no FS.

The public constructor argument `working_dir` is kept for compatibility
with existing call sites (CLI, GUI, smoke scripts); only the attribute
name changed.

Run: python toolkit/code/toolkit/tests/test_working_dir_removed.py
'''
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import RootDirBackend
from toolkit.backends.multi_domain import MultiDomainBackend


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

    def raises_attr(self, label, obj, name):
        try:
            getattr(obj, name)
            print(FAIL + ' ' + label + ' -- attribute present')
            self.failed += 1
        except AttributeError:
            print(PASS + ' ' + label + ' (AttributeError)')
            self.passed += 1


class _LegacyFS:
    '''Fake FS backend that still exposes the old public working_dir.'''
    def __init__(self, wd):
        self.working_dir = wd


class _NoRootFS:
    '''Fake FS backend with neither _root nor working_dir.'''


class _MCPOnly:
    '''Stand-in for an MCP sub-backend (no working_dir).'''


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # --- RootDirBackend: private root, no public working_dir ---
        b = RootDirBackend(root)
        t.expect('fs._root is Path', isinstance(b._root, Path))
        t.expect('fs._root resolves to root', b._root == root.resolve())
        t.raises_attr('fs.working_dir gone', b, 'working_dir')

        # --- Composite: FS with _root -> property returns _root ---
        cb = MultiDomainBackend([('fs', b)])
        t.expect('composite.working_dir == fs._root',
                 cb.working_dir == b._root,
                 'got ' + repr(cb.working_dir))

        # --- Composite: legacy FS with only working_dir ---
        legacy = _LegacyFS(root)
        cb2 = MultiDomainBackend([('fs', legacy)])
        t.expect('composite falls back to legacy working_dir',
                 cb2.working_dir == root,
                 'got ' + repr(cb2.working_dir))

        # --- Composite: FS with neither -> None ---
        cb3 = MultiDomainBackend([('fs', _NoRootFS())])
        t.expect('composite returns None when FS has no root',
                 cb3.working_dir is None,
                 'got ' + repr(cb3.working_dir))

        # --- Composite: no FS at all (only MCP) -> None ---
        cb4 = MultiDomainBackend([('mcp', _MCPOnly())])
        t.expect('composite returns None when no FS sub-backend',
                 cb4.working_dir is None,
                 'got ' + repr(cb4.working_dir))

        # --- Real RootDirBackend still reads/writes files ---
        (root / 'hello.txt').write_text('hi', encoding='utf-8')
        b.open()
        t.expect('read still works', b.read('hello.txt') == 'hi')
        b.close()

    print()
    print('=== ' + str(t.passed) + ' ok, ' + str(t.failed) + ' failed ===')
    return 0 if t.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
