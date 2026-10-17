"""Tests for toolkit.tools.symbols.lua — plain-function implementations."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import RootDirBackend
from toolkit.tools.symbols import lua as _lua


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


SEED = '''\
-- Sample Lua module
local M = {}

function M.hello(name)
    return "hello " .. name
end

function M:method(x)
    return self.value + x
end

local function helper(a, b)
    return a + b
end

function duplicate(a)
    return a * 2
end

function duplicate(b)
    return b * 3
end

return M
'''


SEED_MULTILINE_SIG = '''\
function multiline(
    a,
    b,
    c
)
    return a + b + c
end
'''


def _run(root, fn, *args, **kwargs):
    backend = RootDirBackend(root)
    return fn(backend, *args, **kwargs)


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / "sample.lua"

        # --- list ---
        print("== lua_list_symbols ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, _lua.lua_list_symbols, "sample.lua")
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("has M.hello", "M.hello" in r.message)
        t.expect("has M:method", "M:method" in r.message)
        t.expect("has helper", "helper" in r.message)
        t.expect("has duplicate twice", r.message.count("duplicate") >= 2)

        # --- read ---
        print()
        print("== lua_read_symbol ==")
        r = _run(root, _lua.lua_read_symbol, "sample.lua", "M.hello")
        t.expect("ok", r.status == "ok")
        t.expect("has function M.hello", "function M.hello" in r.message)
        t.expect("no M:method", "M:method" not in r.message)

        # --- read with occurrence=2 ---
        print()
        print("== lua_read_symbol occurrence ==")
        r = _run(root, _lua.lua_read_symbol, "sample.lua", "duplicate")
        t.expect("ambiguous", r.status == "error")
        t.expect("error_code ambiguous_symbol",
                 r.error_code == "ambiguous_symbol")
        r = _run(root, _lua.lua_read_symbol, "sample.lua", "duplicate",
                 occurrence=2)
        t.expect("second ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("second body has * 3", "b * 3" in r.message)

        # --- replace_symbol ---
        print()
        print("== lua_replace_symbol ==")
        p.write_text(SEED, encoding="utf-8")
        new_code = ("function M.hello(name)\n"
                    "    return \"hi \" .. name\n"
                    "end")
        r = _run(root, _lua.lua_replace_symbol, "sample.lua", "M.hello",
                 new_code)
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("new body", 'return "hi "' in content)
        t.expect("old body gone", 'return "hello "' not in content)
        t.expect("M:method intact", "M:method" in content)

        # --- replace_symbol with occurrence ---
        print()
        print("== lua_replace_symbol occurrence=2 ==")
        p.write_text(SEED, encoding="utf-8")
        new_dup = "function duplicate(b)\n    return b * 100\nend"
        r = _run(root, _lua.lua_replace_symbol, "sample.lua", "duplicate",
                 new_dup, occurrence=2)
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("b * 100 present", "b * 100" in content)
        t.expect("first duplicate preserved", "a * 2" in content)

        # --- replace_symbol_signature ---
        print()
        print("== lua_replace_symbol_signature ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, _lua.lua_replace_symbol_signature, "sample.lua",
                 "M.hello", "function M.hello(name, greeting)")
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("new sig", "function M.hello(name, greeting)" in content)
        t.expect("body preserved", 'return "hello "' in content)

        # --- replace_symbol_signature: multi-line ---
        print()
        print("== lua_replace_symbol_signature multiline ==")
        p.write_text(SEED_MULTILINE_SIG, encoding="utf-8")
        r = _run(root, _lua.lua_replace_symbol_signature, "sample.lua",
                 "multiline", "function multiline(a, b)")
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("sig on one line", "function multiline(a, b)" in content)
        # The original multi-line signature had "    c\n)"; after the
        # replacement, the parameter list must be a single line.
        t.expect("multi-line param list gone",
                 "\n    c\n)" not in content, content)
        t.expect("body preserved", "return a + b + c" in content)

        # --- replace_symbol_body ---
        print()
        print("== lua_replace_symbol_body ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, _lua.lua_replace_symbol_body, "sample.lua",
                 "M:method", "return self.value * x")
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("new body", "self.value * x" in content)
        t.expect("signature preserved", "function M:method(x)" in content)

        # --- delete_symbol ---
        print()
        print("== lua_delete_symbol ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, _lua.lua_delete_symbol, "sample.lua", "helper")
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("helper gone", "helper" not in content)
        t.expect("M.hello intact", "M.hello" in content)

        # --- insert_symbol: end ---
        print()
        print("== lua_insert_symbol end ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, _lua.lua_insert_symbol, "sample.lua",
                 "function tail()\n    return 1\nend", position="end")
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        t.expect("tail added", "function tail()" in content)

        # --- insert_symbol: before anchor ---
        print()
        print("== lua_insert_symbol before ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, _lua.lua_insert_symbol, "sample.lua",
                 "function first()\n    return 0\nend",
                 position="before", anchor="M.hello")
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        i_first = content.index("function first")
        i_hello = content.index("function M.hello")
        t.expect("first before M.hello", i_first < i_hello)

        # --- insert_symbol: bad position ---
        print()
        print("== lua_insert_symbol bad position ==")
        r = _run(root, _lua.lua_insert_symbol, "sample.lua",
                 "function nope()\n    return 0\nend", position="middle")
        t.expect("error", r.status == "error")
        t.expect("error_code bad_position", r.error_code == "bad_position")

        # --- move_symbol: reorder ---
        print()
        print("== lua_move_symbol reorder ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, _lua.lua_move_symbol, "sample.lua", "M.hello",
                 position="end")
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        content = p.read_text(encoding="utf-8")
        i_hello = content.index("function M.hello")
        i_method = content.index("function M:method")
        t.expect("M.hello after M:method", i_hello > i_method)

        # --- move_symbol: cross-file ---
        print()
        print("== lua_move_symbol cross-file ==")
        p.write_text(SEED, encoding="utf-8")
        (root / "other.lua").write_text("return {}\n", encoding="utf-8")
        r = _run(root, _lua.lua_move_symbol, "sample.lua", "helper",
                 target_file="other.lua", position="end")
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        src = p.read_text(encoding="utf-8")
        tgt = (root / "other.lua").read_text(encoding="utf-8")
        t.expect("helper gone from source", "function helper" not in src)
        t.expect("helper in target", "function helper" in tgt)

        # --- move_symbol: target missing ---
        print()
        print("== lua_move_symbol target missing ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, _lua.lua_move_symbol, "sample.lua", "helper",
                 target_file="nope.lua")
        t.expect("error", r.status == "error")
        t.expect("error_code target_not_found",
                 r.error_code == "target_not_found")

        # --- read: not found ---
        print()
        print("== lua_read_symbol not found ==")
        p.write_text(SEED, encoding="utf-8")
        r = _run(root, _lua.lua_read_symbol, "sample.lua", "nope")
        t.expect("error", r.status == "error")
        t.expect("error_code not_found", r.error_code == "not_found")

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
