"""Tests for get_index tool: kind resolution, budget, clipping."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import FilesystemBackend
from toolkit.core import Policy, Session
from toolkit.formats import Format
from toolkit.tools import TOOL_MAP
from toolkit.tools.index import GetIndexTool


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


def _run(root: Path, patches: list[dict]):
    backend = FilesystemBackend(root)
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP, policy=Policy()) as s:
        return s.apply_patches(patches)


def main():
    t = T()

    _orig_paths = dict(GetIndexTool._paths)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        GetIndexTool.set_paths(None)  # defaults

        # --- 1. kind is required ---
        print("== kind required ==")
        r = _run(root, [{"action": "get_index", "arguments": {}}])[0]
        t.expect("error status", r.status == "error", f"{r.status}: {r.message}")
        t.expect("error_code == kind_required", r.error_code == "kind_required")
        t.expect("names valid kinds", "docs" in r.message and "code" in r.message)

        # --- 1b. missing index -> not an error ---
        print()
        print("== missing index ==")
        r = _run(root, [{"action": "get_index", "arguments": {"kind": "docs"}}])[0]
        t.expect("ok status", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("says not found", "not found" in r.message)
        t.expect("suggests rebuild", "rebuild_index" in r.message)

        # --- 2. present index, small ---
        print()
        print("== present index ==")
        (root / "INDEX.md").write_text("# Index\n\nhello\n", encoding="utf-8")
        (root / "INDEX.md.version").write_text(json.dumps({"seq": 7}), encoding="utf-8")
        r = _run(root, [{"action": "get_index", "arguments": {"kind": "docs"}}])[0]
        t.expect("ok", r.status == "ok")
        t.expect("version shown", "[v7]" in r.message)
        t.expect("content shown", "hello" in r.message)
        t.expect("not clipped", "clipped" not in r.message)

        # --- 2b. no max_bytes -> full content, no clip marker ---
        print()
        print("== no max_bytes -> full ==")
        big = "line\n" * 5000  # ~25 KB, well past old default 12 KB
        (root / "INDEX.md").write_text(big, encoding="utf-8")
        r = _run(root, [{"action": "get_index", "arguments": {"kind": "docs"}}])[0]
        t.expect("ok", r.status == "ok")
        t.expect("not clipped by default", "clipped" not in r.message)
        t.expect("full content present", r.message.count("line") >= 5000)

        # --- 3. explicit kind ---
        print()
        print("== explicit kind=docs ==")
        r = _run(root, [{"action": "get_index", "arguments": {"kind": "docs"}}])[0]
        t.expect("ok", r.status == "ok")
        t.expect("shows docs", "docs:" in r.message)

        # --- 4. multiple kinds ---
        print()
        print("== kind=[docs, code] ==")
        (root / "CODE_INDEX.md").write_text("# Code\n", encoding="utf-8")
        r = _run(root, [{"action": "get_index", "arguments": {"kind": ["docs", "code"]}}])[0]
        t.expect("ok", r.status == "ok")
        t.expect("has docs block", "docs:" in r.message)
        t.expect("has code block", "code:" in r.message)

        # --- 5. unknown kind ---
        print()
        print("== unknown kind ==")
        r = _run(root, [{"action": "get_index", "arguments": {"kind": "nope"}}])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == unknown_kind", r.error_code == "unknown_kind")

        # --- 6. clipping ---
        print()
        print("== clipping ==")
        big = "line\n" * 5000
        (root / "INDEX.md").write_text(big, encoding="utf-8")
        r = _run(root, [{"action": "get_index",
                         "arguments": {"kind": "docs", "max_bytes": 1000}}])[0]
        t.expect("ok", r.status == "ok")
        t.expect("clipped marker", "clipped to" in r.message)

        # --- 7. dedupe ---
        print()
        print("== duplicate kinds deduped ==")
        r = _run(root, [{"action": "get_index",
                         "arguments": {"kind": ["docs", "docs"]}}])[0]
        t.expect("ok", r.status == "ok")
        t.expect("only one docs block", r.message.count("docs:") == 1)

    GetIndexTool.set_paths(_orig_paths)

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
