"""Shared exceptions used across core, backends, and runner."""
from __future__ import annotations


class BackendUnavailable(RuntimeError):
    """A backend that owns the requested path is not ready.

    Raised when an operation targets a path whose owning sub-backend is
    still starting up (asynchronous open) or has failed to open. Callers
    that only touch filesystem paths never see this when the filesystem
    backend is ready.
    """

    def __init__(self, name: str, state: str):
        super().__init__(f"backend {name!r} not ready: {state}")
        self.name = name
        self.state = state
