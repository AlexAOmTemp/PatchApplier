"""Single entry point for invoking a Tool.

`Patcher` is not the only caller: `status.py` calls `TreeTool`, symbol
sub-tools delegate to sibling tools, presenters call `GetStatusTool`.
Before this module each of those did `ToolCls().execute(**args)` directly,
which bypassed argument validation — a typo like `max_dirs=` after it was
renamed to `max_lines=` fell into `**_` and the tool silently ran with a
default instead. That exact bug degraded `get_status.layout` for several
sessions and only surfaced by accident.

`call_tool` applies the same validation `Patcher` uses and strips
patcher-level args (`force`) that are consumed before the call, not by
the tool itself.
"""
from __future__ import annotations

import inspect
from typing import Any

from .backend import Backend
from .models import Result
from .tool import Tool


# Args the caller (Patcher) consumes itself; not declared on tool.execute.
PATCHER_ARGS = frozenset({"force"})

_SELF_HANDLED = {"self", "backend", "fmt"}


def validate_args(tool_cls: type[Tool], args: dict,
                  action: str) -> Result | None:
    """Reject unknown and missing arguments with an explicit list.

    The message carries the full valid set, so the caller does not need a
    second round-trip to the docs. A tool that declares only `**_` (none
    currently) is skipped: there is nothing to validate against.
    """
    try:
        sig = inspect.signature(tool_cls.execute)
    except (TypeError, ValueError):
        return None
    valid: list[str] = []
    required: list[str] = []
    for name, p in sig.parameters.items():
        if name in _SELF_HANDLED:
            continue
        if p.kind in (inspect.Parameter.VAR_KEYWORD,
                      inspect.Parameter.VAR_POSITIONAL):
            continue
        valid.append(name)
        if p.default is inspect.Parameter.empty:
            required.append(name)
    if not valid:
        return None
    valid_sorted = sorted(set(valid) | PATCHER_ARGS)
    unknown = sorted(set(args) - set(valid) - PATCHER_ARGS)
    if unknown:
        return Result(
            status="error", action=action, error_code="unknown_arg",
            message=(f"unknown argument(s): {', '.join(unknown)}; "
                     f"valid for {action}: {', '.join(valid_sorted)}"),
        )
    missing = [r for r in required if r not in args]
    if missing:
        return Result(
            status="error", action=action, error_code="missing_arg",
            message=(f"required argument(s) not given: {', '.join(missing)}; "
                     f"valid for {action}: {', '.join(valid_sorted)}"),
        )
    return None


def call_tool(tool_cls: type[Tool], backend: Backend,
              fmt: Any = None, **args) -> Result:
    """Validate `args` against `tool_cls.execute` and invoke it.

    `force` is accepted in `args` (the Patcher reads it in `_filter_paths`
    before this call) but stripped here — no tool declares it.
    """
    bad = validate_args(tool_cls, args, getattr(tool_cls, "name", "?"))
    if bad is not None:
        return bad
    clean = {k: v for k, v in args.items() if k not in PATCHER_ARGS}
    return tool_cls().execute(backend=backend, fmt=fmt, **clean)
