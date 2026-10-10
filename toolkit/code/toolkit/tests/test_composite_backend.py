"""Tests for CompositeBackend path routing + lifecycle delegation."""
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends.composite import CompositeBackend
from toolkit.core.paths import ROBLOX_SERVICES


PASS = "[OK]  "
FAIL = "[FAIL]"


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def expect(self, label, cond, detail=""):
        if cond:
            print(f"{PASS} {label}")
            self.passed += 1
        else:
            print(f"{FAIL} {label}" + (f" -- {detail}" if detail else ""))
            self.failed += 1


class FakeBackend:
    def __init__(self, name):
        self.name = name
        self.calls = []
        self._alive = False
        self.files = {}
        self.working_dir = Path("/fake")

    def _log(self, op, path, **kw):
        self.calls.append((op, path, kw))

    def open(self):
        self._alive = True

    def close(self):
        self._alive = False

    def is_alive(self):
        return self._alive

    def read(self, path):
        self._log("read", path)
        return f"[{self.name}] {path}"

    def write(self, path, content):
        self._log("write", path, content=content)

    def exists(self, path):
        self._log("exists", path)
        return True

    def stat(self, path):
        self._log("stat", path)
        return (self.name, path)

    def list(self, root="", glob="*"):
        self._log("list", root, glob=glob)
        return [f"{self.name}::{root}::{glob}"]

    def delete(self, path):
        self._log("delete", path)

    def move(self, src, dst):
        self._log("move", src, dst=dst)

    def filter_check(self, path, spec):
        self._log("filter", path)
        return None


def main():
    t = T()

    fs = FakeBackend("fs")
    mcp = FakeBackend("mcp")
    comp = CompositeBackend([("fs", fs), ("mcp", mcp)])

    print("== lifecycle ==")
    comp.open()
    t.expect("open enables all", fs.is_alive() and mcp.is_alive())
    t.expect("is_alive true when all alive", comp.is_alive())
    mcp.close()
    # A degraded composite (mcp down, fs up) is a supported state:
    # ops owned by live backends keep working. See is_alive() docstring.
    # Note: composite tracks its own state; closing a sub-backend directly
    # does not update it. Check the sub-backend itself.
    t.expect("degraded: composite still alive (fs up)", comp.is_alive())
    t.expect("degraded: mcp sub-backend dead", not mcp.is_alive())
    fs.close()
    comp.close()

    comp.open()

    print()
    print("== routing ==")
    fs.calls.clear(); mcp.calls.clear()
    r = comp.read("toolkit/core/models.py")
    t.expect("read fs path routed to fs", r.startswith("[fs]"), r)
    t.expect("no mcp call", len(mcp.calls) == 0, mcp.calls)

    r = comp.read("ReplicatedStorage.Shared.Domain.ItemFormula")
    t.expect("read DataModel path routed to mcp", r.startswith("[mcp]"), r)

    r = comp.read("README.md")
    t.expect("read root file routed to fs", r.startswith("[fs]"), r)

    r = comp.read("ServerScriptService.Services.CraftService")
    t.expect("read SSS routed to mcp", r.startswith("[mcp]"), r)

    r = comp.read("bridge.py")
    t.expect("read script at root routed to fs", r.startswith("[fs]"), r)

    print()
    print("== write / delete / move routing ==")
    fs.calls.clear(); mcp.calls.clear()
    comp.write("docs/README.md", "hi")
    t.expect("write fs path -> fs", any(c[0]=="write" for c in fs.calls))
    t.expect("write fs path -> no mcp", not any(c[0]=="write" for c in mcp.calls))

    fs.calls.clear(); mcp.calls.clear()
    comp.write("ReplicatedStorage.X", "src")
    t.expect("write mcp path -> mcp", any(c[0]=="write" for c in mcp.calls))
    t.expect("write mcp path -> no fs", not any(c[0]=="write" for c in fs.calls))

    print()
    print("== list routing ==")
    fs.calls.clear(); mcp.calls.clear()
    comp.list("")
    t.expect("list('') -> fs", any(c[0]=="list" for c in fs.calls))
    fs.calls.clear(); mcp.calls.clear()
    comp.list("toolkit")
    t.expect("list('toolkit') -> fs", any(c[0]=="list" for c in fs.calls))
    fs.calls.clear(); mcp.calls.clear()
    comp.list("ReplicatedStorage")
    t.expect("list('ReplicatedStorage') -> mcp", any(c[0]=="list" for c in mcp.calls))

    print()
    print("== cross-backend move rejected ==")
    try:
        comp.move("toolkit/x.py", "ReplicatedStorage.Y")
        t.expect("cross-backend move raises", False)
    except RuntimeError as e:
        t.expect("cross-backend move raises", "cross" in str(e).lower() or "не supported" in str(e).lower())

    print()
    print("== filter delegates ==")
    from toolkit.core import FilterSpec
    fs.calls.clear(); mcp.calls.clear()
    comp.filter_check("toolkit/x.py", FilterSpec())
    t.expect("filter fs path -> fs", any(c[0]=="filter" for c in fs.calls))
    fs.calls.clear(); mcp.calls.clear()
    comp.filter_check("ReplicatedStorage.X", FilterSpec())
    t.expect("filter mcp path -> mcp", any(c[0]=="filter" for c in mcp.calls))

    print()
    print("== ROBLOX_SERVICES coverage ==")
    for svc in ("ReplicatedStorage", "ServerScriptService", "ServerStorage",
                "StarterPlayer", "Workspace", "Players"):
        t.expect(f"{svc} in ROBLOX_SERVICES", svc in ROBLOX_SERVICES)

    comp.close()

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
