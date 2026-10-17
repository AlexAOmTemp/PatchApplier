"""Composite backend with a dead MCP sub-backend must still serve FS ops.

Regression test: previously MultiDomainBackend.open() raised if *any*
sub-backend failed, so a dead MCP killed the whole session and even a
filesystem-only patch was refused with "Session not ready".

Expected behaviour:
  - open() succeeds when at least one sub-backend is ready
  - is_alive() is True with FS up and MCP down
  - a patch touching an FS path applies
  - a patch touching an MCP path fails with `backend_not_ready`
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from toolkit.backends.multi_domain import MultiDomainBackend
from toolkit.backends.root_dir import RootDirBackend
from toolkit.core.session import Session
from toolkit.formats import Format
from toolkit.tools import TOOL_MAP


class DeadMCPBackend:
    """MCP stand-in that always fails to open."""

    def __init__(self):
        self._opened = False

    def open(self):
        raise RuntimeError("simulated bridge failure")

    def close(self):
        self._opened = False

    def is_alive(self):
        return False

    def read(self, path):
        raise RuntimeError("dead")

    def write(self, path, content):
        raise RuntimeError("dead")

    def exists(self, path):
        return False

    def stat(self, path):
        raise RuntimeError("dead")

    def list(self, directory, pattern):
        return []

    def delete(self, path):
        raise RuntimeError("dead")

    def move(self, src, dst):
        raise RuntimeError("dead")

    def filter_check(self, path, spec):
        return None


class T:
    def __init__(self):
        self.ok = 0
        self.fail = 0

    def expect(self, name, cond, extra=""):
        if cond:
            print(f"  PASS  {name}")
            self.ok += 1
        else:
            print(f"  FAIL  {name}  {extra}")
            self.fail += 1


def main():
    t = T()
    tmp = Path(__file__).resolve().parent / "_tmp_composite_degraded"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    try:
        (tmp / "note.md").write_text("# hello\n", encoding="utf-8")

        fs = RootDirBackend(str(tmp))
        mcp = DeadMCPBackend()
        cb = MultiDomainBackend([("fs", fs), ("mcp", mcp)])

        # 1. open() must not raise when only fs comes up
        try:
            cb.open()
            opened_ok = True
            err = ""
        except Exception as e:
            opened_ok = False
            err = f"{type(e).__name__}: {e}"
        t.expect("open() degrades gracefully", opened_ok, err)
        t.expect("fs ready", cb.backend_state("fs") == "ready")
        t.expect("mcp failed", cb.backend_state("mcp").startswith("failed"))

        # 2. is_alive() = True
        t.expect("is_alive() == True", cb.is_alive() is True)

        # 3. FS op through Session works
        fmt = Format.load("default", None)
        s = Session(cb, fmt=fmt, tools=TOOL_MAP)
        try:
            s.__enter__()
        except Exception as e:
            print(f"  (Session __enter__ tried to reopen; {e})")
        r = s.apply_patches([
            {"action": "create_file",
             "arguments": {"file_path": "new.txt", "file_content": "x"}},
        ])
        t.expect("fs patch applied", r and r[0].status == "ok",
                 r[0].message if r else "no result")
        t.expect("new file exists", (tmp / "new.txt").is_file())

        # 4. MCP op fails with backend_not_ready
        r2 = s.apply_patches([
            {"action": "read_file",
             "arguments": {"file_path": "Workspace.Foo"}},
        ])
        t.expect("mcp patch blocked",
                 r2 and r2[0].status == "error"
                 and r2[0].error_code == "backend_not_ready",
                 r2[0].message if r2 else "no result")

        s.__exit__(None, None, None)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n=== ИТОГ: ok={t.ok}, fail={t.fail} ===")
    sys.exit(0 if t.fail == 0 else 1)


if __name__ == "__main__":
    main()
