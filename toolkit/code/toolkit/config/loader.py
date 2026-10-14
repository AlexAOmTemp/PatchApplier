"""Config loader for .patch_applier.json.

**Two files, one merged config.**

*Tool-wide* -- `<toolkit_root>/.patch_applier.json`. Same for every
project: the currently active `project_dir`, `recent_projects`,
`ui_language`, `format`/`format_preset`, `mcp` (bridge config), `exec`
(run_python security policy).

*Per-project* -- `<project>/.patch_applier/config.json`. Describes one
project: `backend`, `filter` (read/write/index), `skip_files`,
`code_*`, `lua_*`, `luau_mode`, `index_*`.

`load()` reads tool-wide first, then overlays the per-project file (its
`project_dir` -- or the explicit argument -- selects which). `save()`
splits a merged dict back into the two files. If no project is set,
`save()` writes everything to the tool-wide file (legacy single-file
behaviour).

The legacy flat form (top-level `filter_mode`/`filter_dirs`) is also
accepted and applied uniformly to all three roles.
"""
from __future__ import annotations

import json
from pathlib import Path


CONFIG_FILENAME = ".patch_applier.json"

# Fields that live in the tool-wide config (<toolkit_root>/.patch_applier.json).
# Everything else in DEFAULTS is per-project and lands in
# <project>/.patch_applier/config.json.
TOOL_FIELDS = frozenset({
    "project_dir",
    "recent_projects",
    "ui_language",
    "format_preset",
    "format",
    "mcp",
    "exec",
})

DEFAULTS: dict = {
    "project_dir": "",
    "recent_projects": [],
    "format_preset": "default",
    "format": {},
    # Backend: filesystem / mcp / composite. Controls which transport
    # the runner uses to open files.
    "backend": "filesystem",
    # Where the Luau code lives: "mcp" (Studio .Source, dotted Roblox
    # paths) or "rojo" (files on disk, ordinary filesystem paths).
    # Determines path format and edit backend for .luau/.lua files.
    # Orthogonal to `backend`: the scene (Parts, GUI, Folders) always
    # goes through MCP in both modes.
    "luau_mode": "mcp",
    # New per-op policy form (used by CLI):
    #     "filter": {"read": {...}, "write": {...}, "index": {...}}
    "filter": {},
    # Legacy flat form (kept for GUI compatibility). Applied uniformly to
    # all three roles if `filter` is empty.
    "filter_mode": "none",
    "filter_dirs": [],
    "index_docs_dir": "",
    "index_output": "",
    "lua_index_output": "",
    # Which indexers are enabled for this project. Read by router.py
    # (which rebuilds to trigger after a write) and written by the GUI
    # backend checkboxes.
    "index_docs": True,
    "index_python": True,
    "index_lua": True,
    # Files skipped by the docs indexer (by basename). Must cover every
    # index artifact it would otherwise try to index recursively:
    # INDEX.md (docs), CODE_INDEX.md (Python), CODE_INDEX_LUA.md (Luau).
    # .version / .manifest.json sidecars do not match *.md, no entry needed.
    "skip_files": ["INDEX.md", "CODE_INDEX.md", "CODE_INDEX_LUA.md"],
    # Language of the LLM starter text (docs/LLM_START.<lang>.md).
    # Falls back to "en" if the selected language file is missing.
    "ui_language": "ru",
    # Directory hiding is controlled by `.patchignore` in the project
    # root (see config/patchignore.py), not by config fields.
    # Python code index settings.
    "code_dir": "",
    "code_index_output": "",
    "code_manifest_output": "",
    "code_skip_files": [],
    "code_skip_dirs": [],
    # Python script runner (`run_python`). Disabled by default — this
    # tool must be explicitly enabled, because executing arbitrary Python
    # is a form-restricted capability, not a security boundary.
    "exec": {
        "enabled": False,
        "interpreter": None,
        "allow_module_mode": True,
        "child_encoding": "utf-8",
        "default_timeout": 60,
        "max_timeout": 600,
        "max_output_bytes": 200000,
        "env_passthrough": [
            "PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT",
            "TEMP", "TMP", "HOME", "USERPROFILE",
            "APPDATA", "LOCALAPPDATA",
            "PYTHONPATH", "PYTHONIOENCODING", "PYTHONUTF8",
            "LANG", "LC_ALL",
        ],
        "env_deny_patterns": ["*_TOKEN", "*_KEY", "*_SECRET", "AWS_*", "GITHUB_*"],
    },
    # MCP backend settings (bridge_script, mcp_command, mcp_args, ...).
    # native_tools enables passthrough of bridge-native tools under their
    # original names (insert_asset, generate_mesh, ...). Off by default.
    "mcp": {
        # bridge_script is normally derived from __file__ (see
        # config.loader.default_bridge_script). Set it only to override
        # for tests or custom bridges; leave null in normal use.
        "bridge_script": None,
        # native_tools: when MCP backend is active, the LLM may call bridge
        # tools by their original names (multi_edit, execute_luau, ...).
        # Default True: if the bridge is up, native tools are the natural
        # way to talk to DataModel. Set enabled=False only to hide them.
        "native_tools": {
            "enabled": True,
            "allow": [],
        },
    },
}


def toolkit_root() -> Path:
    """Root of the toolkit (contains .patch_applier.json, code/, docs/, runtime/)."""
    # loader.py -> config/ -> toolkit (inner) -> code/ -> toolkit (root)
    return Path(__file__).resolve().parents[3]


def toolkit_runtime_state_dir() -> Path:
    """<toolkit_root>/runtime/state — toolkit-global runtime files.

    Unlike per-project `state_dir` (indices, patch.json, outputs.json,
    bridge_log.jsonl), files here are the same for every project: the
    tools schema, MCP timings log, etc. Only the toolkit touches this
    directory; it must not be duplicated into each project tree.
    """
    return toolkit_root() / "runtime" / "state"


def workspaces_root() -> Path:
    """<toolkit_root>/runtime/workspaces — workspace state directories.

    Each workspace lives in its own subdirectory named by its id
    (see config/workspace.py). External by default; a workspace may
    also point at an embedded state directory elsewhere (the path is
    then recorded in runtime/recent.json).
    """
    return toolkit_root() / "runtime" / "workspaces"


def default_bridge_script() -> Path:
    """Bridge ships with the toolkit; its path is derived, not configured."""
    return toolkit_root() / "code" / "bridge" / "bridge.py"


def config_path(base_dir: Path | None = None) -> Path:
    """Tool-wide config: <toolkit_root>/.patch_applier.json."""
    if base_dir is None:
        base_dir = toolkit_root()
    return base_dir / CONFIG_FILENAME


def project_config_path(project_dir: str | Path) -> Path:
    """Per-project config: <project>/.patch_applier/config.json."""
    return Path(project_dir).resolve() / ".patch_applier" / "config.json"


def _read_json(p: Path) -> dict:
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(p: Path, data: dict) -> bool:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def load(path: Path | None = None,
         project_dir: str | Path | None = None) -> dict:
    """Read tool-wide + per-project config, merged over defaults.

    `path` overrides the tool-wide config location. The per-project file
    is selected by `project_dir` (explicit) or by the tool-wide
    `project_dir` value. If neither yields a project, only tool-wide is
    used (legacy single-file behaviour still works: an old combined file
    simply has no per-project overlay).
    """
    cfg = dict(DEFAULTS)
    tool = _read_json(path if path is not None else config_path())
    cfg.update({k: v for k, v in tool.items() if k in DEFAULTS})

    proj = project_dir if project_dir is not None else cfg.get("project_dir")
    if proj:
        overlay = _read_json(project_config_path(proj))
        cfg.update({k: v for k, v in overlay.items() if k in DEFAULTS})

    # Deep-merge `exec` so a partial override does not silently drop the
    # default env allowlist or timeouts.
    exec_defaults = DEFAULTS.get("exec") or {}
    if isinstance(cfg.get("exec"), dict):
        merged = dict(exec_defaults)
        merged.update(cfg["exec"])
        cfg["exec"] = merged
    # Deep-merge `mcp` so a partial override (e.g. just bridge_script) does
    # not drop native_tools defaults.
    mcp_defaults = DEFAULTS.get("mcp") or {}
    if isinstance(cfg.get("mcp"), dict):
        merged = dict(mcp_defaults)
        user_mcp = dict(cfg["mcp"])
        native_user = user_mcp.pop("native_tools", None)
        merged.update(user_mcp)
        native_defaults = dict(mcp_defaults.get("native_tools") or {})
        if isinstance(native_user, dict):
            native_defaults.update(native_user)
        merged["native_tools"] = native_defaults
        cfg["mcp"] = merged
    return cfg


def save(cfg: dict, path: Path | None = None) -> bool:
    """Split merged config into tool-wide + per-project files.

    `path` overrides the tool-wide file path. The per-project path comes
    from `cfg["project_dir"]`; if empty, everything is written to the
    tool-wide file (legacy single-file behaviour).
    """
    tool_path = path if path is not None else config_path()
    tool = {k: v for k, v in cfg.items() if k in TOOL_FIELDS}
    project = {
        k: v for k, v in cfg.items()
        if k in DEFAULTS and k not in TOOL_FIELDS
    }
    ok = _write_json(tool_path, tool)
    proj = cfg.get("project_dir") or ""
    if proj:
        ok = _write_json(project_config_path(proj), project) and ok
    return ok


def add_recent(cfg: dict, path: str, max_n: int = 10) -> dict:
    if not path:
        return cfg
    rec = list(cfg.get("recent_projects", []))
    if path in rec:
        rec.remove(path)
    rec.insert(0, path)
    cfg["recent_projects"] = rec[:max_n]
    return cfg


def recent_path() -> Path:
    """<toolkit_root>/runtime/state/recent.json — recent project folders."""
    return toolkit_runtime_state_dir() / "recent.json"


def read_recent() -> list[dict]:
    """Return [{"path": str, "name": str}, ...] (most recent first)."""
    p = recent_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for it in data:
        if isinstance(it, dict) and it.get("path"):
            out.append({
                "path": str(it["path"]),
                "name": str(it.get("name") or Path(it["path"]).name),
            })
        elif isinstance(it, str) and it:
            out.append({"path": it, "name": Path(it).name})
    return out


def add_recent_file(path: str, name: str | None = None,
                    max_n: int = 10) -> None:
    """Prepend a project folder to recent.json (dedup, cap at max_n)."""
    if not path:
        return
    p_str = str(Path(path).resolve())
    items = [it for it in read_recent() if it["path"] != p_str]
    items.insert(0, {
        "path": p_str,
        "name": str(name) if name else Path(p_str).name,
    })
    items = items[:max_n]
    p = recent_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def parse_csv(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    s = str(value).strip()
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


_SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", ".idea", ".vscode",
    "venv", ".venv",
}


# Default row cap for the policy tree. Chosen so that RimWorld's
# Mods/<86 mods> stops at depth 2 (~115 rows) instead of descending into
# each mod's Defs/Assemblies at depth 3 (thousands). Set higher for a
# deeper view; the trade-off is how many Tk widgets get created.
DEFAULT_SCAN_MAX_ROWS = 200


def scan_subdirs_ex(
    root: Path,
    max_depth: int = 2,
    patterns: list | None = None,
    show_hidden: bool = False,
    max_rows: int = DEFAULT_SCAN_MAX_ROWS,
) -> tuple[list[tuple[str, bool]], int | None]:
    """Return [(relative_path, is_hidden), ...] up to max_depth, capped.

    `patterns` is a list of (glob, negated) pairs from `.patchignore`. A
    directory is hidden if any of its segments matches a hiding pattern
    (see `patchignore.path_hidden`).

    Hidden dirs are **terminal**: they are included when
    `show_hidden=True` (marked hidden), but their contents are never
    walked. This makes the `show_hidden=True` result a superset of the
    `show_hidden=False` result -- callers can scan once with hidden on and
    filter in memory, avoiding a disk round-trip on every toggle.

    Expansion is level by level. If adding the next level would push the
    total over `max_rows`, that whole level is skipped. `max_rows=0`
    disables the cap. Returns (paths, truncated_at_depth); depth is None
    when nothing was truncated.
    """
    if not root or not Path(root).is_dir():
        return [], None
    root = Path(root).resolve()
    from .patchignore import path_hidden, is_state_path
    pats = list(patterns or [])
    out: list[tuple[str, bool]] = []
    truncated_at: int | None = None

    current: list[Path] = [root]
    for depth in range(1, max_depth + 1):
        level: list[tuple[str, bool, Path]] = []
        cancelled = False
        for parent in current:
            try:
                entries = sorted(parent.iterdir())
            except (PermissionError, OSError):
                continue
            for e in entries:
                if not e.is_dir():
                    continue
                try:
                    rel = str(e.relative_to(root)).replace("\\", "/")
                except ValueError:
                    continue
                hidden = path_hidden(rel, pats) or is_state_path(rel)
                if hidden and not show_hidden:
                    continue
                level.append((rel, hidden, e))
            if max_rows > 0 and len(out) + len(level) > max_rows:
                cancelled = True
                break

        if not level:
            break
        if cancelled:
            truncated_at = depth
            break

        for rel, hidden, _e in level:
            out.append((rel, hidden))
        current = [e for (_rel, hid, e) in level if not hid]

    return out, truncated_at


# Thin backwards-compatible wrapper: callers that do not want the cap pass
# max_rows explicitly through scan_subdirs_ex; this one keeps the old
# signature (no cap).
def scan_subdirs(
    root: Path,
    max_depth: int = 2,
    patterns: list | None = None,
    show_hidden: bool = False,
) -> list[tuple[str, bool]]:
    paths, _ = scan_subdirs_ex(root, max_depth, patterns, show_hidden,
                               max_rows=0)
    return paths


def load_workspace(cfg: dict):
    """Read workspace.json from <project_dir>/<state_dir>/.

    Returns a Workspace or None when there is no file. A None result
    means "this project folder has no workspace" — the runner refuses
    to open it rather than silently falling back to a single-root model.
    """
    project = (cfg.get("project_dir") or "").strip()
    if not project:
        return None
    from .workspace import load as _ws_load
    state_dir = Path(project) / resolve_state_dir(cfg)
    return _ws_load(state_dir)


def resolve_index_paths(cfg: dict) -> dict:
    sub = resolve_state_dir(cfg)
    prefix = (sub + "/") if sub else ""
    return {
        "docs":          cfg.get("index_output")        or (prefix + "INDEX.md"),
        "code":          cfg.get("code_index_output")   or (prefix + "CODE_INDEX.md"),
        "code_manifest": cfg.get("code_manifest_output") or (prefix + "CODE_INDEX.manifest.json"),
        "lua":           cfg.get("lua_index_output")    or (prefix + "CODE_INDEX_LUA.md"),
        "lua_manifest":  prefix + "CODE_INDEX_LUA.manifest.json",
    }


STATE_DIR = ".patch_applier"


def resolve_state_dir(cfg: dict | None = None) -> str:
    """Effective toolkit state directory inside the project.

    Fixed: `.patch_applier` in the project root. Historically this was a
    user-configurable field (`state_dir`, legacy alias `service_subdir`),
    but the flexibility bought confusion, not value: the state dir is a
    dotdir, and the `.patchignore` default opens it with `!.patch_applier`
    so the index tools and MCP runtime can reach their own files. Making
    it configurable meant that exception had to track a user-chosen name.

    `cfg` is accepted and ignored for backward compatibility at call
    sites. The legacy fields `state_dir` / `service_subdir` are no longer
    read; if present in a saved config they are dropped on the next save.
    """
    return STATE_DIR
