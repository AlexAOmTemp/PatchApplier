import keyboard
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
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
from .policy_io import load_policy as _load_policy, save_policy_into
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



def _save_policy(policy: dict) -> None:
    save_policy_into(CONFIG, policy)





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
    policy = _load_policy(CONFIG)
    parts = []
    for role, letter in (("read", "R"), ("write", "W"), ("index", "I")):
        ov = policy.get(role, {})
        n_allow = sum(1 for v in ov.values() if v)
        n_deny = sum(1 for v in ov.values() if not v)
        parts.append(f"{letter}:{n_allow}/{n_deny}")
    return f"\U0001F4C1 {proj}  [{' '.join(parts)}]", "#308030"


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

        from ...core import Session, Policy
        from ...formats import Format
        from ...tools import TOOL_MAP
        try:
            policy_obj = Policy.from_dict(CONFIG.get("filter") or {})
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
                policy=policy_obj,
                backends_enabled=_backs,
            )
            s = Session(backend, fmt=fmt, tools=TOOL_MAP, policy=policy_obj)
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


# ==== Диалог настроек ====

def open_settings_dialog():
    dlg = tk.Toplevel(root)
    dlg.title("Настройка проекта")
    dlg.transient(root)
    dlg.grab_set()
    dlg.geometry("1080x700")
    dlg.minsize(1000, 600)

    proj = CONFIG.get("project_dir", "").strip()
    out = CONFIG.get("index_output", "").strip()

    overrides = _load_policy(CONFIG)

    cfg_backend = CONFIG.get("backend", "filesystem")
    cfg_mcp = dict(CONFIG.get("mcp") or {})
    _fs_default = cfg_backend in ("filesystem", "composite")
    md_enabled_initial = bool(CONFIG.get("index_docs", _fs_default))
    py_enabled_initial = bool(CONFIG.get("index_python", _fs_default))
    mcp_enabled_initial = cfg_backend in ("mcp", "composite")
    luau_mode_initial = (CONFIG.get("luau_mode") or "mcp").strip() or "mcp"
    if luau_mode_initial not in ("mcp", "rojo"):
        luau_mode_initial = "mcp"

    # Late-bound reload hook: browse_proj / on_recent fire it after
    # the project path changes, so every widget re-reads its value from
    # the *new* project's config.json (or defaults if absent). Filled in
    # below, once all widgets exist. This makes the dialog reactive:
    # "path determines project" is the single source of truth, no
    # "apply to current / new" questions.
    _reload_hook = {"fn": None}

    main = tk.Frame(dlg, padx=12, pady=12)
    main.pack(fill="both", expand=True)

    # --- Project row ---
    tk.Label(main, text="Папка проекта:", anchor="w").pack(fill="x")
    proj_row = tk.Frame(main)
    proj_row.pack(fill="x", pady=(2, 6))
    proj_var = tk.StringVar(value=proj)
    tk.Entry(proj_row, textvariable=proj_var).pack(side="left", fill="x", expand=True)

    def _copy_proj():
        txt = proj_var.get().strip()
        if txt:
            pyperclip.copy(txt)
    tk.Button(proj_row, text="\U0001F4CB", width=3, command=_copy_proj,
              cursor="hand2").pack(side="left", padx=(6, 0))

    def browse_proj():
        initial = proj_var.get().strip() or str(Path.home())
        p = filedialog.askdirectory(initialdir=initial)
        if p:
            proj_var.set(p)
            _refresh_fs(Path(p))
            if _reload_hook["fn"] is not None:
                _reload_hook["fn"](p)
    tk.Button(proj_row, text="Обзор…", command=browse_proj).pack(side="left", padx=(6, 0))

    recent = CONFIG.get("recent_projects", []) or []
    if recent:
        tk.Label(main, text="Недавние:", anchor="w").pack(fill="x")
        recent_var = tk.StringVar()
        recent_combo = ttk.Combobox(main, textvariable=recent_var, values=recent, state="readonly")
        recent_combo.pack(fill="x", pady=(2, 6))
        def on_recent(_e=None):
            v = recent_var.get()
            if v:
                proj_var.set(v)
                _refresh_fs(Path(v))
                if _reload_hook["fn"] is not None:
                    _reload_hook["fn"](v)
        recent_combo.bind("<<ComboboxSelected>>", on_recent)
    # Two-column body: configuration (service dir + backends) on the left,
    # policy tree on the right. Project row and OK/Cancel stay full width.
    body = tk.Frame(main)
    body.pack(fill="both", expand=True)
    # Left column: fixed width so the policy tree on the right gets the
    # rest. Without pack_propagate(False) the left column grows to the
    # widest child (labels with wraplength) and squeezes the tree.
    LEFT_COL_W = 460
    left = tk.Frame(body, width=LEFT_COL_W)
    left.pack(side="left", fill="y", expand=False)
    left.pack_propagate(False)
    right = tk.LabelFrame(body, text="Политика", padx=8, pady=6)
    right.pack(side="left", fill="both", expand=True, padx=(12, 0))

    # --- State dir (fixed; not user-editable) ---
    service_frame = tk.LabelFrame(
        left, text="Служебный каталог", padx=8, pady=6)
    service_frame.pack(fill="x", pady=(0, 6))

    tk.Label(service_frame, text=".patch_applier",
             anchor="w", font=("Consolas", 10)).pack(fill="x")
    tk.Label(service_frame,
             text=("Фиксированный. Индексы, .version, .manifest, sidecar, "
                   "рантайм MCP. Всегда открыт для LLM (исключение из правила "
                   "скрытых папок)."),
             anchor="w", fg="#888", justify="left",
             wraplength=LEFT_COL_W - 30).pack(fill="x", pady=(4, 0))

    # --- Backends block ---
    backends_frame = tk.LabelFrame(left, text="Backends", padx=8, pady=6)
    backends_frame.pack(fill="x", pady=(6, 4))

    md_var = tk.BooleanVar(value=md_enabled_initial)
    py_var = tk.BooleanVar(value=py_enabled_initial)
    mcp_var = tk.BooleanVar(value=mcp_enabled_initial)

    tk.Checkbutton(backends_frame, text="Markdown — документация",
                   variable=md_var).pack(anchor="w")
    tk.Checkbutton(backends_frame, text="MCP — Roblox Studio",
                   variable=mcp_var).pack(anchor="w")

    # Python row: index gate + exec gate side by side. Exec is
    # meaningless without Python as a source — hide the dependency in
    # the UI: unchecking Python disables the exec checkbox and clears it.
    exec_cfg = dict(CONFIG.get("exec") or {})
    exec_var = tk.BooleanVar(value=bool(exec_cfg.get("enabled", False)))
    py_row = tk.Frame(backends_frame)
    py_row.pack(anchor="w", fill="x")
    tk.Checkbutton(py_row, text="Python — код проекта",
                   variable=py_var).pack(side="left")
    exec_check = tk.Checkbutton(py_row, text="+ запускать скрипты (на свой риск)",
                                variable=exec_var)
    exec_check.pack(side="left", padx=(10, 0))

    def _sync_exec_to_python(*_a):
        on = bool(py_var.get())
        if not on:
            exec_var.set(False)
        exec_check.config(state="normal" if on else "disabled")

    py_var.trace_add("write", _sync_exec_to_python)
    _sync_exec_to_python()

    luau_var = tk.StringVar(value=luau_mode_initial)
    luau_row = tk.Frame(backends_frame)
    luau_row.pack(anchor="w", fill="x", pady=(4, 0))
    tk.Label(luau_row, text="Luau source:").pack(side="left")
    tk.Radiobutton(luau_row, text="Studio (MCP)", variable=luau_var,
                   value="mcp").pack(side="left", padx=(6, 0))
    tk.Radiobutton(luau_row, text="Disk (Rojo)", variable=luau_var,
                   value="rojo").pack(side="left", padx=(6, 0))

    tk.Label(
        backends_frame,
        text=("MCP: .Source в Studio (Service.X.Y). Rojo: .luau на диске. "
              "Сцена — всегда через мост."),
        anchor="w", fg="#888", justify="left", wraplength=LEFT_COL_W - 30,
    ).pack(fill="x", pady=(4, 0))

    # --- Hidden dirs block (drives .patchignore + tree visibility) ---
    from ...config import patchignore as _pi

    hidden_frame = tk.LabelFrame(left, text="Скрытые папки", padx=8, pady=6)
    hidden_frame.pack(fill="x", pady=(6, 4))

    # View-only toggle: reveals hidden paths in the tree, marked and with
    # their cells frozen. It does not change what is enforced — hiding is
    # governed by `.patchignore` alone.
    show_hidden_var = tk.BooleanVar(value=False)
    tk.Checkbutton(
        hidden_frame, text="Показывать скрытое в дереве",
        variable=show_hidden_var,
    ).pack(anchor="w")

    def _pi_path():
        pv = proj_var.get().strip()
        return (Path(pv) / _pi.PATCHIGNORE_NAME) if pv else None

    def _pi_btn_label():
        p = _pi_path()
        if not p or not p.is_file():
            return "Правила (.patchignore)…"
        try:
            n = len(_pi.parse(p.read_text(encoding="utf-8")))
            return f"Правила (.patchignore): {n}"
        except Exception:
            return "Правила (.patchignore)…"

    def _reload_backend_patterns():
        """Best-effort: make running backends pick up a re-written
        .patchignore without a full session restart."""
        with _session_lock:
            s = _session
        if s is None:
            return
        b = s.backend
        if hasattr(b, "reload_patterns"):
            try:
                b.reload_patterns()
            except Exception:
                pass
        for _n, sub in getattr(b, "_pairs", []) or []:
            if hasattr(sub, "reload_patterns"):
                try:
                    sub.reload_patterns()
                except Exception:
                    pass

    def _refresh_tree_now():
        pv = proj_var.get().strip()
        if pv and Path(pv).is_dir():
            _refresh_fs(Path(pv))

    def open_pi_editor():
        p = _pi_path()
        if p is None:
            return
        _pi.ensure_default(p.parent)

        dlg2 = tk.Toplevel(dlg)
        dlg2.title(".patchignore")
        dlg2.transient(dlg)
        dlg2.grab_set()
        dlg2.geometry("560x460")
        dlg2.minsize(420, 340)

        tk.Label(
            dlg2, anchor="w", justify="left",
            text=("Одна строка = один паттерн (.gitignore-подобный).\n"
                  "*, ?, [seq], ! — как в .gitignore. Скрытое закрыто для LLM (R/W/I)."),
        ).pack(fill="x", padx=12, pady=(12, 4))

        body = tk.Frame(dlg2)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        lb = tk.Listbox(body, selectmode="extended", font=("Consolas", 9))
        sb = tk.Scrollbar(body, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        try:
            raw = p.read_text(encoding="utf-8")
        except Exception:
            raw = ""
        for line in raw.splitlines():
            lb.insert("end", line)

        entry_row = tk.Frame(dlg2)
        entry_row.pack(fill="x", padx=12, pady=(0, 6))
        entry = tk.Entry(entry_row, font=("Consolas", 9))
        entry.pack(side="left", fill="x", expand=True)

        def _add(*_a):
            v = entry.get()
            if v.strip():
                lb.insert("end", v)
            entry.delete(0, "end")

        def _remove(*_a):
            for i in reversed(lb.curselection()):
                lb.delete(i)

        def _reset():
            if not messagebox.askyesno(
                    ".patchignore", "Сбросить к дефолту?", parent=dlg2):
                return
            lb.delete(0, "end")
            for ln in _pi.DEFAULT_PATCHIGNORE.splitlines():
                lb.insert("end", ln)

        def _open_all():
            if not messagebox.askyesno(
                    ".patchignore",
                    "Удалить все правила? Скрытие будет отключено.",
                    parent=dlg2):
                return
            lb.delete(0, "end")

        entry.bind("<Return>", _add)
        tk.Button(entry_row, text="Добавить", command=_add,
                  width=10).pack(side="left", padx=(6, 0))
        tk.Button(entry_row, text="Удалить", command=_remove,
                  width=10).pack(side="left", padx=(6, 0))

        tools_row = tk.Frame(dlg2)
        tools_row.pack(fill="x", padx=12, pady=(0, 6))
        tk.Button(tools_row, text="Сбросить к дефолту",
                  command=_reset).pack(side="left")
        tk.Button(tools_row, text="Открыть всё",
                  command=_open_all).pack(side="left", padx=(6, 0))

        btn_row2 = tk.Frame(dlg2)
        btn_row2.pack(fill="x", padx=12, pady=(6, 12))

        def _ok():
            lines = [str(x) for x in lb.get(0, "end")]
            try:
                p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e), parent=dlg2)
                return
            _reload_backend_patterns()
            _refresh_tree_now()
            pi_btn.config(text=_pi_btn_label())
            dlg2.destroy()

        tk.Button(btn_row2, text="OK", command=_ok,
                  width=10).pack(side="right", padx=(6, 0))
        tk.Button(btn_row2, text="Отмена", command=dlg2.destroy,
                  width=10).pack(side="right")

    pi_btn = tk.Button(hidden_frame, text=_pi_btn_label(), command=open_pi_editor)
    pi_btn.pack(fill="x", pady=(6, 0))

    tk.Label(
        hidden_frame,
        text=("Файл .patchignore в корне проекта. Скрытые пути закрыты для LLM "
              "(R/W/I) и не видны в дереве без галки выше."),
        anchor="w", fg="#888", justify="left", wraplength=LEFT_COL_W - 30,
    ).pack(fill="x", pady=(4, 0))


    # --- Legend ---
    tk.Label(
        right,
        text=("R = Read (чтение),   W = Write (запись),   I = Index (индекс)\n"
              "· наследует   + разрешено   − запрещено   (Shift+клик — на поддерево)\n"
              "В корневой строке [project root] наследовать неоткуда — · эквивалентно +.\n"
              "Скрытые папки (.git, __pycache__, ...) закрыты по умолчанию.\n"
              "Исключение — .patch_applier: всегда открыт.\n"
              "Чтобы открыть другую скрытую папку — поставь + на ней или её предке."),
        anchor="w", fg="#555", justify="left",
        wraplength=500,
    ).pack(fill="x", pady=(6, 2))

    # --- Policy tree (filesystem only) ---
    # Roblox paths are not filtered by policy: access is gated at the
    # backend level (mcp.native_tools.enabled). No UI for them.
    views = []

    def _make_view(label, is_fs):
        frame = tk.Frame(right)
        frame.pack(fill="both", expand=True, pady=(2, 6))

        container = tk.Frame(frame, bd=1, relief="sunken")
        container.pack(fill="both", expand=True, padx=6, pady=6)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw", tags="inner")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_canvas_config(event):
            canvas.itemconfigure("inner", width=event.width)
        canvas.bind("<Configure>", _on_canvas_config)

        v = {
            "label": label,
            "is_fs": is_fs,
            "inner": inner,
            "dir_widgets": {},
            "tree_prefixes": {},
            "paths": [],
        }
        views.append(v)
        return v

    fs_view = _make_view("Filesystem", True)

    bg_default = fs_view["inner"].cget("bg")
    bg_hover = "#e6e6e6"

    def _compute_prefixes(paths):
        from collections import defaultdict
        children = defaultdict(list)
        for p in paths:
            if p == ".":
                continue
            parent = p.rsplit("/", 1)[0] if "/" in p else "."
            children[parent].append(p)
        for k in children:
            children[k].sort()
        result = {}
        def walk(p, prefix, is_last):
            if p == ".":
                result[p] = ""
            else:
                result[p] = prefix + ("\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 ")
            kids = children.get(p, [])
            for i, kid in enumerate(kids):
                kid_last = (i == len(kids) - 1)
                new_prefix = "" if p == "." else prefix + ("    " if is_last else "\u2502   ")
                walk(kid, new_prefix, kid_last)
        walk(".", "", True)
        return result

    def _clear_view(view):
        for w in view["inner"].winfo_children():
            w.destroy()
        view["dir_widgets"].clear()

    def _display_name(path, view):
        if path == ".":
            return "[project root]" if view["is_fs"] else "[other services]"
        return path.rsplit("/", 1)[-1]

    def _text_for(path, view):
        base = view["tree_prefixes"].get(path, "") + _display_name(path, view)
        if path in view.get("hidden", ()):
            base += "  (hidden)"
        return base

    def _cell_text(view, path, role):
        from ...config.patchignore import is_state_path
        if is_state_path(path):
            # Fixed: R+ / W+ / I-. The state dir holds the toolkit's own
            # files (indices, MCP runtime); there is nothing to index inside.
            return "+" if role in ("read", "write") else "\u2212"
        if path in view.get("hidden", ()):
            return "\u2212"
        v = overrides[role].get(path)
        if v is None:
            return "\u00b7"
        return "+" if v else "\u2212"

    def _cell_color(view, path, role):
        from ...config.patchignore import is_state_path
        if is_state_path(path):
            return "#307030" if role in ("read", "write") else "#c03030"
        if path in view.get("hidden", ()):
            return "#a02020"
        v = overrides[role].get(path)
        if v is None:
            return "#888888"
        return "#307030" if v else "#c03030"

    def _update_all_views():
        for view in views:
            for p, w in view["dir_widgets"].items():
                try:
                    w["text"].config(text=_text_for(p, view))
                    for role in ("read", "write", "index"):
                        w[role].config(
                            text=_cell_text(view, p, role),
                            fg=_cell_color(view, p, role))
                except Exception:
                    pass

    def _cycle(view, path, role, apply_subtree):
        if path in view.get("hidden", ()):
            return
        cur = overrides[role].get(path)
        if cur is None:
            new = True
        elif cur is True:
            new = False
        else:
            new = None

        def _set(p):
            if new is None:
                overrides[role].pop(p, None)
            else:
                overrides[role][p] = new

        _set(path)
        if apply_subtree:
            for p in list(view["dir_widgets"].keys()):
                if p == path or p in view.get("hidden", ()):
                    continue
                if view["is_fs"] and path == ".":
                    _set(p)
                elif path != "." and p.startswith(path + "/"):
                    _set(p)
        _update_all_views()

    def _make_cell_click(view, path, role):
        def handler(event):
            shift = bool(event.state & 0x0001)
            _cycle(view, path, role, shift)
        return handler

    def _make_row(view, path, hidden=False):
        row = tk.Frame(view["inner"], bg=bg_default)
        row.pack(fill="x", anchor="w")

        cells = {}
        for role in ("read", "write", "index"):
            cell = tk.Label(
                row, text="\u00b7", font=MONO_FONT, width=2,
                bg=bg_default, fg="#888888",
                cursor=("arrow" if hidden else "hand2"))
            cell.pack(side="left", padx=(0, 2))
            if not hidden:
                cell.bind("<Button-1>", _make_cell_click(view, path, role))
            cells[role] = cell

        # Text (including the `(hidden)` suffix) comes from _text_for, so
        # that later _update_all_views() refreshes do not strip it.
        text_label = tk.Label(row, text=_text_for(path, view), font=MONO_FONT,
                              bg=bg_default, fg="black", anchor="w", justify="left")
        text_label.pack(side="left", fill="x", expand=True)

        widgets = [row, text_label] + list(cells.values())

        def _on_enter(_e):
            for w in widgets:
                try:
                    w.config(bg=bg_hover)
                except Exception:
                    pass
        def _on_leave(_e):
            for w in widgets:
                try:
                    w.config(bg=bg_default)
                except Exception:
                    pass

        for w in widgets:
            w.bind("<Enter>", _on_enter)
            w.bind("<Leave>", _on_leave)

        view["dir_widgets"][path] = {"text": text_label, **cells}

    def _make_header_row(view):
        row = tk.Frame(view["inner"], bg=bg_default)
        row.pack(fill="x", anchor="w", pady=(0, 4))
        for hdr in ("R", "W", "I"):
            lbl = tk.Label(row, text=hdr, font=MONO_FONT, width=2,
                           bg=bg_default, fg="#306030", anchor="center")
            lbl.pack(side="left", padx=(0, 2))
        tk.Label(row, text="  путь", font=MONO_FONT,
                 bg=bg_default, fg="#306030", anchor="w").pack(
            side="left", fill="x", expand=True)

    def _render_view(view, paths):
        _clear_view(view)
        view["paths"] = [p for p, _ in paths]
        view["hidden"] = {p for p, h in paths if h}
        view["tree_prefixes"] = _compute_prefixes(view["paths"]) if view["is_fs"] else {}
        _make_header_row(view)
        for p, h in paths:
            _make_row(view, p, hidden=h)
        _update_all_views()

    def _render_fs(dirs):
        _render_view(fs_view, [(".", False)] + list(dirs))

    def _refresh_fs(proj_path):
        patterns = _pi.read(Path(proj_path))
        dirs = _cfg.scan_subdirs(
            Path(proj_path), max_depth=3,
            patterns=patterns,
            show_hidden=bool(show_hidden_var.get()))
        _render_fs(dirs)

    # Live re-render when the user toggles "show hidden".
    show_hidden_var.trace_add("write", lambda *_: _refresh_tree_now())

    initial = proj_var.get().strip()
    initial_dirs = []
    if initial and Path(initial).is_dir():
        patterns = _pi.read(Path(initial))
        initial_dirs = _cfg.scan_subdirs(
            Path(initial), max_depth=3,
            patterns=patterns,
            show_hidden=bool(show_hidden_var.get()))
    _render_fs(initial_dirs)

    def _reload_from_project(new_proj: str) -> None:
        """Re-read per-project config into widgets when the path changes.

        The path *is* the project selector: on every change (browse /
        recent) we pull that project's config.json (or defaults) and
        rebind every widget, so what the user sees always matches what
        they would save. No "apply to current/new" questions.
        """
        if not new_proj or not Path(new_proj).is_dir():
            return
        fresh = _cfg.load(project_dir=new_proj)
        fs_on = fresh.get("backend") in ("filesystem", "composite")
        mcp_on = fresh.get("backend") in ("mcp", "composite")
        md_var.set(bool(fresh.get("index_docs", fs_on)))
        py_var.set(bool(fresh.get("index_python", fs_on)))
        mcp_var.set(mcp_on)
        lm = (fresh.get("luau_mode") or "mcp").strip() or "mcp"
        if lm not in ("mcp", "rojo"):
            lm = "mcp"
        luau_var.set(lm)
        exec_var.set(bool((fresh.get("exec") or {}).get("enabled", False)))
        _sync_exec_to_python()
        try:
            pi_btn.config(text=_pi_btn_label())
        except Exception:
            pass
        new_ovr = _load_policy(fresh)
        for role in ("read", "write", "index"):
            overrides[role].clear()
            overrides[role].update(new_ovr.get(role, {}))
        _refresh_fs(Path(new_proj))

    _reload_hook["fn"] = _reload_from_project

    # --- Buttons ---
    btn_row = tk.Frame(main)
    btn_row.pack(fill="x", padx=12, pady=(12, 12))

    def on_ok():
        proj_v = proj_var.get().strip()
        if not proj_v:
            messagebox.showerror("Ошибка", "Укажите папку проекта", parent=dlg)
            return
        if not Path(proj_v).is_dir():
            messagebox.showerror("Ошибка", f"Папка не существует:\n{proj_v}", parent=dlg)
            return
        # Path changes are handled reactively by _reload_from_project:
        # widgets already reflect the new project's config by the time
        # OK is pressed. Here we only persist what the user sees.
        md_on = md_var.get()
        py_on = py_var.get()
        mcp_on = mcp_var.get()
        if not (md_on or py_on or mcp_on):
            messagebox.showerror("Ошибка", "Включите хотя бы один источник", parent=dlg)
            return
        fs_on = md_on or py_on

        for role in ("read", "write", "index"):
            cleaned = {}
            for p, v in overrides[role].items():
                norm = str(p).replace("\\", "/").strip("/")
                if not norm:
                    continue
                if norm != "." and not (Path(proj_v) / norm).exists():
                    continue
                cleaned[norm] = bool(v)
            for p in sorted(list(cleaned.keys()), key=lambda x: -x.count("/")):
                if p == ".":
                    continue
                parts = p.split("/")
                for i in range(len(parts) - 1, 0, -1):
                    ancestor = "/".join(parts[:i])
                    if ancestor in cleaned and cleaned[ancestor] == cleaned[p]:
                        cleaned.pop(p, None)
                        break
            overrides[role] = cleaned

        if fs_on and mcp_on:
            backend_name = "composite"
        elif mcp_on:
            backend_name = "mcp"
        else:
            backend_name = "filesystem"

        CONFIG["backend"] = backend_name
        CONFIG["index_docs"] = bool(md_on)
        CONFIG["index_python"] = bool(py_on)
        CONFIG["index_lua"] = bool(mcp_on)
        CONFIG["luau_mode"] = luau_var.get() or "mcp"
        CONFIG["project_dir"] = proj_v
        # state_dir is fixed (.patch_applier); drop any legacy fields the
        # saved config may still carry, and clear explicit output overrides
        # that used to shadow it.
        CONFIG.pop("state_dir", None)
        CONFIG.pop("service_subdir", None)
        for _k in ("index_output", "code_index_output", "code_manifest_output",
                   "lua_index_output"):
            CONFIG.pop(_k, None)

        existing_mcp = dict(CONFIG.get("mcp") or {})
        existing_mcp.setdefault("bridge_script", "bridge.py")
        existing_mcp.setdefault("command", "python -u")
        existing_mcp.setdefault("preflight", True)
        existing_mcp.setdefault("auto_switch", True)
        existing_mcp.setdefault("ready_timeout", 120)
        existing_mcp.setdefault("call_timeout", 180)
        existing_mcp.setdefault("studio_timeout", 60)
        CONFIG["mcp"] = existing_mcp

        existing_exec = dict(CONFIG.get("exec") or {})
        existing_exec["enabled"] = bool(exec_var.get())
        CONFIG["exec"] = existing_exec

        CONFIG.pop("ui_show_dotdirs", None)
        CONFIG.pop("ui_hidden_dirs", None)

        _save_policy(overrides)
        CONFIG.pop("filter_mode", None)
        CONFIG.pop("filter_dirs", None)
        _cfg.add_recent(CONFIG, proj_v)
        _cfg.save(CONFIG)
        dlg.destroy()
        update_project_status()
        update_button_state()
        msg_queue.put(("status", "\u23f3 \u041f\u0435\u0440\u0435\u0437\u0430\u043f\u0443\u0441\u043a Session..."))
        _start_session_in_background()
        root.after(200, poll_queue)

    tk.Button(btn_row, text="OK", command=on_ok, width=10).pack(side="right", padx=(6, 0))
    tk.Button(btn_row, text="Отмена", command=dlg.destroy, width=10).pack(side="right")


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

    tk.Button(right_panel, text="⚙ Настройки",
              command=open_settings_dialog).pack(fill="x", pady=(0, 4))

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
