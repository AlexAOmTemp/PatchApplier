"""Pre-refactor git check. Read-only.

Prints the git state of the toolkit's parent repo so we know the
baseline before starting a multi-step refactor. If the working tree
is dirty, we commit or stash before touching code.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _git(args, cwd):
    exe = shutil.which("git")
    if not exe:
        return -1, "", "git not found on PATH"
    try:
        p = subprocess.run(
            [exe] + args, cwd=str(cwd),
            capture_output=True, text=True, timeout=15,
        )
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return -2, "", f"{type(e).__name__}: {e}"


def _section(label, rc, out, err):
    print(f"=== {label}  (rc={rc}) ===")
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print("[stderr]")
        print(err.rstrip())
    print()


def main():
    here = Path(__file__).resolve()
    print(f"script: {here}")
    # here = <root>/toolkit/code/manual/_git_status.py
    root = here.parents[3]
    print(f"repo root candidate: {root}")
    print(f".git exists: {(root / '.git').exists()}")
    print()

    _section("git status -sb", *_git(["status", "-sb"], root))
    _section("git log -1 --stat", *_git(["log", "-1", "--stat"], root))
    _section("git log -5 --oneline", *_git(["log", "-5", "--oneline"], root))
    _section("git diff --stat", *_git(["diff", "--stat"], root))
    _section("git diff --cached --stat", *_git(["diff", "--cached", "--stat"], root))
    _section("git stash list", *_git(["stash", "list"], root))


if __name__ == "__main__":
    main()
