"""Smoke test for toolkit.runner.cli — runs subprocess, checks stdout format."""
from __future__ import annotations

import json
import os
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


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    # Hermetic by default: don't inherit an ambient toolkit/.patch_applier.json.
    # Tests that need a real config pass --config explicitly.
    args = list(args)
    if "--config" not in args and "-c" not in args:
        args += ["--config", "__nonexistent_config__.json"]
    cmd = [sys.executable, "-m", "toolkit.runner.cli"] + args
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _extract_marker(stdout: str) -> dict | None:
    for line in stdout.splitlines():
        if line.startswith("##RESULT:"):
            try:
                return json.loads(line[len("##RESULT:"):])
            except Exception:
                return None
    return None


def _patch_text(*actions) -> str:
    """Serialize actions as one-group-per-line (current patch format:
    each action in its own [...] group, separated by newlines). Every
    action must carry an `id`; groups without one are dropped by the
    parser and reported as a missing_id diagnostic."""
    return "\n".join(json.dumps([a], ensure_ascii=False) for a in actions)


def main():
    t = T()

    # ---- list-tools ----
    print("== --list-tools ==")
    r = _run_cli(["--list-tools"])
    t.expect("exit 0", r.returncode == 0, f"rc={r.returncode}")
    t.expect("lists replace_section", "replace_section" in r.stdout)
    t.expect("lists read_file", "read_file" in r.stdout)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.md").write_text(
            "# A\n\n## 1. One\n<!-- summary: s -->\n\nBody A\n",
            encoding="utf-8",
        )
        (root / "b.md").write_text(
            "# B\n\n## 1. Bee\n<!-- summary: sb -->\n\nBody B\n",
            encoding="utf-8",
        )

        # ---- basic patch run ----
        print()
        print("== basic patch run ==")
        patch = root / "patch.json"
        patch.write_text(_patch_text(
            {"id": 1, "action": "file_exists", "arguments": {"file_path": "a.md"}},
            {"id": 2, "action": "read_file",   "arguments": {"file_path": "a.md"}},
            {"id": 3, "action": "read_file",   "arguments": {"file_path": "missing.md"}},
            {"id": 4, "action": "nope",        "arguments": {}},
        ), encoding="utf-8")

        r = _run_cli([str(patch), "--working-dir", str(root)])
        marker = _extract_marker(r.stdout)
        t.expect("marker present", marker is not None, r.stdout[:300])
        if marker:
            t.expect("ok == 2", marker["ok"] == 2, f"got {marker}")
            t.expect("errors == 1", marker["errors"] == 1, f"got {marker}")
            t.expect("skipped == 1", marker["skipped"] == 1, f"got {marker}")
            t.expect("failed == [3]", marker["failed"] == [3], f"got {marker}")
        t.expect("exit code 1 (errors)", r.returncode == 1, f"rc={r.returncode}")

        # ---- rebuild-only ----
        print()
        print("== --rebuild-only ==")
        r = _run_cli(["--rebuild-only", "--working-dir", str(root)])
        t.expect("exit 0", r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}")
        t.expect("INDEX.md created", (root / ".patch_applier" / "INDEX.md").is_file())
        if (root / ".patch_applier" / "INDEX.md").is_file():
            ix = (root / ".patch_applier" / "INDEX.md").read_text(encoding="utf-8")
            t.expect("INDEX mentions a.md", "a.md" in ix)
            t.expect("INDEX mentions b.md", "b.md" in ix)

        # ---- patch + rebuild-index ----
        print()
        print("== patch + --rebuild-index ==")
        patch2 = root / "patch2.json"
        patch2.write_text(_patch_text(
            {"id": 1, "action": "set_summary", "arguments": {
                "file_path": "a.md", "section_number": "1",
                "summary": "updated summary"}},
        ), encoding="utf-8")
        r = _run_cli([str(patch2), "--working-dir", str(root), "--rebuild-index"])
        t.expect("exit 0", r.returncode == 0, f"rc={r.returncode}\n{r.stdout}")
        ix = (root / ".patch_applier" / "INDEX.md").read_text(encoding="utf-8")
        t.expect("INDEX has updated summary", "updated summary" in ix, ix[:400])

        # ---- legacy --filter-mode/--filter-dirs ----
        print()
        print("== --filter-mode white --filter-dirs docs ==")
        (root / "docs").mkdir()
        (root / "docs" / "c.md").write_text(
            "# C\n\n## 1. See\n<!-- summary: s -->\n\nBody C\n", encoding="utf-8")
        patch3 = root / "patch3.json"
        patch3.write_text(_patch_text(
            {"id": 1, "action": "file_exists", "arguments": {"file_path": "docs/c.md"}},
            {"id": 2, "action": "file_exists", "arguments": {"file_path": "a.md"}},
        ), encoding="utf-8")
        r = _run_cli([str(patch3), "--working-dir", str(root),
                      "--filter-mode", "white", "--filter-dirs", "docs"])
        marker = _extract_marker(r.stdout)
        t.expect("marker present", marker is not None)
        if marker:
            t.expect("ok == 1", marker["ok"] == 1, f"got {marker}")
            t.expect("blocked == [2]", marker["blocked"] == [2], f"got {marker}")

        # ---- config file with project_dir ----
        print()
        print("== config with project_dir ==")
        cfg_file = root / "cfg.json"
        cfg_file.write_text(json.dumps({
            "project_dir": str(root),
            "filter": {
                "read": {"mode": "none"},
                "write": {"mode": "none"},
                "index": {"mode": "black", "paths": ["docs"]},
            },
        }, ensure_ascii=False), encoding="utf-8")
        r = _run_cli(["--config", str(cfg_file), "--rebuild-only"])
        t.expect("exit 0", r.returncode == 0, f"rc={r.returncode}\n{r.stdout}")
        ix = (root / ".patch_applier" / "INDEX.md").read_text(encoding="utf-8")
        t.expect("INDEX excludes docs/c.md", "docs/c.md" not in ix, ix[:400])
        t.expect("INDEX still has a.md", "a.md" in ix)

        # ---- missing working_dir ----
        print()
        print("== no working_dir -> exit 2 ==")
        r = _run_cli([str(patch)])
        t.expect("exit 2", r.returncode == 2, f"rc={r.returncode}")
        t.expect("stderr mentions working_dir", "working_dir" in r.stderr)

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
