"""Tests for FilterSpec / Policy / Backend filter_check (new model).

The model is: three roles, each with a dict of path overrides.
Value True = explicit allow, False = explicit deny. Missing = inherit
from nearest ancestor with an override, default allow at root.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import FilesystemBackend
from toolkit.core import FilterSpec, Policy, Session
from toolkit.formats import Format
from toolkit.tools import TOOL_MAP


PASS = "[OK]  "
FAIL = "[FAIL]"


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def expect(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"{PASS} {label}")
            self.passed += 1
        else:
            print(f"{FAIL} {label}" + (f" -- {detail}" if detail else ""))
            self.failed += 1


def _run(root: Path, patches: list[dict], policy: Policy):
    backend = FilesystemBackend(root)
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP, policy=policy) as s:
        return s.apply_patches(patches)


def main():
    t = T()

    # --- FilterSpec.resolve ---
    print("== FilterSpec.resolve ==")
    empty = FilterSpec()
    t.expect("empty allows any", empty.resolve("anything/x.py"))
    t.expect("empty allows root file", empty.resolve("README.md"))

    w = FilterSpec.from_legacy("white", ["toolkit"])
    t.expect("white: toolkit/x.py allowed", w.resolve("toolkit/x.py"))
    t.expect("white: toolkit/sub/y.py allowed", w.resolve("toolkit/sub/y.py"))
    t.expect("white: root file denied", not w.resolve("README.md"))
    t.expect("white: docs/x.md denied", not w.resolve("docs/x.md"))

    b = FilterSpec.from_legacy("black", ["_reference"])
    t.expect("black: _reference/x.py denied", not b.resolve("_reference/x.py"))
    t.expect("black: _reference/sub/y.py denied", not b.resolve("_reference/sub/y.py"))
    t.expect("black: toolkit/x.py allowed", b.resolve("toolkit/x.py"))
    t.expect("black: root file allowed", b.resolve("README.md"))

    inh = FilterSpec(overrides={".": False, "toolkit": True, "toolkit/tests/fixtures": False})
    t.expect("inh: toolkit/x.py allowed", inh.resolve("toolkit/x.py"))
    t.expect("inh: toolkit/sub/z.py allowed", inh.resolve("toolkit/sub/z.py"))
    t.expect("inh: toolkit/tests/fixtures/a.py denied", not inh.resolve("toolkit/tests/fixtures/a.py"))
    t.expect("inh: toolkit/tests/b.py allowed", inh.resolve("toolkit/tests/b.py"))
    t.expect("inh: root file denied", not inh.resolve("README.md"))
    t.expect("inh: docs/c.md denied", not inh.resolve("docs/c.md"))

    # --- Policy.from_dict ---
    print()
    print("== Policy.from_dict ==")
    p_new = Policy.from_dict({
        "read": {"overrides": {"toolkit": True, ".": False}},
        "write": {"overrides": {"toolkit/tests/fixtures": False}},
        "index": {"overrides": {}},
    })
    t.expect("read allows toolkit", p_new.read.resolve("toolkit/x.py"))
    t.expect("read denies root", not p_new.read.resolve("README.md"))
    t.expect("write denies fixtures",
             not p_new.write.resolve("toolkit/tests/fixtures/y.py"))
    t.expect("write allows toolkit", p_new.write.resolve("toolkit/x.py"))
    t.expect("index allows all", p_new.index.resolve("anything"))

    p_legacy_flat = Policy.from_dict({"mode": "white", "paths": ["toolkit"]})
    t.expect("legacy flat: read toolkit allowed",
             p_legacy_flat.read.resolve("toolkit/x.py"))
    t.expect("legacy flat: read docs denied",
             not p_legacy_flat.read.resolve("docs/y.md"))
    t.expect("legacy flat: same spec for write",
             p_legacy_flat.write.resolve("toolkit/x.py"))

    p_legacy_perop = Policy.from_dict({
        "read": {"mode": "white", "paths": ["toolkit"]},
        "write": {"mode": "none", "paths": []},
        "index": {"mode": "black", "paths": ["_reference"]},
    })
    t.expect("legacy per-op: read toolkit allowed",
             p_legacy_perop.read.resolve("toolkit/x.py"))
    t.expect("legacy per-op: write all allowed",
             p_legacy_perop.write.resolve("anything"))
    t.expect("legacy per-op: index denies _reference",
             not p_legacy_perop.index.resolve("_reference/x.py"))

    # --- Backend filter_check ---
    print()
    print("== Backend filter_check ==")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "toolkit").mkdir()
        (root / "toolkit" / "x.py").write_text("pass\n", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "y.md").write_text("# Y\n", encoding="utf-8")
        (root / "README.md").write_text("# R\n", encoding="utf-8")

        backend = FilesystemBackend(root)
        backend.open()

        spec_w = FilterSpec.from_legacy("white", ["toolkit"])
        t.expect("fc white: toolkit/x.py ok",
                 backend.filter_check("toolkit/x.py", spec_w) is None)
        t.expect("fc white: docs/y.md denied",
                 backend.filter_check("docs/y.md", spec_w) is not None)
        t.expect("fc white: README.md denied",
                 backend.filter_check("README.md", spec_w) is not None)

        spec_b = FilterSpec.from_legacy("black", ["docs"])
        t.expect("fc black: toolkit/x.py ok",
                 backend.filter_check("toolkit/x.py", spec_b) is None)
        t.expect("fc black: docs/y.md denied",
                 backend.filter_check("docs/y.md", spec_b) is not None)
        t.expect("fc black: README.md ok",
                 backend.filter_check("README.md", spec_b) is None)

        spec_i = FilterSpec(overrides={".": False, "toolkit": True, "toolkit/tests": False})
        (root / "toolkit" / "tests").mkdir()
        (root / "toolkit" / "tests" / "t.py").write_text("pass\n", encoding="utf-8")
        t.expect("fc inh: toolkit/x.py ok",
                 backend.filter_check("toolkit/x.py", spec_i) is None)
        t.expect("fc inh: toolkit/tests/t.py denied",
                 backend.filter_check("toolkit/tests/t.py", spec_i) is not None)

    # --- Session integration ---
    print()
    print("== Session + Policy integration ==")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "toolkit").mkdir()
        (root / "toolkit" / "x.md").write_text(
            "# X\n\n## 1. X1\n<!-- summary: s -->\n\nbody\n", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "y.md").write_text(
            "# Y\n\n## 1. Y1\n<!-- summary: s -->\n\nbody\n", encoding="utf-8")

        policy = Policy.uniform(mode="white", paths=["toolkit"])
        res = _run(root, [
            {"action": "read_file", "arguments": {"file_path": "toolkit/x.md"}},
            {"action": "read_file", "arguments": {"file_path": "docs/y.md"}},
            {"action": "rebuild_index", "arguments": {"docs_dir": ""}},
        ], policy)
        t.expect("toolkit readable", res[0].status == "ok", res[0].status)
        t.expect("docs blocked", res[1].status == "blocked", res[1].status)
        t.expect("rebuild ok", res[2].status == "ok", res[2].status)
        ix = (root / "INDEX.md").read_text(encoding="utf-8")
        t.expect("INDEX has toolkit/x.md", "toolkit/x.md" in ix)
        t.expect("INDEX lacks docs/y.md", "docs/y.md" not in ix)

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
