"""Filesystem backend — reads/writes local files under one root directory.

All paths are relative to the root. Sandbox enforcement: any path that
resolves outside the root is rejected before I/O.

This class does **not** know about `.patchignore`. Visibility rules are
a workspace concern: `MultiRootFsBackend` reads them from its own
state_dir and exposes `is_hidden` / `filter_check`. A bare RootDirBackend
driven directly (tests, ad-hoc tools) sees everything inside its root.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..core.models import FileStat


class RootDirBackend:
    def __init__(self, working_dir: str | Path):
        # Public constructor takes `working_dir` for legacy compatibility;
        # internally it is stored as a private root. All path resolution
        # and sandbox enforcement use self._root.
        self._root = Path(working_dir).resolve()
        self._opened = False

    # --- lifecycle --------------------------------------------------------

    def open(self) -> None:
        if not self._root.exists():
            raise RuntimeError(f"working_dir не существует: {self._root}")
        if not self._root.is_dir():
            raise RuntimeError(f"working_dir не директория: {self._root}")
        self._opened = True

    def close(self) -> None:
        self._opened = False

    def is_alive(self) -> bool:
        return self._opened

    # --- helpers ----------------------------------------------------------

    def _resolve(self, path: str) -> Path:
        """Resolve a relative path against working_dir and enforce sandbox.

        Lexical containment check only: `os.path.normpath` collapses `..`
        and `.` without touching the filesystem. `Path.resolve()` was a
        syscall per path component and dominated `read()` on large scans
        (~3.8x slower than a raw open). The root is resolved once in
        `__init__`, so a lexically-clean join stays inside it.

        Known limit: a symlink *inside* the root that points outside is
        not detected here (that needed `resolve()`). Acceptable for a
        local tool reading the user's own tree; revisit if roots ever
        hold untrusted symlinks.
        """
        p = Path(path)
        target = p if p.is_absolute() else (self._root / p)
        norm = os.path.normpath(str(target))
        root_s = str(self._root)
        if norm != root_s and not norm.startswith(root_s + os.sep):
            raise PermissionError(f"Путь вне проекта: {path}")
        return Path(norm)

    @staticmethod
    def _count_lines(text: str) -> int:
        if not text:
            return 0
        n = text.count("\n")
        if not text.endswith("\n"):
            n += 1
        return n

    def resolve_physical(self, path: str) -> Path | None:
        """Best-effort local Path for `path`; None on sandbox violation."""
        try:
            return self._resolve(path)
        except PermissionError:
            return None

    # --- data -------------------------------------------------------------

    def read(self, path: str) -> str:
        with self._resolve(path).open("r", encoding="utf-8", newline="") as f:
            return f.read()

    def read_head(self, path: str, max_bytes: int = 8192) -> bytes:
        """Read the first `max_bytes` bytes without decoding.

        Used for binary detection before the full read. Never raises on
        invalid UTF-8; the caller decides what to do with the bytes.
        """
        with self._resolve(path).open("rb") as f:
            return f.read(max_bytes)

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
        # Fast path for the common `glob="*"`: os.walk skips the per-entry
        # `Path.is_file()` stat that rglob does, which cost ~1.7 s on a
        # 32k-file tree. Non-trivial globs keep the rglob path.
        if glob == "*":
            out: list[str] = []
            root_s = str(self._root)
            for dirpath, _dirnames, filenames in os.walk(base):
                for name in filenames:
                    full = os.path.join(dirpath, name)
                    out.append(os.path.relpath(full, root_s).replace("\\", "/"))
            out.sort()
            return out
        out = []
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

    def copy_to(self, src_rel: str, other: "RootDirBackend",
                dst_rel: str) -> None:
        """Copy a file into another RootDirBackend's root.

        Used by MultiRootFsBackend to support cross-root copies without
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

    def filter_check(self, path: str, op: str) -> tuple[str, str] | None:
        """No path-level policy at the FS level.

        In the new model, RootDirBackend is used as a sub-backend of
        MultiRootFsBackend. Path policy is a Workspace concern (per-root,
        per-path PathPolicy), enforced in MultiRootFsBackend.filter_check.
        When RootDirBackend is driven directly (tests, ad-hoc tools),
        there is no policy to consult — return None.

        Sandbox enforcement (path must be inside the root) still happens
        in `_resolve`, called by every read/write method.
        """
        return None

    def is_hidden(self, rel: str) -> bool:
        """No `.patchignore` at the FS level — visibility is a workspace concern."""
        return False

    def hidden_predicate(self):
        """No visibility rules at this level; see MultiRootFsBackend."""
        return lambda rel: False


