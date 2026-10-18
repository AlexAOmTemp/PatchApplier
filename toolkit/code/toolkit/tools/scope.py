"""LLM-managed scope tools: exclude / include / set / clear / get.

Scope is a soft presentation filter. Files stay indexed and readable;
review tools hide results by default unless the caller passes
`scoped=false` or names the path explicitly. The file lives at
`.patch_applier/llmscope` and is read/written through the backend so
it works for any workspace root.

Every rule carries a mandatory reason (`pattern  # reason`). Tools that
add rules require `reason=` and refuse to append without it.
"""
from __future__ import annotations

from typing import Any

from ..core.backend import Backend
from ..core.models import Result
from ..config import llmscope


SCOPE_PATH = ".patch_applier/llmscope"


def read_scope(backend: Backend) -> tuple[llmscope.Scope, str | None]:
    """Return (scope, error). Error is set when read/parse failed."""
    try:
        if not backend.exists(SCOPE_PATH):
            return llmscope.Scope(), None
        text = backend.read(SCOPE_PATH)
    except Exception as e:
        return llmscope.Scope(), f"read failed: {e}"
    try:
        return llmscope.Scope(llmscope.parse(text)), None
    except llmscope.ScopeParseError as e:
        return llmscope.Scope(), f"parse failed: {e}"


def write_scope(backend: Backend, scope: llmscope.Scope) -> str | None:
    try:
        backend.write(SCOPE_PATH, llmscope.serialize(scope))
    except Exception as e:
        return f"write failed: {e}"
    return None


def _format_scope(scope: llmscope.Scope) -> str:
    if not scope.rules:
        return "(empty — see everything)"
    lines = []
    for r in scope.rules:
        prefix = "!" if r.negated else ""
        lines.append(f"  {prefix}{r.glob}  # {r.reason}")
    return "\n".join(lines)


class GetScopeTool:
    name = "get_scope"
    op = "read"

    def execute(self, backend: Backend, **_: Any) -> Result:
        scope, err = read_scope(backend)
        if err:
            return Result(status="error", message=err,
                          error_code="scope_read_failed", action="get_scope")
        if scope.is_empty:
            return Result(status="ok", message="scope: (empty — see everything)",
                          action="get_scope")
        body = _format_scope(scope)
        return Result(status="ok", message=f"scope: {len(scope.rules)} rule(s)\n{body}",
                      action="get_scope")


class ExcludeTool:
    """Append exclude rules. Requires `patterns` (list) and `reason` (str)."""
    name = "exclude"
    op = "write"

    def execute(self, backend: Backend, patterns: list[str] | str | None = None,
                reason: str | None = None, **_: Any) -> Result:
        if not patterns:
            return Result(status="error", message="`patterns` is required",
                          error_code="bad_options", action="exclude")
        if isinstance(patterns, str):
            patterns = [patterns]
        if not reason or not reason.strip():
            return Result(status="error",
                          message="`reason` is required (brief explanation of why)",
                          error_code="reason_required", action="exclude")
        scope, err = read_scope(backend)
        if err:
            return Result(status="error", message=err,
                          error_code="scope_read_failed", action="exclude")
        added = 0
        for pat in patterns:
            pat = (pat or "").strip().strip("/")
            if not pat:
                continue
            scope.rules.append(llmscope.Rule(glob=pat, reason=reason.strip(),
                                             negated=False))
            added += 1
        werr = write_scope(backend, scope)
        if werr:
            return Result(status="error", message=werr,
                          error_code="scope_write_failed", action="exclude")
        return Result(status="ok",
                      message=f"excluded {added} pattern(s); scope now {len(scope.rules)} rule(s)",
                      action="exclude")


class IncludeTool:
    """Append re-inclusion rules (writes `!pattern  # reason`)."""
    name = "include"
    op = "write"

    def execute(self, backend: Backend, patterns: list[str] | str | None = None,
                reason: str | None = None, **_: Any) -> Result:
        if not patterns:
            return Result(status="error", message="`patterns` is required",
                          error_code="bad_options", action="include")
        if isinstance(patterns, str):
            patterns = [patterns]
        if not reason or not reason.strip():
            return Result(status="error",
                          message="`reason` is required (brief explanation of why)",
                          error_code="reason_required", action="include")
        scope, err = read_scope(backend)
        if err:
            return Result(status="error", message=err,
                          error_code="scope_read_failed", action="include")
        added = 0
        for pat in patterns:
            pat = (pat or "").strip().strip("/")
            if pat.startswith("!"):
                pat = pat[1:].strip()
            if not pat:
                continue
            scope.rules.append(llmscope.Rule(glob=pat, reason=reason.strip(),
                                             negated=True))
            added += 1
        werr = write_scope(backend, scope)
        if werr:
            return Result(status="error", message=werr,
                          error_code="scope_write_failed", action="include")
        return Result(status="ok",
                      message=f"included {added} pattern(s); scope now {len(scope.rules)} rule(s)",
                      action="include")


class SetScopeTool:
    """Replace the whole scope from raw text. Validates before writing."""
    name = "set_scope"
    op = "write"

    def execute(self, backend: Backend, text: str | None = None, **_: Any) -> Result:
        if text is None:
            return Result(status="error", message="`text` is required",
                          error_code="bad_options", action="set_scope")
        try:
            rules = llmscope.parse(text)
        except llmscope.ScopeParseError as e:
            return Result(status="error", message=str(e),
                          error_code="scope_parse_error", action="set_scope")
        scope = llmscope.Scope(rules)
        werr = write_scope(backend, scope)
        if werr:
            return Result(status="error", message=werr,
                          error_code="scope_write_failed", action="set_scope")
        return Result(status="ok",
                      message=f"scope set: {len(scope.rules)} rule(s)",
                      action="set_scope")


class ClearScopeTool:
    """Write an empty scope (= see everything)."""
    name = "clear_scope"
    op = "write"

    def execute(self, backend: Backend, **_: Any) -> Result:
        werr = write_scope(backend, llmscope.Scope())
        if werr:
            return Result(status="error", message=werr,
                          error_code="scope_write_failed", action="clear_scope")
        return Result(status="ok", message="scope cleared (see everything)",
                      action="clear_scope")
