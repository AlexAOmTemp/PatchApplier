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


def assert_project(folder: str | Path,
                   state_subdir: str = DEFAULT_STATE_SUBDIR) -> ProjectLayout:
    """Return the layout or raise NotAProject. Does not modify anything."""
    layout = resolve_layout(folder, state_subdir)
    if not layout.workspace_path.is_file():
        raise NotAProject(str(layout.workspace_path))
    return layout
