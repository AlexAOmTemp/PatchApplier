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
from .. import projects as _projects
from ...core.patchparse import parse_patches
from ...core.router import plan_rebuilds
from ...tools import TOOL_MAP

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
from .widgets import StatusLog as _StatusLog


msg_queue = queue.Queue()

last_applied_patch_norm = None
last_output_text = None
is_executing = False
right_visible = False
_last_mcp_ready = False
_last_mcp_state: str = ""

CONFIG = {}
PROJECT_OK = False

# Persistent Session for in-process patching.
_session = None
_session_lock = threading.Lock()
_session_backend_name = None
mcp_status_var = None
status_label = None







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
    proj = CONFIG.get("project_dir", "").strip()
    out = CONFIG.get("index_output", "").strip()
    fm = CONFIG.get("filter_mode", "none")
    fd = CONFIG.get("filter_dirs", []) or []
    return proj, out, fm, fd


def _validate_project() -> bool:
    global PROJECT_OK
    proj, _, _, _ = _project_state()
    if not proj or not Path(proj).is_dir():
        PROJECT_OK = False
        return False
    PROJECT_OK = True
    return True




def _initialize_project():
    try:
        with _session_lock:
            s = _session
            bn = _session_backend_name or CONFIG.get("backend", "filesystem")
        if s is None:
            msg_queue.put(("status", "\u26a0 Session \u043d\u0435 \u0433\u043e\u0442\u043e\u0432\u0430"))
            return
        has_fs = bn in ("filesystem", "composite")
        want_docs = bool(CONFIG.get("index_docs", has_fs))
        want_py = bool(CONFIG.get("index_python", has_fs))
        patches: list[dict] = []
        if has_fs and want_docs:
            patches.append({"action": "rebuild_index", "arguments": {}})
        if has_fs and want_py:
            patches.append({"action": "rebuild_code_index", "arguments": {}})
        # Lua index is NOT built here: mcp may still be starting. It is
        # rebuilt once mcp transitions to ready (see _check_mcp_transition).
        if not patches:
            msg_queue.put(("status", "\u2139 \u041d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u0438\u043d\u0434\u0435\u043a\u0441\u043e\u0432"))
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
        msg_queue.put(("status", "\u2713 \u041f\u0440\u043e\u0435\u043a\u0442 \u0438\u043d\u0438\u0446\u0438\u0430\u043b\u0438\u0437\u0438\u0440\u043e\u0432\u0430\u043d" if ok else "\u2717 \u041e\u0448\u0438\u0431\u043a\u0430 \u0438\u043d\u0438\u0446\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u0438"))
    except Exception as e:
        msg_queue.put(("status", f"\u2717 \u041e\u0448\u0438\u0431\u043a\u0430 \u0438\u043d\u0438\u0446\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u0438: {e}"))


def worker(patch_text: str, normalized_patch: str):
    try:
        LAST_PATCH.write_text(patch_text, encoding="utf-8")
        msg_queue.put(("status", f"\u2713 \u0411\u0443\u0444\u0435\u0440 \u2192 {LAST_PATCH.name}"))

        with _session_lock:
            s = _session
        if s is None:
            msg_queue.put(("status", "\u2717 Session \u043d\u0435 \u0433\u043e\u0442\u043e\u0432\u0430"))
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
            msg_queue.put(("status", "\u2717 \u041f\u0430\u0442\u0447 \u043d\u0435 \u043f\u0440\u043e\u0447\u0438\u0442\u0430\u043d"))
            msg_queue.put(("error_text", err_text))
            return
        parsed = parse_patches(_raw)
        user_patches = parsed.actions
        if not user_patches:
            msg_queue.put(("status", "\u2717 \u041f\u0430\u0442\u0447 \u043f\u0443\u0441\u0442"))
            return

        with _session_lock:
            active_backend = _session_backend_name or CONFIG.get("backend", "filesystem")
        supports_fs = active_backend in ("filesystem", "composite")
        supports_mcp = active_backend in ("mcp", "composite")

        import io as _io
        import time as _time
        t_total0 = _time.time()

        all_results = []
        all_clean_lines: list[str] = []
        all_structs: list[dict] = []

        def _apply_group(group_patches, label, diagnostics=None):
            old_stdout = sys.stdout
            buf = _io.StringIO()
            t0 = _time.time()
            try:
                sys.stdout = buf
                res = s.apply_patches(group_patches, diagnostics=diagnostics)
            finally:
                sys.stdout = old_stdout
            elapsed = _time.time() - t0
            raw = buf.getvalue()
            struct = None
            group_lines = []
            for line in raw.splitlines():
                if line.startswith("##RESULT:"):
                    try:
                        struct = json.loads(line[len("##RESULT:"):])
                    except Exception:
                        struct = None
                    continue  # merged at the very end of worker()
                group_lines.append(line)
            # Drop the blank the Session printed before ##RESULT, so that
            # [timing] attaches tightly to the last action line.
            while group_lines and not group_lines[-1]:
                group_lines.pop()
            group_lines.append(f"[timing] {label}: {elapsed:.2f}s")
            if all_clean_lines:
                all_clean_lines.append("")
            all_clean_lines.extend(group_lines)
            all_results.extend(res)
            if struct is not None:
                all_structs.append(struct)

        # Step 1: user patches
        n_user = len(user_patches)
        n_before = len(all_results)
        msg_queue.put(("status", f"\u23f3 \u041f\u0430\u0442\u0447 \u043f\u0440\u0438\u043c\u0435\u043d\u044f\u0435\u0442\u0441\u044f ({n_user} actions)..."))
        _apply_group(user_patches, f"user ({n_user} actions)",
                     diagnostics=parsed.diagnostics)
        res_user = all_results[n_before:]

        # Plan index rebuilds from what actually happened.
        auto_groups = plan_rebuilds(
            user_patches, res_user, TOOL_MAP,
            config=CONFIG,
            supports_fs=supports_fs, supports_mcp=supports_mcp,
        )

        # Auto-rebuild: all rebuilds in one group, per-domain labels.
        _AUTO_LABEL = {
            "rebuild_index": "auto-md",
            "rebuild_code_index": "auto-py",
            "rebuild_lua_code_index": "auto-lua",
        }
        if auto_groups:
            auto_patches = []
            for _label, patch in auto_groups:
                p = dict(patch)
                action = p.get("action", "")
                p["id"] = _AUTO_LABEL.get(action, "auto")
                auto_patches.append(p)
            msg_queue.put(("status",
                f"\u23f3 \u0410\u0432\u0442\u043e-\u043f\u0435\u0440\u0435\u0441\u0431\u043e\u0440\u043a\u0430 \u0438\u043d\u0434\u0435\u043a\u0441\u043e\u0432 ({len(auto_patches)})..."))
            _apply_group(auto_patches,
                         f"auto-rebuild ({len(auto_patches)} actions)")

        # Emit one merged ##RESULT for the whole patch (user + auto-rebuild).
        if all_structs:
            merged = {"ok": 0, "errors": 0, "skipped": 0,
                      "failed": [], "blocked": []}
            offset = 0
            for st in all_structs:
                merged["ok"] += st.get("ok", 0)
                merged["errors"] += st.get("errors", 0)
                merged["skipped"] += st.get("skipped", 0)
                merged["failed"].extend(
                    [offset + x for x in st.get("failed", [])])
                merged["blocked"].extend(
                    [offset + x for x in st.get("blocked", [])])
                offset += (st.get("ok", 0) + st.get("errors", 0)
                           + st.get("skipped", 0))
            all_clean_lines.append("")
            all_clean_lines.append(
                f"##RESULT:{json.dumps(merged, ensure_ascii=False)}")

        t_total = _time.time() - t_total0
        output_text = "\n".join(all_clean_lines).rstrip()
        output_text += f"\n[timing] total: {t_total:.2f}s"

        # Persist only the diff block(s) for the "last diff" button.
        _diff_block = "\n\n".join(
            r.message for r in all_results
            if (r.action or "").startswith("rebuild_") and r.status == "ok"
        )
        if _diff_block:
            _save_last_diff(_diff_block)

        pyperclip.copy(output_text)
        _save_last_output(output_text)

        err_count = sum(1 for r in all_results if r.status == "error")
        success = (err_count == 0)
        msg_queue.put(("applied", (normalized_patch, output_text, success)))
        msg_queue.put(("status", f"\u2713 \u0413\u043e\u0442\u043e\u0432\u043e ({len(all_results)} actions, {t_total:.1f}s) \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0432 \u0431\u0443\u0444\u0435\u0440\u0435"))

        # Merge error info from the last struct (partial); for multiple
        # structs we take the union of failed/blocked ids from all of them.
        if all_structs:
            merged = {"ok": 0, "errors": 0, "skipped": 0, "failed": [], "blocked": []}
            offset = 0
            for st in all_structs:
                merged["ok"] += st.get("ok", 0)
                merged["errors"] += st.get("errors", 0)
                merged["skipped"] += st.get("skipped", 0)
                merged["failed"].extend([offset + x for x in st.get("failed", [])])
                merged["blocked"].extend([offset + x for x in st.get("blocked", [])])
                offset += st.get("ok", 0) + st.get("errors", 0) + st.get("skipped", 0)
            msg_queue.put(("error_text", _error_from_result(merged, output_text, 0)))
        else:
            msg_queue.put(("error_text", ""))
    except Exception as e:
        msg_queue.put(("status", f"\u2717 {e}"))
        print(traceback.format_exc(), file=sys.stderr)
    finally:
        msg_queue.put(("done", None))


def _run_patch(patch_text: str):
    """Общий запуск патча. Сброс состояния и thread."""
    global is_executing
    normalized = normalize_patch(patch_text)
    is_executing = True
    btn.config(state="disabled")
    repeat_btn.config(state="disabled")
    status_var.set("⏳ Выполняется...")
    status_var.set_state("")
    t = threading.Thread(target=worker, args=(patch_text, normalized), daemon=True)
    t.start()
    root.after(100, poll_queue)


def on_button_click():
    if is_executing:
        return
    if not _validate_project():
        status_var.set("⚠ укажите путь к проекту")
        return
    try:
        clipboard_text = pyperclip.paste() or ""
    except Exception as e:
        status_var.set(f"✗ Не могу прочитать буфер: {e}")
        return
    if not clipboard_text.strip():
        status_var.set("✗ Буфер пуст")
        return
    normalized = normalize_patch(clipboard_text)
    is_dup = (last_applied_patch_norm is not None
              and normalized == last_applied_patch_norm)
    if is_dup:
        status_var.set("⏹ Этот патч уже применён. Используй «Повторить последний».")
        error_var.set("")
        return
    _run_patch(clipboard_text)


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
        error_var.set("")
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
    text, used = _read_starter_text(lang)
    if text is None:
        status_var.set(f"\u2717 \u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d LLM_START.*.md \u0432 {_docs_dir()}")
        return

    with _session_lock:
        s = _session
    status_block = ""
    if s is not None:
        try:
            from ...tools.status import GetStatusTool
            r = GetStatusTool().execute(backend=s.backend, fmt=s.fmt)
            if r.status == "ok":
                status_block = "\n\n---\n\n" + r.message
            else:
                status_block = f"\n\n---\n\n(status error: {r.message})"
        except Exception as e:
            status_block = f"\n\n---\n\n(status unavailable: {e})"
    else:
        status_block = "\n\n---\n\n(status unavailable: session not ready)"

    extras: list[str] = []
    if starter_include_roblox_var.get():
        docs_dir = _docs_dir()
        for name in ("RobloxCodeRules.md", "MCPBridgeRules.md"):
            p = docs_dir / name
            if p.is_file():
                try:
                    extras.append(
                        "---\n\n# \u0414\u043e\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u0435: " + name + "\n\n"
                        + p.read_text(encoding="utf-8")
                    )
                except Exception as e:
                    extras.append(f"---\n\n({name}: cannot read: {e})")
            else:
                extras.append(f"---\n\n({name} not found at {p})")
        from ...config.loader import toolkit_runtime_state_dir as _trsd
        schema_path = _trsd() / "tools_schema.json"
        if schema_path.is_file():
            try:
                extras.append(
                    "---\n\n# \u0421\u0445\u0435\u043c\u0430 \u043d\u0430\u0442\u0438\u0432\u043d\u044b\u0445 \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u043e\u0432 (tools_schema.json)\n\n"
                    + schema_path.read_text(encoding="utf-8")
                )
            except Exception as e:
                extras.append(f"---\n\n(tools_schema.json: cannot read: {e})")

    extras_block = ("\n\n" + "\n\n".join(extras)) if extras else ""

    try:
        pyperclip.copy(text + extras_block + status_block)
        suffix = "+roblox" if starter_include_roblox_var.get() else ""
        status_var.set(f"\u2713 \u0421\u0442\u0430\u0440\u0442\u043e\u0432\u044b\u0439 \u0442\u0435\u043a\u0441\u0442 \u0441\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d ({used}{suffix})")
    except Exception as e:
        status_var.set(f"\u2717 {e}")


def _format_project_label():
    proj = CONFIG.get("project_dir", "").strip()
    if not proj:
        return "\u26a0 \u0443\u043a\u0430\u0436\u0438\u0442\u0435 \u043f\u0443\u0442\u044c \u043a \u043f\u0440\u043e\u0435\u043a\u0442\u0443", "#c07000"
    if not Path(proj).is_dir():
        return f"\u26a0 \u043f\u0430\u043f\u043a\u0430 \u043d\u0435 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u0435\u0442: {proj}", "#c07000"
    backend = CONFIG.get("backend", "composite")
    return f"\U0001F4C1 {proj}  [{backend}]", "#308030"


def update_project_status():
    global PROJECT_OK
    text, color = _format_project_label()
    project_label.config(text=text, fg=color)
    proj, _, _, _ = _project_state()
    PROJECT_OK = bool(proj) and Path(proj).is_dir()


def update_button_state():
    if is_executing:
        return
    if not PROJECT_OK:
        btn.config(state="disabled", text=f"\u0412\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u044c ({HOTKEY})")
        repeat_btn.config(state="disabled")
        status_var.set_state("")
        return
    if LAST_PATCH.exists():
        repeat_btn.config(state="normal")
    else:
        repeat_btn.config(state="disabled")
    try:
        current_raw = pyperclip.paste() or ""
    except Exception:
        current_raw = ""
    current_norm = normalize_patch(current_raw)
    is_dup = (last_applied_patch_norm is not None
              and current_norm
              and current_norm == last_applied_patch_norm)
    is_response_echo = (last_output_text is not None
                        and current_raw.strip()
                        and current_raw.strip() == last_output_text.strip())
    if is_dup:
        btn.config(state="disabled", text="\u2713 \u0423\u0436\u0435 \u043f\u0440\u0438\u043c\u0435\u043d\u0451\u043d")
        status_var.set_state(
            "\u26a0 \u042d\u0442\u043e\u0442 \u043f\u0430\u0442\u0447 \u0443\u0436\u0435 \u043f\u0440\u0438\u043c\u0435\u043d\u0451\u043d. \u0414\u043b\u044f \u043f\u043e\u0432\u0442\u043e\u0440\u0430 \u043d\u0430\u0436\u043c\u0438 \u00ab\u21bb \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c \u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439\u00bb.")
    elif is_response_echo:
        btn.config(state="disabled", text="\u23f8 \u0421\u043a\u043e\u043f\u0438\u0440\u0443\u0439 \u043d\u043e\u0432\u044b\u0439 \u043f\u0430\u0442\u0447")
        status_var.set_state("")
    else:
        btn.config(state="normal", text=f"\u0412\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u044c ({HOTKEY})")
        status_var.set_state("")


def _status_visual(name: str, state: str) -> tuple[str, str]:
    """Return (text, hex_color) for one backend indicator."""
    if state == "ready":
        return f"{name} \u25cf", "#306030"          # dark green
    if state == "starting":
        return f"{name} \u23f3", "#8b6914"           # dark yellow
    if state.startswith("failed"):
        return f"{name} \u2717", "#a02020"           # red
    return f"{name} \u2014", "#808080"               # gray


def _backend_states(session, backend_name: str) -> dict:
    """Read per-backend readiness from a session's backend.

    Composite exposes backend_state_all(); non-composite (filesystem or
    MCP-only) falls back to a single indicator based on is_alive().
    """
    getter = getattr(session.backend, "backend_state_all", None)
    if callable(getter):
        return getter()
    key = "mcp" if backend_name == "mcp" else "fs"
    try:
        alive = session.backend.is_alive()
    except Exception:
        alive = False
    return {key: "ready" if alive else "failed: not alive"}


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
            msg_queue.put(("status", "\u2713 Session \u0433\u043e\u0442\u043e\u0432\u0430 (composite, mcp \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0451\u043d)"))
        else:
            msg_queue.put(("status", "\u2713 Session \u0433\u043e\u0442\u043e\u0432\u0430 (mcp)"))
    elif is_failed:
        reason = mcp_state.split(":", 1)[1].strip() if ":" in mcp_state else mcp_state
        if len(reason) > 100:
            reason = reason[:100] + "\u2026"
        if backend_name == "composite":
            msg_queue.put(("status",
                f"\u26a0 Session: fs \u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d, mcp \u043d\u0435 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0451\u043d ({reason})"))
        else:
            msg_queue.put(("status", f"\u2717 Session \u043d\u0435 \u0433\u043e\u0442\u043e\u0432\u0430: mcp \u043d\u0435 \u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d ({reason})"))

    _last_mcp_ready = is_ready


def _rebuild_lua_after_ready() -> None:
    with _session_lock:
        s = _session
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
        msg_queue.put(("status", f"\u2717 Lua index rebuild failed: {e}"))
        msg_queue.put(("last_output", buf.getvalue()))
        return
    finally:
        sys.stdout = old_stdout
    _diff_block = "\n\n".join(
        r.message for r in results
        if (r.action or "").startswith("rebuild_") and r.status == "ok"
    )
    if _diff_block:
        _save_last_diff(_diff_block)
    msg_queue.put(("last_output", buf.getvalue()))
    ok = all(r.status == "ok" for r in results)
    msg_queue.put((
        "status",
        "\u2713 Lua \u0438\u043d\u0434\u0435\u043a\u0441 \u043f\u0435\u0440\u0435\u0441\u0442\u0440\u043e\u0435\u043d" if ok
        else "\u2717 Lua \u0438\u043d\u0434\u0435\u043a\u0441: \u043e\u0448\u0438\u0431\u043a\u0430",
    ))


def _on_mcp_reconnect():
    with _session_lock:
        s = _session
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
    global is_executing, last_applied_patch_norm, last_output_text
    with _session_lock:
        _s = _session
        _bn = _session_backend_name
    if _s is not None:
        try:
            _apply_backend_states(_backend_states(_s, _bn or ""))
        except Exception:
            pass
    _check_mcp_transition(_s, _bn or "")
    try:
        while True:
            kind, payload = msg_queue.get_nowait()
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
            elif kind == "done":
                is_executing = False
                update_button_state()
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
    from ...config import loader as _l
    state_dir = Path(project_dir) / _l.resolve_state_dir(CONFIG)
    from ...config.workspace import load as _ws_load
    return _ws_load(state_dir)


def _build_backend_for_config():
    """Build backend from current CONFIG.

    Returns (backend, name) where name is filesystem|mcp|composite.
    On failure returns (None, error_message).
    """
    from ...backends import FilesystemBackend, MCPBackend, CompositeBackend
    backend_name = CONFIG.get("backend", "filesystem")
    work_dir = CONFIG.get("project_dir", "").strip()
    if not work_dir or not Path(work_dir).is_dir():
        return None, "project_dir not set or not a directory"

    if backend_name == "filesystem":
        ws = _load_ws_or_error(work_dir)
        if ws is None:
            return None, "workspace.json not found in project folder"
        from ...backends.workspace import WorkspaceBackend
        from ...config import loader as _l
        state_dir = Path(work_dir) / _l.resolve_state_dir(CONFIG)
        return WorkspaceBackend(ws, state_dir), "filesystem"

    from ...config.loader import default_bridge_script
    mcp_cfg = dict(CONFIG.get("mcp") or {})
    override = mcp_cfg.get("bridge_script")
    if override:
        bridge_path = Path(override)
        if not bridge_path.is_absolute():
            bridge_path = (Path(work_dir) / override).resolve()
    else:
        bridge_path = default_bridge_script()
    if not bridge_path.is_file():
        if backend_name == "mcp":
            return None, f"bridge not found: {bridge_path}"
        # For composite we still build a backend; MCP will fail on open
        # and FS remains usable (see CompositeBackend.open semantics).

    native_cfg = mcp_cfg.get("native_tools") or {}
    from ...config.loader import resolve_state_dir as _resolve_state
    mcp_backend = MCPBackend(
        bridge_script=str(bridge_path),
        command=mcp_cfg.get("command", "python -u"),
        mcp_command=mcp_cfg.get("mcp_command") or "cmd.exe",
        mcp_args=mcp_cfg.get("mcp_args")
                 or r"/c cd /d %LOCALAPPDATA%\Roblox && .\mcp.bat",
        working_dir=work_dir,
        state_subdir=_resolve_state(CONFIG),
        preflight=mcp_cfg.get("preflight", True),
        auto_switch=mcp_cfg.get("auto_switch", True),
        ready_timeout=float(mcp_cfg.get("ready_timeout", 120.0)),
        call_timeout=float(mcp_cfg.get("call_timeout", 180.0)),
        studio_timeout=float(mcp_cfg.get("studio_timeout", 60.0)),
        max_retries=int(mcp_cfg.get("max_retries", 6)),
        retry_delay=float(mcp_cfg.get("retry_delay", 1.0)),
        native_tools_enabled=bool(native_cfg.get("enabled", True)),
        native_tools_allow=native_cfg.get("allow") or None,
        quiet_bridge=bool(mcp_cfg.get("quiet_bridge", True)),
    )

    if backend_name == "mcp":
        return mcp_backend, "mcp"
    if backend_name == "composite":
        ws = _load_ws_or_error(work_dir)
        if ws is None:
            return None, "workspace.json not found in project folder"
        from ...backends.workspace import WorkspaceBackend
        from ...config import loader as _l
        state_dir = Path(work_dir) / _l.resolve_state_dir(CONFIG)
        return CompositeBackend([
            ("fs", WorkspaceBackend(ws, state_dir)),
            ("mcp", mcp_backend),
        ]), "composite"
    return None, f"unknown backend: {backend_name}"


def _start_session_in_background():
    """Close any existing session and start a new one from CONFIG.

    Reports via msg_queue 'mcp_status' events. On success, assigns the global
    _session. Safe to call multiple times (restarts the session).
    """
    global _last_mcp_ready, _last_mcp_state
    _last_mcp_ready = False
    _last_mcp_state = ""
    def _run():
        global _session, _session_backend_name
        with _session_lock:
            old = _session
            _session = None
        if old is not None:
            try:
                old.__exit__(None, None, None)
            except Exception:
                pass

        backend, name = _build_backend_for_config()
        if backend is None:
            msg_queue.put(("status", f"\u2717 {name}"))
            return

        from ...core import Session
        from ...formats import Format
        from ...tools import TOOL_MAP
        try:
            preset = CONFIG.get("format_preset", "default")
            fmt = Format.load(preset, CONFIG.get("format") or None)
            from ...tools.shell import RunPythonTool
            RunPythonTool.set_config(
                CONFIG.get("exec"),
                CONFIG.get("project_dir", ""),
            )
            from ...tools.index import install_index_paths
            install_index_paths(CONFIG)
            from ...tools.status import GetStatusTool
            from ...config.loader import resolve_index_paths
            _mcp_cfg = CONFIG.get("mcp") or {}
            _native_cfg = _mcp_cfg.get("native_tools") or {}
            if name == "composite":
                _backs = {"filesystem", "mcp"}
            elif name == "mcp":
                _backs = {"mcp"}
            else:
                _backs = {"filesystem"}
            _paths = resolve_index_paths(CONFIG)
            _roots: list[str] = []
            try:
                _proj = CONFIG.get("project_dir", "").strip()
                if _proj:
                    _state_sub = _cfg.resolve_state_dir(CONFIG)
                    _ws = _projects.load_workspace(_proj, _state_sub)
                    _roots = list(_ws.root_names())
            except Exception:
                _roots = []
            GetStatusTool.set_context(
                project_name=Path(CONFIG.get("project_dir", "")).name,
                backend=name,
                luau_mode=(CONFIG.get("luau_mode") or "mcp"),
                format_preset=preset,
                exec_enabled=bool((CONFIG.get("exec") or {}).get("enabled")),
                exec_interpreter=(CONFIG.get("exec") or {}).get("interpreter"),
                native_tools_enabled=bool(_native_cfg.get("enabled", True)),
                native_tools_allow=_native_cfg.get("allow") or [],
                index_paths={
                    "docs": _paths["docs"],
                    "code": _paths["code"],
                    "lua":  _paths["lua"],
                },
                roots=_roots,
                backends_enabled=_backs,
            )
            s = Session(backend, fmt=fmt, tools=TOOL_MAP)
            s.open_async()
            with _session_lock:
                _session = s
                _session_backend_name = name
            if name == "composite":
                msg_queue.put(("status", "\u23f3 Session: fs \u0433\u043e\u0442\u043e\u0432, mcp \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0430\u0435\u0442\u0441\u044f..."))
            elif name == "mcp":
                msg_queue.put(("status", "\u23f3 Session: mcp \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0430\u0435\u0442\u0441\u044f..."))
            else:
                msg_queue.put(("status", "\u2713 Session \u0433\u043e\u0442\u043e\u0432\u0430 (filesystem)"))
            threading.Thread(target=_initialize_project, daemon=True).start()
        except Exception as e:
            msg_queue.put(("status", f"\u2717 Session \u043d\u0435 \u0441\u0442\u0430\u0440\u0442\u043e\u0432\u0430\u043b\u0430 ({name}): {e}"))

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
    CONFIG["project_dir"] = str(p)
    try:
        _cfg.save(CONFIG)
    except Exception:
        pass
    try:
        _cfg.add_recent_file(str(p), project_name)
    except Exception:
        pass
    update_project_status()
    update_button_state()
    _refresh_recent_menu()
    msg_queue.put(("status", f"\u23f3 \u041e\u0442\u043a\u0440\u044b\u0432\u0430\u044e \u043f\u0440\u043e\u0435\u043a\u0442: {p.name}..."))
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
    _switch_project(folder, name)


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
    global starter_include_roblox_var
    global fs_status_var, mcp_status_var, fs_status_label, mcp_status_label
    global mcp_reconnect_btn
    global project_label, right_panel, toggle_btn

    CONFIG.update(_cfg.load())
    _load_last_state()

    root = tk.Tk()
    root.title("Patch Applier")
    root.geometry(f"{COLLAPSED_W}x{WINDOW_H}")
    root.resizable(False, False)

    keyboard.add_hotkey(HOTKEY, lambda: root.after(0, on_button_click))
    # --- Menu bar ---
    global _recent_menu
    menubar = tk.Menu(root)
    file_menu = tk.Menu(menubar, tearoff=0)
    file_menu.add_command(label="New project\u2026", command=_menu_new_project)
    file_menu.add_command(label="Open project\u2026", command=_menu_open_project)
    _recent_menu = tk.Menu(file_menu, tearoff=0)
    file_menu.add_cascade(label="Recent", menu=_recent_menu)
    file_menu.add_separator()
    file_menu.add_command(label="Project settings\u2026",
                          command=_menu_project_settings)
    _refresh_recent_menu()
    file_menu.add_separator()
    file_menu.add_command(label="Exit", command=root.destroy)
    menubar.add_cascade(label="File", menu=file_menu)
    root.config(menu=menubar)


    main_frame = tk.Frame(root)
    main_frame.pack(fill="both", expand=True)

    left_panel = tk.Frame(main_frame, width=WIDTH_LEFT, height=WINDOW_H - 20)
    left_panel.pack_propagate(False)
    left_panel.pack(side="left", fill="y", padx=(10, 0), pady=10)

    def _make_copyable(label_widget):
        menu = tk.Menu(label_widget, tearoff=0)
        menu.add_command(
            label="Копировать",
            command=lambda: pyperclip.copy(label_widget.cget("text")))
        def _show_menu(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
        label_widget.bind("<Button-3>", _show_menu)

    patches_frame = tk.LabelFrame(left_panel, text="Патчи", padx=8, pady=6)
    patches_frame.pack(fill="x")

    btn = tk.Button(patches_frame, text=f"Выполнить ({HOTKEY})",
                    command=on_button_click, font=("Arial", 12), height=2)
    btn.pack(fill="x", pady=(0, 4))

    repeat_btn = tk.Button(patches_frame, text="↻ Повторить последний патч",
                           command=on_repeat_click)
    repeat_btn.pack(fill="x", pady=(0, 4))

    tk.Button(patches_frame, text="📋 Получить последний патч",
              command=on_get_last_patch).pack(fill="x", pady=(0, 4))

    tk.Button(patches_frame, text="📋 Получить последний результат",
              command=on_get_last_output).pack(fill="x", pady=(0, 4))

    project_label = tk.Label(left_panel, text="⚠ укажите путь к проекту",
                             anchor="w", fg="#c07000", wraplength=WIDTH_LEFT - 10,
                             justify="left", cursor="hand2")
    project_label.pack(fill="x", pady=(8, 0))

    def _copy_project_path(_e=None):
        proj_v = CONFIG.get("project_dir", "").strip()
        if proj_v:
            try:
                pyperclip.copy(proj_v)
                status_var.set(f"✓ Путь скопирован: {proj_v}")
            except Exception as e:
                status_var.set(f"✗ {e}")
    project_label.bind("<Button-1>", _copy_project_path)

    status_var = _StatusLog(left_panel)
    status_var.pack(fill="both", expand=True, pady=(6, 0))

    # Status row — pinned to the bottom of the left panel.
    # Backend indicators on the left, language toggle on the right.
    backend_row = tk.Frame(left_panel)
    backend_row.pack(side="bottom", fill="x", pady=(6, 0))

    fs_status_var = tk.StringVar(value="")
    fs_status_label = tk.Label(backend_row, textvariable=fs_status_var,
                               anchor="w", fg="#808080",
                               font=("Consolas", 9))
    fs_status_label.pack(side="left")

    mcp_status_var = tk.StringVar(value="")
    mcp_status_label = tk.Label(backend_row, textvariable=mcp_status_var,
                                anchor="w", fg="#808080",
                                font=("Consolas", 9))
    mcp_status_label.pack(side="left", padx=(10, 0))

    mcp_reconnect_btn = tk.Button(backend_row, text="\u21bb", width=2,
                                  command=_on_mcp_reconnect, state="disabled")
    mcp_reconnect_btn.pack(side="left", padx=(6, 0))

    _langs = _scan_starter_langs() or ["ru"]
    _cur = (CONFIG.get("ui_language") or "ru").strip() or "ru"
    if _cur not in _langs:
        _cur = _langs[0]
    lang_var = tk.StringVar(value=_cur)

    def _on_lang_click():
        options = _langs
        try:
            i = options.index(lang_var.get())
        except ValueError:
            i = 0
        nxt = options[(i + 1) % len(options)]
        lang_var.set(nxt)
        CONFIG["ui_language"] = nxt
        try:
            _cfg.save(CONFIG)
        except Exception:
            pass

    lang_btn = tk.Button(backend_row, textvariable=lang_var, width=5,
                         font=("Consolas", 9), command=_on_lang_click)
    lang_btn.pack(side="right")

    clear_log_btn = tk.Button(backend_row, text="\u2715", width=2,
                              font=("Consolas", 9), command=status_var.clear)
    clear_log_btn.pack(side="right", padx=(0, 4))

    # Правый клик → копировать текст сообщения
    _make_copyable(project_label)

    toggle_frame = tk.Frame(main_frame, width=WIDTH_TOGGLE)
    toggle_frame.pack_propagate(False)
    toggle_frame.pack(side="left", fill="y", padx=(6, 6), pady=10)
    toggle_btn = tk.Button(toggle_frame, text="→", command=lambda: toggle_right_panel(), width=2)
    toggle_btn.pack(fill="both", expand=True)

    right_panel = tk.Frame(main_frame, width=WIDTH_RIGHT)
    right_panel.pack_propagate(False)

    topmost_var = tk.BooleanVar(value=True)
    def toggle_topmost():
        root.attributes("-topmost", topmost_var.get())
    tk.Checkbutton(right_panel, text="Поверх всех окон",
                   variable=topmost_var, command=toggle_topmost).pack(anchor="w", pady=(0, 8))

    tk.Button(right_panel, text="📊 Получить последний дифф",
              command=on_get_last_diff).pack(fill="x", pady=(0, 8))

    # --- Start session block ---
    session_frame = tk.LabelFrame(right_panel, text="Старт сессии", padx=8, pady=6)
    session_frame.pack(fill="x", pady=(0, 8))

    tk.Button(session_frame, text="📄 Стартовый текст для LLM",
              command=on_starter_text).pack(fill="x")

    starter_include_roblox_var = tk.BooleanVar(value=False)
    tk.Checkbutton(session_frame, text="+ RobloxCodeRules.md",
                   variable=starter_include_roblox_var,
                   justify="left").pack(anchor="w", pady=(4, 0))

    def toggle_right_panel():
        global right_visible
        right_visible = not right_visible
        if right_visible:
            right_panel.pack(side="right", fill="y", padx=(0, 10), pady=10)
            toggle_btn.config(text="←")
            root.geometry(f"{EXPANDED_W}x{WINDOW_H}")
        else:
            right_panel.pack_forget()
            toggle_btn.config(text="→")
            root.geometry(f"{COLLAPSED_W}x{WINDOW_H}")

    update_project_status()
    update_button_state()

    root.after(100, poll_queue)
    root.after(BUTTON_STATE_REFRESH_MS, periodic_button_state)
    root.attributes("-topmost", True)

    # Always start a session. For filesystem it completes instantly;
    # for mcp/composite it runs in background and reports status.
    root.after(500, _start_session_in_background)

    root.mainloop()

    # Release session on close.
    try:
        with _session_lock:
            s = _session
        if s is not None:
            s.__exit__(None, None, None)
    except Exception:
        pass


if __name__ == "__main__":
    run()
