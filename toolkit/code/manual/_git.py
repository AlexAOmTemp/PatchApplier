"""Tiny git helper for refactor checkpoints.

Subcommands:
  commit <message>       git add -A && git commit -m <message>
  log [n]                show last n commits (default 5)
  status                 short status
  reset-hard [ref]       reset --hard <ref> (default HEAD)
  show-file <ref> <p>    print a file as of <ref>

Run from anywhere inside the repo; resolves root from __file__.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def _git(args, cwd):
    exe = shutil.which("git")
    if not exe:
        return -1, "", "git not found on PATH"
    p = subprocess.run([exe] + args, cwd=str(cwd),
                       capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


def _root() -> Path:
    # here = <repo>/toolkit/code/manual/_git.py
    return Path(__file__).resolve().parents[3]


def cmd_commit(args):
    msg = " ".join(args) if args else "checkpoint"
    root = _root()
    rc, out, err = _git(["add", "-A"], root)
    print(f"[add rc={rc}]")
    if out.strip(): print(out.rstrip())
    if err.strip(): print(err.rstrip())
    rc, out, err = _git(["commit", "-m", msg], root)
    print(f"[commit rc={rc}]")
    if out.strip(): print(out.rstrip())
    if err.strip(): print(err.rstrip())
    return rc


def cmd_log(args):
    n = args[0] if args else "5"
    rc, out, err = _git(["log", f"-{n}", "--oneline"], _root())
    print(out or err)
    return rc


def cmd_status(args):
    rc, out, err = _git(["status", "-sb"], _root())
    print(out or err)
    return rc


def cmd_reset_hard(args):
    ref = args[0] if args else "HEAD"
    rc, out, err = _git(["reset", "--hard", ref], _root())
    print(out or err)
    return rc


def cmd_show_file(args):
    if len(args) < 2:
        print("usage: show-file <ref> <path>")
        return 2
    ref, path = args[0], args[1]
    rc, out, err = _git(["show", f"{ref}:{path}"], _root())
    print(out or err)
    return rc


_DISPATCH = {
    "commit": cmd_commit,
    "log": cmd_log,
    "status": cmd_status,
    "reset-hard": cmd_reset_hard,
    "show-file": cmd_show_file,
}


def main():
    args = sys.argv[1:]
    if not args:
        print("usage: _git.py <subcommand> [args]")
        print("subcommands:", ", ".join(sorted(_DISPATCH)))
        return 2
    fn = _DISPATCH.get(args[0])
    if fn is None:
        print(f"unknown subcommand: {args[0]}")
        return 2
    return fn(args[1:])


if __name__ == "__main__":
    sys.exit(main())
