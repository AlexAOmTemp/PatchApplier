"""WorkspaceBackend — multi-root FS backend (read-only, step 3).

Spec: docs/WORKSPACE_BACKEND.md. Standalone skeleton — routes paths of
the form ``<basename>/<rel>`` to one of N internal FilesystemBackend
instances (one per workspace root). Read-only: write/delete/move/copy
raise NotImplementedError. Write is enabled in step 6.

Not wired into CompositeBackend yet — that is step 4. Nothing in the
runtime uses this class today.

Path forms:
  ``<basename>/<rel>``  — file inside a named root, e.g. ``src/a.py``.
  ``<basename>``        — a root itself (dir), resolved as ``rel=""``.
  ``""``                — list all roots; only ``list`` accepts this.

State dir is workspace-level, one per workspace, not exposed here as a
routed path — see WORKSPACE_BACKEND.md §7.
"""
from __future__ import annotations

from pathlib import Path

from ..config import patchignore
from ..config.workspace import Workspace
from ..core.models import FileStat, FilterSpec
from .filesystem import FilesystemBackend


class WorkspaceBackend:
    """Read-only multi-root FS backend."""

    def __init__(self, workspace: Workspace, state_dir: str | Path):
        self.ws = workspace
        self.state_dir = Path(state_dir).resolve()
        self.roots: dict[str, FilesystemBackend] = {}
        self._patterns: list[tuple[str, bool]] = []
        self._opened = False

    # --- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        if self._opened:
            return
        # One FS backend per root. Their own `.patchignore` (created by
        # FilesystemBackend.open) is separate from the workspace-level one
        # in state_dir — the latter is what filter_check consults.
        for name, root in self.ws.roots.items():
            fb = FilesystemBackend(root.path)
            fb.open()
            self.roots[name] = fb
        patchignore.ensure_default(self.state_dir)
        self._patterns = patchignore.read(self.state_dir)
        self._opened = True

    def close(self) -> None:
        for fb in self.roots.values():
            fb.close()
        self.roots.clear()
        self._opened = False

    def is_alive(self) -> bool:
        """Workspace is alive once open() succeeded.

        Deliberately does not require any live FS root: a workspace with
        zero roots is valid (MCP-only mode). Per-root failures surface as
        errors on read/list of that specific root.
        """
        return self._opened

    def reload_patterns(self) -> None:
        """Re-read workspace-level `.patchignore` from state_dir."""
        self._patterns = patchignore.read(self.state_dir)

    @property
    def working_dir(self):
        """The state directory — where the workspace's own files live.

        Kept for compatibility with tools that need "one path" for
        indexing (RebuildLuaCodeIndexTool) and with CompositeBackend's
        working_dir property. It is NOT a filesystem root; roots are in
        self.roots.
        """
        return self.state_dir


    # --- path routing ------------------------------------------------------

    def _split(self, path: str) -> tuple[str, str]:
        """Split ``<basename>/<rel>`` into (basename, rel).

        Missing ``/`` -> rel is "". Leading slashes stripped. Backslashes
        normalised to forward slashes before splitting.
        """
        p = path.replace("\\", "/").strip("/")
        if "/" in p:
            name, rel = p.split("/", 1)
        else:
            name, rel = p, ""
        return name, rel

    def _resolve_root(self, path: str) -> tuple[str, str, FilesystemBackend]:
        name, rel = self._split(path)
        fb = self.roots.get(name)
        if fb is None:
            raise FileNotFoundError(f"root '{name}' not in workspace")
        return name, rel, fb

    # --- data --------------------------------------------------------------

    def read(self, path: str) -> str:
        _, rel, fb = self._resolve_root(path)
        return fb.read(rel)

    def exists(self, path: str) -> bool:
        try:
            _, rel, fb = self._resolve_root(path)
        except FileNotFoundError:
            return False
        return fb.exists(rel)

    def stat(self, path: str) -> FileStat:
        _, rel, fb = self._resolve_root(path)
        return fb.stat(rel)

    def list(self, root: str = "", glob: str = "*") -> list[str]:
        if not root:
            # Empty path lists root basenames — one per workspace root.
            return sorted(self.roots.keys())
        name, rel = self._split(root)
        fb = self.roots.get(name)
        if fb is None:
            return []
        return [f"{name}/{p}" for p in fb.list(rel, glob)]

    def list_with_stat(self, root: str = "", glob: str = "*"):
        if not root:
            return []
        name, rel = self._split(root)
        fb = self.roots.get(name)
        if fb is None:
            return []
        return [(f"{name}/{p}", size, lines)
                for (p, size, lines) in fb.list_with_stat(rel, glob)]

    # --- write (enabled in step 6) -----------------------------------------

    def write(self, path: str, content: str) -> None:
        raise NotImplementedError(
            "WorkspaceBackend: write is enabled in step 6 of the plan"
        )

    def create(self, path: str, content: str,
               class_name: str = "ModuleScript") -> None:
        raise NotImplementedError(
            "WorkspaceBackend: create is enabled in step 6 of the plan"
        )

    def delete(self, path: str) -> None:
        raise NotImplementedError(
            "WorkspaceBackend: delete is enabled in step 6 of the plan"
        )

    def move(self, src: str, dst: str) -> None:
        raise NotImplementedError(
            "WorkspaceBackend: move is enabled in step 6 of the plan"
        )

    def copy(self, src: str, dst: str) -> None:
        raise NotImplementedError(
            "WorkspaceBackend: copy is enabled in step 6 of the plan"
        )

    # --- filter ------------------------------------------------------------

    def filter_check(self, path: str, spec: FilterSpec) -> str | None:
        """None = ok. Otherwise a message with a block reason.

        Rules (see WORKSPACE_BACKEND.md §5):
          1. Root must exist in workspace.
          2. `.patchignore` from state_dir applies to ``rel`` inside the root.
          3. Policy applies to the *full* ``<basename>/<rel>`` — so
             workspace-level patterns can distinguish ``docs/x.md`` from
             ``src/x.md``. This is the workspace model; the FS backend's own
             filter uses bare ``rel`` for legacy single-root mode.
        """
        name, rel = self._split(path)
        if name not in self.roots:
            return f"root '{name}' not in workspace"
        rel_norm = rel.replace("\\", "/")
        if rel_norm and patchignore.path_hidden(rel_norm, self._patterns):
            return f"Скрытая папка: {path}"
        full = f"{name}/{rel_norm}" if rel_norm else name
        if not spec.resolve(full):
            return f"Запрещено политикой: {path}"
        return None
