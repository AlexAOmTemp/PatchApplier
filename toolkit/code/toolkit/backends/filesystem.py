"""Filesystem backend — reads/writes local files under one root directory.

All paths are relative to the root. Sandbox enforcement: any path that
resolves outside the root is rejected before I/O.

Hiding: `.patchignore` in the project root holds gitignore-like patterns.
A path is hidden if any of its segments (or a path prefix) matches a
pattern. Hidden paths are refused before the policy is consulted, unless
the caller has an explicit True override for the path or one of its
named ancestors.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..config import patchignore
from ..core.models import FileStat


class FilesystemBackend:
    def __init__(self, working_dir: str | Path):
        # Public constructor takes `working_dir` for legacy compatibility;
        # internally it is stored as a private root. All path resolution
        # and sandbox enforcement use self._root.
        self._root = Path(working_dir).resolve()
        self._opened = False
        # Populated on `open()` — empty until then means nothing hidden.
        self._patterns: list[tuple[str, bool]] = []

    # --- lifecycle --------------------------------------------------------

    def open(self) -> None:
        if not self._root.exists():
            raise RuntimeError(f"working_dir не существует: {self._root}")
        if not self._root.is_dir():
            raise RuntimeError(f"working_dir не директория: {self._root}")
        patchignore.ensure_default(self._root)
        self._patterns = patchignore.read(self._root)
        self._opened = True

    def close(self) -> None:
        self._opened = False

    def is_alive(self) -> bool:
        return self._opened

    def reload_patterns(self) -> None:
        """Re-read `.patchignore` from disk.

        Call after the user edits the file (via the toolkit dialog or
        manually) so the running session picks up the new rules without a
        full restart.
        """
        self._patterns = patchignore.read(self._root)

    # --- helpers ----------------------------------------------------------

    def _resolve(self, path: str) -> Path:
        """Resolve a relative path against working_dir and enforce sandbox."""
        target = (self._root / path).resolve()
        try:
            target.relative_to(self._root)
        except ValueError:
            raise PermissionError(f"Путь вне проекта: {path}")
        return target

    @staticmethod
    def _count_lines(text: str) -> int:
        if not text:
            return 0
        n = text.count("\n")
        if not text.endswith("\n"):
            n += 1
        return n

    # --- data -------------------------------------------------------------

    def read(self, path: str) -> str:
        with self._resolve(path).open("r", encoding="utf-8", newline="") as f:
            return f.read()

    def create(self, path: str, content: str, class_name: str = "ModuleScript") -> None:
        """Create a new file. class_name is ignored (FS has no instance kinds)."""
        self.write(path, content)

    def write(self, path: str, content: str) -> None:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8", newline="") as f:
            f.write(content)

    def exists(self, path: str) -> bool:
        try:
            return self._resolve(path).exists()
        except PermissionError:
            return False

    def stat(self, path: str) -> FileStat:
        p = self._resolve(path)
        if not p.exists():
            raise FileNotFoundError(path)
        st = p.stat()
        lines = 0
        if p.is_file():
            try:
                lines = self._count_lines(p.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, OSError):
                lines = 0
        return FileStat(
            size_bytes=st.st_size,
            lines=lines,
            mtime=st.st_mtime,
            is_file=p.is_file(),
        )

    def list(self, root: str = "", glob: str = "*") -> list[str]:
        base = self._resolve(root) if root else self._root
        if not base.exists():
            return []
        out: list[str] = []
        for p in sorted(base.rglob(glob)):
            if not p.is_file():
                continue
            try:
                out.append(str(p.relative_to(self._root)).replace("\\", "/"))
            except ValueError:
                continue
        return out

    def list_with_stat(self, root: str = "", glob: str = "*") -> list[tuple[str, int, int]]:
        """Like `list`, but returns (path, size_bytes, lines) per file.

        Reads contents to count lines; non-decodable files fall back to 0
        lines. Order matches `list` (sorted).
        """
        base = self._resolve(root) if root else self._root
        if not base.exists():
            return []
        rows: list[tuple[str, int, int]] = []
        for p in sorted(base.rglob(glob)):
            if not p.is_file():
                continue
            try:
                rel = str(p.relative_to(self._root)).replace("\\", "/")
            except ValueError:
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            try:
                lines = self._count_lines(p.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, OSError):
                lines = 0
            rows.append((rel, st.st_size, lines))
        return rows


    def delete(self, path: str) -> None:
        self._resolve(path).unlink()

    def move(self, src: str, dst: str) -> None:
        s = self._resolve(src)
        d = self._resolve(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        s.rename(d)

    def copy_to(self, src_rel: str, other: "FilesystemBackend",
                dst_rel: str) -> None:
        """Copy a file into another FilesystemBackend's root.

        Used by WorkspaceBackend to support cross-root copies without
        exposing one backend's `_root` to the other.
        """
        s = self._resolve(src_rel)
        d = other._resolve(dst_rel)  # noqa: SLF001
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)


    def copy(self, src: str, dst: str) -> None:
        """Byte-exact copy (shutil.copy2 preserves metadata). Works on any file."""
        s = self._resolve(src)
        d = self._resolve(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)

    def filter_check(self, path: str, op: str) -> str | None:
        """No path-level policy at the FS level.

        In the new model, FilesystemBackend is used as a sub-backend of
        WorkspaceBackend. Path policy is a Workspace concern (per-root,
        per-path PathPolicy), enforced in WorkspaceBackend.filter_check.
        When FilesystemBackend is driven directly (tests, ad-hoc tools),
        there is no policy to consult — return None.

        Sandbox enforcement (path must be inside the root) still happens
        in `_resolve`, called by every read/write method.
        """
        return None


