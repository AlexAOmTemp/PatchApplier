"""Backend implementations: filesystem, mcp, composite, workspace."""

from .filesystem import FilesystemBackend
from .mcp import MCPBackend
from .composite import CompositeBackend
from .workspace import WorkspaceBackend

__all__ = [
    "FilesystemBackend",
    "MCPBackend",
    "CompositeBackend",
    "WorkspaceBackend",
]
