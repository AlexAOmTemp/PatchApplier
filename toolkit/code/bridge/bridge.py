#!/usr/bin/env python3
"""
Roblox Studio MCP Bridge — ручной мост между веб-чатом LLM и Roblox Studio MCP-сервером.

Ключевые особенности:
  * Работает через файл patch.json + команду accept (см. ниже).
  * Preflight: перед каждым батчем сверяет datamodel_type вызовов с текущим
    состоянием Studio (Edit vs Play). Если режим не совпадает — пытается
    переключить Studio через start_stop_play, затем выполняет батч.
  * Если батч смешивает Edit- и Play-вызовы — прерывает с понятным сообщением.
  * Если режим определить не удалось — пропускает проверку с предупреждением.

Установка зависимостей:
    pip install mcp --break-system-packages

Запуск (Windows, официальный Roblox MCP-сервер):
    python bridge.py --command "cmd.exe" --args "/c cd /d %LOCALAPPDATA%\\Roblox && .\\mcp.bat"

Запуск (community-сервер через npx):
    python bridge.py --command npx --args "-y robloxstudio-mcp@latest"
"""

import argparse
import asyncio
import datetime
import json
import re
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Инструменты, недоступные модели в ручном воркфлоу.
# start_stop_play остаётся в этом списке — модель его не видит, но наш preflight
# вызывает его сам напрямую через all_tool_objs.
DEFAULT_EXCLUDED_TOOLS = {
    "character_navigation",
    "user_mouse_input",
    "user_keyboard_input",
    "start_stop_play",
    "subagent",
}


# ============================================================
# Preflight: определяем требуемый режим Studio и переключаем при необходимости
# ============================================================

PLAY_DATAMODELS = {"Server", "Client"}
EDIT_DATAMODEL = "Edit"

# Session-scoped preflight cache: after one successful verification of a
# given required mode (Edit/Play), we do not re-check on every accept.
# MCP roundtrip is expensive (~0.4s) and repeating it 30-60 times per index
# rebuild dominates the wall time.
_PREFLIGHT_STATE = {"confirmed_mode": None}

# Инструменты, которым режим Studio безразличен. Батч только из них не трогает Studio.
MODE_AGNOSTIC_TOOLS = {
    "http_get",
    "skill",
    "list_roblox_studios",
    "set_active_studio",
    "upload_image",
    "store_image",
    "search_asset",
    "wait_job_finished",
    "get_studio_state",
    # генерирующие инструменты — они не зависят от DataModel
    "generate_mesh",
    "generate_material",
    "generate_procedural_model",
    "generate_texture",
    "segment_mesh",
}


def _is_playing_state(state, raw_text: str = ""):
    """True если Studio в Play, False если в Edit, None если не поняли.
    Ответ get_studio_state приходит plain text, поэтому парсим текст."""
    if isinstance(state, dict):
        for key in ("isPlaying", "is_playing", "playing", "isPlayMode",
                    "playMode", "isRunning", "running"):
            if key in state:
                v = state[key]
                if isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    return v.strip().lower() in ("playing", "true", "yes", "run", "running")
        for key in ("datamodelTypes", "datamodel_types",
                    "availableDatamodelTypes", "available_datamodel_types"):
            dts = state.get(key)
            if isinstance(dts, list):
                has_play = any(x in dts for x in ("Server", "Client"))
                has_edit = "Edit" in dts
                if has_play and not has_edit:
                    return True
                if has_edit and not has_play:
                    return False

    text = raw_text if raw_text else (state if isinstance(state, str) else "")
    if text and text.strip():
        low = text.lower()

        m = re.search(r"current\s+studio\s+mode\s*:\s*([a-zA-Z]+)", low)
        if m:
            mode = m.group(1).strip().lower()
            if mode == "edit":
                return False
            if mode in ("play", "run", "running", "server", "client", "playtest"):
                return True

        m2 = re.search(r"available\s+datamodels?\s*:\s*(.+)", low)
        if m2:
            seg = m2.group(1).strip()
            has_play = ("server" in seg) or ("client" in seg)
            has_edit = "edit" in seg
            if has_play and not has_edit:
                return True
            if has_edit and not has_play:
                return False

    return None


async def _call_text(session, name: str, args: dict) -> str:
    result = await session.call_tool(name, args)
    texts = [(c.text if hasattr(c, "text") else str(c)) for c in result.content]
    return "\n".join(texts)


async def _get_state(session, studio_id: str):
    """Возвращает (parsed_or_None, raw_text)."""
    raw = await _call_text(session, "get_studio_state", {"studio_id": studio_id})
    parsed = None
    if raw and raw.strip().startswith("{"):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None
    return parsed, raw


async def _detect_playing(session, studio_id: str):
    """Комплексная детекция режима. Возвращает True/False/None."""
    state, raw = await _get_state(session, studio_id)
    playing = _is_playing_state(state, raw)
    if playing is not None:
        return playing

    # Пустой ответ get_studio_state — характерный признак Play-режима.
    # Проверим через лёгкий Edit-вызов.
    if not raw or not raw.strip():
        try:
            probe = await _call_text(session, "execute_luau", {
                "studio_id": studio_id,
                "datamodel_type": "Edit",
                "code": "return 'probe-ok'",
            })
        except Exception:
            return None
        low = (probe or "").lower()
        if "probe-ok" in low:
            return False
        if "not available" in low or "edit mode" in low:
            return True
    return None


async def _resolve_studio_id(session, calls):
    """Ищем studio_id в аргументах вызовов, иначе через list_roblox_studios."""
    for call in calls:
        sid = (call.get("arguments") or {}).get("studio_id")
        if sid:
            return sid
    try:
        raw = await _call_text(session, "list_roblox_studios", {})
        data = json.loads(raw)
    except Exception:
        return None
    studios = None
    if isinstance(data, dict):
        studios = data.get("studios")
    elif isinstance(data, list):
        studios = data
    if isinstance(studios, list) and len(studios) == 1 and isinstance(studios[0], dict):
        return studios[0].get("id")
    return None


def _required_mode(calls):
    """Возвращает 'Edit', 'Play', 'MIXED' или None (режим не важен)."""
    wants_edit = False
    wants_play = False
    saw_data_tool = False

    for call in calls:
        tool = call.get("tool") or ""
        if tool in MODE_AGNOSTIC_TOOLS:
            continue
        dt = (call.get("arguments") or {}).get("datamodel_type")
        if not dt:
            continue
        saw_data_tool = True
        if dt == EDIT_DATAMODEL:
            wants_edit = True
        elif dt in PLAY_DATAMODELS:
            wants_play = True

    if not saw_data_tool:
        return None
    if wants_edit and wants_play:
        return "MIXED"
    return "Play" if wants_play else "Edit"


async def _switch_play(session, studio_id: str, want_playing: bool):
    """Переключает Studio в нужный режим через start_stop_play.
    Возвращает (ok, message)."""
    try:
        await _call_text(session, "start_stop_play", {
            "studio_id": studio_id,
            "is_start": bool(want_playing),
        })
    except Exception as e:
        return False, f"ошибка вызова start_stop_play: {e}"

    # Ждём смены режима — Play стартует несколько секунд, стоп почти мгновенно
    for _ in range(40):
        await asyncio.sleep(1)
        playing = await _detect_playing(session, studio_id)
        if playing == want_playing:
            return True, "режим переключён"
    return False, "не удалось дождаться смены режима (таймаут 40 с)"


async def preflight_mode(session, calls, all_tool_objs, auto_switch: bool = True):
    """Возвращает (ok, message).
    ok=True — можно выполнять (message может быть информационным).
    ok=False — батч надо прервать, message — инструкция пользователю.

    Кэширует результат для одинакового требуемого режима в рамках одной
    сессии bridge: префлайт — это 2 MCP-вызова (list_studios + state),
    на поток из 30 батчей это 60 лишних round trip'ов. Режим меняется
    только при переключении Edit/Play, а не от батча к батчу.
    """
    req = _required_mode(calls)
    if req is None:
        return True, ""

    # Skip preflight if we already verified the same required mode.
    cached = _PREFLIGHT_STATE.get("confirmed_mode")
    if cached == req:
        return True, ""

    if req == "MIXED":
        return False, (
            "Батч смешивает Edit- и Play-вызовы. Раздели на два патча: "
            "сначала Edit, потом Play (или наоборот)."
        )

    want_playing = (req == "Play")

    studio_id = await _resolve_studio_id(session, calls)
    if not studio_id:
        return True, "[preflight] ⚠ Не могу определить studio_id, пропускаю проверку режима."

    playing = await _detect_playing(session, studio_id)
    if playing is None:
        return True, (
            "[preflight] ⚠ Не смог определить режим Studio, выполняю как есть. "
            "Проверь вручную, что Studio в нужном режиме."
        )

    if playing == want_playing:
        _PREFLIGHT_STATE["confirmed_mode"] = req
        return True, f"[preflight] ✓ Режим OK ({req})."

    current = "Play" if playing else "Edit"
    print(f"[preflight] Studio в {current}, требуется {req}.")

    if not auto_switch:
        if want_playing:
            hint = "Нажми F5 в Studio (Play) и повтори патч."
        else:
            hint = "Останови Play в Studio (Stop) и повтори патч."
        return False, (
            f"[preflight] ❌ Нужен {req}-режим, а Studio сейчас в {current}.\n"
            f"[preflight] Автопереключение выключено (--no-auto-switch). {hint}"
        )

    if "start_stop_play" not in all_tool_objs:
        return False, (
            f"[preflight] ❌ Нужен {req}, но инструмент start_stop_play недоступен. "
            f"Переключи Studio вручную."
        )

    print(f"[preflight] Переключаю Studio в {req}...")
    ok, msg = await _switch_play(session, studio_id, want_playing)
    if not ok:
        return False, f"[preflight] ❌ {msg}"

    # Небольшая пауза, чтобы MCP-сервер и Studio синхронизировали состояние
    await asyncio.sleep(1.5)
    _PREFLIGHT_STATE["confirmed_mode"] = req
    return True, f"[preflight] ✓ Переключено в {req} ({msg})."


# ============================================================
# Конец preflight
# ============================================================


def print_tools(tools, tools_file: str, excluded: set, quiet: bool = False):
    tool_summaries = []
    skipped = []
    if not quiet:
        print("\n=== Доступные MCP-инструменты (edit-time) ===\n")
    for t in tools:
        if t.name in excluded:
            skipped.append(t.name)
            continue
        input_schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)
        schema = {
            "tool": t.name,
            "description": t.description,
            "arguments_schema": input_schema,
        }
        tool_summaries.append(schema)
        if not quiet:
            print(f"- {t.name}: {t.description}")

    with open(tools_file, "w", encoding="utf-8") as f:
        json.dump(tool_summaries, f, ensure_ascii=False, indent=2)

    if not quiet:
        if skipped:
            print(f"\n(Исключены runtime-инструменты: {', '.join(skipped)})")
        print(f"\nПолная JSON-схема сохранена в файл: {tools_file}")
        print(
            "Открой этот файл и вставь его содержимое в системный промпт своего веб-чата.\n"
            "Попроси модель отвечать в формате одного объекта или списка объектов:\n"
            '{"tool": "имя_инструмента", "arguments": { ... }}\n'
            'или для пакета действий: [{"tool": "...", "arguments": {...}}, {"tool": "...", "arguments": {...}}]\n'
            "Оборачивать в ```json — можно и даже удобнее для копирования, мост сам снимает обёртку.\n"
        )


def append_log(log_file: Path, entry: dict) -> None:
    """Append one JSON line to the bridge log."""
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_patch(path: Path):
    """Read a patch file and normalise it to a list of calls.

    Accepts: a single object {"tool": ...}, a list of such objects, or
    either wrapped in a ```json fence. Anything else — including an
    unreadable or unparseable file — returns an empty list.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
        m = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.DOTALL)
        if m:
            raw = m.group(1)
        data = json.loads(raw)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


async def execute_calls(session, calls, excluded, outputs_file: Path, log_file: Path,
                        append_mode: bool, all_tool_objs=None,
                        preflight: bool = True, auto_switch: bool = True):
    import time as _time
    _t_start = _time.time()
    _t_preflight = 0.0
    # Preflight: сверяем режим Studio с тем, что требует батч
    if preflight and all_tool_objs is not None:
        _tp0 = _time.time()
        ok, pre_msg = await preflight_mode(session, calls, all_tool_objs, auto_switch)
        _t_preflight = _time.time() - _tp0
        if pre_msg:
            print(pre_msg)
        if not ok:
            err_entry = {
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "preflight_error": True,
                "message": pre_msg,
            }
            with open(outputs_file, "w", encoding="utf-8") as f:
                json.dump([err_entry], f, ensure_ascii=False, indent=2)
            append_log(log_file, {
                "timestamp": err_entry["timestamp"],
                "preflight_error": True,
                "message": pre_msg,
            })
            print("[preflight] Батч прерван до выполнения.")
            return

    new_entries = []
    _per_call_times = []

    for i, call in enumerate(calls, start=1):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            tool_name = call["tool"]
            arguments = call.get("arguments", {})
        except Exception as e:
            print(f"[Ошибка формата вызова #{i}] {e}")
            append_log(log_file, {"timestamp": ts, "index": i, "error": f"bad format: {e}"})
            continue

        if tool_name in excluded:
            msg = f"'{tool_name}' исключён из edit-time набора (runtime-инструмент)."
            print(f"[Заблокировано #{i}] {msg}")
            append_log(log_file, {"timestamp": ts, "index": i, "tool": tool_name, "blocked": True, "reason": msg})
            continue

        _tc0 = _time.time()
        try:
            result = await session.call_tool(tool_name, arguments)
            _per_call_times.append(_time.time() - _tc0)
            texts = [(c.text if hasattr(c, "text") else str(c)) for c in result.content]

            # Библиотека mcp переименовала isError -> is_error. Поддерживаем оба имени.
            is_error = getattr(result, "is_error", None)
            if is_error is None:
                is_error = getattr(result, "isError", False)

            entry = {
                "timestamp": ts,
                "tool_called": tool_name,
                "arguments": arguments,
                "result": texts,
                "is_error": is_error,
            }
            new_entries.append(entry)

            preview = (texts[0][:300] + ("..." if len(texts[0]) > 300 else "")) if texts else ""
            print(f"\n=== #{i} '{tool_name}' [{ts}] (is_error={is_error}) ===")
            print(f"Превью: {preview}")

            append_log(log_file, {
                "timestamp": ts, "index": i, "tool": tool_name, "arguments": arguments,
                "is_error": is_error,
            })
        except Exception as e:
            print(f"[Ошибка вызова #{i} '{tool_name}'] {e}")
            append_log(log_file, {"timestamp": ts, "index": i, "tool": tool_name, "error": str(e)})

    if append_mode:
        existing = load_existing_outputs(outputs_file)
        combined = new_entries + existing
    else:
        combined = new_entries

    with open(outputs_file, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    _t_total = _time.time() - _t_start
    if _per_call_times:
        _call_min = min(_per_call_times)
        _call_max = max(_per_call_times)
        _call_sum = sum(_per_call_times)
    else:
        _call_min = _call_max = _call_sum = 0.0
    _timing_line = (
        f"[bridge.timing] calls={len(calls)} preflight={_t_preflight:.3f}s "
        f"call_min={_call_min:.3f}s call_max={_call_max:.3f}s "
        f"call_sum={_call_sum:.3f}s total={_t_total:.3f}s"
    )
    print(_timing_line, flush=True)
    # Also append to timing log so GUI users can see it without console.
    try:
        import os as _os
        _log_dir = _os.path.dirname(_os.path.abspath(__file__))
        _timing_log = _os.path.join(_log_dir, "bridge_timings.log")
        with open(_timing_log, "a", encoding="utf-8") as _tf:
            _tf.write(f"{datetime.datetime.now().isoformat()}  {_timing_line}\n")
    except Exception:
        pass

    print(f"\nНовых записей: {len(new_entries)}. Всего в файле сейчас: {len(combined)} -> {outputs_file}")


async def run(command: str, args: list, tools_file: str, patch_file: str,
              outputs_file: str, log_file: str, excluded: set,
              preflight: bool = True, auto_switch: bool = True,
              quiet: bool = False):
    server_params = StdioServerParameters(command=command, args=args)
    default_patch_path = Path(patch_file)
    outputs_path = Path(outputs_file)
    log_path = Path(log_file)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            all_tool_objs = {t.name: t for t in tools_result.tools}
            print_tools(tools_result.tools, tools_file, excluded, quiet=quiet)

            print(f"Мост готов. Рабочий файл для патчей (по умолчанию): {default_patch_path.resolve()}")
            if not quiet:
                print(f"Результаты сессии: {outputs_path.resolve()}")
                print(f"Постоянный лог всех действий: {log_path.resolve()}")
                print(f"Preflight-проверка режима Studio: {'включена' if preflight else 'ВЫКЛЮЧЕНА'}")
                if preflight:
                    print(f"Автопереключение Edit/Play:      {'включено' if auto_switch else 'ВЫКЛЮЧЕНО'}")
                print("=" * 70)
                print(
                    "\nКоманды:\n"
                    f"  accept [файл]          — прочитать указанный файл (или {default_patch_path.name} по умолчанию) и ЗАМЕНИТЬ результаты\n"
                    f"  accept -add [файл]     — прочитать указанный файл и ДОБАВИТЬ результаты в начало\n"
                    f"  accept -f файл          — то же, что accept файл\n"
                    f"  accept -add -f файл     — добавить результаты из указанного файла\n"
                    "  exit                    — выйти\n"
                    "Файл можно указывать как с флагом -f, так и просто как аргумент после -add (если есть).\n"
                    "Например: accept patch2.json, accept -add patch2.json, accept -f patch2.json, accept -add -f patch2.json\n"
                )

            while True:
                try:
                    cmd_raw = input("\n>>> ").strip().lower()
                except EOFError:
                    return

                if cmd_raw in ("exit", "quit", "q"):
                    return

                parts = cmd_raw.split()
                base_cmd = parts[0] if parts else ""

                if base_cmd in ("accept", "a", ""):
                    append_mode = False
                    patch_path_override = None
                    i = 1
                    while i < len(parts):
                        token = parts[i]
                        if token == "-add":
                            append_mode = True
                            i += 1
                        elif token in ("-f", "--file"):
                            if i + 1 >= len(parts):
                                print("Ошибка: после -f/--file должно следовать имя файла.")
                                break
                            patch_path_override = Path(parts[i + 1])
                            i += 2
                        elif not token.startswith("-") and patch_path_override is None:
                            patch_path_override = Path(token)
                            i += 1
                        else:
                            print(f"Неизвестный параметр: {token}")
                            i += 1

                    current_patch_path = patch_path_override if patch_path_override is not None else default_patch_path

                    if not current_patch_path.exists():
                        print(f"[Нет файла] {current_patch_path} не найден. Сохрани туда JSON от модели и повтори команду.")
                        continue
                    try:
                        calls = load_patch(current_patch_path)
                        if not quiet:
                            print(f"Читаю патч из: {current_patch_path.resolve()}")
                    except Exception as e:
                        print(f"[Ошибка чтения patch-файла] {e}")
                        continue

                    await execute_calls(session, calls, excluded, outputs_path, log_path,
                                        append_mode, all_tool_objs=all_tool_objs,
                                        preflight=preflight, auto_switch=auto_switch)
                    continue

                print("Неизвестная команда. Доступно: accept / accept -add / exit")


def main():
    parser = argparse.ArgumentParser(description="Мост между веб-чатом LLM и Roblox Studio MCP-сервером")
    parser.add_argument("--command", required=True, help="Путь к исполняемому файлу MCP-сервера или 'npx'")
    parser.add_argument("--args", default="", help="Аргументы команды одной строкой")
    parser.add_argument("--tools-file", default="tools_schema.json", help="Куда сохранить JSON-схему инструментов")
    parser.add_argument("--patch-file", default="patch.json", help="Файл, откуда читать JSON-вызов(ы) от LLM")
    parser.add_argument("--outputs-file", default="outputs.json", help="Единый файл со всеми результатами")
    parser.add_argument("--log-file", default="bridge_log.jsonl", help="Файл-лог всех действий за всё время")
    parser.add_argument("--exclude", default="", help="Доп. инструменты для исключения через запятую")
    parser.add_argument("--include-all", action="store_true", help="Не исключать ничего")
    parser.add_argument("--no-preflight", action="store_true",
                        help="Отключить preflight-проверку режима Studio (Edit/Play)")
    parser.add_argument("--no-auto-switch", action="store_true",
                        help="Не переключать Studio автоматически; только сообщать о несоответствии режима")
    parser.add_argument("--quiet", action="store_true",
                        help="Подавить баннер и служебные строки; оставить только ready-маркер и ошибки")
    parsed = parser.parse_args()

    args_list = parsed.args.split() if parsed.args else []

    excluded = set() if parsed.include_all else set(DEFAULT_EXCLUDED_TOOLS)
    if parsed.exclude:
        excluded.update(name.strip() for name in parsed.exclude.split(",") if name.strip())

    try:
        asyncio.run(run(
            parsed.command, args_list, parsed.tools_file, parsed.patch_file,
            parsed.outputs_file, parsed.log_file, excluded,
            preflight=(not parsed.no_preflight),
            auto_switch=(not parsed.no_auto_switch),
            quiet=parsed.quiet,
        ))
    except KeyboardInterrupt:
        print("\nВыход.")
        sys.exit(0)


if __name__ == "__main__":
    main()