"""MultiDomainBackend -- routes operations across multiple backends by path.

Motivating case: one Session that edits both local docs/Python (Filesystem)
and Roblox code (MCP). Path domains are disjoint by construction:

    - DataModel paths start with a Roblox service name:
      ReplicatedStorage.X.Y, ServerScriptService.Services.CraftService, ...
    - Filesystem paths look like file paths: toolkit/core/models.py, docs/README.md

Routing rule is unambiguous. The two backends have different semantics for
filter_check (FS = filesystem paths relative to working_dir; MCP = dotted
DataModel paths), so this class simply delegates to whichever sub-backend
owns the path.

List(root) is also routed by root: FS list('') lists the project dir;
MCP list('ReplicatedStorage') lists modules under that service. This lets
the same rebuild_* tools work against a composite without change.
"""
from __future__ import annotations

import threading
import time

from ..core.errors import BackendUnavailable
from ..core.paths import is_mcp_path


# Standard Roblox DataModel services. Any path whose first dotted segment is
# one of these is treated as an MCP path.


class MultiDomainBackend:
    """Routes each operation to the sub-backend that owns the path.

    Constructor takes (name, backend) pairs. The two standard
    configurations are ('fs', RootDirBackend) and ('mcp', MCPBackend),
    but any pair is accepted for testing.
    """
    def __init__(self, pairs):
        self._pairs = list(pairs)
        self._open_failures: list[tuple[str, Exception]] = []
        self._state: dict[str, str] = {name: "not_started" for name, _ in self._pairs}
        self._state_lock = threading.Lock()

    # --- routing -----------------------------------------------------------

    def _owner(self, path: str):
        want_mcp = is_mcp_path(path)
        for name, backend in self._pairs:
            if name == "mcp" and want_mcp:
                self._require_ready("mcp")
                return name, backend
            if name == "fs" and not want_mcp:
                self._require_ready("fs")
                return name, backend
        return None, None

    def _require_ready(self, name: str) -> None:
        st = self.backend_state(name)
        if st != "ready":
            raise BackendUnavailable(name, st)

    def _owner_for_root(self, root: str):
        # Same rule as for paths, but the root may be "" (project dir).
        if not root:
            for name, backend in self._pairs:
                if name == "fs":
                    self._require_ready("fs")
                    return name, backend
            return None, None
        return self._owner(root)

    # --- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        """Open every sub-backend. Only raise if *none* came up.

        A composite with a live filesystem and a dead MCP is still usable
        for filesystem operations. Per-backend readiness is visible via
        `backend_state(name)`; a patch that actually touches the dead
        backend will fail with `backend_not_ready` from `_require_ready`.

        Mirrors the degraded-composite semantics of `is_alive()`.
        """
        self._open_failures = []
        for name, backend in self._pairs:
            self._set_state(name, "starting")
            try:
                backend.open()
                self._set_state(name, "ready")
            except Exception as e:
                self._open_failures.append((name, e))
                self._set_state(name, f"failed: {e}")
        ready = [n for n, _ in self._pairs if self.backend_state(n) == "ready"]
        if not ready and self._open_failures:
            names = ", ".join(n for n, _ in self._open_failures)
            first_err = self._open_failures[0][1]
            raise RuntimeError(
                f"composite open failed for [{names}]: {first_err}"
            )

    def open_async(self) -> None:
        """Non-blocking open: filesystem sync, other sub-backends in a thread.

        Returns immediately and never raises. Readiness is observable via
        backend_state() / backend_state_all(); wait_ready(timeout) blocks
        until every sub-backend is terminal (ready or failed).
        """
        self._open_failures = []
        for name, backend in self._pairs:
            self._set_state(name, "starting")
            if name == "fs":
                try:
                    backend.open()
                    self._set_state(name, "ready")
                except Exception as e:
                    self._open_failures.append((name, e))
                    self._set_state(name, f"failed: {e}")
            else:
                threading.Thread(
                    target=self._open_one_bg, args=(name, backend), daemon=True
                ).start()

    def _open_one_bg(self, name: str, backend) -> None:
        try:
            backend.open()
            self._set_state(name, "ready")
        except Exception as e:
            self._open_failures.append((name, e))
            self._set_state(name, f"failed: {e}")

    def reopen(self, name: str) -> None:
        """Close and reopen one sub-backend in the background.

        Never raises. FS backends are left alone; the intended use is
        recovering the MCP (Roblox) connection without restarting the GUI.
        State transitions are observable via backend_state().
        """
        target = None
        for n, b in self._pairs:
            if n == name:
                target = b
                break
        if target is None:
            return
        threading.Thread(
            target=self._reopen_bg, args=(name, target), daemon=True
        ).start()

    def _reopen_bg(self, name: str, backend) -> None:
        self._set_state(name, "starting")
        try:
            backend.close()
        except Exception:
            pass
        try:
            backend.open()
            self._set_state(name, "ready")
        except Exception as e:
            self._open_failures.append((name, e))
            self._set_state(name, f"failed: {e}")

    # --- state ------------------------------------------------------------

    def _set_state(self, name: str, value: str) -> None:
        with self._state_lock:
            self._state[name] = value

    def backend_state(self, name: str) -> str:
        """Per-backend readiness, cached state overlaid with a live check.

        The cache records the intent (`starting` / `ready` / `failed: ...`),
        but it is only updated on open/close/reopen. If a sub-backend dies on
        its own, the cache would keep reporting `ready`. To prevent that, we
        probe `sub.is_alive()` and downgrade a stale `ready` to
        `failed: not alive`. Any other cached value is returned as-is.
        """
        with self._state_lock:
            cached = self._state.get(name, "not_started")
        if cached != "ready":
            return cached
        for n, sub in self._pairs:
            if n != name:
                continue
            try:
                alive = sub.is_alive()
            except Exception:
                alive = False
            if not alive:
                return "failed: not alive"
            break
        return cached

    def backend_state_all(self) -> dict[str, str]:
        """Per-backend readiness for every sub-backend, live-checked.

        Same overlay as `backend_state`, applied to all pairs in one pass.
        """
        with self._state_lock:
            cached = dict(self._state)
        out: dict[str, str] = {}
        for n, sub in self._pairs:
            value = cached.get(n, "not_started")
            if value == "ready":
                try:
                    alive = sub.is_alive()
                except Exception:
                    alive = False
                if not alive:
                    value = "failed: not alive"
            out[n] = value
        return out

    def wait_ready(self, timeout: float | None = None) -> bool:
        """Block until every sub-backend is ready or failed.

        Returns True if all are ready, False if any failed or timeout hit.
        """
        deadline = (time.time() + timeout) if timeout else None
        while True:
            states = self.backend_state_all()
            if all(s == "ready" or s.startswith("failed")
                   for s in states.values()):
                return all(s == "ready" for s in states.values())
            if deadline is not None and time.time() >= deadline:
                return False
            time.sleep(0.1)

    def close(self) -> None:
        for _name, backend in self._pairs:
            try:
                backend.close()
            except Exception:
                pass

    def is_alive(self) -> bool:
        """Alive if at least one sub-backend is ready.

        A degraded composite (MCP down, FS up) is still usable for ops
        owned by live backends. Per-backend readiness is observable via
        `backend_state(name)`; this answers only "should apply_patches
        be attempted at all".
        """
        return any(
            self.backend_state(name) == "ready" for name, _ in self._pairs
        )

    # --- bulk read ---------------------------------------------------------

    def read_many(self, paths, batch_size: int = 8) -> dict:
        """Group paths by owner backend, delegate read_many (or per-path read)
        to each. Needed so that composite does not fall back to per-path reads
        on 260+ DataModel modules -- that path is 5x slower than batching."""
        groups: dict = {}
        for p in paths:
            name, backend = self._owner(p)
            if backend is None:
                continue
            bucket = groups.setdefault(name, {"backend": backend, "paths": []})
            bucket["paths"].append(p)

        result: dict = {}
        for _name, grp in groups.items():
            b = grp["backend"]
            bucket_paths = grp["paths"]
            if hasattr(b, "read_many"):
                try:
                    chunk = b.read_many(bucket_paths, batch_size=batch_size)
                    result.update(chunk)
                    continue
                except Exception:
                    pass
            for p in bucket_paths:
                try:
                    result[p] = b.read(p)
                except Exception:
                    continue
        return result

    # --- data --------------------------------------------------------------

    def read(self, path: str) -> str:
        name, backend = self._owner(path)
        if backend is None:
            raise FileNotFoundError(f"no backend owns path {path!r}")
        return backend.read(path)

    def read_head(self, path: str, max_bytes: int = 8192) -> bytes:
        name, backend = self._owner(path)
        if backend is None:
            raise FileNotFoundError(f"no backend owns path {path!r}")
        fn = getattr(backend, "read_head", None)
        if not callable(fn):
            return b""
        return fn(path, max_bytes)

    def write(self, path: str, content: str) -> None:
        name, backend = self._owner(path)
        if backend is None:
            raise FileNotFoundError(f"no backend owns path {path!r}")
        backend.write(path, content)

    def exists(self, path: str) -> bool:
        name, backend = self._owner(path)
        if backend is None:
            return False
        return backend.exists(path)

    def stat(self, path: str):
        name, backend = self._owner(path)
        if backend is None:
            raise FileNotFoundError(f"no backend owns path {path!r}")
        return backend.stat(path)

    def list(self, root: str = "", glob: str = "*") -> list[str]:
        name, backend = self._owner_for_root(root)
        if backend is None:
            return []
        return backend.list(root, glob)

    def grep_mcp(self, root: str, pattern: str, *, fixed_strings: bool = False,
                 ignore_case: bool = False, word_boundary: bool = False,
                 max_results: int = 200,
                 before: int = 0, after: int = 0) -> str:
        """Delegate Lua grep to the MCP sub-backend.

        Only MCPBackend has grep_mcp (it runs a script inside Studio).
        Raises RuntimeError if the MCP backend is absent or not ready.
        """
        for name, backend in self._pairs:
            if name == "mcp":
                self._require_ready("mcp")
                fn = getattr(backend, "grep_mcp", None)
                if not callable(fn):
                    raise RuntimeError("mcp backend does not support grep_mcp")
                return fn(
                    root=root, pattern=pattern,
                    fixed_strings=fixed_strings, ignore_case=ignore_case,
                    word_boundary=word_boundary,
                    max_results=max_results, before=before, after=after,
                )
        raise RuntimeError("grep_mcp requires an MCP backend")

    def grep_replace_mcp(self, root: str, pattern=None, *,
                         replacement=None,
                         mappings=None,
                         fixed_strings: bool = False,
                         ignore_case: bool = False,
                         word_boundary: bool = False,
                         max_replacements: int = 1000,
                         dry_run: bool = True) -> str:
        """Delegate Lua grep-replace to the MCP sub-backend.

        Only MCPBackend has grep_replace_mcp. Raises RuntimeError if the MCP
        backend is absent or not ready.
        """
        for name, backend in self._pairs:
            if name == "mcp":
                self._require_ready("mcp")
                fn = getattr(backend, "grep_replace_mcp", None)
                if not callable(fn):
                    raise RuntimeError("mcp backend does not support grep_replace_mcp")
                return fn(
                    root=root, pattern=pattern, replacement=replacement,
                    mappings=mappings, fixed_strings=fixed_strings,
                    ignore_case=ignore_case, word_boundary=word_boundary,
                    max_replacements=max_replacements, dry_run=dry_run,
                )
        raise RuntimeError("grep_replace_mcp requires an MCP backend")


    def list_with_stat(self, root: str = "", glob: str = "*") -> list[tuple[str, int, int]]:
        """Like `list`, but each row carries (path, size_bytes, lines).

        Routes to whichever sub-backend owns the root. Backends without a
        native list_with_stat fall back to list + stat per file.
        """
        name, backend = self._owner_for_root(root)
        if backend is None:
            return []
        fn = getattr(backend, "list_with_stat", None)
        if callable(fn):
            return fn(root, glob)
        out: list[tuple[str, int, int]] = []
        for p in backend.list(root, glob):
            try:
                st = backend.stat(p)
                out.append((p, st.size_bytes, st.lines))
            except Exception:
                out.append((p, 0, 0))
        return out


    def create(self, path: str, content: str, class_name: str = "ModuleScript") -> None:
        """Create a file/script at `path`. Routes to the owning sub-backend.

        MCPBackend has a dedicated create (via multi_edit); RootDirBackend
        falls back to write. Cross-domain create (e.g. into an MCP folder
        with a filesystem path) is rejected by routing: the owner is one.
        """
        name, backend = self._owner(path)
        if backend is None:
            raise FileNotFoundError(f"no backend owns path {path!r}")
        fn = getattr(backend, "create", None)
        if callable(fn):
            fn(path, content, class_name=class_name)
        else:
            backend.write(path, content)

    def delete(self, path: str) -> None:
        name, backend = self._owner(path)
        if backend is None:
            raise FileNotFoundError(f"no backend owns path {path!r}")
        backend.delete(path)

    def move(self, src: str, dst: str) -> None:
        src_owner = self._owner(src)
        dst_owner = self._owner(dst)
        if src_owner[1] is None or dst_owner[1] is None:
            raise FileNotFoundError(f"move: no backend for {src!r} -> {dst!r}")
        if src_owner[0] != dst_owner[0]:
            raise RuntimeError(
                f"move across backends ({src_owner[0]} -> {dst_owner[0]}) is not supported"
            )
        src_owner[1].move(src, dst)

    def copy(self, src: str, dst: str) -> None:
        """Route a byte-exact copy to the backend that owns src.

        Cross-backend copies are not supported: a file in the filesystem and a
        script in the Roblox DataModel have incompatible storage models.
        """
        src_owner = self._owner(src)
        dst_owner = self._owner(dst)
        if src_owner[1] is None or dst_owner[1] is None:
            raise FileNotFoundError(f"copy: no backend for {src!r} -> {dst!r}")
        if src_owner[0] != dst_owner[0]:
            raise NotImplementedError(
                f"copy across backends ({src_owner[0]} -> {dst_owner[0]}) is not supported"
            )
        src_owner[1].copy(src, dst)

    # --- physical path ----------------------------------------------------

    def resolve_physical(self, path: str):
        """Physical Path for `path`, or None.

        Delegates to the sub-backend that owns the path. MCP paths
        (Service.X.Y) are not physical files -- they return None so the
        caller falls back to its non-FS resolution path.
        """
        name, backend = self._owner(path)
        if backend is None:
            return None
        fn = getattr(backend, "resolve_physical", None)
        if not callable(fn):
            return None
        try:
            return fn(path)
        except Exception:
            return None

    # --- filter ------------------------------------------------------------

    def filter_check(self, path: str, op: str) -> tuple[str, str] | None:
        name, backend = self._owner(path)
        if backend is None:
            return None
        return backend.filter_check(path, op)

    def is_hidden(self, rel: str) -> bool:
        """Delegate visibility to the owning sub-backend.

        FS backends consult `.patchignore`; MCP has no such file and
        returns False. Unknown owner -> False (do not hide silently).
        """
        name, backend = self._owner(rel)
        if backend is None:
            return False
        fn = getattr(backend, "is_hidden", None)
        if not callable(fn):
            return False
        try:
            return fn(rel)
        except Exception:
            return False

    def hidden_predicate(self):
        """Preload visibility from the FS sub-backend (MCP has none)."""
        for name, backend in self._pairs:
            if name != "fs":
                continue
            fn = getattr(backend, "hidden_predicate", None)
            if callable(fn):
                try:
                    return fn()
                except Exception:
                    break
        return lambda rel: False

    def invoke_native(self, name: str, args: dict):
        """Delegate to the MCP sub-backend, if present and ready.

        Returns None when there is no MCP sub-backend (filesystem-only mode),
        so the caller can fall back to "unknown action".
        """
        for n, b in self._pairs:
            if n == "mcp":
                self._require_ready("mcp")
                fn = getattr(b, "invoke_native", None)
                if callable(fn):
                    return fn(name, args)
                return None
        return None

    def execute(self, code: str, datamodel_type: str = "Edit") -> str:
        """Delegate `execute_luau` to the MCP sub-backend.

        Composite has no own Luau runtime; `indexers.lua_runner` reaches
        through this method into Studio. Mirrors `invoke_native` routing.
        """
        for n, b in self._pairs:
            if n == "mcp":
                self._require_ready("mcp")
                return b.execute(code, datamodel_type)
        raise BackendUnavailable("no mcp sub-backend for execute()")

    # --- introspection -----------------------------------------------------

    def enabled(self) -> list[str]:
        return [name for name, _ in self._pairs]

    @property
    def working_dir(self):
        for name, backend in self._pairs:
            if name == "fs":
                return getattr(backend, "_root", None) or getattr(backend, "working_dir", None)
        return None
