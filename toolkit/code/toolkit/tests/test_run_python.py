"""Tests for run_python tool (exec.enabled gate, sandbox, encoding, env)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import RootDirBackend
from toolkit.core import Session
from toolkit.formats import Format
from toolkit.tools import TOOL_MAP
from toolkit.tools.shell import RunPythonTool


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
    backend = RootDirBackend(root)
    fmt = Format.load("default")
    with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:
        return s.apply_patches(patches)


def _write(root: Path, name: str, content: str) -> Path:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _cfg(root: Path, **overrides) -> None:
    """Set RunPythonTool config with sane defaults + per-test overrides."""
    base = {
        "enabled": True,
        "interpreter": None,
        "allow_module_mode": True,
        "child_encoding": "utf-8",
        "default_timeout": 30,
        "max_timeout": 60,
        "max_output_bytes": 200_000,
        "env_passthrough": ["PATH", "SYSTEMROOT", "PYTHONIOENCODING", "PYTHONUTF8"],
        "env_deny_patterns": ["*_TOKEN", "*_KEY", "*_SECRET"],
    }
    base.update(overrides)
    RunPythonTool.set_config(base, root)


def main():
    t = T()

    # Snapshot RunPythonTool's class-level state so we restore whatever was
    # there before this test ran. In the common case (run_all.py -> fresh
    # subprocess) this is `{}` / `None`. But if a long-lived host (GUI) ever
    # invokes this test inline, the snapshot preserves its real config.
    _orig_cfg = dict(RunPythonTool._config)
    _orig_root = RunPythonTool._project_root

    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()

        # --- 1. gate: enabled=false ---
        print("== gate: enabled=false ==")
        RunPythonTool.set_config({"enabled": False}, root)
        _write(root, "hello.py", "print('hi')\n")
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "hello.py"}},
        ])[0]
        t.expect("blocked", r.status == "blocked", f"{r.status}: {r.message}")
        t.expect("error_code == exec_disabled", r.error_code == "exec_disabled")
        t.expect("not executed (no stdout in msg)", "hi" not in r.message)

        # --- 2. script outside project ---
        print()
        print("== script outside project ==")
        _cfg(root)
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "../outside.py"}},
        ])[0]
        t.expect("blocked", r.status == "blocked", f"{r.status}: {r.message}")
        t.expect("error_code == script_outside_project",
                 r.error_code == "script_outside_project")

        # --- 3. script not .py ---
        print()
        print("== script not .py ==")
        _cfg(root)
        _write(root, "notes.txt", "x")
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "notes.txt"}},
        ])[0]
        t.expect("error", r.status == "error", f"{r.status}: {r.message}")
        t.expect("error_code == script_not_python",
                 r.error_code == "script_not_python")

        # --- 4. script not found ---
        print()
        print("== script not found ==")
        _cfg(root)
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "missing.py"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == script_not_found",
                 r.error_code == "script_not_found")

        # --- 5. module disabled ---
        print()
        print("== module disabled ==")
        _cfg(root, allow_module_mode=False)
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"module": "platform"}},
        ])[0]
        t.expect("blocked", r.status == "blocked", f"{r.status}: {r.message}")
        t.expect("error_code == module_mode_disabled",
                 r.error_code == "module_mode_disabled")

        # --- 6. ambiguous: neither ---
        print()
        print("== ambiguous: neither script nor module ==")
        _cfg(root)
        r = _run(root, [
            {"action": "run_python",
             "arguments": {}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == ambiguous_input", r.error_code == "ambiguous_input")

        # --- 7. ambiguous: both ---
        print()
        print("== ambiguous: both script and module ==")
        _cfg(root)
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "hello.py", "module": "platform"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == ambiguous_input", r.error_code == "ambiguous_input")

        # --- 8. cwd outside project ---
        print()
        print("== cwd outside project ==")
        _cfg(root)
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "hello.py", "cwd": ".."}},
        ])[0]
        t.expect("blocked", r.status == "blocked", f"{r.status}: {r.message}")
        t.expect("error_code == cwd_outside_project",
                 r.error_code == "cwd_outside_project")

        # --- 9. timeout too large ---
        print()
        print("== timeout too large ==")
        _cfg(root, max_timeout=5)
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "hello.py", "timeout": 30}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == timeout_too_large",
                 r.error_code == "timeout_too_large")

        # --- 10. normal run: non-ASCII in stdout ---
        print()
        print("== normal run: cyrillic + warning glyph ==")
        _cfg(root)
        _write(root, "nonascii.py",
               "print('привет ⚠ → всё ок')\n")
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "nonascii.py"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("exit=0 in message", "exit=0" in r.message)
        t.expect("cyrillic preserved", "привет" in r.message)
        t.expect("warning glyph preserved", "⚠" in r.message)
        t.expect("arrow preserved", "→" in r.message)

        # --- 11. non-zero exit ---
        print()
        print("== non-zero exit ==")
        _cfg(root)
        _write(root, "fail.py", "import sys; sys.exit(3)\n")
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "fail.py"}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == nonzero_exit", r.error_code == "nonzero_exit")
        t.expect("exit=3 in message", "exit=3" in r.message)

        # --- 12. timeout kill ---
        print()
        print("== timeout kill ==")
        _cfg(root, max_timeout=10)
        _write(root, "slow.py", "import time; time.sleep(20)\n")
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "slow.py", "timeout": 1}},
        ])[0]
        t.expect("error", r.status == "error")
        t.expect("error_code == timeout", r.error_code == "timeout")
        t.expect("TIMED_OUT flag in message", "TIMED_OUT" in r.message)

        # --- 13. truncation ---
        print()
        print("== truncation ==")
        _cfg(root, max_output_bytes=100)
        _write(root, "loud.py", "print('x' * 5000)\n")
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "loud.py"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("stdout_truncated flag", "stdout_truncated" in r.message)

        # --- 14. env deny pattern ---
        print()
        print("== env deny: MY_TOKEN filtered out ==")
        _cfg(root)
        _write(root, "envcheck.py",
               "import os; print(os.environ.get('MY_TOKEN', '<unset>'))\n")
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "envcheck.py",
                           "env": {"MY_TOKEN": "should-not-leak"}}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("token filtered", "<unset>" in r.message)
        t.expect("token value absent", "should-not-leak" not in r.message)

        # --- 15. env passthrough: PYTHONIOENCODING set ---
        print()
        print("== env passthrough: PYTHONIOENCODING ==")
        _cfg(root)
        _write(root, "envenc.py",
               "import os; print(os.environ.get('PYTHONIOENCODING', '<unset>'))\n")
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "envenc.py"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("PYTHONIOENCODING=utf-8 in child", "utf-8" in r.message)

        # --- 16. args inert (no shell interpretation) ---
        print()
        print("== args inert: shell metachars passed as-is ==")
        _cfg(root)
        _write(root, "argdump.py",
               "import sys; print('ARG=' + sys.argv[1])\n")
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "argdump.py",
                           "args": ["; rm -rf / && echo pwned"]}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("metachars preserved verbatim",
                 "ARG=; rm -rf / && echo pwned" in r.message)
        t.expect("no shell expansion", "pwned" not in r.message.replace("echo pwned", ""))

        # --- 17. child_encoding override ---
        print()
        print("== child_encoding override: cp1251 round-trip ==")
        _cfg(root, child_encoding="cp1251")
        _write(root, "cp.py", "print('привет')\n")
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "cp.py"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("cp1251 round-trip reads back", "привет" in r.message)

        # --- 18. child_encoding override: PYTHONUTF8 off ---
        print()
        print("== child_encoding override: PYTHONUTF8 disabled ==")
        _cfg(root, child_encoding="cp1251")
        _write(root, "utf8flag.py",
               "import os; print(os.environ.get('PYTHONUTF8', '<unset>'))\n")
        r = _run(root, [
            {"action": "run_python",
             "arguments": {"script": "utf8flag.py"}},
        ])[0]
        t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
        t.expect("PYTHONUTF8=0 for non-utf8 encoding", "=0" in r.message or "<unset>" in r.message)

    # --- restore class state (see snapshot at top of main) ---
    RunPythonTool.set_config(_orig_cfg, _orig_root)

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
