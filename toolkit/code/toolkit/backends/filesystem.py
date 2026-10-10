"""Filesystem backend — reads/writes local files under a working directory.

All paths are relative to working_dir. Sandbox enforcement: any path that
resolves outside working_dir is rejected before I/O.

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
from ..core.models import FileStat, FilterSpec


def _explicitly_allowed(spec: FilterSpec, rel_str: str) -> bool:
    """True if `spec.overrides` has an explicit True for the path or one
    of its named ancestors.

    The root (`.`) is deliberately ignored: it is an ancestor of every
    path, so treating `.'=True` as "everything allowed" would disable the
    .patchignore rule for the entire tree. Only named intermediate paths
    count — e.g. `.patch_applier=True` opens `.patch_applier/...` without
    opening `.git/...`.
    """
    ov = (spec.overrides if spec is not None else None) or {}
    parts = rel_str.split("/")
    for i in range(len(parts), 0, -1):
        prefix = "/".join(parts[:i])
        if prefix == ".":
            continue
        if prefix in ov and ov[prefix] is True:
            return True
    return False


class FilesystemBackend:
    def __init__(self, working_dir: str | Path):
        self.working_dir = Path(working_dir).resolve()
        self._opened = False
        # Populated on `open()` — empty until then means nothing hidden.
        self._patterns: list[tuple[str, bool]] = []

    # --- lifecycle --------------------------------------------------------

    def open(self) -> None:
        if not self.working_dir.exists():
            raise RuntimeError(f"working_dir не существует: {self.working_dir}")
        if not self.working_dir.is_dir():
            raise RuntimeError(f"working_dir не директория: {self.working_dir}")
        patchignore.ensure_default(self.working_dir)
        self._patterns = patchignore.read(self.working_dir)
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
        self._patterns = patchignore.read(self.working_dir)

    # --- helpers ----------------------------------------------------------

    def _resolve(self, path: str) -> Path:
        """Resolve a relative path against working_dir and enforce sandbox."""
        target = (self.working_dir / path).resolve()
        try:
            target.relative_to(self.working_dir)
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
        base = self._resolve(root) if root else self.working_dir
        if not base.exists():
            return []
        out: list[str] = []
        for p in sorted(base.rglob(glob)):
            if not p.is_file():
                continue
            try:
                out.append(str(p.relative_to(self.working_dir)).replace("\\", "/"))
            except ValueError:
                continue
        return out

    def list_with_stat(self, root: str = "", glob: str = "*") -> list[tuple[str, int, int]]:
        """Like `list`, but returns (path, size_bytes, lines) per file.

        Reads contents to count lines; non-decodable files fall back to 0
        lines. Order matches `list` (sorted).
        """
        base = self._resolve(root) if root else self.working_dir
        if not base.exists():
            return []
        rows: list[tuple[str, int, int]] = []
        for p in sorted(base.rglob(glob)):
            if not p.is_file():
                continue
            try:
                rel = str(p.relative_to(self.working_dir)).replace("\\", "/")
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

    def copy(self, src: str, dst: str) -> None:
        """Byte-exact copy (shutil.copy2 preserves metadata). Works on any file."""
        s = self._resolve(src)
        d = self._resolve(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)

    # --- filter -----------------------------------------------------------

    def filter_check(self, path: str, spec: FilterSpec) -> str | None:
        try:
            target = self._resolve(path)
            rel = target.relative_to(self.working_dir)
        except (PermissionError, ValueError):
            return f"Путь вне проекта: {path}"
        rel_str = str(rel).replace("\\", "/")

        # Service dir (`.patch_applier`) is hardcoded: the toolkit's own
        # state. Always accessible for R/W so index / MCP tools can reach
        # their files, regardless of policy or .patchignore. The tree shows
        # it with fixed R+/W+/I- cells.
        if patchignore.is_state_path(rel_str):
            return None

        # Hidden by .patchignore: blocked before the policy is consulted,
        # unless the caller added an explicit True override for the path or
        # one of its named ancestors. That is how the user opens a specific
        # hidden dir from the tree without touching the pattern file.
        if patchignore.path_hidden(rel_str, self._patterns) and not _explicitly_allowed(spec, rel_str):
            return f"Скрытая папка: {path}"

        if spec.resolve(rel_str):
            return None
        return f"Запрещено политикой: {path}"
