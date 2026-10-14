"""Tests for MCPBackend — lifecycle, invoke protocol, read/exists/stat/list/write/delete/move/filter."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import MCPBackend


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


FAKE_BRIDGE = r'''\
import json
import os
import sys

WORK = os.path.dirname(os.path.abspath(__file__))
N_FLAG = os.path.join(WORK, "transient_count.txt")
STORE = os.path.join(WORK, "store.json")

# MCPBackend writes patch.json/outputs.json into a bridge_state/ subdir of
# working_dir and passes explicit paths via --patch-file/--outputs-file.
# fake_bridge must read those flags, not guess paths.
def _arg(name, default):
    try:
        i = sys.argv.index(name)
        return sys.argv[i + 1]
    except (ValueError, IndexError):
        return default

PATCH_FILE = _arg("--patch-file", os.path.join(WORK, "patch.json"))
OUTPUTS_FILE = _arg("--outputs-file", os.path.join(WORK, "outputs.json"))
try:
    os.makedirs(os.path.dirname(PATCH_FILE) or WORK, exist_ok=True)
    os.makedirs(os.path.dirname(OUTPUTS_FILE) or WORK, exist_ok=True)
except Exception:
    pass

def _next_transient():
    try:
        with open(N_FLAG, "r", encoding="utf-8") as f:
            n = int(f.read().strip() or "0")
    except Exception:
        n = 0
    if n > 0:
        with open(N_FLAG, "w", encoding="utf-8") as f:
            f.write(str(n - 1))
        return True
    return False

# Persistent store per path, so write→read verifies.
def _load_store():
    try:
        with open(STORE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "ReplicatedStorage.Foo.Bar": "-- initial source",
            "ReplicatedStorage.Foo.Baz": "-- baz source",
        }

def _save_store(s):
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False)

def _write_result(text, is_error=False):
    entry = {
        "timestamp": "2026-10-03 12:00:00",
        "tool_called": "execute_luau",
        "arguments": {},
        "result": [text],
        "is_error": is_error,
    }
    with open(OUTPUTS_FILE, "w", encoding="utf-8") as f:
        json.dump([entry], f, ensure_ascii=False)

FAKE_LIST = "\n".join([
    "ReplicatedStorage.Shared.Domain.ItemFormula",
    "ReplicatedStorage.Shared.Domain.MathUtils",
    "ServerScriptService.Services.CraftService",
])

print("=" * 40, flush=True)
print("Мост готов. Fake bridge for tests.", flush=True)
print("=" * 40, flush=True)
print(">>> ", end="", flush=True)

while True:
    line = sys.stdin.readline()
    if not line:
        break
    cmd = line.strip().lower()
    if cmd in ("exit", "quit", "q"):
        break
    if cmd.startswith("accept"):
        try:
            with open(PATCH_FILE, encoding="utf-8") as f:
                patch = json.load(f)
        except Exception as e:
            print(f"[fake] bad patch: {e}", flush=True)
            print(">>> ", end="", flush=True)
            continue
        args = patch.get("arguments", {}) or {}
        code = args.get("code", "")

        if _next_transient():
            _write_result(
                "No Roblox Studio instances are connected. Ask the user to confirm...",
                is_error=True,
            )
            print(">>> ", end="", flush=True)
            continue

        if "__studio_ready__" in code:
            _write_result("__studio_ready__")
            print(">>> ", end="", flush=True)
            continue

        store = _load_store()

        # write: matches pattern t.Source = <literal>
        if "t.Source = " in code:
            # Extract path and literal (very rough for test purposes).
            # code format: ... return game.<PATH> end ... t.Source = <LIT>
            try:
                path_start = code.index("return game.") + len("return game.")
                path_end = code.index(" end", path_start)
                path = code[path_start:path_end]
                lit_start = code.index("t.Source = ") + len("t.Source = ")
                lit_end = code.index("\n", lit_start)
                lit = code[lit_start:lit_end]
                content = json.loads(lit)
            except Exception as e:
                _write_result(f"__PARSE_FAIL__: {e}")
                print(">>> ", end="", flush=True)
                continue
            if path not in store and "Missing" in path:
                _write_result("__MISSING__")
            elif "NotAScript" in path:
                _write_result("__NOT_SOURCE__")
            else:
                store[path] = content
                _save_store(store)
                _write_result("__OK__")
        # read
        elif "return val.Source" in code:
            try:
                path_start = code.index("return game.") + len("return game.")
                path_end = code.index(" end", path_start)
                path = code[path_start:path_end]
            except Exception:
                path = ""
            if "Missing" in path or "Nope" in path:
                _write_result("__MISSING__")
            elif "NotAScript" in path:
                _write_result("__NOT_SOURCE__")
            elif path in store:
                val = store[path]
                if val == "__DELETED__":
                    _write_result("__MISSING__")
                else:
                    _write_result(val)
            else:
                _write_result(f"-- mocked source for: {path}")
        # exists (lua/scripts/exists.lua) — unique marker: return '1'
        elif "return '1'" in code:
            try:
                path_start = code.index("return game.") + len("return game.")
                path_end = code.index(" end", path_start)
                path = code[path_start:path_end]
            except Exception:
                path = ""
            if "Missing" in path or "Nope" in path or "NotAScript" in path:
                _write_result("0")
            elif path in store and store[path] == "__DELETED__":
                _write_result("0")
            else:
                _write_result("1")
        # list
        elif "GetDescendants" in code and "LuaSourceContainer" in code:
            _write_result(FAKE_LIST)
        # stat
        elif "return #src" in code:
            _write_result("1234|42|1")
        # delete
        elif ":Destroy()" in code and "Clone" not in code:
            try:
                path_start = code.index("return game.") + len("return game.")
                path_end = code.index(" end", path_start)
                path = code[path_start:path_end]
            except Exception:
                path = ""
            if path in store and store[path] != "__DELETED__":
                store[path] = "__DELETED__"
                _save_store(store)
                _write_result("__OK__")
            else:
                _write_result("__MISSING__")
        # move
        elif "s:Clone()" in code and "s:Destroy()" in code:
            try:
                s_start = code.index("return game.") + len("return game.")
                s_end = code.index(" end", s_start)
                src_path = code[s_start:s_end]
                # second "return game." for dst parent
                second = code.index("return game.", s_end)
                p_start = second + len("return game.")
                p_end = code.index(" end", p_start)
                dst_parent = code[p_start:p_end]
                # third for dst existence
                third = code.index("return game.", p_end)
                d_start = third + len("return game.")
                d_end = code.index(" end", d_start)
                dst_path = code[d_start:d_end]
            except Exception:
                _write_result("__PARSE_FAIL__")
                print(">>> ", end="", flush=True)
                continue
            if src_path not in store or store[src_path] == "__DELETED__":
                _write_result("__SRC_MISSING__")
            elif dst_parent not in store and "ReplicatedStorage" not in dst_parent \
                    and "ServerScriptService" not in dst_parent and "ServerStorage" not in dst_parent:
                _write_result("__DST_PARENT_MISSING__")
            elif dst_path in store and store[dst_path] != "__DELETED__":
                _write_result("__DST_EXISTS__")
            else:
                store[dst_path] = store[src_path]
                store[src_path] = "__DELETED__"
                _save_store(store)
                _write_result("__OK__")
        else:
            _write_result(f"mock-result: {code[:60]}")
        print(">>> ", end="", flush=True)
'''


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        fake = root / "fake_bridge.py"
        fake.write_text(FAKE_BRIDGE, encoding="utf-8")
        (root / "transient_count.txt").write_text("0", encoding="utf-8")

        backend = MCPBackend(
            bridge_script=str(fake),
            command=f"{sys.executable} -u",
            working_dir=str(root),
            ready_timeout=15.0,
            call_timeout=15.0,
            studio_timeout=5.0,
            max_retries=6,
            retry_delay=0.05,
        )

        try:
            _run_all(backend, root, t)
        finally:
            try:
                backend.close()
            except Exception:
                pass

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


def _run_all(backend, root, t):
    print("== lifecycle ==")
    t.expect("before open: not alive", not backend.is_alive())
    backend.open()
    t.expect("after open: alive", backend.is_alive())

    print()
    print("== read ==")
    src = backend.read("ReplicatedStorage.Foo.Bar")
    t.expect("read returned text", "source" in src.lower(), src[:80])

    try:
        backend.read("ReplicatedStorage.Missing.Thing")
        t.expect("missing raises", False)
    except FileNotFoundError:
        t.expect("missing raises FileNotFoundError", True)

    print()
    print("== exists ==")
    t.expect("existing -> True", backend.exists("ReplicatedStorage.Foo.Bar"))
    t.expect("missing -> False", not backend.exists("ReplicatedStorage.Missing"))

    print()
    print("== stat ==")
    st = backend.stat("ReplicatedStorage.Foo.Bar")
    t.expect("stat size == 1234", st.size_bytes == 1234, str(st))
    t.expect("stat lines == 42", st.lines == 42, str(st))

    print()
    print("== list ==")
    lst = backend.list("ReplicatedStorage")
    t.expect("list returned 3 items", len(lst) == 3, str(lst))

    print()
    print("== write ==")
    new_content = "-- new source\nlocal x = 42\nprint(x)\n"
    backend.write("ReplicatedStorage.Foo.Bar", new_content)
    after = backend.read("ReplicatedStorage.Foo.Bar")
    t.expect("write+read round-trips", after == new_content,
             f"got: {after[:80]!r}")

    try:
        backend.write("ReplicatedStorage.Missing.Thing", "x")
        t.expect("write missing raises", False)
    except FileNotFoundError:
        t.expect("write missing raises FileNotFoundError", True)

    try:
        backend.write("ReplicatedStorage.NotAScript", "x")
        t.expect("write not-source raises", False)
    except ValueError:
        t.expect("write not-source raises ValueError", True)

    print()
    print("== write: control-char guard ==")
    try:
        backend.write("ReplicatedStorage.Foo.Bar", "bad\x00byte")
        t.expect("control char rejected", False)
    except ValueError:
        t.expect("control char rejected", True)

    print()
    print("== delete ==")
    backend.delete("ReplicatedStorage.Foo.Baz")
    t.expect("deleted -> exists False",
             not backend.exists("ReplicatedStorage.Foo.Baz"))
    try:
        backend.delete("ReplicatedStorage.Foo.Baz")
        t.expect("delete twice raises", False)
    except FileNotFoundError:
        t.expect("delete twice raises FileNotFoundError", True)

    print()
    print("== move ==")
    backend.move("ReplicatedStorage.Foo.Bar", "ServerScriptService.MovedBar")
    t.expect("src gone after move",
             not backend.exists("ReplicatedStorage.Foo.Bar"))
    t.expect("dst exists after move",
             backend.exists("ServerScriptService.MovedBar"))

    try:
        backend.move("ReplicatedStorage.Nope", "ServerScriptService.X")
        t.expect("move missing src raises", False)
    except FileNotFoundError:
        t.expect("move missing src raises FileNotFoundError", True)

    try:
        backend.move("ServerScriptService.MovedBar", "ServerScriptService.MovedBar")
        t.expect("move to existing raises", False)
    except FileExistsError:
        t.expect("move to existing raises FileExistsError", True)

    print()
    print("== filter_check (no-op for Roblox) ==")
    # Roblox DataModel paths are not filtered by policy: access is gated
    # at the backend level (native_tools_enabled). filter_check always
    # returns None regardless of the op.
    t.expect("filter_check -> None (ReplicatedStorage)",
             backend.filter_check("ReplicatedStorage.Foo", "read") is None)
    t.expect("filter_check -> None (ServerScriptService)",
             backend.filter_check("ServerScriptService.Bar", "write") is None)

    print()
    print("== retry: transient ==")
    (root / "transient_count.txt").write_text("3", encoding="utf-8")
    # Foo.Bar was moved to ServerScriptService.MovedBar above — read that path.
    src3 = backend.read("ServerScriptService.MovedBar")
    t.expect("read survives 3 transient", "source" in src3.lower(), src3[:80])


if __name__ == "__main__":
    sys.exit(main())
