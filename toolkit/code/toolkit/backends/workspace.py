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
from ..core.models import FileStat
from .filesystem import FilesystemBackend


class WorkspaceBackend:
    """Read-only multi-root FS backend."""

    def __init__(self, workspace: Workspace, state_dir: str | Path):
        self.ws = workspace
        self.state_dir = Path(state_dir).resolve()
        self.roots: dict[str, FilesystemBackend] = {}
        self._state_fs: FilesystemBackend | None = None
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
        # State directory — a separate FS backend. Addressed by the reserved
        # prefix `.patch_applier/` (patchignore.STATE_DIR), never by a root
        # basename. Exempt from policy: RW for internal tools, never indexed.
        self._state_fs = FilesystemBackend(self.state_dir)
        self._state_fs.open()
        patchignore.ensure_default(self.state_dir)
        self._patterns = patchignore.read(self.state_dir)
        self._opened = True

    def close(self) -> None:
        for fb in self.roots.values():
            fb.close()
        self.roots.clear()
        if self._state_fs is not None:
            self._state_fs.close()
            self._state_fs = None
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
        # See also: list() / list_with_stat() above for walk semantics.
        name, rel = self._split(path)
        # State directory is addressed by its reserved prefix — never by a
        # root basename. It is exempt from policy (see filter_check).
        if name == patchignore.STATE_DIR:
            if self._state_fs is None:
                raise FileNotFoundError("state backend not open")
            return name, rel, self._state_fs
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
            # All files across all roots, prefixed with <basename>/. This is
            # what indexers expect from list(""). The state directory is
            # excluded when it happens to be inside a root.
            out: list[str] = []
            for name, fb in self.roots.items():
                state_rel = self._state_rel_for(name)
                for p in fb.list("", glob):
                    if state_rel is not None and (
                            p == state_rel or p.startswith(state_rel + "/")):
                        continue
                    out.append(f"{name}/{p}")
            return sorted(out)
        name, rel = self._split(root)
        if name == patchignore.STATE_DIR:
            if self._state_fs is None:
                return []
            return [f"{name}/{p}" for p in self._state_fs.list(rel, glob)]
        fb = self.roots.get(name)
        if fb is None:
            return []
        return [f"{name}/{p}" for p in fb.list(rel, glob)]

    def list_with_stat(self, root: str = "", glob: str = "*"):
        if not root:
            out: list[tuple[str, int, int]] = []
            for name, fb in self.roots.items():
                state_rel = self._state_rel_for(name)
                for (p, size, lines) in fb.list_with_stat("", glob):
                    if state_rel is not None and (
                            p == state_rel or p.startswith(state_rel + "/")):
                        continue
                    out.append((f"{name}/{p}", size, lines))
            return sorted(out, key=lambda r: r[0])
        name, rel = self._split(root)
        if name == patchignore.STATE_DIR:
            if self._state_fs is None:
                return []
            return [(f"{name}/{p}", size, lines)
                    for (p, size, lines) in self._state_fs.list_with_stat(rel, glob)]
        fb = self.roots.get(name)
        if fb is None:
            return []
        return [(f"{name}/{p}", size, lines)
                for (p, size, lines) in fb.list_with_stat(rel, glob)]

    def list_roots(self) -> list[str]:
        """Basenames of all workspace roots (not files).

        For GUI tree tabs and diagnostics. The general `list("")` returns
        all files across all roots with `<basename>/<rel>` prefixes, which
        is what the indexers expect.
        """
        return sorted(self.roots.keys())

    def _state_rel_for(self, root_name: str) -> str | None:
        """Relative state path under a root, or None if state is elsewhere.

        state_dir may be inside a root (embedded project folder). We must
        exclude it from list()-based walks so the indexer does not eat its
        own artifacts.
        """
        fb = self.roots.get(root_name)
        if fb is None:
            return None
        try:
            rel = self.state_dir.relative_to(fb._root)  # noqa: SLF001
        except ValueError:
            return None
        return str(rel).replace("\\", "/")


    def _state_write_target(self, path: str):
        """Return (state_fs, rel) if path is under the state prefix; else None.

        Writes into the state directory are allowed even though the
        backend is read-only for workspace roots (step 3 of the plan).
        The state directory is the toolkit's own — indexes, manifests,
        .version files — and is hardcoded RW in the old model too
        (see WORKSPACE_BACKEND.md §5).
        """
        name, rel = self._split(path)
        if name != patchignore.STATE_DIR:
            return None
        if self._state_fs is None:
            raise FileNotFoundError("state backend not open")
        return self._state_fs, rel


    # --- write (enabled in step 6) -----------------------------------------

    def write(self, path: str, content: str) -> None:
        target = self._state_write_target(path)
        if target is not None:
            fb, rel = target
            fb.write(rel, content)
            return
        _, rel, fb = self._resolve_root(path)
        fb.write(rel, content)

    def create(self, path: str, content: str,
               class_name: str = "ModuleScript") -> None:
        target = self._state_write_target(path)
        if target is not None:
            fb, rel = target
            fb.write(rel, content)
            return
        _, rel, fb = self._resolve_root(path)
        fb.write(rel, content)

    def delete(self, path: str) -> None:
        target = self._state_write_target(path)
        if target is not None:
            fb, rel = target
            fb.delete(rel)
            return
        _, rel, fb = self._resolve_root(path)
        fb.delete(rel)

    def move(self, src: str, dst: str) -> None:
        s_name, s_rel = self._split(src)
        d_name, d_rel = self._split(dst)
        # Both ends must be in the same logical storage: state or the same root.
        if s_name == patchignore.STATE_DIR or d_name == patchignore.STATE_DIR:
            if s_name != d_name:
                raise RuntimeError(
                    f"move across state/root ({s_name} -> {d_name}) is not supported"
                )
            if self._state_fs is None:
                raise FileNotFoundError("state backend not open")
            self._state_fs.move(s_rel, d_rel)
            return
        if s_name != d_name:
            raise RuntimeError(
                f"move across roots ({s_name} -> {d_name}) is not supported"
            )
        _, _, fb = self._resolve_root(src)
        fb.move(s_rel, d_rel)

    def copy(self, src: str, dst: str) -> None:
        s_name, s_rel = self._split(src)
        d_name, d_rel = self._split(dst)
        # Cross-root copy is allowed at the FS level (both sides are local
        # files); the physical copy goes through the source's FS backend.
        # Cross-state/root is not — different backends.
        s_state = s_name == patchignore.STATE_DIR
        d_state = d_name == patchignore.STATE_DIR
        if s_state != d_state:
            raise RuntimeError(
                f"copy across state/root ({s_name} -> {d_name}) is not supported"
            )
        if s_state:
            if self._state_fs is None:
                raise FileNotFoundError("state backend not open")
            self._state_fs.copy(s_rel, d_rel)
            return
        src_fb = self.roots.get(s_name)
        dst_fb = self.roots.get(d_name)
        if src_fb is None or dst_fb is None:
            raise FileNotFoundError(f"copy: unknown root in {src!r} -> {dst!r}")
        src_fb.copy_to(s_rel, dst_fb, d_rel)

    def resolve_physical(self, path: str) -> Path | None:
        """Physical Path for a workspace-relative path, or None.

        Delegates to the owning FilesystemBackend (or state FS for the
        `.patch_applier/` prefix). Returns None for unknown roots and
        sandbox violations.
        """
        name, rel = self._split(path)
        if name == patchignore.STATE_DIR:
            if self._state_fs is None:
                return None
            return self._state_fs.resolve_physical(rel)
        fb = self.roots.get(name)
        if fb is None:
            return None
        return fb.resolve_physical(rel)

    # --- filter ------------------------------------------------------------

    def filter_check(self, path: str, op: str) -> tuple[str, str] | None:
        """None = ok. Otherwise (error_code, message).

        Rules (see WORKSPACE_BACKEND.md §5):
          0. State prefix (`.patch_applier/`) is always OK.
          1. Root must exist in workspace.
          2. `.patchignore` from state_dir applies to ``rel`` inside the root.
          3. Per-path policy applies: nearest override under the root,
             otherwise the root default, otherwise all-True.

        `op` is one of read / write / index_docs / index_py / index_lua —
        the flag consulted on the resolved PathPolicy.
        """
        name, rel = self._split(path)
        if name == patchignore.STATE_DIR:
            return None
        if name not in self.roots:
            return ("filter", f"root '{name}' not in workspace")
        rel_norm = rel.replace("\\", "/")
        if rel_norm and patchignore.path_hidden(rel_norm, self._patterns):
            return ("hidden_path", f"Скрытая папка: {path}")
        pol = self.ws.policy_for(name, rel_norm)
        if not bool(getattr(pol, op, True)):
            return ("filter", f"Запрещено политикой: {path}")
        return None
