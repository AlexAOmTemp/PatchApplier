import keyboard
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import sys
import threading
import queue
import json
import re
from pathlib import Path
import pyperclip
import os
import traceback

from ...config import loader as _cfg
from ..patch_runner import apply_patch as _apply_patch, ApplyError as _ApplyError
from ..presenters import main as _presenter

from .. import projects as _projects
from ...core.patchparse import parse_patches
from ...core.router import plan_rebuilds
from ...tools import TOOL_MAP

from . import state as _state
from .clipboard_watch import ClipboardWatcher
from .state import (
    HERE, RUNNER_DIR, TOOLKIT_ROOT, PROJECT_ROOT,
    LAST_PATCH, LAST_OUTPUT, LAST_DIFF,
    HOTKEY, BUTTON_STATE_REFRESH_MS,
    WIDTH_LEFT, WIDTH_RIGHT, WIDTH_TOGGLE, WINDOW_H,
    COLLAPSED_W, EXPANDED_W, MONO_FONT,
)
from .formatting import (
    normalize_patch, output_looks_successful,
    save_last_output as _save_last_output,
    save_last_diff as _save_last_diff,
    status_from_result as _status_from_result,
    error_from_result as _error_from_result,
)

# Note: `_load_last_state` stays local — it mutates `last_applied_patch_norm`
# and `last_output_text` in this module's namespace, and the formatting
# helper returns a tuple instead (different contract, kept separate).

from .starter_text import (
    docs_dir as _docs_dir,
    scan_langs as _scan_starter_langs,
    read_text as _read_starter_text,
)
from ..views.widgets import StatusLog as _StatusLog



last_applied_patch_norm = None
last_output_text = None
is_executing = False
# True from session start until the init index rebuilds finish. The
# project may already be configured (PROJECT_OK) while the session and
# its indexes are still coming up; the readiness dot must stay yellow
# for that whole window, not turn green on config alone.
is_initializing = False
# Monotonic token: each session start bumps it. _initialize_project echoes
# the token it was started with, and poll_queue ignores a stale init_done
# (one arriving after a newer session start). Without it, a slow init from
# project A would clear the yellow dot of a freshly started project B.
_init_gen = 0
_last_mcp_ready = False
_last_mcp_state: str = ""

CONFIG = {}
PROJECT_OK = False

mcp_status_var = None
status_label = None


# Clipboard watcher instance (Ctrl+Alt auto-run). Created in run(), stopped
# after mainloop returns. None until then, and None when the feature is off.
clipboard_watcher = None

# Tk widgets are created in run(); placeholders let the helpers below
# run before run() reaches the assignment without a NameError.
ready_light = None
auto_run_on_copy_var = None


def update_ready_light() -> None:
    """Refresh the big readiness dot. No-op before the widget exists."""
    if ready_light is None:
        return
    if is_executing or is_initializing:
        ready_light.set_state("busy")
    elif PROJECT_OK:
        ready_light.set_state("ready")
    else:
        ready_light.set_state("off")







def _load_last_state():
    """Восстанавливает last_applied_patch_norm и last_output_text из файлов."""
    global last_applied_patch_norm, last_output_text
    if LAST_PATCH.exists():
        try:
            raw = LAST_PATCH.read_text(encoding="utf-8")
            if raw.strip():
                last_applied_patch_norm = normalize_patch(raw)
        except Exception:
            pass
    if LAST_OUTPUT.exists():
        try:
            last_output_text = LAST_OUTPUT.read_text(encoding="utf-8")
        except Exception:
            pass





def _project_state():
    return _presenter.project_state(CONFIG)


def _validate_project() -> bool:
    global PROJECT_OK
    PROJECT_OK = _presenter.project_ok(CONFIG)
    return PROJECT_OK




def _initialize_project(gen: int = 0):
    try:
        with _state._session_lock:
            s = _state._session
            bn = _state._session_backend_name or CONFIG.get("backend", "filesystem")
        if s is None:
            _state.msg_queue.put(("status", "\u26a0 Session \u043d\u0435 \u0433\u043e\u0442\u043e\u0432\u0430"))
            return
        patches = _presenter.plan_init_patches(CONFIG, bn)
        if not patches:
            _state.msg_queue.put(("status", "\u2139 \u041d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u0438\u043d\u0434\u0435\u043a\u0441\u043e\u0432"))
            return
        import io as _io
        old_stdout = sys.stdout
        buf = _io.StringIO()
        try:
            sys.stdout = buf
            results = s.apply_patches(patches)
        finally:
            sys.stdout = old_stdout
        _diff_block = "\n\n".join(
            r.message for r in results
            if (r.action or "").startswith("rebuild_") and r.status == "ok"
        )
        if _diff_block:
            _save_last_diff(_diff_block)
        ok = all(r.status == "ok" for r in results)
        _state.msg_queue.put(("status", "\u2713 \u041f\u0440\u043e\u0435\u043a\u0442 \u0438\u043d\u0438\u0446\u0438\u0430\u043b\u0438\u0437\u0438\u0440\u043e\u0432\u0430\u043d" if ok else "\u2717 \u041e\u0448\u0438\u0431\u043a\u0430 \u0438\u043d\u0438\u0446\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u0438"))
    except Exception as e:
        _state.msg_queue.put(("status", f"\u2717 \u041e\u0448\u0438\u0431\u043a\u0430 \u0438\u043d\u0438\u0446\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u0438: {e}"))
    finally:
        # Every exit path -- success, no indexes, failure -- must clear the
        # initializing flag, or the dot stays yellow forever. The generation
        # lets poll_queue drop a stale completion from a previous session.
        _state.msg_queue.put(("init_done", gen))


def worker(patch_text: str, normalized_patch: str):
    try:
        LAST_PATCH.write_text(patch_text, encoding="utf-8")
        _state.msg_queue.put(("status", "\u2713 \u0411\u0443\u0444\u0435\u0440 \u2192 " + LAST_PATCH.name))

        with _state._session_lock:
            s = _state._session
            bn = _state._session_backend_name
        if s is None:
            _state.msg_queue.put(("status", "\u2717 Session \u043d\u0435 \u0433\u043e\u0442\u043e\u0432\u0430"))
            return

        try:
            _raw = LAST_PATCH.read_text(encoding="utf-8")
        except Exception as e:
            err_text = f"PATCH READ ERROR: {e}"
            try:
                pyperclip.copy(err_text)
            except Exception:
                pass
            _save_last_output(err_text)
            _state.msg_queue.put(("status", "\u2717 \u041f\u0430\u0442\u0447 \u043d\u0435 \u043f\u0440\u043e\u0447\u0438\u0442\u0430\u043d"))
            _state.msg_queue.put(("error_text", err_text))
            return

        def _notify(kind, payload):
            _state.msg_queue.put((kind, payload))

        try:
            outcome = _apply_patch(
                s, _raw,
                config=CONFIG,
                tool_map=TOOL_MAP,
                backend_name=bn,
                notify=_notify,
            )
        except _ApplyError as e:
            _state.msg_queue.put(("status", f"\u2717 {e}"))
            return

        if outcome.diff_block:
            _save_last_diff(outcome.diff_block)

        pyperclip.copy(outcome.output_text)
        _save_last_output(outcome.output_text)

        _state.msg_queue.put(("applied", (normalized_patch, outcome.output_text, outcome.success)))

        if outcome.merged is not None:
            _state.msg_queue.put(("error_text", _error_from_result(outcome.merged, outcome.output_text, 0)))
        else:
            _state.msg_queue.put(("error_text", ""))
    except Exception as e:
        _state.msg_queue.put(("status", f"\u2717 {e}"))
        print(traceback.format_exc(), file=sys.stderr)
    finally:
        _state.msg_queue.put(("done", None))


def _run_patch(patch_text: str):
    """Общий запуск патча. Сброс состояния и thread."""
    global is_executing
    normalized = normalize_patch(patch_text)
    is_executing = True
    btn.config(state="disabled")
    repeat_btn.config(state="disabled")
    status_var.set("\u23f3 \u0412\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f...")
    status_var.set_state("")
    update_ready_light()
    t = threading.Thread(target=worker, args=(patch_text, normalized), daemon=True)
    t.start()
    root.after(100, poll_queue)


def _try_run_patch_text(patch_text: str) -> None:
    """Shared path for button, hotkey, and clipboard auto-run.

    Checks for a duplicate, empties the clipboard *before* starting the
    worker, then runs the patch. The clipboard is cleared so the user
    cannot paste a stale patch while this one is still being applied;
    ``worker`` writes the result back on completion.

    The caller is responsible for ``is_executing`` and project checks.
    """
    global is_executing
    normalized = normalize_patch(patch_text)
    is_dup = (last_applied_patch_norm is not None
              and normalized == last_applied_patch_norm)
    if is_dup:
        status_var.set("\u23f9 \u042d\u0442\u043e\u0442 \u043f\u0430\u0442\u0447 \u0443\u0436\u0435 \u043f\u0440\u0438\u043c\u0435\u043d\u0451\u043d. \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 \u00ab\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439\u00bb.")
        return
    try:
        pyperclip.copy("")
    except Exception:
        pass
    _run_patch(patch_text)


def _set_auto_run_enabled(enabled: bool) -> None:
    """Start or stop the Ctrl+Alt clipboard watcher.

    Called once at startup (only if the option is on) and again when the
    user toggles the checkbox. Idempotent. When disabled, no thread runs
    at all -- the feature costs nothing until it is turned on.
    """
    global clipboard_watcher
    if enabled:
        if clipboard_watcher is None:
            clipboard_watcher = ClipboardWatcher(_on_clipboard_trigger)
            clipboard_watcher.start()
    else:
        if clipboard_watcher is not None:
            try:
                clipboard_watcher.stop()
            except Exception:
                pass
            clipboard_watcher = None


def _on_clipboard_trigger(patch_text: str) -> None:
    """Called from ClipboardWatcher's worker thread.

    Marshals to the Tk thread and freezes the text: the clipboard may
    change again before the Tk callback fires, and we want to run the
    patch that was actually copied, not whatever landed afterwards.
    """
    if root is None:
        return
    try:
        root.after(0, lambda t=patch_text: _handle_clipboard_patch(t))
    except Exception:
        pass


def _handle_clipboard_patch(patch_text: str) -> None:
    """Tk-thread side of the Ctrl+Alt auto-run.

    Runs only when the option is on and the text looks like a patch
    (a JSON list). Silent on failure -- the auto-run must not spam the
    log while the user is just browsing.
    """
    if not CONFIG.get("auto_run_on_copy"):
        return
    if is_executing:
        return
    if not patch_text or not patch_text.strip():
        return
    # A patch is one fence containing one or more JSON arrays (R-FMT-1).
    # parse_patches already speaks that format and never raises; use it
    # rather than json.loads, which only accepts a single array and would
    # silently reject the canonical multi-group patch.
    try:
        parsed = parse_patches(patch_text)
    except Exception:
        return
    if not getattr(parsed, "actions", None):
        return
    if not _validate_project():
        return
    _try_run_patch_text(patch_text)


def on_button_click():
    if is_executing:
        return
    if not _validate_project():
        status_var.set("\u26a0 \u0443\u043a\u0430\u0436\u0438\u0442\u0435 \u043f\u0443\u0442\u044c \u043a \u043f\u0440\u043e\u0435\u043a\u0442\u0443")
        return
    try:
        clipboard_text = pyperclip.paste() or ""
    except Exception as e:
        status_var.set(f"\u2717 \u041d\u0435 \u043c\u043e\u0433\u0443 \u043f\u0440\u043e\u0447\u0438\u0442\u0430\u0442\u044c \u0431\u0443\u0444\u0435\u0440: {e}")
        return
    if not clipboard_text.strip():
        status_var.set("\u2717 \u0411\u0443\u0444\u0435\u0440 \u043f\u0443\u0441\u0442")
        return
    _try_run_patch_text(clipboard_text)


def on_repeat_click():
    if is_executing:
        return
    if not _validate_project():
        status_var.set("⚠ укажите путь к проекту")
        return
    if not LAST_PATCH.exists():
        status_var.set("✗ Нет last_patch.json")
        return
    try:
        patch_text = LAST_PATCH.read_text(encoding="utf-8")
    except Exception as e:
        status_var.set(f"✗ Не могу прочитать last_patch.json: {e}")
        return
    if not patch_text.strip():
        status_var.set("✗ last_patch.json пуст")
        return
    _run_patch(patch_text)


def on_get_last_patch():
    if not LAST_PATCH.exists():
        status_var.set("✗ Нет last_patch.json")
        return
    try:
        patch_text = LAST_PATCH.read_text(encoding="utf-8")
        pyperclip.copy(patch_text)
        status_var.set(f"✓ Последний патч в буфере ({len(patch_text)} симв.)")
    except Exception as e:
        status_var.set(f"✗ {e}")




def on_get_last_output():
    text = last_output_text
    if not text:
        status_var.set("✗ Нет сохранённого результата")
        return
    try:
        pyperclip.copy(text)
        status_var.set(f"✓ Последний результат в буфере ({len(text)} симв.)")
    except Exception as e:
        status_var.set(f"✗ {e}")


def on_get_last_diff():
    """Copy the diff block from the last rebuild to the clipboard."""
    if not LAST_DIFF.exists():
        status_var.set("\u2717 \u041d\u0435\u0442 \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d\u043d\u043e\u0433\u043e \u0434\u0438\u0444\u0444\u0430")
        return
    try:
        text = LAST_DIFF.read_text(encoding="utf-8")
    except Exception as e:
        status_var.set(f"\u2717 {e}")
        return
    if not text.strip():
        status_var.set("\u2717 \u0414\u0438\u0444\u0444 \u043f\u0443\u0441\u0442 (\u0438\u043d\u0434\u0435\u043a\u0441 \u043d\u0435 \u043c\u0435\u043d\u044f\u043b\u0441\u044f)")
        return
    try:
        pyperclip.copy(text)
        status_var.set(f"\u2713 \u0414\u0438\u0444\u0444 \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d ({len(text)} \u0441\u0438\u043c\u0432.)")
    except Exception as e:
        status_var.set(f"\u2717 {e}")






def on_starter_text():
    """Copy LLM starter text (with current status appended) to clipboard."""
    lang = (CONFIG.get("ui_language") or "ru").strip() or "ru"
    with _state._session_lock:
        s = _state._session
    include_roblox = bool(starter_include_roblox_var.get())
    include_xml = bool(starter_include_xml_var.get())
    from ...config.loader import toolkit_runtime_state_dir as _trsd
    try:
        full_text, used, suffix = _presenter.build_starter_text(
            lang=lang,
            session=s,
            include_roblox=include_roblox,
            include_xml=include_xml,
            docs_dir=_docs_dir(),
            runtime_state_dir=_trsd(),
            read_text_fn=_read_starter_text,
        )
    except _presenter.StarterTextError as e:
        status_var.set(str(e))
        return
    try:
        pyperclip.copy(full_text)
        status_var.set(f"\u2713 \u0421\u0442\u0430\u0440\u0442\u043e\u0432\u044b\u0439 \u0442\u0435\u043a\u0441\u0442 \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d ({used}{suffix})")
    except Exception as e:
        status_var.set(f"\u2717 {e}")


def _format_project_label():
    return _presenter.format_project_label(CONFIG)


def update_project_status():
    global PROJECT_OK
    text, color = _presenter.format_project_label(CONFIG)
    project_label.config(text=text, fg=color)
    PROJECT_OK = _presenter.project_ok(CONFIG)
    update_ready_light()


def update_button_state():
    update_ready_light()
    if is_executing:
        return
    try:
        current_raw = pyperclip.paste() or ""
    except Exception:
        current_raw = ""
    try:
        last_exists = LAST_PATCH.exists()
    except Exception:
        last_exists = False
    decision = _presenter.decide_button_state(
        project_ok=PROJECT_OK,
        last_patch_exists=last_exists,
        current_raw=current_raw,
        last_applied_norm=last_applied_patch_norm,
        last_output_text=last_output_text,
        hotkey=HOTKEY,
    )
    btn.config(state=decision.btn_state, text=decision.btn_text)
    repeat_btn.config(state=decision.repeat_state)
    status_var.set_state(decision.status_state)


def _status_visual(name: str, state: str) -> tuple[str, str]:
    """Return (text, hex_color) for one backend indicator."""
    return _presenter.status_visual(name, state)


def _backend_states(session, backend_name: str) -> dict:
    """Read per-backend readiness from a session's backend.

    Composite exposes backend_state_all(); non-composite (filesystem or
    MCP-only) falls back to a single indicator based on is_alive().
    """
    return _presenter.backend_states(session, backend_name)


def _apply_backend_states(states: dict) -> None:
    for name, var, lbl in (
        ("fs", fs_status_var, fs_status_label),
        ("mcp", mcp_status_var, mcp_status_label),
    ):
        if var is None or lbl is None:
            continue
        if name not in states:
            var.set("")
            continue
        text, color = _status_visual(name, states[name])
        var.set(text)
        try:
            lbl.configure(fg=color)
        except Exception:
            pass
    if mcp_reconnect_btn is not None:
        st = states.get("mcp")
        visible = bool(mcp_reconnect_btn.winfo_manager())
        want_visible = st is not None
        if want_visible and not visible:
            mcp_reconnect_btn.pack(side="left", padx=(6, 0))
        elif not want_visible and visible:
            mcp_reconnect_btn.pack_forget()
        if want_visible:
            mcp_reconnect_btn.configure(
                state="normal" if st.startswith("failed") else "disabled"
            )


def _check_mcp_transition(session, backend_name: str) -> None:
    """Track mcp state changes: report status, rebuild Lua index on ready.

    Status is reported regardless of `index_lua` — the user must know whether
    mcp is available even when Lua indexing is disabled. Status events fire
    only on state transitions, so the periodic poll does not spam the log.
    """
    global _last_mcp_ready, _last_mcp_state
    if session is None or backend_name not in ("mcp", "composite"):
        return
    try:
        states = _backend_states(session, backend_name)
    except Exception:
        return
    mcp_state = states.get("mcp", "")
    if mcp_state == _last_mcp_state:
        return
    _last_mcp_state = mcp_state
    is_ready = mcp_state == "ready"
    is_failed = mcp_state.startswith("failed")

    if is_ready and not _last_mcp_ready:
        if bool(CONFIG.get("index_lua", True)):
            threading.Thread(target=_rebuild_lua_after_ready, daemon=True).start()
        if backend_name == "composite":
            _state.msg_queue.put(("status", "\u2713 Session \u0433\u043e\u0442\u043e\u0432\u0430 (composite, mcp \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0451\u043d)"))
        else:
            _state.msg_queue.put(("status", "\u2713 Session \u0433\u043e\u0442\u043e\u0432\u0430 (mcp)"))
    elif is_failed:
        reason = mcp_state.split(":", 1)[1].strip() if ":" in mcp_state else mcp_state
        if len(reason) > 100:
            reason = reason[:100] + "\u2026"
        if backend_name == "composite":
            _state.msg_queue.put(("status",
                f"\u26a0 Session: fs \u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d, mcp \u043d\u0435 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0451\u043d ({reason})"))
        else:
            _state.msg_queue.put(("status", f"\u2717 Session \u043d\u0435 \u0433\u043e\u0442\u043e\u0432\u0430: mcp \u043d\u0435 \u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d ({reason})"))

    _last_mcp_ready = is_ready


def _rebuild_lua_after_ready() -> None:
    with _state._session_lock:
        s = _state._session
    if s is None:
        return
    import io as _io
    old_stdout = sys.stdout
    buf = _io.StringIO()
    try:
        sys.stdout = buf
        results = s.apply_patches(
            [{"action": "rebuild_lua_code_index", "arguments": {}}]
        )
    except Exception as e:
        sys.stdout = old_stdout
        _state.msg_queue.put(("status", f"\u2717 Lua index rebuild failed: {e}"))
        _state.msg_queue.put(("last_output", buf.getvalue()))
        return
    finally:
        sys.stdout = old_stdout
    _diff_block = "\n\n".join(
        r.message for r in results
        if (r.action or "").startswith("rebuild_") and r.status == "ok"
    )
    if _diff_block:
        _save_last_diff(_diff_block)
    _state.msg_queue.put(("last_output", buf.getvalue()))
    ok = all(r.status == "ok" for r in results)
    _state.msg_queue.put((
        "status",
        "\u2713 Lua \u0438\u043d\u0434\u0435\u043a\u0441 \u043f\u0435\u0440\u0435\u0441\u0442\u0440\u043e\u0435\u043d" if ok
        else "\u2717 Lua \u0438\u043d\u0434\u0435\u043a\u0441: \u043e\u0448\u0438\u0431\u043a\u0430",
    ))


def _on_mcp_reconnect():
    with _state._session_lock:
        s = _state._session
    if s is None:
        return
    fn = getattr(s.backend, "reopen", None)
    if callable(fn):
        fn("mcp")
        return
    # MCP-only backend: reopen inline in a background thread.
    def _do():
        try:
            s.backend.close()
        except Exception:
            pass
        try:
            s.backend.open()
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()


def poll_queue():
    global is_executing, is_initializing, last_applied_patch_norm, last_output_text
    with _state._session_lock:
        _s = _state._session
        _bn = _state._session_backend_name
    if _s is not None:
        try:
            _apply_backend_states(_backend_states(_s, _bn or ""))
        except Exception:
            pass
    _check_mcp_transition(_s, _bn or "")
    try:
        while True:
            kind, payload = _state.msg_queue.get_nowait()
            if kind == "status":
                status_var.set(payload)
            elif kind == "error_text":
                status_var.set_state(payload)
            elif kind == "applied":
                norm, out, success = payload
                last_output_text = out
                if success:
                    last_applied_patch_norm = norm
                update_button_state()
            elif kind == "last_output":
                last_output_text = payload
                update_button_state()
            elif kind == "mcp_status":
                # Legacy channel: no longer produced by the runner, kept
                # for compatibility with older messages already in queue.
                if mcp_status_var is not None:
                    mcp_status_var.set(payload)
            elif kind == "project_changed":
                update_project_status()
                update_button_state()
            elif kind == "init_done":
                if payload == _init_gen:
                    is_initializing = False
                    update_ready_light()
            elif kind == "done":
                is_executing = False
                update_button_state()
                update_ready_light()
                return
    except queue.Empty:
        pass
    root.after(100, poll_queue)


def periodic_button_state():
    update_button_state()
    root.after(BUTTON_STATE_REFRESH_MS, periodic_button_state)


# ==== Session management (persistent backend) ====

def _load_ws_or_error(project_dir):
    """Load workspace.json from a project folder; None if missing."""
    return _presenter.load_workspace_or_none(project_dir, CONFIG)


def _build_backend_for_config():
    """Build backend from current CONFIG.

    Returns (backend, name) where name is filesystem|mcp|composite.
    On failure returns (None, error_message).
    """
    try:
        return _presenter.build_backend_for_config(CONFIG)
    except _presenter.BackendError as e:
        return None, str(e)


def _start_session_in_background():
    """Close any existing session and start a new one from CONFIG.

    Reports via _state.msg_queue 'mcp_status' events. On success, assigns the global
    _state._session. Safe to call multiple times (restarts the session).
    """
    global _last_mcp_ready, _last_mcp_state, is_initializing, _init_gen
    _last_mcp_ready = False
    _last_mcp_state = ""
    _init_gen += 1
    my_gen = _init_gen
    is_initializing = True
    update_ready_light()

    def _run():
        with _state._session_lock:
            old = _state._session
            _state._session = None
        if old is not None:
            try:
                old.__exit__(None, None, None)
            except Exception:
                pass

        try:
            backend, name = _presenter.build_backend_for_config(CONFIG)
        except _presenter.BackendError as e:
            _state.msg_queue.put(("status", f"\u2717 {e}"))
            _state.msg_queue.put(("init_done", my_gen))
            return

        try:
            s = _presenter.build_session(backend, name, CONFIG)
            s.open_async()
            with _state._session_lock:
                _state._session = s
                _state._session_backend_name = name
            if name == "composite":
                _state.msg_queue.put(("status", "\u23f3 Session: fs \u0433\u043e\u0442\u043e\u0432, mcp \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0430\u0435\u0442\u0441\u044f..."))
            elif name == "mcp":
                _state.msg_queue.put(("status", "\u23f3 Session: mcp \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0430\u0435\u0442\u0441\u044f..."))
            else:
                _state.msg_queue.put(("status", "\u2713 Session \u0433\u043e\u0442\u043e\u0432\u0430 (filesystem)"))
            threading.Thread(target=_initialize_project,
                             args=(my_gen,), daemon=True).start()
        except Exception as e:
            _state.msg_queue.put(("status", f"\u2717 Session \u043d\u0435 \u0441\u0442\u0430\u0440\u0442\u043e\u0432\u0430\u043b\u0430 ({name}): {e}"))
            _state.msg_queue.put(("init_done", my_gen))

    threading.Thread(target=_run, daemon=True).start()


def _menu_project_settings() -> None:
    """Open the project settings dialog (roots + policies + name)."""
    proj = CONFIG.get("project_dir", "").strip()
    if not proj:
        messagebox.showwarning(
            "\u041d\u0435\u0442 \u043f\u0440\u043e\u0435\u043a\u0442\u0430",
            "\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043e\u0442\u043a\u0440\u043e\u0439\u0442\u0435 \u0438\u043b\u0438 \u0441\u043e\u0437\u0434\u0430\u0439\u0442\u0435 \u043f\u0440\u043e\u0435\u043a\u0442 (File).",
            parent=root,
        )
        return
    state_subdir = _cfg.resolve_state_dir(CONFIG)
    from .settings_window import open_project_settings

    def _on_settings_saved(new_name=None):
        try:
            _cfg.save(CONFIG)
        except Exception:
            pass
        _switch_project(proj, new_name)

    try:
        open_project_settings(
            parent=root,
            project_dir=Path(proj),
            state_subdir=state_subdir,
            config=CONFIG,
            on_save=_on_settings_saved,
        )
    except _projects.NotAProject:
        messagebox.showerror(
            "\u041d\u0435 \u043f\u0440\u043e\u0435\u043a\u0442",
            f"\u0412 {proj} \u043d\u0435\u0442 workspace.json",
            parent=root,
        )


def _switch_project(project_dir: str, project_name: str | None = None) -> None:
    """Activate a project folder and restart the session.

    Called from the File menu. Updates CONFIG, saves tool-wide config,
    records the folder in recent.json, then restarts Session in the
    background. If workspace.json is missing, the session will fail to
    build — that is the correct behaviour (no fallback in the new model).
    """
    p = Path(project_dir).resolve()
    # Read the target project's config BEFORE writing anything: DEFAULTS +
    # tool-wide + that project's per-project overlay. Without this step,
    # CONFIG still holds the previously-active project's settings, and
    # `save` would copy them into the new project's config.json — the
    # exact "backend/indexes leak from A into B" bug.
    try:
        fresh = _cfg.load(project_dir=p)
    except Exception:
        fresh = {}
    if fresh:
        CONFIG.update(fresh)
    CONFIG["project_dir"] = str(p)
    try:
        _cfg.save(CONFIG)
    except Exception:
        pass
    try:
        _cfg.add_recent_file(str(p), project_name or _cfg.project_display_name(CONFIG))
    except Exception:
        pass
    update_project_status()
    update_button_state()
    _refresh_recent_menu()
    _state.msg_queue.put(("status", f"\u23f3 \u041e\u0442\u043a\u0440\u044b\u0432\u0430\u044e \u043f\u0440\u043e\u0435\u043a\u0442: {CONFIG.get('project_dir') and _cfg.project_display_name(CONFIG) or p.name}..."))
    _start_session_in_background()


def _menu_new_project() -> None:
    folder = filedialog.askdirectory(title="\u041f\u0430\u043f\u043a\u0430 \u0434\u043b\u044f \u043d\u043e\u0432\u043e\u0433\u043e \u043f\u0440\u043e\u0435\u043a\u0442\u0430")
    if not folder:
        return
    state_subdir = _cfg.resolve_state_dir(CONFIG)
    if _projects.is_project(folder, state_subdir):
        if messagebox.askyesno(
                "\u041f\u0440\u043e\u0435\u043a\u0442 \u0443\u0436\u0435 \u0435\u0441\u0442\u044c",
                f"\u0412 {Path(folder).name} \u0443\u0436\u0435 \u0435\u0441\u0442\u044c workspace.json.\n"
                "\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u0435\u0433\u043e?",
                parent=root):
            _switch_project(folder)
        return
    name = simpledialog.askstring(
        "\u041d\u043e\u0432\u044b\u0439 \u043f\u0440\u043e\u0435\u043a\u0442",
        "\u0418\u043c\u044f \u043f\u0440\u043e\u0435\u043a\u0442\u0430:",
        initialvalue=Path(folder).name,
        parent=root,
    )
    if not name:
        return
    try:
        _projects.create_project(folder, name, state_subdir)
    except _projects.ProjectExists:
        messagebox.showerror(
            "\u041e\u0448\u0438\u0431\u043a\u0430",
            "\u041f\u0440\u043e\u0435\u043a\u0442 \u0443\u0436\u0435 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u0435\u0442",
            parent=root,
        )
        return
    except Exception as e:
        messagebox.showerror("\u041e\u0448\u0438\u0431\u043a\u0430", str(e), parent=root)
        return
    # New project is created but not configured: workspace.json exists,
    # but no per-project config.json yet. project_ok() reports "not
    # configured" until the user saves the settings dialog.
    #
    # Reset CONFIG completely before priming it. Without the reset, fields
    # the previous project happened to have set (index_rojo, luau_mode,
    # exec, ...) leak into this brand-new project's settings dialog — the
    # user saw "Lua files on disk" pre-checked on a fresh project because
    # CONFIG still carried index_rojo=True from whatever project was open
    # a moment ago.
    #
    # We do NOT call _switch_project here: no session should be started
    # until the user confirms a source selection. _menu_project_settings
    # calls _switch_project on save, which is what creates config.json.
    from ...config.loader import DEFAULTS as _CFG_DEFAULTS
    CONFIG.clear()
    CONFIG.update(_CFG_DEFAULTS)
    CONFIG["project_dir"] = str(Path(folder).resolve())
    CONFIG["backend"] = "filesystem"
    CONFIG["index_docs"] = False
    CONFIG["index_python"] = False
    CONFIG["index_lua"] = False
    CONFIG["index_rojo"] = False
    CONFIG["luau_mode"] = "mcp"
    update_project_status()
    update_button_state()
    _refresh_recent_menu()
    _menu_project_settings()


def _menu_open_project() -> None:
    folder = filedialog.askdirectory(title="\u041f\u0430\u043f\u043a\u0430 \u043f\u0440\u043e\u0435\u043a\u0442\u0430")
    if not folder:
        return
    state_subdir = _cfg.resolve_state_dir(CONFIG)
    if not _projects.is_project(folder, state_subdir):
        messagebox.showerror(
            "\u041d\u0435 \u043f\u0440\u043e\u0435\u043a\u0442",
            f"\u0412 {Path(folder).name} \u043d\u0435\u0442 workspace.json.\n"
            "\u0421\u043e\u0437\u0434\u0430\u0442\u044c: File \u2192 New project.",
            parent=root,
        )
        return
    _switch_project(folder)


def _menu_open_recent(path: str) -> None:
    _switch_project(path)


_recent_menu = None


def _refresh_recent_menu() -> None:
    global _recent_menu
    if _recent_menu is None:
        return
    _recent_menu.delete(0, "end")
    try:
        items = _cfg.read_recent()
    except Exception:
        items = []
    if not items:
        _recent_menu.add_command(label="(\u043f\u0443\u0441\u0442\u043e)", state="disabled")
        return
    for it in items:
        p = it["path"]
        nm = it["name"]
        exists = Path(p).is_dir()
        label = f"{nm}  \u2014  {p}" if exists else f"\u2717 {nm}  \u2014  {p}"
        if exists:
            _recent_menu.add_command(
                label=label,
                command=(lambda path=p: _menu_open_recent(path)),
            )
        else:
            _recent_menu.add_command(label=label, state="disabled")


# ==== GUI ====

def run():
    global root, btn, repeat_btn, status_var
    global starter_include_roblox_var, starter_include_xml_var
    global fs_status_var, mcp_status_var, fs_status_label, mcp_status_label
    global mcp_reconnect_btn
    global project_label, right_panel, toggle_btn
    global ready_light, auto_run_on_copy_var, clipboard_watcher
    global _recent_menu

    CONFIG.update(_cfg.load())
    try:
        from ...core import metrics as _metrics
        _proj = (CONFIG.get("project_dir") or "").rstrip("/\\")
        _metrics.set_context(Path(_proj).name if _proj else None)
    except Exception:
        pass

    _load_last_state()

    from ..views.main_window import MainWindow
    _langs = _scan_starter_langs() or ["ru"]
    _cur = (CONFIG.get("ui_language") or "ru").strip() or "ru"
    if _cur not in _langs:
        _cur = _langs[0]

    def _on_copy_project_path():
        proj_v = CONFIG.get("project_dir", "").strip()
        if not proj_v:
            return
        try:
            pyperclip.copy(proj_v)
            status_var.set(f"\u2713 \u041f\u0443\u0442\u044c \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d: {proj_v}")
        except Exception as e:
            status_var.set(f"\u2717 {e}")

    mw = MainWindow(
        config=CONFIG,
        callbacks={
            "on_button_click": on_button_click,
            "on_repeat_click": on_repeat_click,
            "on_get_last_patch": on_get_last_patch,
            "on_get_last_output": on_get_last_output,
            "on_get_last_diff": on_get_last_diff,
            "on_starter_text": on_starter_text,
            "on_mcp_reconnect": _on_mcp_reconnect,
            "on_copy_project_path": _on_copy_project_path,
            "on_new_project": _menu_new_project,
            "on_open_project": _menu_open_project,
            "on_project_settings": _menu_project_settings,
            "on_auto_run_toggle": _set_auto_run_enabled,
            "next_language": _presenter.next_language,
            "save_config": _cfg.save,
        },
        hotkey=HOTKEY,
        langs=_langs,
        initial_lang=_cur,
        geometry_collapsed=f"{COLLAPSED_W}x{WINDOW_H}",
        geometry_expanded=f"{EXPANDED_W}x{WINDOW_H}",
        width_left=WIDTH_LEFT,
        width_toggle=WIDTH_TOGGLE,
        width_right=WIDTH_RIGHT,
        window_h=WINDOW_H,
    )

    root = mw.root
    btn = mw.btn
    repeat_btn = mw.repeat_btn
    status_var = mw.status_var
    starter_include_roblox_var = mw.starter_include_roblox_var
    starter_include_xml_var = mw.starter_include_xml_var
    fs_status_var = mw.fs_status_var
    mcp_status_var = mw.mcp_status_var
    fs_status_label = mw.fs_status_label
    mcp_status_label = mw.mcp_status_label
    mcp_reconnect_btn = mw.mcp_reconnect_btn
    project_label = mw.project_label
    right_panel = mw.right_panel
    toggle_btn = mw.toggle_btn
    ready_light = mw.ready_light
    auto_run_on_copy_var = mw.auto_run_on_copy_var
    _recent_menu = mw.recent_menu

    keyboard.add_hotkey(HOTKEY, lambda: root.after(0, on_button_click))

    _refresh_recent_menu()
    update_project_status()
    update_button_state()

    root.after(100, poll_queue)
    root.after(BUTTON_STATE_REFRESH_MS, periodic_button_state)
    root.attributes("-topmost", True)

    root.after(500, _start_session_in_background)

    # Ctrl+Alt auto-run: only run the watcher thread when the option is on.
    # Off by default; the user enables it from the collapsible right panel.
    if bool(CONFIG.get("auto_run_on_copy")):
        _set_auto_run_enabled(True)

    root.mainloop()

    _set_auto_run_enabled(False)

    try:
        with _state._session_lock:
            s = _state._session
        if s is not None:
            s.__exit__(None, None, None)
    except Exception:
        pass


if __name__ == "__main__":
    run()
