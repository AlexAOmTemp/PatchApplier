"""Toolkit CLI — apply patches via Session/Patcher.

Usage:
    python -m toolkit.runner.cli <patch.json> --project <folder>
    python -m toolkit.runner.cli --rebuild-only --project <folder>
    python -m toolkit.runner.cli <patch.json> --rebuild-index --project <folder>

--project is a folder that contains `<folder>/.patch_applier/workspace.json`.
There is no single-root fallback in this model.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Make `import toolkit...` work when run as a script directly.
def _ensure_path() -> None:
    here = Path(__file__).resolve()
    project_root = here.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


_ensure_path()


# Force UTF-8 on stdout/stderr so `\u2713` etc. survive on Windows cp1251.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from toolkit.backends import FilesystemBackend, MCPBackend, CompositeBackend
from toolkit.config import loader as cfg_loader
from toolkit.core.patchparse import parse_patches
from toolkit.core import Session
from toolkit.formats import Format
from toolkit.tools import TOOL_MAP


# --- argparse ---------------------------------------------------------------


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="toolkit.runner.cli",
        description="Apply toolkit patches to a project.",
    )
    p.add_argument("patch_file", nargs="?",
                   help="Path to patch JSON (or use --rebuild-*-only)")
    p.add_argument("--project", "-p", default=None,
                   help="Project folder (contains .patch_applier/workspace.json)")
    p.add_argument("--config", "-c", default=None,
                   help="Path to .patch_applier.json")
    p.add_argument("--backend", default=None,
                   choices=["filesystem", "mcp", "composite", "auto"],
                   help=("Backend transport (default: from config or 'composite'). "
                         "'composite' = FS for local paths + MCP for DataModel paths. "
                         "'auto' = composite if mcp.bridge_script set in config, else FS."))
    p.add_argument("--format-preset", default=None)
    p.add_argument("--rebuild-index", action="store_true",
                   help="Append a rebuild_index action after the patch")
    p.add_argument("--rebuild-code-index", action="store_true",
                   help="Append a rebuild_code_index action after the patch")
    p.add_argument("--rebuild-lua-index", action="store_true",
                   help="Append a rebuild_lua_code_index action after the patch")
    p.add_argument("--rebuild-only", action="store_true",
                   help="Skip patch_file; only rebuild INDEX")
    p.add_argument("--rebuild-code-only", action="store_true",
                   help="Skip patch_file; only rebuild CODE_INDEX")
    p.add_argument("--rebuild-lua-only", action="store_true",
                   help="Skip patch_file; only rebuild Lua code index")
    p.add_argument("--list-tools", action="store_true",
                   help="Print registered tools and exit")
    # MCP overrides (take precedence over config mcp.* fields)
    p.add_argument("--bridge-script", default=None,
                   help="Path to bridge.py (overrides config mcp.bridge_script)")
    p.add_argument("--mcp-command", default=None,
                   help="Executable to launch MCP server (e.g. cmd.exe)")
    p.add_argument("--mcp-args", default=None,
                   help="Arguments for the MCP server")
    return p.parse_args(argv)


# --- helpers ----------------------------------------------------------------


def _resolve_project(args, cfg: dict) -> Path | None:
    if args.project:
        return Path(args.project).resolve()
    proj = (cfg.get("project_dir") or "").strip()
    if proj:
        return Path(proj).resolve()
    return None


def _load_patches(path: Path):
    text = path.read_text(encoding="utf-8")
    return parse_patches(text)


def _rebuild_patch(args, cfg: dict) -> dict:
    skip = cfg.get("skip_files") or ["INDEX.md"]
    arguments: dict = {}
    if skip:
        arguments["skip_files"] = list(skip)
    return {"action": "rebuild_index", "arguments": arguments}


def _rebuild_code_patch(args, cfg: dict) -> dict:
    skip_files = cfg.get("code_skip_files") or []
    skip_dirs = cfg.get("code_skip_dirs") or []
    arguments: dict = {}
    if skip_files:
        arguments["skip_files"] = list(skip_files)
    if skip_dirs:
        arguments["skip_dirs"] = list(skip_dirs)
    return {"action": "rebuild_code_index", "arguments": arguments}


def _rebuild_lua_patch(args, cfg: dict) -> dict:
    return {"action": "rebuild_lua_code_index", "arguments": {}}


# --- main -------------------------------------------------------------------


def _create_backend(args, cfg, project_dir: Path):
    """FS side is a WorkspaceBackend loaded from workspace.json. Missing
    workspace.json is a hard error — no single-root fallback."""
    backend_name = args.backend or cfg.get("backend", "composite")
    if backend_name == "auto":
        mcp_cfg = cfg.get("mcp") or {}
        backend_name = "composite" if mcp_cfg.get("bridge_script") else "filesystem"

    def _build_fs():
        from toolkit.backends.workspace import WorkspaceBackend
        from toolkit.config import loader as _l
        state_dir = project_dir / _l.resolve_state_dir(cfg)
        ws = _l.load_workspace(cfg)
        if ws is None:
            raise RuntimeError(
                f"no workspace.json under {state_dir}/ "
                "— create a project via the GUI first"
            )
        return WorkspaceBackend(ws, state_dir)

    if backend_name == "filesystem":
        return _build_fs()
    if backend_name == "mcp":
        return _create_mcp_backend(args, cfg, project_dir)
    if backend_name == "composite":
        return CompositeBackend([
            ("fs", _build_fs()),
            ("mcp", _create_mcp_backend(args, cfg, project_dir)),
        ])
    raise RuntimeError(f"unknown backend: {backend_name!r}")


def _create_mcp_backend(args, cfg, project_dir: Path):
    mcp_cfg = cfg.get("mcp") or {}
    bridge_script = args.bridge_script or mcp_cfg.get("bridge_script") or ""
    from ..config.loader import default_bridge_script, resolve_state_dir
    if bridge_script:
        bridge_path = Path(bridge_script)
        if not bridge_path.is_absolute():
            bridge_path = (project_dir / bridge_script).resolve()
    else:
        bridge_path = default_bridge_script()
    if not bridge_path.is_file() and args.backend != "composite":
        raise RuntimeError(f"bridge script not found: {bridge_path}")

    mcp_command = args.mcp_command if args.mcp_command is not None else mcp_cfg.get("mcp_command", "")
    mcp_args = args.mcp_args if args.mcp_args is not None else mcp_cfg.get("mcp_args", "")
    if not mcp_command:
        mcp_command = "cmd.exe"
    if not mcp_args:
        mcp_args = r"/c cd /d %LOCALAPPDATA%\Roblox && .\mcp.bat"

    native_cfg = mcp_cfg.get("native_tools") or {}
    return MCPBackend(
        bridge_script=str(bridge_path),
        command=mcp_cfg.get("command", "python -u"),
        mcp_command=mcp_command or None,
        mcp_args=mcp_args or "",
        working_dir=project_dir,
        state_subdir=resolve_state_dir(cfg),
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


def main(argv=None) -> int:
    args = _parse_args(argv)

    if args.list_tools:
        print("Registered tools:")
        for name in sorted(TOOL_MAP.keys()):
            cls = TOOL_MAP[name]
            op = getattr(cls, "op", "?")
            print(f"  {name:22s}  op={op}")
        return 0

    cfg_path = Path(args.config).resolve() if args.config else None
    cfg = cfg_loader.load(cfg_path)

    project_dir = _resolve_project(args, cfg)
    if project_dir is None:
        print("[error] project not set: pass --project or set project_dir in config",
              file=sys.stderr)
        return 2
    if not project_dir.is_dir():
        print(f"[error] project is not a directory: {project_dir}", file=sys.stderr)
        return 2
    cfg = cfg_loader.load(cfg_path, project_dir=project_dir)

    backend_name = args.backend or cfg.get("backend", "composite")
    preset = args.format_preset or cfg.get("format_preset", "default")
    fmt = Format.load(preset, cfg.get("format") or None)

    from toolkit.tools.shell import RunPythonTool
    RunPythonTool.set_config(cfg.get("exec"), project_dir)

    from toolkit.tools.index import install_index_paths
    install_index_paths(cfg)

    _roots: list[str] = []
    try:
        from toolkit.config import loader as _l
        _ws = _l.load_workspace(cfg)
        if _ws is not None:
            _roots = list(_ws.root_names())
    except Exception:
        _roots = []

    patches: list[dict] = []
    only_patches: list[dict] = []
    parsed = None
    if args.rebuild_only:
        only_patches.append(_rebuild_patch(args, cfg))
    if args.rebuild_code_only:
        only_patches.append(_rebuild_code_patch(args, cfg))
    if args.rebuild_lua_only:
        only_patches.append(_rebuild_lua_patch(args, cfg))

    if only_patches:
        patches = only_patches
    elif args.patch_file:
        patch_path = Path(args.patch_file)
        if not patch_path.is_file():
            print(f"[error] patch file not found: {patch_path}", file=sys.stderr)
            return 2
        try:
            parsed = _load_patches(patch_path)
            patches = parsed.actions
        except Exception as e:
            print(f"[error] failed to parse patch: {e}", file=sys.stderr)
            return 1
        if args.rebuild_index:
            patches.append(_rebuild_patch(args, cfg))
        if args.rebuild_code_index:
            patches.append(_rebuild_code_patch(args, cfg))
        if args.rebuild_lua_index:
            patches.append(_rebuild_lua_patch(args, cfg))
    else:
        print("[error] no patch_file and no --rebuild-*-only flag",
              file=sys.stderr)
        return 2

    print(f"Backend:     {backend_name}")
    print(f"Project:     {project_dir}")
    print(f"Config:      {cfg_path if cfg_path else cfg_loader.config_path()}")
    print(f"Format:      {preset}  |  Tools: {len(TOOL_MAP)}  |  Patches: {len(patches)}")
    print()

    try:
        backend = _create_backend(args, cfg, project_dir)
    except Exception as e:
        print(f"[error] cannot create backend: {e}", file=sys.stderr)
        return 2

    from toolkit.backends import CompositeBackend as _CB, MCPBackend as _MB
    if isinstance(backend, _CB):
        _enabled_backends = {"filesystem", "mcp"}
    elif isinstance(backend, _MB):
        _enabled_backends = {"mcp"}
    else:
        _enabled_backends = {"filesystem"}
    from toolkit.tools.status import GetStatusTool
    _mcp_cfg = cfg.get("mcp") or {}
    _native_cfg = _mcp_cfg.get("native_tools") or {}
    GetStatusTool.set_context(
        project_name=project_dir.name,
        backend=backend_name,
        luau_mode=(cfg.get("luau_mode") or "mcp"),
        format_preset=preset,
        exec_enabled=bool((cfg.get("exec") or {}).get("enabled")),
        exec_interpreter=(cfg.get("exec") or {}).get("interpreter"),
        native_tools_enabled=bool(_native_cfg.get("enabled", True)),
        native_tools_allow=_native_cfg.get("allow") or [],
        index_paths={
            "docs": cfg.get("index_output") or "INDEX.md",
            "code": cfg.get("code_index_output") or "CODE_INDEX.md",
            "lua":  cfg.get("lua_index_output") or "CODE_INDEX_LUA.md",
        },
        roots=_roots,
        backends_enabled=_enabled_backends,
    )

    with Session(backend, fmt=fmt, tools=TOOL_MAP) as s:
        diags = parsed.diagnostics if parsed is not None else None
        results = s.apply_patches(patches, diagnostics=diags)

    err = sum(1 for r in results if r.status == "error")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
