"""Restricted Python runner for the toolkit.

Runs `sys.executable <script> [args...]` or `sys.executable -m <module> [args...]`
with cwd inside the project. Shell is never used — arguments are passed as a
list, so `;`, `&&`, `|`, backticks are inert.

Threat model (read before enabling):

  This tool restricts the *form* of what can be executed, not its *effect*.
  A Python script inside the project is arbitrary code: it can open sockets,
  spawn processes, delete files. The tool therefore:

    * refuses to run anything except the configured interpreter;
    * refuses any script or cwd outside the project root;
    * enforces a hard timeout and caps captured output;
    * strips environment variables matching common secret patterns.

  It does NOT prevent a malicious script from escaping the project via
  absolute paths, networking, or child processes. That is out of scope for
  a subprocess wrapper; use OS-level isolation (Job Objects, AppContainer)
  if that is needed.

  `exec.enabled` defaults to False. Enable it deliberately.
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..core.backend import Backend
from ..core.models import Result


_DEFAULT_ENV_ALLOW = [
    "PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT",
    "TEMP", "TMP", "HOME", "USERPROFILE",
    "APPDATA", "LOCALAPPDATA",
    "PYTHONPATH", "PYTHONIOENCODING", "PYTHONUTF8",
    "LANG", "LC_ALL",
]

_DEFAULT_ENV_DENY = [
    "*_TOKEN", "*_KEY", "*_SECRET", "AWS_*", "GITHUB_*",
]


def _matches_any(name: str, patterns: list[str]) -> bool:
    upper = name.upper()
    for p in patterns:
        if fnmatch.fnmatchcase(upper, p.upper()):
            return True
    return False


def _clip(data: bytes, cap: int) -> tuple[bytes, bool]:
    if len(data) <= cap:
        return data, False
    return data[:cap], True


def _kill_tree(proc: subprocess.Popen) -> None:
    """Best-effort kill of a process and its descendants."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


class RunPythonTool:
    """Restricted Python subprocess runner.

    Registered under the name `run_python`. Config lives on the class and is
    set once per process via `RunPythonTool.set_config(exec_cfg, project_root)`.
    Tools in this toolkit are otherwise stateless; the class attribute is a
    pragmatic compromise to avoid threading config through Patcher/Session.
    """

    name = "run_python"
    op = "write"
    path_args: list[str] = []          # `script` is checked inside execute
    path_list_args: list[str] = []

    _config: dict = {}
    _project_root: Path | None = None

    @classmethod
    def set_config(
        cls,
        cfg: dict | None,
        project_root: str | Path | None = None,
    ) -> None:
        cls._config = dict(cfg or {})
        cls._project_root = (
            Path(project_root).resolve() if project_root else None
        )

    # --- helpers ----------------------------------------------------------

    @classmethod
    def _opt(cls, key: str, default):
        return cls._config.get(key, default)

    @classmethod
    def _resolve_inside_project(cls, rel: str) -> Path:
        if cls._project_root is None:
            raise ValueError("project root not configured")
        raw = Path(rel)
        p = (
            (cls._project_root / raw).resolve()
            if not raw.is_absolute()
            else raw.resolve()
        )
        try:
            p.relative_to(cls._project_root)
        except ValueError:
            raise ValueError(f"path escapes project: {rel}")
        return p

    @classmethod
    def _build_env(cls, extra: dict | None) -> dict[str, str]:
        allow = cls._opt("env_passthrough", _DEFAULT_ENV_ALLOW)
        deny = cls._opt("env_deny_patterns", _DEFAULT_ENV_DENY)
        out: dict[str, str] = {}
        for k in allow:
            v = os.environ.get(k)
            if v is None or _matches_any(k, deny):
                continue
            out[k] = v
        for k, v in (extra or {}).items():
            k = str(k)
            if _matches_any(k, deny):
                continue
            out[k] = str(v)
        # Force a deterministic encoding on child stdio. Under run_python
        # the child's stdout is a pipe, not a console; Python then falls
        # back to the locale encoding -- cp1251 on a Russian Windows. Any
        # non-ASCII glyph in the child's output (arrows, warning signs)
        # then crashes it with UnicodeEncodeError before its real work is
        # done, and the parent would also mis-decode the resulting bytes.
        #
        # `exec.child_encoding` defaults to "utf-8" so both ends of the
        # pipe agree. It can be overridden for legacy scripts that must
        # emit a different codec; the parent uses the same value when
        # decoding. Set last so neither env_passthrough nor caller `env`
        # can silently undo it.
        enc = cls._opt("child_encoding", "utf-8") or "utf-8"
        out["PYTHONIOENCODING"] = enc
        # PYTHONUTF8=1 only makes sense when we are actually in UTF-8.
        norm = enc.lower().replace("_", "-")
        out["PYTHONUTF8"] = "1" if norm in ("utf-8", "utf8") else "0"
        return out

    # --- execute ----------------------------------------------------------

    def execute(
        self,
        backend: Backend,
        fmt: Any,
        path: str | None = None,
        module: str | None = None,
        code: str | None = None,
        script: str | None = None,  # legacy alias for `path`
        args: list[str] | None = None,
        cwd: str | None = None,
        timeout: int | None = None,
        max_bytes: int | None = None,
        env: dict | None = None,
        **_: Any,
    ) -> Result:
        # -- 1. gate --------------------------------------------------------
        if not self._opt("enabled", False):
            return Result(
                status="blocked",
                message=(
                    "run_python disabled (exec.enabled=false). "
                    "Set exec.enabled=true in .patch_applier.json to use it."
                ),
                error_code="exec_disabled",
                action="run_python",
            )

        # -- 2. shape -------------------------------------------------------
        # `script` is a legacy alias for `path`.
        if path is None and script is not None:
            path = script
        modes = [path, module, code]
        if sum(x is not None for x in modes) != 1:
            return Result(
                status="error",
                message="Specify exactly one of `path` / `module` / `code`.",
                error_code="ambiguous_input",
                action="run_python",
            )
        if module and not self._opt("allow_module_mode", True):
            return Result(
                status="blocked",
                message="module mode disabled (exec.allow_module_mode=false).",
                error_code="module_mode_disabled",
                action="run_python",
            )

        # -- 3. interpreter -------------------------------------------------
        interp = self._opt("interpreter", None) or sys.executable
        if not interp:
            return Result(
                status="error",
                message=(
                    "no interpreter (exec.interpreter unset and "
                    "sys.executable empty)."
                ),
                error_code="no_interpreter",
                action="run_python",
            )

        # -- 4. argv --------------------------------------------------------
        argv: list[str] = [str(interp)]
        script_path: Path | None = None
        temp_code: Path | None = None
        if path is not None:
            resolver = getattr(backend, "resolve_physical", None)
            sp: Path | None = None
            if callable(resolver):
                sp = resolver(path)
            if sp is None:
                try:
                    sp = self._resolve_inside_project(path)
                except ValueError as e:
                    return Result(
                        status="blocked",
                        message=str(e),
                        error_code="script_outside_project",
                        action="run_python",
                    )
            if not sp.is_file():
                return Result(
                    status="error",
                    message=f"script not found: {path}",
                    error_code="script_not_found",
                    action="run_python",
                )
            if sp.suffix.lower() != ".py":
                return Result(
                    status="error",
                    message=f"script must be a .py file: {path}",
                    error_code="script_not_python",
                    action="run_python",
                )
            argv.append(str(sp))
            script_path = sp
        elif code is not None:
            if not isinstance(code, str) or not code.strip():
                return Result(
                    status="error",
                    message="`code` must be a non-empty string.",
                    error_code="empty_input",
                    action="run_python",
                )
            import tempfile as _tempfile
            if cwd is not None:
                base = self._resolve_inside_project(cwd)
            elif self._project_root is not None:
                base = self._project_root
            else:
                base = Path.cwd()
            try:
                fd, tmp_name = _tempfile.mkstemp(suffix=".py", dir=str(base))
            except OSError as e:
                return Result(
                    status="error",
                    message=f"cannot create temp file: {e}",
                    error_code="os_error",
                    action="run_python",
                )
            os.close(fd)
            temp_code = Path(tmp_name)
            temp_code.write_text(code, encoding="utf-8")
            argv.append(str(temp_code))
            script_path = temp_code
        else:
            argv.extend(["-m", str(module)])

        if args is not None:
            if not isinstance(args, list) or not all(
                isinstance(a, str) for a in args
            ):
                return Result(
                    status="error",
                    message="`args` must be a list of strings.",
                    error_code="bad_args",
                    action="run_python",
                )
            argv.extend(args)

        # -- 5. cwd ---------------------------------------------------------
        if cwd is None and script_path is not None:
            cwd_path = script_path.parent
        else:
            try:
                cwd_path = self._resolve_inside_project(cwd or ".")
            except ValueError as e:
                return Result(
                    status="blocked",
                    message=str(e),
                    error_code="cwd_outside_project",
                    action="run_python",
                )
        if not cwd_path.is_dir():
            return Result(
                status="error",
                message=f"cwd is not a directory: {cwd_path}",
                error_code="cwd_not_found",
                action="run_python",
            )

        # -- 6. timeout -----------------------------------------------------
        t_default = int(self._opt("default_timeout", 60))
        t_max = int(self._opt("max_timeout", 600))
        t = int(timeout) if timeout is not None else t_default
        if t <= 0:
            t = t_default
        if t > t_max:
            return Result(
                status="error",
                message=f"timeout {t}s exceeds max_timeout {t_max}s.",
                error_code="timeout_too_large",
                action="run_python",
            )

        # -- 7. output cap --------------------------------------------------
        cfg_cap = int(self._opt("max_output_bytes", 200_000))
        cap = int(max_bytes) if max_bytes else cfg_cap
        if cap <= 0:
            cap = cfg_cap
        cap = min(cap, cfg_cap)

        # -- 8. env ---------------------------------------------------------
        child_env = self._build_env(env)

        # -- 9. spawn -------------------------------------------------------
        popen_kwargs: dict = {
            "args": argv,
            "cwd": str(cwd_path),
            "env": child_env,
            "shell": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        t0 = time.monotonic()
        try:
            proc = subprocess.Popen(**popen_kwargs)
        except FileNotFoundError as e:
            return Result(
                status="error",
                message=f"cannot start interpreter: {e}",
                error_code="interpreter_not_found",
                action="run_python",
            )
        except OSError as e:
            return Result(
                status="error",
                message=f"OSError starting process: {e}",
                error_code="os_error",
                action="run_python",
            )

        timed_out = False
        try:
            out_b, err_b = proc.communicate(timeout=t)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            try:
                out_b, err_b = proc.communicate(timeout=5)
            except Exception:
                out_b, err_b = b"", b""
        duration_ms = int((time.monotonic() - t0) * 1000)
        exit_code = proc.returncode if proc.returncode is not None else -1

        # Cleanup inline-code tempfile. On Windows the file may still be
        # held briefly by AV/indexer after the child exits; retry a few
        # times with small sleeps to avoid leaking the file into the project.
        if temp_code is not None:
            import time as _t
            for _ in range(5):
                try:
                    temp_code.unlink()
                    break
                except OSError:
                    _t.sleep(0.05)

        # -- 10. truncate ---------------------------------------------------
        out_b, out_tr = _clip(out_b or b"", cap)
        err_b, err_tr = _clip(err_b or b"", cap)
        enc = self._opt("child_encoding", "utf-8") or "utf-8"
        stdout = out_b.decode(enc, errors="replace")
        stderr = err_b.decode(enc, errors="replace")

        # -- 11. result -----------------------------------------------------
        if timed_out:
            status, code = "error", "timeout"
        elif exit_code == 0:
            status, code = "ok", None
        else:
            status, code = "error", "nonzero_exit"

        flags = []
        if timed_out:
            flags.append("TIMED_OUT")
        if out_tr:
            flags.append("stdout_truncated")
        if err_tr:
            flags.append("stderr_truncated")
        flag_s = ("  " + " ".join(flags)) if flags else ""

        parts = [
            f"exit={exit_code}  duration={duration_ms}ms{flag_s}",
        ]
        if stdout:
            parts.append("--- stdout ---\n" + stdout.rstrip("\n"))
        if stderr:
            parts.append("--- stderr ---\n" + stderr.rstrip("\n"))
        message = "\n".join(parts)

        return Result(
            status=status,
            message=message,
            error_code=code,
            action="run_python",
        )


__all__ = ["RunPythonTool"]
