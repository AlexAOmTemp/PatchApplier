"""Main presenter: pure logic extracted from gui/app.py.

Steps 3c.1 (stateless helpers) and 3c.2 (state updaters) done.
Later sub-steps add event handlers, session lifecycle, menu wiring.

No imports from gui/ -- callers pass `config` explicitly. This keeps
the presenter independent of where CONFIG lives (app.py local vs a
future state module).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..gui.formatting import normalize_patch


# -- 3c.1 stateless helpers ----------------------------------------------


def format_project_label(config: dict) -> tuple[str, str]:
    """Return (text, hex_color) for the top project label."""
    proj = config.get("project_dir", "").strip()
    if not proj:
        return "\u26a0 \u0443\u043a\u0430\u0436\u0438\u0442\u0435 \u043f\u0443\u0442\u044c \u043a \u043f\u0440\u043e\u0435\u043a\u0442\u0443", "#c07000"
    if not Path(proj).is_dir():
        return f"\u26a0 \u043f\u0430\u043f\u043a\u0430 \u043d\u0435 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u0435\u0442: {proj}", "#c07000"
    backend = config.get("backend", "composite")
    return f"\U0001F4C1 {proj}  [{backend}]", "#308030"


def status_visual(name: str, state: str) -> tuple[str, str]:
    """Return (text, hex_color) for one backend indicator."""
    if state == "ready":
        return f"{name} \u25cf", "#306030"
    if state == "starting":
        return f"{name} \u23f3", "#8b6914"
    if state.startswith("failed"):
        return f"{name} \u2717", "#a02020"
    return f"{name} \u2014", "#808080"


def backend_states(session, backend_name: str) -> dict:
    """Read per-backend readiness from a session's backend."""
    getter = getattr(session.backend, "backend_state_all", None)
    if callable(getter):
        return getter()
    key = "mcp" if backend_name == "mcp" else "fs"
    try:
        alive = session.backend.is_alive()
    except Exception:
        alive = False
    return {key: "ready" if alive else "failed: not alive"}


# -- 3c.2 state updaters -------------------------------------------------


def project_state(config: dict) -> tuple[str, str, str, list]:
    """(project_dir, index_output, filter_mode, filter_dirs) from config."""
    return (
        config.get("project_dir", "").strip(),
        config.get("index_output", "").strip(),
        config.get("filter_mode", "none"),
        config.get("filter_dirs", []) or [],
    )


def project_ok(config: dict) -> bool:
    """True iff project_dir is set and points at a real directory."""
    proj, _, _, _ = project_state(config)
    return bool(proj) and Path(proj).is_dir()


@dataclass
class ButtonDecision:
    """Computed visual state for btn / repeat_btn / status_var."""

    btn_state: str
    btn_text: str
    repeat_state: str
    status_state: str


def decide_button_state(
    *,
    project_ok: bool,
    last_patch_exists: bool,
    current_raw: str,
    last_applied_norm: str | None,
    last_output_text: str | None,
    hotkey: str,
) -> ButtonDecision:
    """Decide button/status state from inputs. No Tk, no clipboard."""
    if not project_ok:
        return ButtonDecision(
            btn_state="disabled",
            btn_text=f"\u0412\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u044c ({hotkey})",
            repeat_state="disabled",
            status_state="",
        )
    repeat_state = "normal" if last_patch_exists else "disabled"
    current_norm = normalize_patch(current_raw) if current_raw else ""
    is_dup = bool(
        last_applied_norm is not None
        and current_norm
        and current_norm == last_applied_norm
    )
    stripped = current_raw.strip()
    is_response_echo = bool(
        last_output_text is not None
        and stripped
        and stripped == last_output_text.strip()
    )
    if is_dup:
        return ButtonDecision(
            btn_state="disabled",
            btn_text="\u2713 \u0423\u0436\u0435 \u043f\u0440\u0438\u043c\u0435\u043d\u0451\u043d",
            repeat_state=repeat_state,
            status_state=(
                "\u26a0 \u042d\u0442\u043e\u0442 \u043f\u0430\u0442\u0447 \u0443\u0436\u0435 "
                "\u043f\u0440\u0438\u043c\u0435\u043d\u0451\u043d. \u0414\u043b\u044f \u043f\u043e\u0432\u0442\u043e\u0440\u0430 "
                "\u043d\u0430\u0436\u043c\u0438 \u00ab\u21bb \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c "
                "\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439\u00bb."
            ),
        )
    if is_response_echo:
        return ButtonDecision(
            btn_state="disabled",
            btn_text="\u23f8 \u0421\u043a\u043e\u043f\u0438\u0440\u0443\u0439 \u043d\u043e\u0432\u044b\u0439 \u043f\u0430\u0442\u0447",
            repeat_state=repeat_state,
            status_state="",
        )
    return ButtonDecision(
        btn_state="normal",
        btn_text=f"\u0412\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u044c ({hotkey})",
        repeat_state=repeat_state,
        status_state="",
    )


# -- 3c.3 starter text --------------------------------------------------


class StarterTextError(Exception):
    """Raised when the LLM_START text cannot be located."""


def build_starter_text(
    *,
    lang: str,
    session,
    include_roblox: bool,
    docs_dir: Path,
    runtime_state_dir: Path,
    read_text_fn,
) -> tuple[str, str, str]:
    """Assemble the LLM starter message: base text + optional extras + status.

    Returns (full_text, used_lang, suffix). The suffix is "+roblox" when
    extras were appended, "" otherwise.

    Raises StarterTextError when the base text is missing.
    """
    text, used = read_text_fn(lang)
    if text is None:
        raise StarterTextError(
            f"\u2717 \u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d LLM_START.*.md \u0432 {docs_dir}"
        )

    status_block = _build_status_block(session)
    extras = _build_extras(include_roblox, docs_dir, runtime_state_dir)
    extras_block = ("\n\n" + "\n\n".join(extras)) if extras else ""
    suffix = "+roblox" if include_roblox else ""
    return text + extras_block + status_block, used, suffix


def _build_status_block(session) -> str:
    if session is None:
        return "\n\n---\n\n(status unavailable: session not ready)"
    try:
        from ...tools.status import GetStatusTool
        r = GetStatusTool().execute(backend=session.backend, fmt=session.fmt)
        if r.status == "ok":
            return "\n\n---\n\n" + r.message
        return f"\n\n---\n\n(status error: {r.message})"
    except Exception as e:
        return f"\n\n---\n\n(status unavailable: {e})"


def _build_extras(include_roblox: bool, docs_dir: Path, runtime_state_dir: Path) -> list[str]:
    if not include_roblox:
        return []
    extras: list[str] = []
    for name in ("RobloxCodeRules.md", "MCPBridgeRules.md"):
        p = docs_dir / name
        if p.is_file():
            try:
                extras.append(
                    "---\n\n# \u0414\u043e\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u0435: " + name + "\n\n"
                    + p.read_text(encoding="utf-8")
                )
            except Exception as e:
                extras.append(f"---\n\n({name}: cannot read: {e})")
        else:
            extras.append(f"---\n\n({name} not found at {p})")
    schema_path = runtime_state_dir / "tools_schema.json"
    if schema_path.is_file():
        try:
            extras.append(
                "---\n\n# \u0421\u0445\u0435\u043c\u0430 \u043d\u0430\u0442\u0438\u0432\u043d\u044b\u0445 \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u043e\u0432 (tools_schema.json)\n\n"
                + schema_path.read_text(encoding="utf-8")
            )
        except Exception as e:
            extras.append(f"---\n\n(tools_schema.json: cannot read: {e})")
    return extras


# -- 3c.4 session lifecycle ----------------------------------------------


class BackendError(Exception):
    """Backend could not be constructed (missing workspace, no bridge, ...)."""


def load_workspace_or_none(project_dir, config: dict):
    """Load workspace.json from project_dir; None if missing/unreadable."""
    from ...config import loader as _l
    from ...config.workspace import load as _ws_load
    state_dir = Path(project_dir) / _l.resolve_state_dir(config)
    try:
        return _ws_load(state_dir)
    except Exception:
        return None


def build_backend_for_config(config: dict):
    """Construct a backend from config. Mirrors the original in app.py.

    Returns (backend, name) on success. Raises BackendError with a short
    human message on failure -- caller renders it.
    """
    from ...backends import FilesystemBackend, MCPBackend, CompositeBackend  # noqa: F401
    backend_name = config.get("backend", "filesystem")
    work_dir = config.get("project_dir", "").strip()
    if not work_dir or not Path(work_dir).is_dir():
        raise BackendError("project_dir not set or not a directory")

    from ...config import loader as _l

    if backend_name == "filesystem":
        ws = load_workspace_or_none(work_dir, config)
        if ws is None:
            raise BackendError("workspace.json not found in project folder")
        from ...backends.workspace import WorkspaceBackend
        state_dir = Path(work_dir) / _l.resolve_state_dir(config)
        return WorkspaceBackend(ws, state_dir), "filesystem"

    from ...config.loader import default_bridge_script
    mcp_cfg = dict(config.get("mcp") or {})
    override = mcp_cfg.get("bridge_script")
    if override:
        bridge_path = Path(override)
        if not bridge_path.is_absolute():
            bridge_path = (Path(work_dir) / override).resolve()
    else:
        bridge_path = default_bridge_script()
    if not bridge_path.is_file() and backend_name == "mcp":
        raise BackendError(f"bridge not found: {bridge_path}")

    native_cfg = mcp_cfg.get("native_tools") or {}
    mcp_backend = MCPBackend(
        bridge_script=str(bridge_path),
        command=mcp_cfg.get("command", "python -u"),
        mcp_command=mcp_cfg.get("mcp_command") or "cmd.exe",
        mcp_args=mcp_cfg.get("mcp_args")
                 or r"/c cd /d %LOCALAPPDATA%\Roblox && .\mcp.bat",
        working_dir=work_dir,
        state_subdir=_l.resolve_state_dir(config),
        preflight=mcp_cfg.get("preflight", True),
        auto_switch=mcp_cfg.get("auto_switch", True),
        ready_timeout=float(mcp_cfg.get("ready_timeout", 120.0)),
        call_timeout=float(mcp_cfg.get("call_timeout", 180.0)),
        studio_timeout=float(mcp_cfg.get("studio_timeout", 60.0)),
        max_retries=int(mcp_cfg.get("max_retries", 6)),
        retry_delay=float(mcp_cfg.get("retry_delay", 1.0)),
        native_tools_enabled=bool(native_cfg.get("enabled", True)),
        native_tools_allow=native_cfg.get("allow") or None,
        quiet_bridge=bool(mcp_cfg.get("quiet_bridge", True)),
    )

    if backend_name == "mcp":
        return mcp_backend, "mcp"
    if backend_name == "composite":
        ws = load_workspace_or_none(work_dir, config)
        if ws is None:
            raise BackendError("workspace.json not found in project folder")
        from ...backends.workspace import WorkspaceBackend
        state_dir = Path(work_dir) / _l.resolve_state_dir(config)
        return CompositeBackend([
            ("fs", WorkspaceBackend(ws, state_dir)),
            ("mcp", mcp_backend),
        ]), "composite"
    raise BackendError(f"unknown backend: {backend_name}")


def build_session(backend, name: str, config: dict):
    """Construct a Session for `backend` and register side-effect setup.

    Registers RunPythonTool config, index paths, and GetStatusTool context.
    Does NOT open the session -- caller decides (open_async, open, ...).
    """
    from ...core import Session
    from ...formats import Format
    from ...tools import TOOL_MAP
    from ...tools.shell import RunPythonTool
    from ...tools.index import install_index_paths
    from ...tools.status import GetStatusTool
    from ...config import loader as _l

    preset = config.get("format_preset", "default")
    fmt = Format.load(preset, config.get("format") or None)
    RunPythonTool.set_config(
        config.get("exec"),
        config.get("project_dir", ""),
    )
    install_index_paths(config)

    mcp_cfg = config.get("mcp") or {}
    native_cfg = mcp_cfg.get("native_tools") or {}
    if name == "composite":
        backs = {"filesystem", "mcp"}
    elif name == "mcp":
        backs = {"mcp"}
    else:
        backs = {"filesystem"}

    paths = _l.resolve_index_paths(config)
    roots: list[str] = []
    ws = _l.load_workspace(config)
    if ws is not None:
        try:
            roots = list(ws.root_names())
        except Exception:
            roots = []

    GetStatusTool.set_context(
        project_name=Path(config.get("project_dir", "")).name,
        backend=name,
        luau_mode=(config.get("luau_mode") or "mcp"),
        format_preset=preset,
        exec_enabled=bool((config.get("exec") or {}).get("enabled")),
        exec_interpreter=(config.get("exec") or {}).get("interpreter"),
        native_tools_enabled=bool(native_cfg.get("enabled", True)),
        native_tools_allow=native_cfg.get("allow") or [],
        index_paths={
            "docs": paths["docs"],
            "code": paths["code"],
            "lua":  paths["lua"],
        },
        roots=roots,
        backends_enabled=backs,
    )

    return Session(backend, fmt=fmt, tools=TOOL_MAP)


def plan_init_patches(config: dict, backend_name: str) -> list[dict]:
    """Return the initial index rebuild patches (docs/py only; lua is late).

    Lua is intentionally not included: MCP may still be starting, and the
    Lua index is rebuilt once MCP transitions to ready (app.py drives
    that via _check_mcp_transition).
    """
    has_fs = backend_name in ("filesystem", "composite")
    if not has_fs:
        return []
    want_docs = bool(config.get("index_docs", has_fs))
    want_py = bool(config.get("index_python", has_fs))
    patches: list[dict] = []
    if want_docs:
        patches.append({"action": "rebuild_index", "arguments": {}})
    if want_py:
        patches.append({"action": "rebuild_code_index", "arguments": {}})
    return patches
