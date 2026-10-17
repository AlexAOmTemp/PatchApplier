# Patch Applier — стартовая инструкция для LLM

## 1. Что это и зачем
<!-- summary: Что такое Patch Applier, три идеи (индекс, unit-модель, детерминированный результат), структура стартового сообщения и опциональные дополнения. -->
**Patch Applier** — утилита правки проекта через **JSON-патчи**: один ответ = список действий (чтения и правки). Работает с docs, Python, Luau-кодом и Roblox-сценой (что включено — см. `get_status` внизу).

Три идеи:
1. **Индекс как карта.** `INDEX.md` / `CODE_INDEX.md` — где что. Не открывай файлы наугад; индекс пересобирается после write автоматически.
2. **Unit-модель.** Правка адресуется unit'ом (`read_unit` / `replace_unit` / `insert_block`), не текстом и не номером строки — не падает на пробелах и сдвиге.
3. **Детерминированный результат.** После патча — `Result` и diff индекса: что применилось и что изменилось.

**Структура стартового сообщения.** Этот документ + опциональные блоки `---` + `# Дополнение: <name>.md` (0–3, по включённым доменам: `RobloxCodeRules.md`, `MCPBridgeRules.md`, `XML_START.md`) + снимок `get_status` под `## Session`.

**Перед первым патчем прокрути сообщение до конца.** Прочитай блоки `# Дополнение:` — их правила применяются наравне с этим документом. Если блока нет — домен не включён, его тулы не вызывай. `get_status` читай первым: он говорит, что доступно.

**Этот документ — часть утилиты, не проекта.** Не правится обычными патчами.
## 2. Как читать этот документ
<!-- summary: Опциональные дополнения ниже (# Дополнение:), приоритет документа и унифицированных тулов над нативными MCP. -->
После этого документа в сообщении может быть **от 0 до 3 блоков** `---` + `# Дополнение: <name>.md` — по числу доменов, включённых в «Старт сессии»:
- `RobloxCodeRules.md` / `MCPBridgeRules.md` — Roblox-режим: правила кода и работа с мостом.
- `XML_START.md` — XML-тулсет (адресация, 10 тулов, дискриминаторы). Нет блока — `xml_*` не вызывай.

**Приоритет.** Правило из дополнения противоречит этому документу — приоритет у этого. Дополнения описывают **что** писать (домен); этот — **как** применяется.

**Приоритет инструментов.** Всегда предпочитай **унифицированные тулы** (`read_unit` / `replace_unit` / `insert_block` / `grep` / `get_index` / `run_python` и т.д. — §7): path-политика, лог, verify-after-write. **Нативные MCP-тулы** (`multi_edit`, `execute_luau`, `insert_asset`, …) — только когда унифицированного нет; их схемы — в `tools_schema.json`. Гейт `native_tools.enabled` выключен → `native_tools_disabled` (это гейт, не ошибка).
## 3. Оглавление
<!-- summary: Оглавление операторского справочника (16 секций) + опциональные дополнения ниже блока ---. -->
> 1. Что это и зачем
> 2. Как читать этот документ
> 3. Оглавление
> 4. Первые шаги в новой сессии
> 5. Формат патча
> 6. Парадигма: работа по структурным единицам
> 7. Действия, доступные тебе
> 8. Версии индекса и diff
> 9. Формат markdown-документов
> 10. Метки в индексе
> 11. Быстрый выбор тула
> 12. Что помнить
> 13. Коды ошибок
> 14. Чего не делать
> 15. С чего начать
> 16. Примеры патчей
>
> **Опциональные дополнения** (появляются как `---` + `# Дополнение: <name>.md`, по числу включённых доменов):
>
> - `RobloxCodeRules.md`, `MCPBridgeRules.md` — правила Roblox-кода и работа с мостом.
> - `XML_START.md` — XML-тулсет (адресация, 10 тулов, дискриминаторы).
## 4. Первые шаги в новой сессии
<!-- summary: Первые шаги: get_status (что в снимке), флаги политики R/W/Id/Ip/Il, get_index с обязательным kind. -->
**1. Проверь статус.** В стартовом сообщении обычно приложен `get_status` — это конфигурация сессии, не runtime; мост может быть не поднят (`backend_not_ready`). Важно: `sources:` и `Luau source:` (`mcp` — Studio, `rojo` — `.luau` на диске) задают формат путей; список индексов `[vN]`; `## Policy Filesystem` / `## MCP`; флаг `run_python`.

Нет статуса — запроси:
```json
[{"id": 1, "action": "get_status", "arguments": {}}]
```

**Флаги политики.** `R` read, `W` write, `Id`/`Ip`/`Il` — индекс docs/python/lua. Операция без флага → `■ blocked`. Разрешение на чтение не даёт запись.

**2. Получи индекс:**
```json
[{"id": 1, "action": "get_index", "arguments": {"kind": ["docs", "code"]}}]
```
`kind` (`docs` / `code` / `lua` / список) **обязателен** — выбирай домен явно. Индекс — карта мира: файлы, секции, диапазоны, зависимости. Не читай файлы целиком без нужды.
## 5. Формат патча
<!-- summary: Правило №1: ровно один фенс на ответ, внутри — несколько JSON-массивов подряд. Плюс id, изоляция групп, compiler messages, ##RESULT, объединение действий, diff после write. -->
**Правило №1. Нарушение = потеря патча.** Весь ответ — **ровно один** блок кода. Внутри — **несколько** независимых JSON-массивов подряд, по одному действию в каждом.

**✅ Правильно — один фенс, три группы:**
```json
[{"id": 1, "action": "read_file", "arguments": {"file_path": "a.py"}}]

[{"id": 2, "action": "replace_in_file", "arguments": {...}}]

[{"id": 3, "action": "rebuild_index", "arguments": {}}]
```

**❌ Неправильно:** отдельный фенс на каждую группу (пользователь копирует поштучно и теряет действия) либо все действия в одном массиве (слитая группа падает целиком).

**Самопроверка перед отправкой.** Открывающих фенсов — **ровно один** (или ноль). Открывающих `[` на верхнем уровне внутри фенса — столько же, сколько действий. Не сходится — перепиши.

**У каждого действия обязателен `id`.** Любое значение — число, строка, `null`; проверяется только на наличие. По нему ты сопоставляешь действие с ответом.

**Почему группы.** Каждая группа парсится независимо: ошибка в одной (запятая, скобка, кавычка, забытый `id`) не мешает остальным — валидные применяются, проблемная игнорируется и описывается в `=== Compiler messages ===`. Виды сообщений: `syntax` (не парсится JSON), `missing_id` (нет `id`), `duplicate_id` (две одинаковых метки — обе применились, метка неоднозначна).

**Результаты:** `✓ ok` / `✗ error` / `■ blocked` (политика/песочница) / `– skipped` (неизвестное действие). Префикс `[N]` — твой `id`, не позиция. Внизу — `##RESULT:{...}` со счётчиками `ok`/`errors`/`skipped` и списками `failed`/`blocked`.

**Патч — ручная операция, объединяй действия.** Пять мелких патчей = пять копипастов. Объединяй **механически связанные**: однотипные правки в одном файле, `rebuild_*` после write, чтение и правка одной сущности. Если следующее действие **зависит от результата** предыдущего (read → увидеть → write) — два патча.

**Проверяй diff индекса после write.** `+` добавлено, `~` изменено, `-` удалено. `-N` без намерения — аномалия (write-тул не теряет соседей); рядом стоит `⚠`.
## 6. Парадигма: работа по структурным единицам
<!-- summary: Правка через unit-модель, а не текст/номера строк; когда допустим текстовый escape hatch; per-line repr для точной замены; формат пути в MCP vs Rojo. -->
**Главное правило: правь файлы через структурные единицы, не через текст и не по номерам строк.**

`replace_range` (по номерам) и `replace_in_file` (по тексту) существуют, но ненадёжны: номера строк смещаются после правок, а `replace_in_file` падает на пробелах, невидимых символах и эскейпах. Для `.py` / `.lua` / `.luau` / `.md` используй unit-модель: `read_unit` / `replace_unit` / `insert_block`. Адрес — `qualname` (`Foo.bar`, `3`, `<module>`) или `title_match` (подстрока заголовка). Части `head` / `annotation` / `body`; блоки в body — `block`. Тулы сами пересчитывают позиции от AST/структуры и не зависят от предыдущих правок.

**Текстовый escape hatch** (`replace_between`, `replace_in_file`, `insert_at_anchor`, `replace_range`) — только для того, что unit-модель не адресует: комментарии между unit'ами, отдельные строки внутри statement'а, файлы без парсера, fenced-код в md. Работает на любом источнике (для Roblox — `.Source`).

**Точное чтение → точная замена.** `read_file` по умолчанию возвращает **per-line repr**: `45: 'def foo():   \n'`. Видно `\n` vs `\r\n`, хвостовые пробелы, табы. Копируй строку из `read_file` в `replace_in_file` — тул распакует литерал и сматчит точные байты. Оси: `numbered` (дефолт `true`), `escape` (`perline` / `blob` / `none`). `numbered=true` + `escape=blob` — ошибка. CRLF сохраняется.

**⚠ Формат пути зависит от режима Luau.** MCP-mode (`Luau source: mcp`) — dot-notation `ReplicatedStorage.X.Y` (первый сегмент — сервис). Rojo-mode — файловый путь (`src/ServerScriptService/Foo/init.luau`).
## 7. Действия, доступные тебе

### Чтение

| Действие | Аргументы |
|---|---|
| `read_file` | `file_path` + одно из: `section_number` (`"4"`, `"4.1"`), `section_title` (подстрока), `start_line`+`end_line`; иначе весь файл. Опц. `numbered` (дефолт `true`), `escape` (дефолт `perline`), `max_bytes` |
| `file_stat` | `file_path` — размер и разбивка по секциям |
| `file_exists` | `file_path` |
| `list_files` | `directory`, опц. `show_size`. >2000 файлов — вернёт счётчик и подсказку `survey_dir` |
| `survey_dir` | `path` (каталог), опц. `ext`, `top` (20). Агрегат «сколько файлов и каких расширений» + разбивка по подкаталогам. Первый контакт с незнакомым проектом |
| `tree` | `path`; опц. `max_dirs` (500), `max_types` (7), `max_depth` (50). **FS-only.** Только каталоги: size, число файлов, топ-типы. При обрыве — футер `stopped: ...`. Dotdirs скрыты |
| `grep` | `pattern` + (`paths`: список **файлов** / `directory`+`file_glob`); опц. `regex` (дефолт `true`), `fixed_strings`, `ignore_case`, `word_boundary`, `before`, `after`, `max_results`, `exclude_glob`. **Только файловая система**; Roblox-путь → `wrong_domain` |
| `grep_mcp` | `pattern` + `directory` (Roblox-путь: модуль или каталог); опц. `fixed_strings`, `ignore_case`, `before`, `after`, `max_results` (200). **Только Roblox.** Паттерн — **Lua patterns** (`%d`, `%w`, `.-`), не Python regex |

**Поля `Result`.** `status` (`ok`/`error`/`skipped`/`blocked`), `message`, `delta` (write), `verified`, `error_code`, `action`.

`read_file` без параметров — только для маленьких файлов. Для секции надёжнее `section_number`: заголовки могут повторяться. `paths` в `grep` — файлы, не каталоги (`bad_options`). `grep_replace` использует тот же матчер, что `grep`: что нашёл — то и заменит.

**Реконнессанс незнакомого корня.** Не начинай с `list_files` или `grep`. Сначала `tree(path)` — форма дерева в 100–500 строк вместо 30 000; потом `survey_dir` — плоский агрегат. Дальше точечно.
### Запись (текстовые тулы, escape hatch)

**Escape hatch** — только для того, что unit-модель не адресует: комментарии между unit'ами, отдельные строки внутри statement'а, файлы без парсера, fenced-код в md. Всё остальное — unit-тулы.

| Действие | Аргументы |
|---|---|
| `replace_in_file` | `file_path`, `search`, `replace`, опц. `occurrence` (число или `"all"`), `search_repr` (дефолт `true`), `regex` (дефолт `false`) |
| `replace_range` | `file_path`, `start_line`, `end_line`, `new_content`, **настоятельно рекомендуется** `expected_first_line` |
| `replace_between` | `file_path`, `start_anchor`, `end_anchor`, `new_content`, опц. `include_start`/`include_end` (`true`), `occurrence` (`1`) |
| `insert_at_anchor` | `file_path`, `anchor`, `position` (`"before"`/`"after"`), `new_content`, опц. `occurrence` (`1`) |

**Правила.** `search` **копируй из вывода `read_file`**, а не набирай вручную — иначе промахи по пробелам и эскейпам. Бери 2–3 строки контекста, одной мало. `replace_in_file` терпит расхождение в trailing whitespace (сообщит пометкой), но не в отступах; `no_match` покажет похожие строки с маркерами `␣` / `⇥`. `regex: true` — Python-regex с `\1`-backrefs. `expected_first_line` в `replace_range`: не совпало → `content_mismatch`, файл не тронут. `replace_between` — основной тул для многострочных замен; якоря короткие и уникальные.

**`replace_range` и `replace_in_file` — не надёжны.** Только когда структурного тула нет.
### Массовая замена по файлам (`grep_replace`)
<!-- summary: grep_replace — массовая замена по файловой системе, симметричная с grep. Общий матчер, двухпроходный гейт (no_matches как ok / too_many_replacements до записи), dry_run=true по умолчанию, per-file atomic write. Работает на docs, Python, Luau-на-диске (Rojo). Не путать с grep_replace_mcp. -->

**`grep_replace`** (FS) и **`grep_replace_mcp`** (Roblox `.Source`) — find-and-replace по многим файлам. Симметричны парным `grep` / `grep_mcp`: те же `paths`/`directory`+`file_glob`/`exclude_glob`, `regex`, `fixed_strings`, `ignore_case`, `word_boundary`. **Что нашёл grep — то и заменит.** Не путать с `replace_in_file` (точная замена в одном файле).

**Контракт.** Ровно одно из: `pattern`+`replacement`, либо `mappings` (`[{"from": ..., "to": ...}]`, требует `fixed_strings=true`, применяется одновременно longest-first).

**Гейт.** `dry_run=true` по умолчанию. `total == 0` → `ok`/`no_matches` («не найдено» — не ошибка). `total > max_replacements` (1000) → `too_many_replacements`, ничего не записано. Запись — только `dry_run=false`; у FS-версии per-file policy и возможен частичный откат, у MCP — атомарно.

**Стратегия.** A — `grep` → `grep_replace(dry_run=true)` → `dry_run=false`. B — сразу `dry_run=false, max_replacements=N` (N = ожидаемое число); больше — откажется. Замена текстовая, без AST: комментарии и строки включаются.
### Roblox: массовая замена через мост (`grep_replace_mcp`)
<!-- summary: Ссылка на объединённую секцию grep_replace: та же семантика для .Source. -->
См. выше: `grep_replace_mcp` — та же семантика для `.Source` через мост; матчер общий с `grep_mcp` (Lua patterns).
### Файловые операции

| Действие | Аргументы |
|---|---|
| `create_file` | `file_path`, `file_content`; опц. `class_name` (для Roblox — `ModuleScript` по умолчанию, также `Script` / `LocalScript`). Ошибка, если существует |
| `overwrite_file` | `file_path`, `file_content` |
| `delete_file` | `file_path` |
| `move_file` | `source_path`, `destination_path`. **Кросс-домен запрещён** (FS ↔ Roblox) |
| `copy_file` | `source_path`, `destination_path` — байтовая копия, source остаётся. **Кросс-домен запрещён**: FS ↔ Roblox не копируется (разные модели хранения) |

### Unit-операции: единая модель для `.py` / `.lua` / `.md` (приоритетно)

**Модель.** Файл — дерево **unit'ов**. Unit: `module` / `function` / `method` / `class` / `section`.
- **Адрес**: `{"qualname": "Foo.bar"}` (Python/Lua), `{"qualname": "3"}` (md-секция), `{"qualname": "<module>"}` (модуль). Плюс матчер `{"title_match": "Format"}` — подстрока в заголовке (поиск, не адрес). `section_number`/`section_title` в `address` не поддерживаются.
- **Три части**: `head` (объявление), `annotation` (docstring / `--[[ ]]` / `<!-- summary: -->`; может отсутствовать), `body` (тело).
- **blocks** — нумерованные элементы в body: statements в функции, методы в классе, подсекции в секции. `block=3`, `"1-10"`, `[1,3,7]`.

**Модуль:** head до первого def/class/function; всё дальше — body. **Декораторы Python** входят в head функции/класса. **`part`** — строка или список (`"head,annotation"`), порядок `head → annotation → body`. У md-секций есть `own_body` — тело без подсекций. `part` и `block` вместе нельзя; неоднозначность → `occurrence=N` (иначе `ambiguous_symbol`).

| Действие | Аргументы |
|---|---|
| `list_units` | `file_path` — карта: qualname + kind + L-range + число блоков |
| `read_unit` | `file_path`, `address`; опц. `part`, `block`. Блоки — с метками `=== block N ===` |
| `replace_unit` | `file_path`, `address`, `new_text`, **ровно одно из `part` / `block`** (иначе `scope_required`). `part="all"` — целиком; `"body"` — только тело; `"own_body"` — без подсекций; `"annotation"` — docstring/summary. Пустой `new_text` → `empty_input` (для удаления — `remove_unit`) |
| `remove_unit` | `file_path`, `address`, ровно одно из `part` / `block`. Фаза 1: `part="all"` или `block` |
| `create_unit` | `file_path`, `address`, `part`, `new_text`. Фаза 1: `part="annotation"` — создать, если нет (`already_exists` иначе) |
| `insert_block` | `file_path`, `address`, `new_text`, `position` (`start`/`end`/`before`/`after`); `anchor` — номер блока или qualname (для before/after) |

**Write-тулы** после записи парсят текст повторно: сломал парсинг или потерял unit → `result_syntax_error` / `result_missing_symbol`, файл не тронут. Отступ и EOL сохраняются.

**Lua.** Blocks внутри функций не нумеруются (`blocks=0`) — для правки тела `replace_unit part="body"`. В Rojo путь файловый, в MCP — `Service.X.Y` без расширения; адаптер один, `list_units`/`read_unit` работают одинаково.
### Граф и модульный поиск

| Действие | Аргументы |
|---|---|
| `find_symbol` | `query` (подстрока qualname или путь модуля) |
| `find_usages` | `query` (подстрока пути модуля); опц. `limit`, `local`. Модульный: `imports` / `used by` |
| `symbol_graph` | `qualname`; опц. `occurrence`, `depth` (`1`), `max_nodes` (`300`), `kind` (`code`/`lua`), `local` |
| `copy_unit` | `source_file`, `target_file`, `selector`, опц. `position`, `anchor`, `container` |

`symbol_graph` — обход по рёбрам, не поиск: от известного символа вниз на `depth`, callers — 1 уровень вверх. Граф эвристичен (`getattr`, `from X import *` — в `unresolved`).
### Индексы

| Действие | Аргументы |
|---|---|
| `get_index` | `kind` (`docs`/`code`/`lua`/список) — **обязателен**; опц. `max_bytes` |
| `get_status` | опц. `sections` (`session`/`indexes`/`policy`) |
| `rebuild_index` | опц. `docs_dir`, `output`, `skip_files` |
| `rebuild_code_index` | опц. `code_dir`, `output`, `manifest_output`, `skip_files`, `skip_dirs` |
| `rebuild_lua_code_index` | требует MCP (Roblox) |

`rebuild_*` возвращают `[vN]` и diff. `⚠` в конце diff-строки = были удаления (`-N`); удаление соседнего unit'а без намерения — аномалия, разберись.
### Исполнение

| Действие | Аргументы |
|---|---|
| `run_python` | одно из `script` (путь `.py` в проекте) / `module` (dotted-name); опц. `args`, `cwd`, `timeout`, `max_bytes`, `env` |
| `verify_syntax` | `paths` (файлы/каталоги `.py`) или `directory`; компилирует без импорта и побочных эффектов |

**⚠ `module=` = `python -m` = `__main__`:** модуль с `if __name__ == "__main__":` запустится (был инцидент — второй GUI поломал мост). Для проверки синтаксиса — `verify_syntax`. Гейт `exec.enabled`; только `sys.executable`, внутри проекта, таймаут и лимит вывода. Это **не песочница**. `run_python` не подчиняется `filter.read`/`filter.write` — своя проверка «внутри проекта».
### Native Roblox tools (если разрешены)

Если `mcp.native_tools.enabled`, нативные Roblox-тулы вызываются в том же формате под оригинальными именами: `{"action": "insert_asset", "arguments": {...}}`. Правила — в `MCPBridgeRules.md`, схемы — в `tools_schema.json`. Гейт выключен → `native_tools_disabled` (не ошибка). Используй только когда унифицированного тула нет.
## 8. Версии индекса и diff

<!-- summary: Три правила чтения diff: проверяй после каждого write, при неожиданном сверяй [vN], пустой diff ≠ файлы не менялись. -->
1. **После каждого write-патча проверяй diff индекса** — он показывает реальные изменения на диске, а не намерения патча. Пустой diff = на диске ничего не поменялось.
2. **Diff не тот, что ожидал — сверь `[vN]`.** Номер вырос на 2+ — был пропущенный rebuild; перечитай `get_index`, не складывай diff'ы из памяти.
3. **`[без изменений]` ≠ «файлы не менялись».** Это «индекс совпадает с тем, что было бы собрано сейчас»; если `[vN]` вырос, изменения уже учтены кем-то раньше.
## 9. Формат markdown-документов

Индекс парсит заголовки строго:

```
## N. Название              ← секция верхнего уровня
<!-- summary: одна строка -->  ← обязательно для ##
<!-- tags: a, b -->           ← опционально

тело

### N.M Название           ← подсекция
<!-- summary: ... -->        ← опционально
```

- Заголовки: `## N.`, `### N.M`, `#### N.M.K` (пробел после номера, точка только у `##`).
- `summary` — одна строка, без переносов.
- `tags` — через запятую, опционально.

## 10. Метки в индексе
<!-- summary: Пять самых частых меток индекса: stale, large, cycle, main, users. Метки — факты, интерпретирует LLM. -->
Метки — **факты** из AST или пути, интерпретируешь сам. Чаще всего:

- `⚠ stale` (md) — тело менялось после подтверждения summary; обнови annotation через `replace_unit(part="annotation")`.
- `⚠ large` — не читай целиком: секциями / unit'ами / `max_bytes`.
- `⚠ cycle` — модуль в цикле импортов.
- `◉` (Python) — есть `if __name__ == "__main__":`.
- `→ N users (M tests)` — сколько модулей импортируют; M из них — тесты.

Не знаешь метку — прочитай файл и действуй по факту: метка сама по себе к действию не обязывает.
## 11. Стратегии
<!-- summary: Быстрый выбор тула: задача → инструмент. Примеры — в §16. -->

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

Примеры патчей — §16.
## 12. Что помнить
<!-- summary: Что помнить: формат, читать перед правкой, проверять diff, blocked ≠ error, не полагаться на память, скрытое закрыто. -->
- **Правило №1 — формат** (§5): один фенс, несколько массивов.
- **Перед правкой прочитай актуальное**, после write — проверь diff: `-N` с `⚠` — аномалия.
- **`blocked` ≠ `error`** — не повторяй, сообщи пользователю.
- **Не полагайся на память** — факт для решения перечитай.
- **Скрытое = закрытое**: `.patchignore`, dotdir'ы, `.patch_applier/` не открываются прямыми путями; индексы — через `get_index` / `get_status`.
## 13. Коды ошибок
<!-- summary: Коды ошибок: топ-16 операциональных кодов с действиями, blocked ≠ error, не гадать при not_found/ambiguous. -->
`Result` содержит `error_code` — машиночитаемую метку. Что делать:

| Код | Что значит | Что делать |
|---|---|---|
| `not_found` | unit / секция / файл / адрес не найдены | Прочитай индекс или `read_unit` / `read_file`; не угадывай |
| `ambiguous_symbol` | адрес встречается N раз | Передай `occurrence=N` (L-диапазоны в сообщении) |
| `occurrence_out_of_range` | N вне диапазона | Смотри реальное число в сообщении |
| `no_match` | `replace_in_file`: `search` не найден | Прочитай `Similar lines` — обычно пробел/таб; копируй `search` из `read_file` |
| `no_annotation` | `replace_unit(part="annotation")` без annotation | Создать — `create_unit(part="annotation")` |
| `empty_input` | `new_text` пустой | Для удаления — `remove_unit` |
| `scope_required` / `scope_conflict` | `replace_unit` без `part`/`block` или с обоими | Ровно одно из двух |
| `syntax_error` / `result_syntax_error` | файл / новый текст не парсится | Файл не тронут; поправь `new_text` |
| `result_missing_symbol` | после правки unit исчез | Патч отменён; перечитай файл |
| `range_order` / `range_after_write` | `replace_range` сверху вниз или после другого write | Сначала `replace_range` снизу вверх, **до** других write на файл |
| `hidden_path` / `filter` / `sandbox` | `status=blocked`: политика / песочница | Не retry — сообщи пользователю |
| `backend_not_ready` | MCP (Roblox) не поднят | Попроси нажать `↻` в GUI |
| `native_tools_disabled` / `exec_disabled` | гейт в конфиге | Не ошибка — тул просто недоступен |
| `timeout` / `nonzero_exit` | `run_python` | Сообщение содержит `TIMED_OUT` / `exit=N` |
| `already_exists` | `create_file` / `create_unit(annotation)` | Файл уже есть; для annotation — `replace_unit` |
| `source_changed` (XML) | `source_hash` не совпал | Перечитай `xml_read`, повтори с новым хешем |

Код не в таблице — прочитай `message`: он обычно объясняет причину. Не retry `blocked`. Не гадай адрес при `not_found` / `ambiguous_*`.
## 14. Чего не делать
<!-- summary: Чего не делать: разорванный фенс и слитый массив, текстовые тулы вместо unit, не retry blocked, не гадать, большие файлы — по частям. -->
- **Правило №1 — формат** (§5). Один фенс, внутри несколько JSON-массивов. Разорванный фенс и слитый массив — две самые частые ошибки.
- **Для `.py` / `.lua` / `.luau` / `.md` — unit-тулы**, не `replace_range` и не `replace_in_file` (они — escape hatch, §6).
- **`replace_range` на файл — только снизу вверх и до других write на тот же файл** (`range_order` / `range_after_write`).
- **Не retry `blocked`.** Это политика или песочница, не transient-ошибка.
- **Перед правкой — перечитай актуальное** (`read_unit` / `read_file`). Исключение — `create_file` для точно отсутствующего файла.
- **Не гадать при `not_found` / `ambiguous_symbol`** — прочитай индекс или unit.
- **Файлы >100 KB — только секциями** (`section_number` / `max_bytes`).
## 15. С чего начать

1. Прочитай статус — обычно он приложен в конце стартового текста; если нет — запроси `get_status`.
2. `get_index` — увидеть карту.
3. Читать секцию → править секцию → проверять.
4. Если что-то неясно — спроси пользователя, не гадай.

## 16. Примеры патчей
<!-- summary: Два ключевых примера патчей: правка тела функции Python и правка секции md (body + annotation). Остальное — схемы §7. -->
**Один пример = один патч = один фенс.** Все группы — в одном блоке кода (§5).

**Правка функции Python — заменить тело, сохранив сигнатуру:**
```json
[{"id": 1, "action": "read_unit",
  "arguments": {"file_path": "toolkit/core/patcher.py",
                "address": {"qualname": "Patcher._apply_one"},
                "part": "head,annotation"}}]

[{"id": 2, "action": "replace_unit",
  "arguments": {"file_path": "toolkit/core/patcher.py",
                "address": {"qualname": "Patcher._apply_one"},
                "part": "body",
                "new_text": "return self._dispatch(patch)"}}]
```
`part="body"` сохраняет head и annotation.

**Правка секции md — обновить body и annotation:**
```json
[{"id": 1, "action": "replace_unit",
  "arguments": {"file_path": "docs/CONFIG.md",
                "address": {"qualname": "3"},
                "part": "body",
                "new_text": "Новое тело секции."}}]

[{"id": 2, "action": "replace_unit",
  "arguments": {"file_path": "docs/CONFIG.md",
                "address": {"qualname": "3"},
                "part": "annotation",
                "new_text": "Обновлённое описание"}}]
```

**Остальное — через схемы §7.** Граф — `symbol_graph`; создание — `create_file` + `rebuild_index`; удаление — `remove_unit`.
