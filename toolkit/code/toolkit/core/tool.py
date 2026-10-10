"""Tool protocol.

Every action is a class implementing this. Tools are stateless — they receive
Backend and Format as arguments, return a Result. They never touch sandbox,
whitelist, session, or GUI directly.

Optional class attributes:
    op: "read" | "write" | "index"  — which Policy slot applies. Default "write".
    path_args: list[str]             — kwargs keys that hold single paths,
                                       checked against Policy[op].
    path_list_args: list[str]        — kwargs keys that hold path lists.
"""
from __future__ import annotations

from typing import Any, Protocol

from .backend import Backend
from .models import Result


class Tool(Protocol):
    name: str
    op: str
    path_args: list[str]
    path_list_args: list[str]

    def execute(self, backend: Backend, fmt: Any, **kwargs) -> Result:
        """Run the action. `fmt` is a Format instance (may be unused by
        some Tools — e.g. raw file operations).
        """
        ...
