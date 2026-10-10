"""Restart the Patch Applier GUI.

Called via `run_python` from inside the GUI process. The main invocation
just spawns a *detached* helper (this same script with --do-restart) and
exits; the helper waits for the parent run_python call to finish cleanly,
then kills the running GUI by PID and launches a fresh one.

Why detached: run_python runs as a child of the GUI process. If we kill
the GUI from within the run_python subprocess, the subprocess dies with
its parent and the restart never completes. The detached helper is
reparented to the OS init, so it outlives both.

PID source: `run_gui.py` writes `os.getpid()` to a temp file at startup;
the helper reads it back. This avoids matching on window title, which is
fragile and depends on the exact string in the title bar.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUN_GUI = HERE / "run_gui.py"
PID_FILE = Path(tempfile.gettempdir()) / "patch_applier_gui.pid"

# Windows process creation flags: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP.
_DETACHED_WIN = 0x00000008 | 0x00000200


def _spawn_detached(argv: list[str]) -> None:
    if os.name == "nt":
        # DETACHED_PROCESS alone: no console inherited, no window. Do NOT
        # add CREATE_NO_WINDOW — MSDN says it is *ignored* when
        # DETACHED_PROCESS is present. Hide any residual window via
        # STARTUPINFO/SW_HIDE, which is the documented combination.
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        subprocess.Popen(
            argv,
            creationflags=0x00000008,  # DETACHED_PROCESS
            startupinfo=si,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(
            argv,
            start_new_session=True,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _pythonw() -> str:
    """Prefer pythonw.exe on Windows: it never opens a console window.

    Falls back to sys.executable (with CREATE_NO_WINDOW at spawn time)
    when pythonw is not next to the current interpreter.
    """
    if os.name != "nt":
        return sys.executable
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate) if candidate.exists() else sys.executable


def _read_pid() -> int | None:
    try:
        raw = PID_FILE.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except Exception:
        return None


def _kill(pid: int) -> None:
    if os.name == "nt":
        # /F for force, no /T: killing the whole tree would also reach this
        # helper process, which is a descendant of the GUI via run_python.
        # The MCP bridge subprocess dies on its own when the GUI's pipes
        # close (EOF on stdin), so orphan cleanup is not needed here.
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
        )
    else:
        try:
            os.kill(pid, 15)  # SIGTERM
        except ProcessLookupError:
            pass
        except Exception:
            pass


def _do_restart() -> None:
    # Let the parent run_python call return cleanly before we kill the
    # GUI: its stdout/stderr pipes are still open for a moment.
    time.sleep(2.0)
    pid = _read_pid()
    if pid is not None:
        _kill(pid)
    time.sleep(0.5)
    _spawn_detached([_pythonw(), str(RUN_GUI)])


def main() -> int:
    if "--do-restart" in sys.argv:
        _do_restart()
        return 0
    # Main entry: invoked via run_python. Print a short diagnostic so the
    # tool result shows what will actually run, then spawn the detached
    # helper and exit.
    pw = _pythonw()
    pid = _read_pid()
    print(f"sys.executable = {sys.executable}")
    print(f"pythonw path   = {pw}")
    print(f"pythonw exists = {Path(pw).exists()}")
    print(f"PID file       = {PID_FILE}")
    print(f"PID read       = {pid}")
    _spawn_detached([pw, str(Path(__file__).resolve()),
                     "--do-restart"])
    print("GUI restart scheduled. Current GUI will be killed in ~2s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
