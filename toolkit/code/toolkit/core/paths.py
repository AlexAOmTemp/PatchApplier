"""Path classification for the composite backend and the rebuild router.

A path is either a filesystem path (contains a separator) or a Roblox
DataModel path (dotted, starting with a service name). The set of service
names is fixed by Roblox itself.
"""
from __future__ import annotations


# Standard Roblox DataModel services. Any path whose first dotted segment
# is one of these is treated as an MCP path.
ROBLOX_SERVICES = frozenset({
    "ReplicatedStorage",
    "ReplicatedFirst",
    "ServerScriptService",
    "ServerStorage",
    "StarterPlayer",
    "StarterGui",
    "Workspace",
    "Players",
    "Lighting",
    "Teams",
    "SoundService",
    "Chat",
    "CoreGui",
    "RobloxGui",
    "TestService",
})


def is_mcp_path(path: str) -> bool:
    """True if `path` looks like a Roblox DataModel path.

    Filesystem paths almost always contain a slash. DataModel paths are
    dotted. Both signals are used: a path with no slash whose first dotted
    segment is a known service is treated as MCP.
    """
    if not path:
        return False
    if "/" in path or "\\" in path:
        return False
    first = path.split(".", 1)[0]
    return first in ROBLOX_SERVICES


def normalize_path(path: str) -> str:
    """Normalize a path for backend routing.

    If it starts with a Roblox service name and uses slashes, convert
    slashes to dots (ReplicatedStorage/Shared -> ReplicatedStorage.Shared).
    Otherwise return as-is: filesystem paths and already-dotted paths are
    untouched.
    """
    if not path or "/" not in path:
        return path
    first = path.split("/", 1)[0]
    if first in ROBLOX_SERVICES:
        return path.replace("/", ".")
    return path
