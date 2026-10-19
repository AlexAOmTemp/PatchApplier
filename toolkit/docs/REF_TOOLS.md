# REF_TOOLS — полные схемы тулов
<!-- pa: suppress no-summary -->

Справочник аргументов. В `LLM_START.ru.md` — компактные сигнатуры, здесь — полные. Грузить при первом использовании незнакомого/редкого тула.

## Чтение

| Действие | Аргументы |
|---|---|
| `read_file` | `file_path` + одно из: `section_number` (`"4"`, `"4.1"`), `section_title` (подстрока), `start_line`+`end_line`; иначе весь файл. Опц. `numbered` (дефолт `true`), `escape` (`perline`/`blob`/`none`, дефолт `perline`), `max_bytes` (дефолт 32768; `0` — без капа) |
| `file_stat` | `file_path` — размер и разбивка по секциям |
| `file_exists` | `file_path` |
| `list_files` | `directory`, опц. `show_size`, `scoped` (дефолт `true`), `recursive`, `show_hidden`. >2000 файлов — вернёт счётчик и подсказку `survey_dir` |
| `survey_dir` | `path`, опц. `ext`, `top` (20), `scoped` (дефолт `true`) |
| `tree` | `path`; опц. `max_dirs` (500), `max_types` (7), `max_depth` (50), `scoped`. **FS-only** |
| `grep` | `pattern` + (`paths`: список файлов / `directory`+`file_glob`); опц. `regex` (дефолт `true`), `fixed_strings`, `ignore_case`, `word_boundary`, `before`, `after`, `max_results` (200), `exclude_glob`, `scoped`. **FS-only**; Roblox-путь → `wrong_domain` |
| `grep_mcp` | `pattern` + `directory` (Roblox-путь); опц. `fixed_strings`, `ignore_case`, `before`, `after`, `max_results` (200). Паттерн — **Lua patterns**, не Python regex |

`paths` в `grep` — файлы, не каталоги (`bad_options`). `grep_replace` использует тот же матчер.

## Запись (escape hatch)

Только для того, что unit-модель не адресует: комментарии между unit'ами, отдельные строки внутри statement'а, файлы без парсера, fenced-код в md.

| Действие | Аргументы |
|---|---|
| `replace_in_file` | `file_path`, `search`, `replace`, опц. `occurrence` (число или `"all"`), `search_repr` (дефолт `true`), `regex` (дефолт `false`) |
| `replace_range` | `file_path`, `start_line`, `end_line`, `new_content`, **настоятельно** `expected_first_line` |
| `replace_between` | `file_path`, `start_anchor`, `end_anchor`, `new_content`, опц. `include_start`/`include_end` (`true`), `occurrence` (`1`) |
| `insert_at_anchor` | `file_path`, `anchor`, `position` (`before`/`after`), `new_content`, опц. `occurrence` (`1`) |

`search` копируй из вывода `read_file` (per-line repr), а не набирай вручную. `regex: true` — Python-regex с `\1`-backrefs.

## Массовая замена

**`grep_replace`** (FS) и **`grep_replace_mcp`** (Roblox `.Source`) — find-and-replace по многим файлам. Симметричны `grep`/`grep_mcp`.

| Параметр | Значение |
|---|---|
| Ровно одно из | `pattern`+`replacement` ИЛИ `mappings` (`[{"from":...,"to":...}]`, требует `fixed_strings=true`) |
| Гейт | `dry_run=true` по умолчанию; `total>max_replacements` (1000) → `too_many_replacements`, ничего не записано |
| Возврат | `total == 0` → `ok`/`no_matches` (не ошибка) |

Стратегия: `grep` → `grep_replace(dry_run=true)` → `dry_run=false`.

## Unit-операции

Файл — дерево **unit'ов**: `module` / `function` / `method` / `class` / `section`. Адрес — `{"qualname": "Foo.bar"}` (Python/Lua), `{"qualname": "3"}` (md), `{"qualname": "<module>"}`. Плюс матчер `{"title_match": "..."}`.

Три части: `head` (объявление), `annotation` (docstring / `--[[ ]]` / `<!-- summary: -->`), `body` (тело). `blocks` — нумерованные элементы в body (`block=3`, `"1-10"`, `[1,3,7]`).

| Действие | Аргументы |
|---|---|
| `list_units` | `file_path` — карта: qualname + kind + L-range + число блоков |
| `read_unit` | `file_path`, `address`; опц. `part` (`head,annotation`, `body`, `own_body`, `all`), `block` |
| `replace_unit` | `file_path`, `address`, `new_text`, **ровно одно из** `part` / `block`. `part="all"` — целиком; `"body"` — тело; `"own_body"` — без подсекций; `"annotation"` — docstring |
| `remove_unit` | `file_path`, `address`, ровно одно из `part` / `block` |
| `create_unit` | `file_path`, `address`, `part`, `new_text`. Фаза 1: `part="annotation"` |
| `insert_block` | `file_path`, `address`, `new_text`, `position` (`start`/`end`/`before`/`after`); `anchor` — номер блока или qualname |
| `copy_unit` | `source_file`, `target_file`, `selector`, опц. `position`, `anchor`, `container` |

**Lua.** Blocks внутри функций не нумеруются (`blocks=0`) — для правки тела `replace_unit part="body"`.

## Файловые операции

| Действие | Аргументы |
|---|---|
| `create_file` | `file_path`, `file_content`; опц. `class_name` (`ModuleScript`/`Script`/`LocalScript`). Ошибка, если существует |
| `overwrite_file` | `file_path`, `file_content` |
| `delete_file` | `file_path` |
| `move_file` | `source_path`, `destination_path`. **Кросс-домен запрещён** (FS ↔ Roblox) |
| `copy_file` | `source_path`, `destination_path`. **Кросс-домен запрещён** |

## Индексы

| Действие | Аргументы |
|---|---|
| `get_index` | `kind` (`docs`/`code`/`csharp`/`lua`/список) — **обязателен**; опц. `max_bytes` (дефолт 32768; `0` — без капа), `limit` (500; `0` — все), `path` (срез по поддереву), `sort` (`path`/`size`), `scoped` |
| `get_status` | опц. `sections` (`session`/`indexes`/`policy`/`scope`). Секция `## Scope` показывается, если scope непустой |
| `rebuild_index` | опц. `docs_dir`, `output`, `skip_files` |
| `rebuild_code_index` | опц. `code_dir`, `output`, `manifest_output`, `skip_files`, `skip_dirs` |
| `rebuild_csharp_index` | то же |
| `rebuild_lua_code_index` | требует MCP (Roblox) |

`rebuild_*` возвращают `[vN]` и diff. `⚠` в конце diff-строки = были удаления (`-N`).

`get_index` в structure-режиме (`code`/`csharp`/`lua`) — по строке на модуль с метками (`⧉dub:N`, `⚠ large`, `◉`, `← N imp`, `→ N users`).

## Граф и модульный поиск

| Действие | Аргументы |
|---|---|
| `find_symbol` | `query` (подстрока qualname или путь модуля); опц. `kind`, `limit`, `max_bytes`, `local`, `scoped`, `manifest_path` |
| `find_usages` | `query` (подстрока пути модуля); опц. `limit`, `local`, `scoped`, `manifest_path` |
| `symbol_graph` | `qualname`; опц. `occurrence`, `depth` (`1`), `max_nodes` (`300`), `kind`, `local` |

Граф эвристичен (`getattr`, `from X import *` — в `unresolved`).

## Scope

| Действие | Аргументы |
|---|---|
| `get_scope` | — |
| `exclude` | `patterns` (строка или список), `reason` (опц., дефолт `llm-session`) |
| `include` | `patterns`, `reason` (опц.) — re-inclusion (`!pattern`) |
| `set_scope` | `text` — заменить целиком |
| `clear_scope` | — |

Что фильтруется: `get_index`, `tree`, `grep` (по `directory=`), `list_files`, `survey_dir`, `find_symbol`, `find_usages` — при `scoped=true` (дефолт). Что НЕ фильтруется: `read_file`/`read_unit`/`file_stat`/`file_exists` (явный путь), `grep(paths=[...])`, `find_*` с явным `manifest_path`.

`scoped=false` — на один вызов, scope игнорируется, файл не меняется.

## Исполнение

| Действие | Аргументы |
|---|---|
| `run_python` | одно из `script` (путь `.py`) / `module` (dotted-name); опц. `args`, `cwd`, `timeout`, `max_bytes`, `env` |
| `verify_syntax` | `paths` (файлы/каталоги `.py`) или `directory` |

⚠ `module=` = `python -m` = `__main__`: модуль с `if __name__ == "__main__":` запустится. Для проверки синтаксиса — `verify_syntax`.

## Нативные Roblox-тулы

Если `mcp.native_tools.enabled`, нативные Roblox-тулы вызываются в том же формате: `{"action": "insert_asset", "arguments": {...}}`. Схемы — `tools_schema.json`. Выключено → `native_tools_disabled` (не ошибка).

## Стратегии (задача → тул)

| Задача | Тул |
|---|---|
| Прочитать секцию / файл | `read_file` / `read_unit` |
| Заменить тело функции | `replace_unit part="body"` |
| Заменить «своё» тело md-секции | `replace_unit part="own_body"` |
| Удалить метод / unit | `remove_unit(block=N)` / `remove_unit(part="all")` |
| Вставить statement | `insert_block` |
| Найти unit / кто вызывает / кто импортирует | `find_symbol` / `symbol_graph` / `find_usages` |
| Точная / regex-замена строки | `replace_in_file` (`regex=true`) |
| Первый взгляд на незнакомый корень | `tree` / `survey_dir` |
| Массовая замена (FS / Roblox) | `grep_replace` / `grep_replace_mcp` |
| Пересборка индекса | `rebuild_*` (авто при write) |
| Запустить скрипт | `run_python` |
