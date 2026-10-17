"""Tests for index version counter (toolkit/indexers/state.py)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import RootDirBackend
from toolkit.indexers.state import bump_seq, read_seq


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


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        backend = RootDirBackend(root)
        vpath = "INDEX.md.version"

        print("== read missing ==")
        t.expect("missing -> 0", read_seq(backend, vpath) == 0)

        print()
        print("== first bump ==")
        seq = bump_seq(backend, vpath)
        t.expect("first bump -> 1", seq == 1)
        t.expect("file created", (root / vpath).is_file())
        t.expect("read matches", read_seq(backend, vpath) == 1)

        print()
        print("== subsequent bumps ==")
        t.expect("bump -> 2", bump_seq(backend, vpath) == 2)
        t.expect("bump -> 3", bump_seq(backend, vpath) == 3)
        t.expect("read matches 3", read_seq(backend, vpath) == 3)

        print()
        print("== content shape ==")
        data = json.loads((root / vpath).read_text(encoding="utf-8"))
        t.expect("dict with seq", isinstance(data, dict) and "seq" in data)
        t.expect("seq is int 3", data["seq"] == 3)

        print()
        print("== malformed file ==")
        (root / vpath).write_text("not json", encoding="utf-8")
        t.expect("malformed -> 0", read_seq(backend, vpath) == 0)
        t.expect("bump after malformed -> 1", bump_seq(backend, vpath) == 1)

        print()
        print("== wrong shape ==")
        (root / vpath).write_text(json.dumps({"seq": "abc"}), encoding="utf-8")
        t.expect("non-int seq -> 0", read_seq(backend, vpath) == 0)

        (root / vpath).write_text(json.dumps({"seq": -5}), encoding="utf-8")
        t.expect("negative seq -> 0", read_seq(backend, vpath) == 0)

        (root / vpath).write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        t.expect("list not dict -> 0", read_seq(backend, vpath) == 0)

        (root / vpath).write_text(json.dumps({"seq": True}), encoding="utf-8")
        t.expect("bool not counted as int -> 0", read_seq(backend, vpath) == 0)

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
