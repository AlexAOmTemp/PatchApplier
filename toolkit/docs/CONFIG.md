# Конфигурация

> **Статус:** контракт формата `.patch_applier.json`. Дефолты — в `config/loader.py:DEFAULTS`. Если документ расходится с кодом — верь коду.

## 1. Файл
<!-- summary: Два файла: tool-wide `<toolkit_root>/.patch_applier.json` + per-project `<project>/.patch_applier/config.json`; load мержит, save разбивает; граница — TOOL_FIELDS. -->

**Два файла, один merged конфиг.**

- **Tool-wide** — `<toolkit_root>/.patch_applier.json` (рядом с кодом утилиты, вне проекта). Одинаков для всех проектов: `project_dir`, `recent_projects`, `ui_language`, `format`/`format_preset`, `mcp` (настройки bridge), `exec` (политика `run_python`).
- **Per-project** — `<project>/.patch_applier/config.json`. Описывает один проект: `backend`, `filter` (read/write/index), `skip_files`, `code_*`, `lua_*`, `state_dir`, `luau_mode`, `index_*`.

`load()` читает tool-wide, затем накладывает per-project overlay. `save()` разбивает merged dict обратно на два. Граница полей — `TOOL_FIELDS` в `toolkit/config/loader.py`. Если в конфиге нет `project_dir` — всё пишется в tool-wide файл (legacy single-file поведение).

**Почему разделено.** `backend`, `filter`, `state_dir`, `luau_mode` относятся к конкретному проекту и не должны переноситься при переключении. `mcp`, `exec`, `ui_language` — про утилиту. GUI при смене пути проекта реактивно перечитывает `<project>/.patch_applier/config.json` в виджеты (путь и есть определитель проекта; никаких диалогов «перенести / загрузить»).

**Legacy.** Старый объединённый формат продолжает читаться: `load()` примет его как tool-wide и подтянет per-project overlay, если есть. Для миграции есть `toolkit/code/manual/migrate_config.py`.

## 2. Структура

Все поля опциональны. Полный набор ключей:

```json
{
  "backend": "filesystem" | "mcp" | "composite" | "auto",
  "project_dir": "/abs/path",
  "luau_mode": "mcp" | "rojo",

  "format_preset": "default" | "plain",
  "format": { ... },

  "filter": {
    "read":  { "overrides": { ".": false, "toolkit": true } },
    "write": { "overrides": { "toolkit": true } },
    "index": { "overrides": { "toolkit": true } }
  },

  "state_dir": ".patch_applier",
  "index_docs_dir": "",
  "index_output": "",
  "skip_files": ["INDEX.md", "CODE_INDEX.md"],

  "code_dir": "",
  "code_index_output": "",
  "code_manifest_output": "",
  "code_skip_files": [],
  "code_skip_dirs": [],

  "lua_index_output": "CODE_INDEX_LUA.md",

  "ui_language": "ru",

  "exec": {
    "enabled": false,
    "interpreter": null,
    "allow_module_mode": true,
    "child_encoding": "utf-8",
    "default_timeout": 60,
    "max_timeout": 600,
    "max_output_bytes": 200000,
    "env_passthrough": [ ... ],
    "env_deny_patterns": [ ... ]
  },

  "mcp": { ... }
}
```

- `backend`: `filesystem` — только локальные файлы; `mcp` — только Roblox; `composite` — оба (FS-операции мгновенные, MCP поднимается в фоне); `auto` — `composite`, если задан `mcp.bridge_script`, иначе `filesystem`.
- `luau_mode`: где живёт Luau-код. `mcp` (дефолт) — `.Source` в Studio, пути `Service.X.Y`. `rojo` — `.luau` на диске, обычные файловые пути. Сцена (Parts/GUI/Folders) в обоих режимах идёт через мост. См. `LLM_START` §1.
- `state_dir`: **один служебный каталог** внутри проекта для всего, что генерирует утилита — индексы (`INDEX.md`, `CODE_INDEX*.md`, их `.version` и `.manifest.json`), sidecar (`.index_meta.json`) и рантайм MCP (`patch.json`, `outputs.json`, `bridge_log.jsonl`, `tools_schema.json`). Дефолт `.patch_applier` (скрытый, удобно в `.gitignore`). Пусто — всё в корень проекта. Legacy-алиас `service_subdir` читается, если `state_dir` отсутствует; новые конфиги пишут `state_dir` и очищают `service_subdir`.
- `ui_language`: язык стартовой инструкции для LLM (`docs/LLM_START.<lang>.md`). Fallback — `en`.
- `exec`: секция `run_python`. По дефолту выключена — включается явно.

## 3. Format (markdown)

<!-- summary: Пресеты + override синтаксиса, ключевых слов, нумерации. -->
<!-- tags: config, format -->

```json
{
  "format_preset": "default",
  "format": {
    "heading": { "prefix": "#", "min_level": 2, "max_level": 8 },
    "numbering": { "pattern": "^\\d+(?:\\.\\d+)*", "trailing_dot": true },
    "annotations": {
      "open": "<!--", "close": "-->",
      "case_sensitive": false,
      "summary":  { "keyword": "summary" },
      "tags":     { "keyword": "tags" },
      "large_ok": { "keyword": "large-ok", "bare": true },
      "flat":     { "keyword": "flat",     "bare": true }
    }
  }
}
```

**Пресеты:** `default`, `plain` (в `formats/presets_data/`).

**Конфигурируется:** синтаксис комментариев, ключевые слова, регистр, паттерн нумерации.
**Фиксировано:** роли маркеров, структура `Section`, семантика top-region.

## 4. Policy — три роли

<!-- summary: read / write / index, dict overrides с наследованием (per-project, лежит в <project>/.patch_applier/config.json). Заменяет mode=white/black. -->
<!-- tags: config, policy -->

**Роли:**

- **read** — чтение (`read_file`, `read_unit`, `grep`, ...).
- **write** — изменение (`replace_*`, `insert_block`, `set_annotation`, `create_file`, ...).
- **index** — включение в `INDEX.md` / `CODE_INDEX.md` / `CODE_INDEX_LUA.md`.

**Overrides** — dict `{path: bool}`:

```json
"filter": {
  "read":  { "overrides": { ".": false, "toolkit": true, "bridge.py": true } },
  "write": { "overrides": { "toolkit": true } },
  "index": { "overrides": { "toolkit": true } }
}
```

**Семантика:**

- `path: true` — путь явно разрешён
- `path: false` — путь явно запрещён
- Отсутствующий путь наследует ближайшего предка (по префиксу), дефолт — **разрешено**
- `.` — корень проекта

**Пример:**

```json
{ ".": false, "toolkit": true, "toolkit/tests/fixtures": false }
```

Это значит: по умолчанию всё запрещено, `toolkit/` разрешён, но `toolkit/tests/fixtures/` запрещён. Раньше (через `mode=white`) такую комбинацию выразить было нельзя.

### 4.1 Legacy-совместимость

Если в конфиге старый формат, `Policy.from_dict` разворачивает:

- `{ "mode": "white", "paths": [...] }` → `{ ".": false, **{p: True for p in paths} }`
- `{ "mode": "black", "paths": [...] }` → `{ **{p: False for p in paths} }`
- `{ "mode": "none" }` → пустой dict (всё разрешено)

Также принимается legacy flat-форма на верхнем уровне (`filter_mode` / `filter_dirs`) — применяется ко всем трём ролям одинаково.

## 5. Exec — запуск Python-скриптов

<!-- summary: Секция run_python. Выключена по умолчанию. -->
<!-- tags: config, exec -->

Секция `exec` управляет тулом `run_python`:

- `enabled` (bool, дефолт `false`) — пока `false`, любой вызов `run_python` возвращает `error_code="exec_disabled"` и ничего не запускает.
- `interpreter` (str | null) — путь к интерпретатору. По умолчанию `sys.executable` — тот же Python, что запустил toolkit.
- `allow_module_mode` (bool, дефолт `true`) — разрешает `run_python(module="...")` в дополнение к `script="..."`.
- `child_encoding` (str, дефолт `"utf-8"`) — кодировка `PYTHONIOENCODING` дочернего процесса и декодирования его stdout/stderr. Меняется только если legacy-скрипт ожидает другую.
- `default_timeout` / `max_timeout` — секунды. `timeout` в вызове больше `max_timeout` → ошибка.
- `max_output_bytes` — лимит на stdout и stderr по отдельности. Обрезка помечается флагом `stdout_truncated` / `stderr_truncated`.
- `env_passthrough` — список переменных окружения, пробрасываемых дочернему.
- `env_deny_patterns` — glob-паттерны, при совпадении с которыми переменная отбрасывается (секреты, токены).

**Не является песочницей.** Ограничивает форму запуска (только `sys.executable`, только внутри проекта, жёсткий таймаут, лимит вывода), но не эффекты скрипта.

## 6. MCP settings

<!-- summary: bridge script, command/args, timeouts, retry; native_tools (дефолт enabled=true); tools_schema.json в toolkit-global runtime/state. -->
<!-- tags: config, mcp -->

Используется `MCPBackend` и `CompositeBackend`. Секция `mcp` живёт в **tool-wide** файле (одинакова для всех проектов).

- `bridge_script` (str) — путь к `bridge.py`. Обычно `null`: bridge поставляется с toolkit, путь выводится из `__file__`. Явный путь — для override в тестах и кастомных bridge.
- `command` (str, дефолт `"python -u"`) — команда запуска bridge.
- `mcp_command` / `mcp_args` — как bridge запускает MCP-сервер Roblox. Дефолт — `cmd.exe` с переходом в `%LOCALAPPDATA%\Roblox` и запуском `mcp.bat`.
- `preflight` (bool) — проверять готовность Studio до handshake.
- `auto_switch` (bool) — автоматически переключать активный DataModel.
- `ready_timeout` / `studio_timeout` — секунды на handshake bridge и на ожидание Studio.
- `call_timeout` — таймаут одного `execute_luau`.
- `max_retries` / `retry_delay` — retry-политика для transient-ошибок («No Roblox Studio instances»).

### 6.1 Native tools (passthrough)

Секция `mcp.native_tools` разрешает вызов нативных инструментов Roblox по их оригинальным именам (`insert_asset`, `generate_mesh`, `execute_luau`, ...) через обычный JSON-патч:

```json
{
  "mcp": {
    "native_tools": {
      "enabled": true,
      "allow": ["insert_asset", "generate_mesh"]
    }
  }
}
```

- `enabled` (bool, **дефолт `true`**) — если `false`, любой вызов native tool возвращает `status=blocked, error_code="native_tools_disabled"`. Включайте осознанно: native tools не фильтруются политикой путей и могут создать/изменить/удалить любой инстанс в живой Studio.
- `allow` (список строк) — allowlist имён. Пустой список = «allow всё, что понимает bridge». Непустой = разрешены только перечисленные.

**Схема доступных bridge-инструментов** — `tools_schema.json`, генерируется bridge при старте и живёт в **toolkit-global** `<toolkit_root>/runtime/state/tools_schema.json` (не в проекте: файл одинаков для всех проектов). GUI подмешивает содержимое в стартовый текст для LLM, если включён Roblox-режим.

**Почему политики путей для Roblox не работают.** Native tool может изменить то же, что и унифицированный (`execute_luau` создаёт и правит `.Source` любого скрипта), поэтому path-фильтр на унифицированных тулах не даёт реальной защиты — только ложную уверенность. Доступ к Roblox гейтится на уровне backend: `backend=mcp|composite` + `native_tools.enabled`. См. `DECISIONS.md §1.18`.

Дефолты — в `backends/mcp.py`.

## 7. Что конфигурируется, что нет

**Да:** backend, Policy overrides, format preset + override, MCP settings, пути и состав индексов, секция `exec`, язык стартовой инструкции.

**Нет:** набор ролей Policy (фиксировано 3), набор маркеров markdown (summary/tags/large-ok/flat), структура `Section`/`Symbol`/`Result`, алгоритм diff.
