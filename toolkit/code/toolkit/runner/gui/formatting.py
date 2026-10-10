"""Pure formatting helpers for the GUI. No Tk, no widgets.

Everything here maps structured data (Result lists, result markers,
patch text) into strings that the View can display. Safe to call from
any thread. Imported by presenters and by app.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from .state import LAST_OUTPUT, LAST_DIFF


def normalize_patch(text: str) -> str:
    if not text:
        return ""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
    try:
        data = json.loads(t)
        return json.dumps(data, sort_keys=True, ensure_ascii=False)
    except Exception:
        return t


def output_looks_successful(returncode: int, result_struct) -> bool:
    if returncode != 0 or result_struct is None:
        return False
    return result_struct.get("errors", 0) == 0


def save_last_output(text: str) -> None:
    try:
        LAST_OUTPUT.write_text(text, encoding="utf-8")
    except Exception:
        pass


def save_last_diff(text: str) -> None:
    """Persist only the diff block from the most recent rebuild."""
    try:
        LAST_DIFF.write_text(text, encoding="utf-8")
    except Exception:
        pass


def load_last_state() -> tuple[str | None, str | None]:
    """Return (last_applied_patch_norm, last_output_text) from disk.

    The caller assigns them to module-level state; keeping this pure (no
    global writes) avoids a circular import with state.py.
    """
    norm = None
    out = None
    from .state import LAST_PATCH
    if LAST_PATCH.exists():
        try:
            raw = LAST_PATCH.read_text(encoding="utf-8")
            if raw.strip():
                norm = normalize_patch(raw)
        except Exception:
            pass
    if LAST_OUTPUT.exists():
        try:
            out = LAST_OUTPUT.read_text(encoding="utf-8")
        except Exception:
            pass
    return norm, out


def status_from_result(result_struct, output_len: int, returncode: int) -> str:
    """Short neutral status line."""
    if returncode != 0:
        return "\u2717 \u041e\u0448\u0438\u0431\u043a\u0430 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f"
    if result_struct is None:
        return f"\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0432 \u0431\u0443\u0444\u0435\u0440\u0435 ({output_len} \u0441\u0438\u043c\u0432.)"
    err = result_struct.get("errors", 0)
    skip = result_struct.get("skipped", 0)
    if err:
        return f"\u041f\u0440\u0438\u043c\u0435\u043d\u0435\u043d\u043e \u0441 \u043e\u0448\u0438\u0431\u043a\u0430\u043c\u0438 ({output_len} \u0441\u0438\u043c\u0432.)"
    if skip:
        return f"\u2713 \u041f\u0440\u0438\u043c\u0435\u043d\u0435\u043d\u043e ({output_len} \u0441\u0438\u043c\u0432., \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e {skip})"
    return f"\u2713 \u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0432 \u0431\u0443\u0444\u0435\u0440\u0435 ({output_len} \u0441\u0438\u043c\u0432.)"


def error_from_result(result_struct, output_text=None, returncode=0) -> str:
    """Error line for a separate field. Empty when there is nothing to show.

    Three categories:
    - \u26a0 item error  — the patch did not apply (not found, etc.).
    - \U0001f6ab forbidden path in item(s) — sandbox/whitelist rejection.
    - \U0001f6ab script error — patch did not parse or crashed before
      the summary marker.
    """
    if result_struct is None:
        if returncode != 0:
            text = output_text or ""
            if ("\u041e\u0448\u0438\u0431\u043a\u0430 \u0447\u0442\u0435\u043d\u0438\u044f/\u043f\u0430\u0440\u0441\u0438\u043d\u0433\u0430" in text
                    or "JSONDecodeError" in text
                    or "Expecting value" in text):
                return "\U0001f6ab \u0422\u0435\u043a\u0441\u0442 \u0432 \u0431\u0443\u0444\u0435\u0440\u0435 \u043d\u0435 \u044f\u0432\u043b\u044f\u0435\u0442\u0441\u044f \u043f\u0430\u0442\u0447\u0435\u043c"
            return "\U0001f6ab \u041e\u0448\u0438\u0431\u043a\u0430 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f \u0441\u043a\u0440\u0438\u043f\u0442\u0430. \u041f\u043e\u0434\u0440\u043e\u0431\u043d\u043e\u0441\u0442\u0438 \u0432 \u0431\u0443\u0444\u0435\u0440\u0435"
        return ""

    lines = []

    failed = result_struct.get("failed", [])
    if failed:
        shown = ", ".join(str(x) for x in failed[:5])
        if len(failed) > 5:
            shown += ", ..."
        if len(failed) == 1:
            lines.append(f"\u26a0 \u041e\u0448\u0438\u0431\u043a\u0430 \u0432 \u043f\u0443\u043d\u043a\u0442\u0435: {shown}")
        else:
            lines.append(f"\u26a0 \u041e\u0448\u0438\u0431\u043a\u0438 \u0432 \u043f\u0443\u043d\u043a\u0442\u0430\u0445: {shown}")

    blocked = result_struct.get("blocked", [])
    if blocked:
        shown = ", ".join(str(x) for x in blocked[:5])
        if len(blocked) > 5:
            shown += ", ..."
        if len(blocked) == 1:
            lines.append(f"\U0001f6ab \u0417\u0430\u043f\u0440\u0435\u0449\u0451\u043d\u043d\u044b\u0439 \u043f\u0443\u0442\u044c \u0432 \u043f\u0443\u043d\u043a\u0442\u0435: {shown}")
        else:
            lines.append(f"\U0001f6ab \u0417\u0430\u043f\u0440\u0435\u0449\u0451\u043d\u043d\u044b\u0435 \u043f\u0443\u0442\u0438 \u0432 \u043f\u0443\u043d\u043a\u0442\u0430\u0445: {shown}")

    if not lines and result_struct.get("skipped"):
        lines.append(f"\u26a0 \u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e: {result_struct['skipped']}")

    return "\n".join(lines)
