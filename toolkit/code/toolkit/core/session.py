"""Session — lifecycle wrapper over Backend + Patcher.

CLI usage:
    with Session(backend, fmt, tools, policy) as s:
        s.apply_patches(patches)

GUI/persistent usage (MCP):
    session = Session(...)
    session.__enter__()
    # ... session.apply_patches(...) on every button press
    session.__exit__(None, None, None)  # on shutdown
"""
from __future__ import annotations

from typing import Any

from .backend import Backend
from .models import Policy, Result
from .patcher import Patcher
from .tool import Tool


class Session:
    def __init__(
        self,
        backend: Backend,
        fmt: Any,
        tools: dict[str, type[Tool]],
        policy: Policy | None = None,
    ):
        self.backend = backend
        self.fmt = fmt
        self.tools = tools
        self.policy = policy or Policy()
        self.patcher = Patcher(backend, fmt, tools, self.policy)

    def __enter__(self) -> "Session":
        self.backend.open()
        return self

    def open_async(self) -> "Session":
        """Non-blocking variant of __enter__.

        CompositeBackend opens the filesystem synchronously and any remote
        backend in a background thread, so the session is immediately
        usable for filesystem operations. Backends without open_async fall
        back to the blocking open().
        """
        fn = getattr(self.backend, "open_async", None)
        if callable(fn):
            fn()
        else:
            self.backend.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.backend.close()

    def is_alive(self) -> bool:
        return self.backend.is_alive()

    def apply_patches(self, patches: list[dict], diagnostics=None) -> list[Result]:
        results = self.patcher.apply(patches)
        self.patcher.print_log(results)
        self.patcher.print_diagnostics(diagnostics or [])
        print()
        print(self.patcher.result_marker(results, diagnostics=diagnostics))
        return results
