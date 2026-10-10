"""Backend implementations: filesystem, mcp, composite."""

from .filesystem import FilesystemBackend
from .mcp import MCPBackend
from .composite import CompositeBackend

__all__ = ["FilesystemBackend", "MCPBackend", "CompositeBackend"]
