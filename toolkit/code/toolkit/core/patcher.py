"""Patcher — dispatch, filter, aggregate.

Stateless. Receives Backend, Format, tool registry, and a Policy.
Returns list[Result] and prints an action log.

The Patcher does NOT know which Tools exist — the registry is passed in
by the runner. This keeps core/ free of imports from tools/.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from . import metrics
from .backend import Backend
from .errors import BackendUnavailable
from .models import Result
from .tool import Tool


# Marker glyphs include Unicode. Guard against narrow stdout encodings
# (e.g. Windows cp1251) by falling back to plain ASCII when the glyph
# cannot be encoded.
_GLYPH_CANDIDATES = {
    "ok": ("\u2713", "OK"),
    "error": ("\u2717", "X"),
    "skipped": ("\u2013", "-"),
    "blocked": ("\u25a0", "#"),
}


def _pick_glyph(unicode_glyph: str, ascii_fallback: str) -> str:
    enc = (getattr(sys.stdout, "encoding", None) or "utf-8")
    try:
        unicode_glyph.encode(enc)
        return unicode_glyph
    except (UnicodeEncodeError, LookupError):
        return ascii_fallback


STATUS_MARKER = {
    k: _pick_glyph(g, f) for k, (g, f) in _GLYPH_CANDIDATES.items()
}
RESULT_PREFIX = "##RESULT:"


def _format_id(value) -> str:
    """Render the patch `id` for display in the log.

    Strings print bare, scalars via json.dumps, None as `null`. The value
    is not validated — the parser only requires the `id` key to be present.
    """
    if value is None:
        return "null"
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


class Patcher:
    def _pre_validate_ranges(self, patches: list[dict]) -> dict[int, tuple[str, str]]:
        """Pre-validate replace_range actions across the patch.

        Returns {idx: (error_code, message)} for actions that must be
        rejected before applying. `idx` is 1-based, matching apply().

        Rules (patch-order is the whole point):
          * A replace_range may not follow another write to the same file
            (its line numbers would have shifted).
          * Multiple replace_ranges on one file must go bottom-up
            (strictly decreasing start_line) -- each edit then sits
            below the ones already applied and its numbers stay valid.
          * Other write tools MAY follow replace_range on the same file:
            they match by content, not by position, so they stay correct.

        Paths come from `path_args` / `path_list_args` of the tool class.
        `run_python` and native actions declare no paths and are not
        tracked -- combining them with replace_range in one patch is
        the caller's responsibility.
        """
        errors: dict[int, tuple[str, str]] = {}
        writes_seen: set[str] = set()
        last_range_start: dict[str, int] = {}

        for idx, patch in enumerate(patches, start=1):
            action = patch.get("action")
            args = patch.get("arguments")
            if not action or not isinstance(args, dict):
                continue
            tool_cls = self.tools.get(action)
            if tool_cls is None:
                continue
            op = getattr(tool_cls, "op", "write")
            if op != "write":
                continue

            paths: list[str] = []
            for key in getattr(tool_cls, "path_args", []) or []:
                v = args.get(key)
                if isinstance(v, str) and v:
                    paths.append(v)
            for key in getattr(tool_cls, "path_list_args", []) or []:
                v = args.get(key)
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, str) and item:
                            paths.append(item)

            if action == "replace_range":
                fp = args.get("file_path")
                if not isinstance(fp, str) or not fp:
                    continue  # the tool itself reports the missing path
                if fp in writes_seen:
                    errors[idx] = (
                        "range_after_write",
                        f"replace_range on {fp!r} follows another write to "
                        f"the same file in this patch; line numbers may have "
                        f"shifted. Put replace_range before other writes on "
                        f"this file, or use replace_in_file / replace_unit.",
                    )
                    continue
                try:
                    start = int(args.get("start_line"))
                except (TypeError, ValueError):
                    continue  # the tool reports the bad range itself
                prev = last_range_start.get(fp)
                if prev is not None and start >= prev:
                    errors[idx] = (
                        "range_order",
                        f"replace_range on {fp!r} at L{start} follows L{prev}; "
                        f"multiple ranges on one file must go bottom-up "
                        f"(strictly decreasing start_line) so line numbers "
                        f"stay valid after each edit.",
                    )
                    continue
                last_range_start[fp] = start
            else:
                for fp in paths:
                    writes_seen.add(fp)

        return errors
    def __init__(
        self,
        backend: Backend,
        fmt: Any,
        tools: dict[str, type[Tool]],
    ):
        self.backend = backend
        self.fmt = fmt
        self.tools = tools

    # --- public ------------------------------------------------------------

    def apply(self, patches: list[dict]) -> list[Result]:
        results: list[Result] = []
        pre_errors = self._pre_validate_ranges(patches)
        for idx, patch in enumerate(patches, start=1):
            if idx in pre_errors:
                action = patch.get("action", "?")
                code, msg = pre_errors[idx]
                r = Result(status="error", message=msg,
                           action=action, error_code=code)
            else:
                r = self._apply_one(idx, patch)
            if r.id_label is None and "id" in patch:
                r.id_label = _format_id(patch["id"])
            results.append(r)
            metrics.bump(
                r.action or patch.get("action", "?"),
                r.status,
                r.error_code,
            )
        return results

    def print_log(self, results: list[Result]) -> None:
        for idx, r in enumerate(results, start=1):
            if idx > 1:
                print()
            marker = STATUS_MARKER.get(r.status, "?")
            action = r.action or "?"
            label = r.id_label if r.id_label is not None else str(idx)
            print(f"[{label}] {marker} {action}: {r.message}")

    def print_diagnostics(self, diagnostics) -> None:
        """Render compiler-style messages from the patch parser.

        Each diagnostic is a Diagnostic dataclass (see core.patchparse):
        kind, line, column, message, fragment. Fragment is not printed —
        the position is enough, and the LLM can look at its own patch text.
        """
        if not diagnostics:
            return
        print()
        print("=== Compiler messages ===")
        for d in diagnostics:
            loc = f"line {d.line}, col {d.column}"
            print(f"  {loc:20s} {d.kind}: {d.message}")

    def result_marker(self, results: list[Result], diagnostics=None) -> str:
        """Structured marker for GUI consumers.

        Shape mirrors the legacy format (lists of ids, not counts, for
        failed/blocked). When parser diagnostics are supplied, they are
        embedded as `diagnostics` — a flat list of {kind, line, column, message}.
        """
        ok = sum(1 for r in results if r.status == "ok")
        err = sum(1 for r in results if r.status == "error")
        skipped = sum(1 for r in results if r.status == "skipped")
        failed_ids = [i for i, r in enumerate(results, 1) if r.status == "error"]
        blocked_ids = [i for i, r in enumerate(results, 1) if r.status == "blocked"]
        payload = {
            "ok": ok,
            "errors": err,
            "skipped": skipped,
            "failed": failed_ids,
            "blocked": blocked_ids,
        }
        if diagnostics:
            payload["diagnostics"] = [
                {"kind": d.kind, "line": d.line, "column": d.column,
                 "message": d.message}
                for d in diagnostics
            ]
        return RESULT_PREFIX + json.dumps(payload, ensure_ascii=False)

    # --- internal ----------------------------------------------------------

    def _apply_one(self, idx: int, patch: dict) -> Result:
        action = patch.get("action")
        args = patch.get("arguments")
        if not action or not isinstance(args, dict):
            return Result(
                status="skipped",
                message="\u043d\u0443\u0436\u043d\u044b 'action' \u0438 'arguments'",
                action=action or "?",
            )

        tool_cls = self.tools.get(action)
        if tool_cls is None:
            native = getattr(self.backend, "invoke_native", None)
            if callable(native):
                try:
                    r = native(action, dict(args))
                except Exception as e:
                    return Result(
                        status="error",
                        message=f"{type(e).__name__}: {e}",
                        action=action,
                        error_code="native_error",
                    )
                if r is not None:
                    return r
            return Result(
                status="skipped",
                message="\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u043e\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435",
                action=action,
            )

        bad = self._validate_args(tool_cls, args, action)
        if bad is not None:
            return bad

        op = getattr(tool_cls, "op", "write")

        # For op in ("index_docs", "index_py", "index_lua") path_args typically
        # point at a directory. Individual files are filtered later by the
        # indexer via backend.filter_check(path, op).
        if not op.startswith("index"):
            block = self._filter_paths(tool_cls, args, op)
            if block is not None:
                code, msg = block
                return Result(status="blocked", message=msg, action=action,
                              error_code=code)

        try:
            from .tool_call import call_tool
            return call_tool(tool_cls, self.backend, self.fmt, **dict(args))
        except PermissionError as e:
            return Result(status="blocked", message=str(e), action=action,
                          error_code="sandbox")
        except FileNotFoundError as e:
            return Result(status="error", message=f"\u0424\u0430\u0439\u043b \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d: {e}",
                          action=action, error_code="not_found")
        except BackendUnavailable as e:
            return Result(status="error",
                          message=f"Backend {e.name!r} \u043d\u0435 \u0433\u043e\u0442\u043e\u0432: {e.state}",
                          action=action,
                          error_code="backend_not_ready")
        except Exception as e:
            return Result(status="error",
                          message=f"\u0418\u0421\u041a\u041b\u042e\u0427\u0415\u041d\u0418\u0415: {type(e).__name__}: {e}",
                          action=action)

    def _validate_args(self, tool_cls: type[Tool], args: dict,
                       action: str) -> Result | None:
        from .tool_call import validate_args
        return validate_args(tool_cls, args, action)

    def _filter_paths(self, tool_cls: type[Tool], args: dict,
                      op: str) -> tuple[str, str] | None:
        force = bool(args.get("force"))
        for key in getattr(tool_cls, "path_args", []) or []:
            val = args.get(key)
            if isinstance(val, str) and val:
                err = self.backend.filter_check(val, op)
                if err:
                    if force and err[0] == "hidden_path":
                        continue
                    return err
        for key in getattr(tool_cls, "path_list_args", []) or []:
            val = args.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item:
                        err = self.backend.filter_check(item, op)
                        if err:
                            if force and err[0] == "hidden_path":
                                continue
                            return err
        return None
