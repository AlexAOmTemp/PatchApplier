"""Smoke: grep with explicit `paths` must not apply default excludes."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

from toolkit.backends import FilesystemBackend  # noqa: E402
from toolkit.core import Policy, Session  # noqa: E402
from toolkit.formats import Format  # noqa: E402
from toolkit.tools import TOOL_MAP  # noqa: E402


def _check(label, ok):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return ok


def _run(root, patches):
    backend = FilesystemBackend(root)
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP, policy=Policy()) as s:
        return s.apply_patches(patches)


def main():
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".patch_applier").mkdir()
        (root / ".patch_applier" / "INDEX.md").write_text(
            "# Index\n\n## docs/a.md\nNEEDLE in dot dir\n", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "a.md").write_text(
            "# A\n\nNEEDLE in docs\n", encoding="utf-8")
        (root / "INDEX.md").write_text(
            "# Root index\nNEEDLE in root index\n", encoding="utf-8")

        # 1. explicit path inside a dot dir is read literally
        r = _run(root, [{"action": "grep",
                         "arguments": {"pattern": "NEEDLE",
                                       "paths": [".patch_applier/INDEX.md"],
                                       "fixed_strings": True}}])[0]
        ok &= _check("dot-dir explicit path: ok", r.status == "ok")
        ok &= _check("dot-dir explicit path: match", "NEEDLE" in r.message)

        # 2. explicit path to a normally-excluded INDEX.md is read
        r = _run(root, [{"action": "grep",
                         "arguments": {"pattern": "NEEDLE",
                                       "paths": ["INDEX.md"],
                                       "fixed_strings": True}}])[0]
        ok &= _check("explicit INDEX.md: match", "NEEDLE" in r.message)

        # 3. directory scan still excludes INDEX.md by default
        r = _run(root, [{"action": "grep",
                         "arguments": {"pattern": "NEEDLE",
                                       "directory": "",
                                       "file_glob": "*.md",
                                       "fixed_strings": True}}])[0]
        ok &= _check("dir scan: docs/a.md matched", "docs/a.md" in r.message)
        ok &= _check("dir scan: INDEX.md excluded",
                     "INDEX.md" not in r.message)

        # 4. explicit path + explicit exclude_glob narrows
        r = _run(root, [{"action": "grep",
                         "arguments": {"pattern": "NEEDLE",
                                       "paths": [".patch_applier/INDEX.md"],
                                       "exclude_glob": "INDEX.md",
                                       "fixed_strings": True}}])[0]
        ok &= _check("explicit + exclude: no match",
                     "Совпадений не найдено" in r.message)

    print()
    print("ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
