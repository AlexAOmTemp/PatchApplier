"""Apply a patch through a Session, with planned index rebuilds.

Pure logic: no GUI, no pyperclip, no LAST_PATCH file, no msg_queue.
Callers (GUI worker, CLI) own persistence and side-effects. Progress
notifications are delivered via an optional ``notify(kind, payload)``
callback, so the same kernel runs headless.

Not to be confused with ``runner/cli.py`` — that is the CLI entry point.
This module is the shared apply kernel both entry points can call.
"""
from __future__ import annotations

import io
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.patchparse import parse_patches
from ..core.router import plan_rebuilds

Notify = Callable[[str, object], None]

_AUTO_LABEL = {
    "rebuild_index": "auto-md",
    "rebuild_code_index": "auto-py",
    "rebuild_lua_code_index": "auto-lua",
}


@dataclass
class ApplyOutcome:
    """Result of one apply_patch() run.

    success     — True iff no result had status="error".
    output_text — cleaned log + merged ##RESULT + [timing] total.
    diff_block  — concatenated .message of successful rebuild_* results,
                  or "" if none.
    merged      — merged ##RESULT dict, or None if no structs were seen.
    elapsed     — wall time in seconds.
    all_results — flat list of Result objects, in execution order.
    """

    success: bool
    output_text: str
    diff_block: str
    merged: dict | None
    elapsed: float
    all_results: list = field(default_factory=list)


class ApplyError(Exception):
    """Early-exit condition: empty patch, unparsable text, backend mismatch.

    The caller (GUI worker, CLI) translates this into whatever UX it uses;
    patch_runner does not know about status messages.
    """


# -- notification ---------------------------------------------------------


def _emit(notify: Notify | None, kind: str, payload: object) -> None:
    if notify is None:
        return
    try:
        notify(kind, payload)
    except Exception:
        # Notification is best-effort; never abort an apply because of it.
        pass


# -- result merging -------------------------------------------------------


def _merge_structs(structs: list[dict]) -> dict | None:
    """Merge per-group ##RESULT dicts into one, renumbering ids across groups."""
    if not structs:
        return None
    merged = {"ok": 0, "errors": 0, "skipped": 0, "failed": [], "blocked": []}
    offset = 0
    for st in structs:
        merged["ok"] += st.get("ok", 0)
        merged["errors"] += st.get("errors", 0)
        merged["skipped"] += st.get("skipped", 0)
        merged["failed"].extend([offset + x for x in st.get("failed", [])])
        merged["blocked"].extend([offset + x for x in st.get("blocked", [])])
        offset += st.get("ok", 0) + st.get("errors", 0) + st.get("skipped", 0)
    return merged


# -- accumulator ----------------------------------------------------------


class _Accumulator:
    """Collects clean lines, results and structs across apply_groups."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.results: list = []
        self.structs: list[dict] = []

    def group(self, session: Any, patches: list,
              label: str, diagnostics=None) -> list:
        """Apply one group with stdout captured; return the new Result slice."""
        before = len(self.results)
        old_stdout = sys.stdout
        buf = io.StringIO()
        t0 = time.time()
        try:
            sys.stdout = buf
            res = session.apply_patches(patches, diagnostics=diagnostics)
        finally:
            sys.stdout = old_stdout
        elapsed = time.time() - t0
        raw = buf.getvalue()
        struct = None
        group_lines: list[str] = []
        for line in raw.splitlines():
            if line.startswith("##RESULT:"):
                try:
                    struct = json.loads(line[len("##RESULT:"):])
                except Exception:
                    struct = None
                continue  # merged at the very end
            group_lines.append(line)
        # Drop the blank Session prints before ##RESULT so [timing] hugs the
        # last action line instead of floating after an empty one.
        while group_lines and not group_lines[-1]:
            group_lines.pop()
        group_lines.append(f"[timing] {label}: {elapsed:.2f}s")
        if self.lines:
            self.lines.append("")
        self.lines.extend(group_lines)
        self.results.extend(res)
        if struct is not None:
            self.structs.append(struct)
        return self.results[before:]


# -- main -----------------------------------------------------------------


def apply_patch(
    session: Any,
    raw_text: str,
    *,
    config: dict,
    tool_map: dict,
    backend_name: str | None = None,
    notify: Notify | None = None,
) -> ApplyOutcome:
    """Parse ``raw_text``, apply it, plan and run index rebuilds, return outcome.

    Raises ApplyError for early-exit conditions (empty patch, unparsable
    text). Domain errors stay inside individual Result objects and surface
    in ``output_text`` / ``merged`` rather than raising.

    The caller is responsible for: writing the patch to disk beforehand,
    picking it up after, updating clipboards, storing last_* files, and
    deciding how to render the outcome.
    """
    parsed = parse_patches(raw_text)
    user_patches = parsed.actions
    if not user_patches:
        raise ApplyError("empty patch")

    active_backend = backend_name or config.get("backend", "filesystem")
    supports_fs = active_backend in ("filesystem", "composite")
    supports_mcp = active_backend in ("mcp", "composite")

    t_total0 = time.time()
    acc = _Accumulator()

    n_user = len(user_patches)
    _emit(notify, "status", f"\u23f3 \u041f\u0430\u0442\u0447 \u043f\u0440\u0438\u043c\u0435\u043d\u044f\u0435\u0442\u0441\u044f ({n_user} actions)...")
    res_user = acc.group(
        session, user_patches,
        f"user ({n_user} actions)",
        diagnostics=parsed.diagnostics,
    )

    auto_groups = plan_rebuilds(
        user_patches, res_user, tool_map,
        config=config,
        supports_fs=supports_fs, supports_mcp=supports_mcp,
    )

    if auto_groups:
        auto_patches = []
        for _label, patch in auto_groups:
            p = dict(patch)
            action = p.get("action", "")
            p["id"] = _AUTO_LABEL.get(action, "auto")
            auto_patches.append(p)
        _emit(notify, "status",
              f"\u23f3 \u0410\u0432\u0442\u043e-\u043f\u0435\u0440\u0435\u0441\u0431\u043e\u0440\u043a\u0430 \u0438\u043d\u0434\u0435\u043a\u0441\u043e\u0432 ({len(auto_patches)})...")
        acc.group(session, auto_patches,
                  f"auto-rebuild ({len(auto_patches)} actions)")

    merged = _merge_structs(acc.structs)
    if merged is not None:
        acc.lines.append("")
        acc.lines.append(f"##RESULT:{json.dumps(merged, ensure_ascii=False)}")

    t_total = time.time() - t_total0
    output_text = "\n".join(acc.lines).rstrip()
    output_text += f"\n[timing] total: {t_total:.2f}s"

    diff_block = "\n\n".join(
        r.message for r in acc.results
        if (r.action or "").startswith("rebuild_") and r.status == "ok"
    )

    err_count = sum(1 for r in acc.results if r.status == "error")
    success = (err_count == 0)

    _emit(notify, "status",
          f"\u2713 \u0413\u043e\u0442\u043e\u0432\u043e ({len(acc.results)} actions, {t_total:.1f}s) \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0432 \u0431\u0443\u0444\u0435\u0440\u0435")

    return ApplyOutcome(
        success=success,
        output_text=output_text,
        diff_block=diff_block,
        merged=merged,
        elapsed=t_total,
        all_results=acc.results,
    )
