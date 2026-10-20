"""Backend protocol.

The only transport contract Tools know about. Two implementations planned:
  - RootDirBackend (this release)
  - MCPBackend (next)

Sandbox and whitelist checks live here, not in Tools. Each Backend interprets
`FilterSpec.paths` in its own domain (relative paths vs DataModel roots).
"""
from __future__ import annotations

from typing import Protocol

from .models import FileStat


class Backend(Protocol):
    # --- lifecycle --------------------------------------------------------

    def open(self) -> None:
        """Acquire resources (spawn subprocess, handshake). No-op for FS."""
        ...

    def close(self) -> None:
        """Release resources. Idempotent. No-op for FS."""
        ...

    def is_alive(self) -> bool:
        """True if the backend is ready to serve requests."""
        ...

    # --- data -------------------------------------------------------------

    def read(self, path: str) -> str:
        """Read full text. Raises on failure."""
        ...

    def read_head(self, path: str, max_bytes: int = 8192) -> bytes:
        """Read the first `max_bytes` bytes without decoding.

        Used for binary detection before the full read (grep scan,
        read_file on a binary target). Never raises on invalid UTF-8.
        """
        ...

    def write(self, path: str, content: str) -> None:
        """Write text. Creates parent directories if needed."""
        ...

    def exists(self, path: str) -> bool:
        ...

    def stat(self, path: str) -> FileStat:
        ...

    def list(self, root: str = "", glob: str = "*") -> list[str]:
        """Recursive listing. Paths are relative to the backend root."""
        ...

    def delete(self, path: str) -> None:
        ...

    def move(self, src: str, dst: str) -> None:
        ...

    def copy(self, src: str, dst: str) -> None:
        """Byte-exact copy. Preserves the source. Raises on failure."""
        ...

    # --- filter -----------------------------------------------------------

    def filter_check(self, path: str, op: str) -> tuple[str, str] | None:
        """None = ok. Otherwise (error_code, message).

        `op` selects which policy flag to consult: read, write, or one
        of the index flags (index_docs / index_py / index_lua).

        error_code distinguishes the reason for blocking:
          "hidden_path" — matched .patchignore or a dot-dir default;
          "filter"      — denied by per-path policy, or unknown root.
        The two had no distinguishing signal before; the GUI/LLM saw
        only `■ blocked` and could not tell which rule fired.
        """
        ...

    def is_hidden(self, rel: str) -> bool:
        """Soft visibility filter for scan tools (`.patchignore`).

        Not consulted by address access (`read` / `stat`): naming a path
        explicitly is the caller's consent. Scan tools (tree / list_files /
        survey_dir / grep / index rebuild) use this to skip hidden entries.
        """
        ...

    def hidden_predicate(self):
        """Preloaded `is_hidden` for loops: one stat, then fnmatch per path."""
        ...
