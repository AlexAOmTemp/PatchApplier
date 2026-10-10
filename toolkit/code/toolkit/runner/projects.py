"""Project folder operations — layout, validate, create.

Pure logic. No Tk, no messagebox. Called by the GUI File menu and by
any non-GUI runner that needs the same operations.

A project is a folder with `workspace.json` inside its state subdir
(`<folder>/<state_subdir>/workspace.json`). Creating a project seeds
`workspace.json`, `.patchignore`, `.mcpignore` with defaults.

Spec: docs/WORKSPACE.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_STATE_SUBDIR = ".patch_applier"
WORKSPACE_FILENAME = "workspace.json"


@dataclass
class ProjectLayout:
    """Resolved paths for a project folder."""
    folder: Path
    state_dir: Path
    workspace_path: Path


class NotAProject(Exception):
    """Raised when a folder has no workspace.json in its state subdir."""


class ProjectExists(Exception):
    """Raised when create_project is called on a folder that already has one."""


def resolve_layout(folder: str | Path,
                   state_subdir: str = DEFAULT_STATE_SUBDIR) -> ProjectLayout:
    """Return the canonical layout for a project folder.

    Does not touch the filesystem beyond resolving the path.
    """
    folder_p = Path(folder).resolve()
    state = folder_p / state_subdir
    return ProjectLayout(
        folder=folder_p,
        state_dir=state,
        workspace_path=state / WORKSPACE_FILENAME,
    )


def is_project(folder: str | Path,
               state_subdir: str = DEFAULT_STATE_SUBDIR) -> bool:
    return resolve_layout(folder, state_subdir).workspace_path.is_file()


def create_project(folder: str | Path, name: str,
                   state_subdir: str = DEFAULT_STATE_SUBDIR) -> ProjectLayout:
    """Create a fresh project at `folder` with the given display name.

    Raises ProjectExists if a workspace.json is already there.
    Side effects: creates state_dir; writes workspace.json,
    .patchignore, .mcpignore (default texts).
    """
    from ..config import workspace as _ws
    from ..config import patchignore as _pi
    from ..config import mcpignore as _mi

    layout = resolve_layout(folder, state_subdir)
    if layout.workspace_path.is_file():
        raise ProjectExists(str(layout.workspace_path))
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    w = _ws.Workspace(id=_ws.new_id(), name=name)
    if not _ws.save(w, layout.state_dir):
        raise RuntimeError("failed to write workspace.json")
    _pi.ensure_default(layout.state_dir)
    _mi.ensure_default(layout.state_dir)
    return layout


def load_workspace(folder: str | Path,
                   state_subdir: str = DEFAULT_STATE_SUBDIR):
    """Load the Workspace for a project folder; raise NotAProject if absent."""
    from ..config import workspace as _ws
    layout = assert_project(folder, state_subdir)
    w = _ws.load(layout.state_dir)
    if w is None:
        raise NotAProject(str(layout.workspace_path))
    return w


def save_workspace(folder: str | Path, w,
                   state_subdir: str = DEFAULT_STATE_SUBDIR) -> None:
    """Save a Workspace; validate happens inside _ws.save.

    Raises ValueError on validation failure (nested roots, duplicate
    basename, reserved name).
    """
    from ..config import workspace as _ws
    layout = resolve_layout(folder, state_subdir)
    if not _ws.save(w, layout.state_dir):
        # _ws.save returns False when validate() raised; run validate
        # again to surface the concrete reason to the caller.
        _ws.validate(w)
        raise RuntimeError("failed to write workspace.json")


def list_roots(folder: str | Path, state_subdir: str = DEFAULT_STATE_SUBDIR):
    """Return a list of dicts: {name, path, include, exclude, policy}.

    Policy is a plain dict (read/write/index_docs/index_py/index_lua).
    """
    w = load_workspace(folder, state_subdir)
    out = []
    for name in w.root_names():
        r = w.roots[name]
        p = w.policy.get(name)
        out.append({
            "name": name,
            "path": r.path,
            "include": list(r.include),
            "exclude": list(r.exclude),
            "policy": {
                "read": bool(p.read) if p else True,
                "write": bool(p.write) if p else True,
                "index_docs": bool(p.index_docs) if p else True,
                "index_py": bool(p.index_py) if p else True,
                "index_lua": bool(p.index_lua) if p else True,
            },
        })
    return out


def add_root(folder: str | Path, root_path: str,
             state_subdir: str = DEFAULT_STATE_SUBDIR) -> str:
    """Add a root. Returns its derived name.

    Raises ValueError (nested / duplicate basename / reserved name /
    path missing) on failure. Saves on success.
    """
    from ..config import workspace as _ws
    p = Path(root_path).resolve()
    if not p.is_dir():
        raise ValueError(f"path is not a directory: {p}")
    w = load_workspace(folder, state_subdir)
    name = _ws.add_root(w, str(p))
    save_workspace(folder, w, state_subdir)
    return name


def remove_root(folder: str | Path, name: str,
                state_subdir: str = DEFAULT_STATE_SUBDIR) -> None:
    """Remove a root by name. No-op if absent. Saves on success."""
    w = load_workspace(folder, state_subdir)
    if name in w.roots:
        del w.roots[name]
        w.policy.pop(name, None)
        save_workspace(folder, w, state_subdir)


def update_root_policy(folder: str | Path, name: str,
                       flags: dict,
                       state_subdir: str = DEFAULT_STATE_SUBDIR) -> None:
    """Update a root's policy flags. `flags` is a partial dict.

    Accepted keys: read / write / index_docs / index_py / index_lua.
    Missing keys are left unchanged. Saves on success.
    """
    from ..config.workspace import RootPolicy
    w = load_workspace(folder, state_subdir)
    if name not in w.roots:
        raise KeyError(f"no such root: {name!r}")
    cur = w.policy.get(name) or RootPolicy()
    for k in ("read", "write", "index_docs", "index_py", "index_lua"):
        if k in flags:
            setattr(cur, k, bool(flags[k]))
    w.policy[name] = cur
    save_workspace(folder, w, state_subdir)


def rename_project(folder: str | Path, new_name: str,
                   state_subdir: str = DEFAULT_STATE_SUBDIR) -> None:
    """Rename the workspace. Saves on success."""
    w = load_workspace(folder, state_subdir)
    w.name = str(new_name)
    save_workspace(folder, w, state_subdir)


def assert_project(folder: str | Path,
                   state_subdir: str = DEFAULT_STATE_SUBDIR) -> ProjectLayout:
    """Return the layout or raise NotAProject. Does not modify anything."""
    layout = resolve_layout(folder, state_subdir)
    if not layout.workspace_path.is_file():
        raise NotAProject(str(layout.workspace_path))
    return layout
