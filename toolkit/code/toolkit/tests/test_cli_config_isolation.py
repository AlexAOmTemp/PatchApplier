"""Regression test: CLI must not inherit an ambient toolkit config
when --working-dir points elsewhere."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent


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


def _run(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "toolkit.runner.cli"] + args
    e = (env or {}).copy()
    e.setdefault("PYTHONIOENCODING", "utf-8")
    e.setdefault("PYTHONUTF8", "1")
    return subprocess.run(
        cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env={**__import__("os").environ, **e},
    )


def _marker(stdout: str) -> dict | None:
    for line in stdout.splitlines():
        if line.startswith("##RESULT:"):
            try:
                return json.loads(line[len("##RESULT:"):])
            except Exception:
                return None
    return None


def _patch_text(*actions) -> str:
    """Serialize actions as one-group-per-line (current format)."""
    return "\n".join(json.dumps([a], ensure_ascii=False) for a in actions)


def main():
    t = T()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "x.md").write_text(
            "# X\n\n## 1. X1\n<!-- summary: s -->\n\nbody\n",
            encoding="utf-8",
        )

        # Fabricate an "ambient" config in the temp dir with a strict filter
        # that would block everything under our working_dir.
        cfg = root / "ambient.json"
        cfg.write_text(json.dumps({
            "project_dir": str(root / "other_project"),
            "filter": {
                "read": {"mode": "white", "paths": ["nonexistent"]},
                "write": {"mode": "white", "paths": ["nonexistent"]},
                "index": {"mode": "white", "paths": ["nonexistent"]},
            },
        }, ensure_ascii=False), encoding="utf-8")

        patch = root / "patch.json"
        patch.write_text(_patch_text(
            {"id": 1, "action": "read_file", "arguments": {"path": "x.md"}},
        ), encoding="utf-8")

        # Case 1: explicit --config with foreign project_dir + --working-dir
        # to a different path. Filter from config must be ignored.
        print("== --config(foreign) + --working-dir(differs) ==")
        r = _run([str(patch), "--working-dir", str(root), "--config", str(cfg)])
        m = _marker(r.stdout)
        t.expect("marker present", m is not None, r.stdout[:300])
        if m:
            t.expect("not blocked", m["blocked"] == [], m)
            t.expect("ok == 1", m["ok"] == 1, m)

        # Case 2: --config with matching project_dir — filter applies.
        print()
        print("== --config + --working-dir matches project_dir ==")
        cfg2 = root / "matching.json"
        cfg2.write_text(json.dumps({
            "project_dir": str(root),
            "filter": {
                "read": {"mode": "white", "paths": ["nonexistent"]},
            },
        }, ensure_ascii=False), encoding="utf-8")
        r = _run([str(patch), "--working-dir", str(root), "--config", str(cfg2)])
        m = _marker(r.stdout)
        t.expect("marker present", m is not None)
        if m:
            t.expect("blocked (filter applies)", m["blocked"] == [1], m)

        # Case 3: explicit --filter-mode wins over config.
        print()
        print("== --filter-mode overrides config ==")
        r = _run([str(patch), "--working-dir", str(root),
                  "--config", str(cfg2), "--filter-mode", "none"])
        m = _marker(r.stdout)
        t.expect("marker present", m is not None)
        if m:
            t.expect("not blocked", m["blocked"] == [], m)

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
