"""Tests for get_status: session, indexes, policy rendering."""
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
from toolkit.tools.status import GetStatusTool


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

    _orig_ctx = dict(GetStatusTool._context)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # --- 1. filesystem only, empty policy ---
        print("== fs only, empty policy ==")
        GetStatusTool.set_context(
            project_name="proj",
            backend="filesystem",
            format_preset="default",
            exec_enabled=False,
            index_paths={"docs": "INDEX.md", "code": "CODE_INDEX.md",
                         "lua": "CODE_INDEX_LUA.md"},
            policy=Policy(),
            backends_enabled={"filesystem"},
        )
        r = _run(root, [{"action": "get_status", "arguments": {}}])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("has Session", "## Session" in r.message)
        t.expect("project shown", "proj" in r.message)
        t.expect("has Indexes", "## Indexes" in r.message)
        t.expect("has Policy Filesystem", "## Policy Filesystem" in r.message)
        t.expect("no Policy Roblox", "## Policy Roblox" not in r.message)
        t.expect("no native line (no mcp)", "native:" not in r.message)
        t.expect("no lua mention", "CODE_INDEX_LUA" not in r.message)
        t.expect("exec disabled shown", "disabled" in r.message)
        t.expect("root RWI", "(root)" in r.message and "[RWI]" in r.message)

        # --- 2. exec enabled with interpreter ---
        print()
        print("== exec enabled ==")
        GetStatusTool.set_context(
            project_name="proj",
            backend="filesystem",
            exec_enabled=True,
            exec_interpreter="/usr/bin/python3",
            policy=Policy(),
            backends_enabled={"filesystem"},
        )
        r = _run(root, [{"action": "get_status", "arguments": {"sections": "session"}}])[0]
        t.expect("ok", r.status == "ok")
        t.expect("enabled shown", "enabled" in r.message)
        t.expect("interpreter shown", "/usr/bin/python3" in r.message)
        t.expect("only session section", "## Indexes" not in r.message)

        # --- 3. whitelist on read ---
        print()
        print("== whitelist read: docs, toolkit ==")
        pol = Policy.uniform(mode="white", paths=["docs", "toolkit"])
        GetStatusTool.set_context(
            project_name="proj",
            backend="filesystem",
            policy=pol,
            backends_enabled={"filesystem"},
        )
        r = _run(root, [{"action": "get_status", "arguments": {"sections": "policy"}}])[0]
        t.expect("ok", r.status == "ok", r.message)
        # Policy.uniform applies the same rule to all three roles, so a
        # white-list with ".": False denies read, write and index at root.
        t.expect("root empty", "[]" in r.message)
        t.expect("docs RWI", "docs" in r.message and "[RWI]" in r.message)
        t.expect("toolkit RWI", "toolkit" in r.message)

        # --- 4. composite backends -> both policy sections ---
        print()
        print("== composite backends ==")
        GetStatusTool.set_context(
            project_name="proj",
            backend="composite",
            policy=Policy(),
            backends_enabled={"filesystem", "mcp"},
            index_paths={"docs": "INDEX.md", "code": "CODE_INDEX.md",
                         "lua": "CODE_INDEX_LUA.md"},
        )
        r = _run(root, [{"action": "get_status", "arguments": {}}])[0]
        t.expect("ok", r.status == "ok")
        t.expect("Policy Filesystem", "## Policy Filesystem" in r.message)
        t.expect("no Policy Roblox", "## Policy Roblox" not in r.message)
        t.expect("lua mentioned", "CODE_INDEX_LUA" in r.message)
        t.expect("native disabled shown", "native:   disabled" in r.message)

        # --- 5. mcp only -> no FS policy section ---
        print()
        print("== mcp only ==")
        GetStatusTool.set_context(
            project_name="proj",
            backend="mcp",
            policy=Policy(),
            backends_enabled={"mcp"},
            index_paths={"docs": "INDEX.md", "code": "CODE_INDEX.md",
                         "lua": "CODE_INDEX_LUA.md"},
        )
        r = _run(root, [{"action": "get_status", "arguments": {}}])[0]
        t.expect("ok", r.status == "ok")
        t.expect("no Policy Filesystem", "## Policy Filesystem" not in r.message)
        t.expect("no Policy Roblox", "## Policy Roblox" not in r.message)
        t.expect("native disabled shown", "native:   disabled" in r.message)
        t.expect("no INDEX.md mention", "INDEX.md" not in r.message)
        t.expect("no CODE_INDEX.md mention", "CODE_INDEX.md" not in r.message)

        # --- 6. index present, version shown ---
        print()
        print("== index present ==")
        (root / "INDEX.md").write_text("# Index\n\n## docs/a.md\n", encoding="utf-8")
        (root / "INDEX.md.version").write_text(json.dumps({"seq": 12}), encoding="utf-8")
        GetStatusTool.set_context(
            project_name="proj",
            backend="filesystem",
            policy=Policy(),
            backends_enabled={"filesystem"},
        )
        r = _run(root, [{"action": "get_status", "arguments": {"sections": "indexes"}}])[0]
        t.expect("ok", r.status == "ok")
        t.expect("version shown", "[v12]" in r.message)
        t.expect("files counted", "1 files" in r.message)

        # --- 7. unknown section ---
        print()
        print("== unknown section ==")
        r = _run(root, [{"action": "get_status",
                         "arguments": {"sections": ["nope"]}}])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code", r.error_code == "unknown_section")

    GetStatusTool._context = _orig_ctx

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
