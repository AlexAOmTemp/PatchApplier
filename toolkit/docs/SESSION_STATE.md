# SESSION_STATE — состояние между сессиями

<!-- summary: Snapshot of what was done in the last big session (unified text matcher + source_hash full-source + Lua index write fix + verify_syntax fix + GUI settings UX + scope design) and what to pick up next. Update on session close, read on session start. -->
<!-- tags: session, state, bridge -->

## Зачем этот документ

LLM_START — стабильная инструкция. DECISIONS — почему так решено. SESSION_STATE — **где мы прямо сейчас**: что закрыто в последней сессии, что открыто, что первым делом проверить при следующем старте.

Обновляется **в конце каждой большой сессии** (или при смене контекста). Читается **первым делом** в новой сессии, вместе с `get_status`.

## Сессия: единый текстовый матчер + фиксы индекса + GUI settings UX (закрыта)

**Тема:** снять накопившийся долг по текстовому матчингу, найти и починить баги индекса (лимит 2048, двойной префикс), привести в порядок GUI settings, зафиксировать дизайн `.llmscope` в DECISIONS.

**Git log:** `fba696c` (матчер + индекс + LLM_START) → `94c5dd1` (GUI settings UX) → `255bdc2` (scope design + session state).

### Ключевые решения

- **Формат патча — один фенс на весь ответ.** Формулировка «один фенс на патч» была слабее: оставляла дыру «а если в ответе два патча». Упростили до одной строки + проверка «посчитай фенсы перед отправкой».
- **`source_hash` без лимита.** Лимит 2048 байт убран во всех трёх местах (Python `formats/code.py`, Lua `lua_symbols.lua`, `code_index_regen.lua`). **Мотивации лимита не нашли** ни в коде, ни в доках — считаем техническим долгом. Кросс-сравнение Python↔Lua хешей нигде не используется (grep пуст).
- **Lua-индекс и `backend.write`.** `RebuildLuaCodeIndexTool` писал через `Path.write_text` в обход backend (двойной префикс `.patch_applier/.patch_applier/`). Приведён к тому же способу, что `RebuildIndexTool` и `RebuildCodeIndexTool` — все три через `backend.write`. Унификация достигнута без отдельного хелпера.
- **Scope — отложен.** Дизайн зафиксирован в `DECISIONS §2.2`. Два варианта: A (scope режет build индекса) и B (фильтруется только представление). Три мотивации: handoff через контекстные окна, индекс на больших корнях, повторение `directory=`. Метрика готовности: 3+ случая за сессию, когда нужна «записка себе». Сейчас — 0.
- **GUI settings — простота важнее структуры.** Пробовали три вложенных LabelFrame в Sources — оказалось громоздко. Вернулись к плоскому списку, переименовали кнопки: `Hide paths` → `FS ignore`, `Hide modules` → `MCP ignore`. Описания — внутри диалогов.

### Что сделано

**LLM_START (ru + en):**
- §5 — упрощён до одного правила про фенс + проверки. Антипаттерн «разорванный фенс» удалён (не понадобился).
- §8 — переписан в три операциональных правила чтения diff: (1) проверяй diff после каждого write, (2) сверяй `[vN]` при неожиданном, (3) `[без изменений]` ≠ «файлы не менялись» (warm-up мог уже собрать).
- §16 — шапка «один пример = один патч = один фенс».
- §12 — короткое напоминание про фенс.
- §7 EN — `replace_unit` синхронизирован с RU (был устаревший + осиротевшая строка).

**Единый текстовый матчер (`toolkit/matching/text.py`):**
- `find_all_text` / `find_text` / `similar_lines` / `mark_invisible` / `TextMatch` / `Rule`.
- Tier 1 (byte-exact) и tier 2 (trailing-whitespace tolerance) — общие для всех write-тулов.
- Переведены: `replace_in_file`, `replace_between`, `insert_at_anchor`, `replace_range` (tier-2 tolerance для `expected_first_line`).
- Удалено 92 строки дублирующих хелперов (`_find_all`, `_find_normalised`, `_similar_lines`, `_mark_invisible`, `_rstrip_lines`).
- 27 тестов в `tests/test_matching_text.py`. `run_all.py` расширен (заодно вернул забытые `test_replace_in_file`, `test_range_order`).

**Индекс и диффы:**
- `source_hash` без лимита (см. выше). Тест `test_code_parser.py` инвертирован.
- Lua-индекс пишется через `backend.write`, двойной префикс убран.
- `verify_syntax` — починен баг: `compile(src, path, "exec", doraise=True)` — у builtin `compile()` нет `doraise`.
- `tools/__init__.py` — выпил 13 мёртвых импортов; `__all__` больше не врёт. `unit/__init__.py` — убраны `ReplaceBlockTool` / `DeleteBlockTool`.

**GUI settings (`settings_window.py`):**
- `Sources` — плоский список, кнопки `FS ignore` / `MCP ignore` справа на своих строках.
- Окна редакторов `.patchignore` / `.mcpignore` — заголовок, описание (что делают, куда применяются), список **только правил** (без комментариев и пустых строк).
- Кнопка `Disable` / `Enable` — правило с префиксом `@` серое, не работает. Формат: `@pattern`, `@!pattern` (disabled negation). `Rule` dataclass + `serialize()` в конфигах.
- Крестик окна: если были изменения — `askyesnocancel` «Save changes?» (Yes / No / Cancel). Раньше крестик = молчаливая отмена.
- Окна центрируются на родителе (`_center_on_parent`, `Tk` на Windows сам не центрирует).
- Главное окно: `format_project_label` показывает **имя проекта** без пути и без `[composite]`.
- Путь в настройках — readonly, копируется.
- Дефолтные `.patchignore` / `.mcpignore` — только правила, без комментариев.

**Пост-коммитные фиксы (после закрытия записи):**
- **Зависание при открытии редактора правил в новом проекте.** `_center_on_parent` вызывал `parent.update_idletasks()`, что синхронно выполняло pending `_sync_all` (от недавних чекбоксов) — скан большого корня блокировал GUI-поток, окно уже было с `grab_set()`, Windows решал «Not Responding». Убрал `update_idletasks`, `grab_set` перенесён в конец билда диалога.
- **Воркфлоу нового проекта.** `create_project` пишет `workspace.json` + ignore-файлы, **не** пишет `config.json`. `project_ok` теперь проверяет наличие `config.json`; нет его — «проект не настроен». `_menu_new_project` после создания обнуляет источники в памяти и сразу открывает `Project settings`. Настройки сохранили — `_cfg.save` создаёт `config.json`, `_switch_project` поднимает сессию. Старые проекты не затронуты: `_switch_project` при открытии пишет config.json с дефолтами как и раньше.

**Docs:**
- `DECISIONS §2.2` — снятие лимита 2048 и двойной префикс.
- `DECISIONS §2.2` — scope design (мотивации, варианты A/B, статус «отложено»).
- `SESSION_STATE` — обновлён.

### Что открыто

- **`.llmscope`** — обсуждено, отложено. Дизайн в `DECISIONS §2.2`. Метрика возврата: 3+ реальных случая за сессию.
- **`.lua` / `.luau` не триггерит auto-lua** в `router._classify_path` — дыра для Rojo-backend. Для текущего `luau: mcp` не критично.
- **`_lua_script` кэш без mtime.** Правки Lua-скриптов видны только после рестарта GUI (для разработчика утилиты). Задокументировано, ничего не делаем.
- **Единый текстовый матчинг — этап 2.** EOL tier (`eol` / `eol+trailing`) — нормализация `\r\n` ↔ `\n` в матчере. Сейчас CRLF обрабатывается в каждом туле отдельно.
- **`get_index overview` / `path_filter`.** Сжатый вид на 5 KB; фильтр по путям для одного файла.
- **Rojo backend.** Третий namespace.
- **Символьный reverse phase 2, diff edges, новые маркеры.** См. `DECISIONS §2.2`.
- **Пороги маркеров в конфиг.** `_LARGE_FILE_LINES` / `_LARGE_FILE_KB` / `_LARGE_SYMBOL_LINES` — hard-coded в `renderer.py`.
- **`TOOL_PRACTICE §2`** — таблица «Инвентарь» устарела после удаления символьных тулов.
- **Lua reverse-dep graph** — `script.*`-формы не резолвятся в `_invert_lua_imports`.

### Пост-коммитные фиксы (продолжение, коммиты `417de98` … `2fd0c8a`)

После закрытия записи нашли и починили ещё четыре бага в GUI настроек:

- **Бесконечный цикл `luau_var.set`.** При регистрации трейсов до начального `_sync_all()` `luau_var.set("mcp")` в `_sync_luau_state` вызывал write trace → `_defer(_sync_all)` → `_sync_all` → `luau_var.set`… Цикл запускался, только когда включён ровно один из MCP/Rojo. Чиним порядком: сначала `_sync_all()`, потом `trace_add`. Тот же паттерн описан в SO: «register traces after initial setup».
- **`project_ok` — мёртвый код.** Первый `return bool(proj) and Path(proj).is_dir()` делал всю логику с `config.json` недостижимой. Убран; теперь «настроен» = есть `config.json` **и** хотя бы один источник включён.
- **`_menu_new_project` утекал CONFIG от прошлого проекта.** Сбрасывали только `index_docs/py/lua`, а `index_rojo` / `luau_mode` / `exec` оставались. Теперь `CONFIG.clear()` + `DEFAULTS`, потом обнуляются все источники.
- **Per-project `exec.enabled` и `index_rojo`.** `exec` был в `TOOL_FIELDS` — общий на все проекты. Убран; `exec.enabled` теперь per-project. Плюс новое поле `index_rojo` (не восстанавливается из агрегата `index_lua`).
- **Roots panel симметрична.** При выключении FS-источников теперь `disabled`, не `pack_forget`. Симметрично «открыли с выключенными — панель видна, контролы недоступны».

Умный рестарт сессии после Save в настройках — **открыто**, `DECISIONS §2.3`. Сейчас `_switch_project` пересоздаёт Session целиком на любое сохранение, включая переименование.

### Проверить в начале следующей сессии

1. `get_status` — backend, версии индексов (`[vN]`), корни.
2. `run_all.py` — exit=0.
3. Сценарий нового проекта: File → New project → настройки **все источники выключены** (включая `Lua files on disk`), статус «⚠ проект не настроен». Выбрать источники → OK → сессия поднимается, индекс собирается.
4. Открыть Project settings на существующем проекте — визуально проверить: `FS ignore` / `MCP ignore`, редакторы с описанием и disable/enable, центрирование окон, крестик с подтверждением, Roots panel не исчезает при выключении FS-источников.
5. `verify_syntax(paths=[...])` — на одном файле после правок.

---

## Сессия: multi-root финализация + GUI-производительность + первый внешний проект (закрыта)

**Тема:** довести multi-root модель до конца; починить отзывчивость Project settings на большом корне; освоить первый внешний проект (RimWorld) как кейс reconnaissance-driven workflow; закрыть накопившееся мелкое из DECISIONS.

**Ключевые решения:**

- **`.patchignore` — один, в `state_dir`.** `FilesystemBackend` больше не знает про `.patchignore` и не создаёт его в корне как side-effect старого `open()`. Policy и скрытие — концерн `WorkspaceBackend`, читается из `state_dir`.
- **`filter_check` возвращает `(error_code, message) | None`,** не `str | None`. `hidden_path` (скрыто `.patchignore` / dot-dir) отделён от `filter` (per-path policy / unknown root). В `##RESULT` теперь различимо.
- **`survey_dir` — новый тул.** Первый контакт с незнакомым корнем: агрегат по расширениям + подкаталоги первого уровня. `list_files` при >2000 файлов отдаёт счётчик вместо плоского списка.
- **GUI Project settings — три уровня оптимизации.** (1) `scan_subdirs_ex` с `DEFAULT_SCAN_MAX_ROWS=200` — RimWorld останавливается на depth 2, не уходит в глубину каждого мода; (2) скан всегда с `show_hidden=True` (superset), фильтр в памяти — toggle без повторного диска; (3) чанковый рендер через `after` + кэш подписи в `PolicyTree.render`. Census в корневой строке (`[RimWorld] (115 dirs, 3 hidden)`).
- **Корневая политика отображается по эффективному значению,** не по наличию override. У корня нет родителя — точка «не задано» бессмысленна.
- **`verify_syntax` как тул.** `compile(src, path, "exec")` по тексту из backend, без импорта. Заменяет ad-hoc `run_python(script="manual/verify_syntax.py")`.
- **`⚠ no summary` — только на `##`.** В проектах, где summary только на верхнем уровне, метка на `###`/`####` была 90% шума.
- **`run_python module=` = `python -m` = `__main__`.** Инцидент: `module="toolkit.runner.gui.app"` поднял второй GUI. Явное предупреждение в LLM_START §Execution (ru+en).

### Что сделано

**Код:**
- `FilesystemBackend`: убраны `_patterns`, `ensure_default`, `reload_patterns` — мёртвый код с side-effect.
- `WorkspaceBackend.filter_check` → `tuple[str, str] | None`; различает `hidden_path` и `filter`.
- `Patcher._filter_paths` пробрасывает код в `Result.error_code`.
- `toolkit/tools/verify.py` — `VerifySyntaxTool`, зарегистрирован в `TOOL_MAP`.
- `toolkit/tools/read.py` — `SurveyDirTool`; `list_files` при >2000 файлов возвращает счётчик.
- `formats/renderer.py` — `⚠ no summary` только на уровне 2.
- `config/loader.py` — `scan_subdirs_ex` с cap `DEFAULT_SCAN_MAX_ROWS=200`; старый `scan_subdirs` как тонкая обёртка.
- `runner/gui/settings_window.py` — lazy render, кэш скана, кэш подписи в `PolicyTree`, чанковый рендер.
- `runner/gui/tree_view.py` — кэш подписи, `invalidate()`, корневая политика по эффективному значению.

**Доки:**
- `LLM_START.ru.md` / `.en.md`: `survey_dir` в §Чтение; `hidden_path` в §13; `verify_syntax` + `module=` warning в §Execution; cheat-sheet §11.
- `DECISIONS.md`: §Workspace refactor актуализирован; §Единый текстовый матчинг (открыто); §Внешние проекты: reconnaissance-driven workflow; закрыты `read_symbol include=*`, Passthrough MCP, `hidden_path`, `verify_syntax`, `module=` warning, `⚠ no summary` для подсекций.

**Гигиена:**
- `toolkit/.gitignore` — runtime-scratch (`last_patch.json`, `last_output.txt`, `last_diff.txt`) и `bridge_timings.log`.
- Удалён `RimWorld/.patchignore` (side-effect старого open); `.patch_applier/.patchignore` — авторитетный.
- `bridge_timings.log` (663 KB) удалён.

### Проверено live (RimWorld, 86 модов)

- Reconnaissance: `survey_dir` показал форму дерева (29 712 файлов, 1.5 GB) за один вызов.
- `rimworld_inventory.py` — таблица 86 модов с именами из `About.xml` (`xml.etree`, не regex — regex нашёл первый `<packageId>` в `<modDependencies>`).
- Патч големов: `<VacuumResistance>1</VacuumResistance>` через `<Patches>` — фикс одной строкой XML, без декомпиляции DLL.
- `test_workspace_backend.py` — 29/29 на двух корнях.

### Что открыто

- **`.llmscope` + три тула.** Дизайн перенесён в `DECISIONS §1` — «Scope — LLM-editable soft filter (2026-10-14)». Согласовано в деталях, реализация — отдельная сессия.
- **Единый текстовый матчинг.** `toolkit/matching/text.py` с `find_text(...)`; tier'ы (`none` / `trailing` / `eol` / `eol+trailing`), общий для `replace_in_file` / `replace_between` / `insert_at_anchor` / `replace_range`. Единый `no_match` с кандидатами. Отдельная сессия. См. `DECISIONS §Единый текстовый матчинг`.
- **`get_index overview`.** Сжатый вид на 5 KB вместо 150 KB. Идея: единая точка входа поверх трёх файлов; не «один индекс» — «разные источники, единое представление».
- **Rojo backend.** Третий namespace.
- **Символьный reverse phase 2, diff edges, новые маркеры.** См. `DECISIONS §2.2`.
- **Пороги маркеров в конфиг.** `_LARGE_FILE_LINES` / `_LARGE_FILE_KB` / `_LARGE_SYMBOL_LINES` — hard-coded в `renderer.py`.
- **`TOOL_PRACTICE §2`** — таблица «Инвентарь» устарела после удаления символьных тулов.
- **`Lua reverse-dep graph`** — `script.*`-формы не резолвятся в `_invert_lua_imports`.
- **`_lua_script` кэш без mtime.** Правки Lua-скриптов видны только после рестарта GUI (для разработчика утилиты).
- **`get_index path_filter`** — фильтр по путям для одного файла. Простое поле.

### Проверить в начале следующей сессии

1. `get_status` — backend `composite`, mcp/rojo состояние, версии индексов (`[vN]`), `roots: RimWorld, toolkit` (если живёт тот же проект).
2. `run_all.py` — exit=0.
3. Открыть Project settings на RimWorld-корне — должно быть мгновенно (lazy render + кэш).
4. `verify_syntax(paths=[...])` — на одном файле после правок.

---

## Сессия: grep_replace + shared matcher (закрыта)

**Тема:** реализовать FS-side `grep_replace` как аналог `grep_replace_mcp`, вынести общий матчер, синхронизировать `grep` ↔ `grep_replace` внутри каждого домена, почистить устаревшие тесты, обновить доки под новую модель.

**Ключевые решения:**

- **Симметрия `grep` ↔ `grep_replace` — контракт, не пожелание.** Один матчер `toolkit/matching/Pattern`, одинаковые match-параметры и дефолты внутри домена. Что `grep` нашёл — то `grep_replace` заменит. FS↔MCP не унифицируются (разный язык паттернов), симметрия гарантируется **внутри** каждого домена.
- **`no_matches` на FS — не ошибка.** Возвращается `ok` (симметрия с `grep`), не `error` как в MCP-версии.
- **`dry_run=true` по умолчанию.** Двухпроходный гейт: pass 1 считает, pass 2 пишет. `too_many_replacements` до записи.
- **Без all-or-nothing отката.** Per-file atomic write: падение N-го файла не откатывает 1..N-1. Сознательный компромисс (в MCP-версии проблемы нет по построению).
- **`word_boundary` добавлен в FS-`grep`.** Раньше был только на MCP-стороне; без него `grep_replace` имел бы флаг, недоступный парному `grep`.

### Что сделано

**Новый слой `toolkit/matching/`.**
- `word.py` — `is_word` (ASCII-only, под Lua `[%w_]`).
- `pattern.py` — `Pattern` с `search` / `finditer` / `sub`. Один объект, симметрия по построению.
- Не в `core/` (там священный инвариант). Правило зависимостей обновлено: `tools → {backends, formats, indexers, matching} → core`.

**`toolkit/tools/grep_replace.py` (FS).** Симметрия с `grep` по построению. `pattern` / `mappings`, `regex` (дефолт `true`) / `fixed_strings` / `ignore_case` / `word_boundary`, `paths` / `directory`+`file_glob` / `exclude_glob`, `max_replacements` (дефолт 1000), `dry_run` (дефолт `true`). Работает на `.md` / `.py` / `.lua` / `.luau` (Rojo).

**`toolkit/tools/read.py::GrepTool`.** Рефакторинг матчера: inline `re.compile` → `Pattern`. Добавлен `word_boundary`.

**Lua-side рефакторинг.**
- `lua/scripts/_match.lua` — `ascii_lower`, `is_word`, `match_from`.
- `grep.lua` и `grep_replace.lua` переписаны через `-- include: _match` (в `_lua_script` — препроцессинг, потому что `require` в `execute_luau` даёт свежую копию модуля, не shared instance).
- Оба — per-line. Раньше `grep.lua` был per-line, `grep_replace.lua` — whole-source, расходились на `^` / `$`.

**Регистрация.** `grep_replace` в `TOOL_MAP` и `__all__`. Оба FS-тула триггерят rebuild.

**Тесты.** Удалены 8 устаревших файлов (тестировали удалённые 2026-10-11 символ-тулы и старый CLI-контракт): `test_section_tools`, `test_symbol_tools`, `test_lua_tools`, `test_lua_indent`, `test_apply_indent`, `test_code_tools`, `test_cli`, `manual/verify_grep_replace`. Починены `test_indexer` / `test_code_indexer` (устаревший `filter_spec=FilterSpec()`), `test_mcp_backend` (новая сигнатура `filter_check(path, op)`), `test_write` (мёртвый `filter_paths`). Создан `tests/test_grep_replace.py` (27 проверок). Обновлён `run_all.py`. Финальный прогон — `exit=0`.

**Доки.**
- `ARCHITECTURE.md` §1, §3 — добавлен слой `matching`, правило зависимостей, обновлён §5 (`refactor_rename` → `grep_replace_mcp`).
- `LLM_START.ru.md` / `.en.md` — новая секция «Массовая замена по файлам (`grep_replace`)», симметрия в §7, `word_boundary` в таблице `grep`, обновлены §11 (cheat-sheet), §13 (коды ошибок), §16 (примеры `replace_unit(block=...)` вместо `replace_block`/`delete_block`).
- `DECISIONS.md` §2.2 — `refactor_rename` закрыт для обоих доменов, симметрия с `grep` как контракт.
- `CONFIG.md` §4, `REQUIREMENTS.md` §2/§5, `MCPBridgeRules.md` §1/§3 — убраны ссылки на удалённые тулы.

### Проверено на живом Studio (AiTest, Edit mode)

- Цикл ренейма `getMultiplier` → `calculateMultiplier` → обратно: симметрично, индекс возвращается к исходному состоянию (`[v357]` → `[v363]`, символы идентичны).
- `word_boundary=true`: `Multiplier` не захватывает `getMultiplier` (0 совпадений). `word_boundary=false`: захватывает (3).
- `mappings` (2 пары, longest-first): 5 замен за один проход, без каскада.
- MCP overflow (`pattern="a"`, лимит 5): `too_many_replacements`, ничего не записано.
- FS `dry_run`: 35 замен в 6 файлах по `toolkit/docs`, ничего не записано.
- FS `noop_mapping` / `bad_input` (pattern + mappings) — отбито.
- Lua-индекс увидел изменение символьного хеша без сдвига строк (`getNormalizedChances` помечен `(изменён)`).

### Что открыто

- **`dry_run=true` триггерит auto-rebuild.** Тул имеет `op=write`, router пересобирает индекс даже когда ничего не записано. Безопасно, но лишний проход. Направление фикса: `Patcher` смотрит на `[dry_run]` в сообщении и не триггерит rebuild.
- **`verify_annotation` не реализован.** Упомянут в `DECISIONS §2.1` как замена `verify_section`, но в `TOOL_MAP` его нет. Помечен как не реализованный в DECISIONS, LLM_START, REQUIREMENTS.
- **Старые смоуки `verify_*.py` в `manual/`** — 12 штук, не перенесены в `tests/`. Обсуждалось, не решено (было отмечено и ранее).
- **`TOOL_PRACTICE §2`** — устарел (несколько тулов из «ни разу» реально использовались). Отдельная задача.
- **`CONFIG.md` §4 (Policy), §6 (MCP), `README.md`, `LIFECYCLE.md`** — не перечитаны после config split / Workspace refactor. Отмечено в §2.4 ранее, в этой сессии затронуты только прямые ссылки на удалённые тулы.

### Git log этой сессии

См. `git log` — сессия закрыта без коммита, коммит делает человек.

---

## Сессия: Functional Core refactor + replace_range validation (закрыта)

**Тема:** сделать GUI необязательным. Развести ядро (чистые функции) и оболочку (Tk-виджеты), вынести apply-kernel в отдельный модуль, доказать headless-режим через CLI. Плюс — фиксы тулов на основе наблюдений из сессии.

**Git log:** от `ec578a7 checkpoint: before MVP step 3a` до `6e0fb34 replace_range: order/after-write validation; docs updated` — ~16 коммитов.

### Что сделано

**Парадигма — Functional Core / Imperative Shell** (не MVP, как планировалось в DECISIONS §2.3 ранее). Зафиксировано в `DECISIONS §2.3`:
- Ядро (`patch_runner.py`, `presenters/main.py`) — без Tk, без `pyperclip`, без `msg_queue`. Принимает `config` аргументом, возвращает dataclass'ы (`ApplyOutcome`, `ButtonDecision`).
- Оболочка (`app.py`, `views/`) — Tk-виджеты и callback'и.
- Связь односторонняя: View → Core. Обратных ссылок нет.
- Почему не MVP: в Tk MVP вырождается — либо cyclic `View ↔ Presenter`, либо абстрактный View-интерфейс с 20 методами-заглушками для CLI. Functional Core снимает обе проблемы, `decide_button_state(...)` тестируется без мока.

**Шаг 3a.** `_session`, `_session_lock`, `_session_backend_name`, `msg_queue` → `gui/state.py`.
**Шаг 3b.** `worker` (165 строк) → `runner/patch_runner.py::apply_patch(session, raw_text, *, config, tool_map, backend_name, notify)` → `ApplyOutcome`. GUI-обвязка (`pyperclip`, `last_*`, `msg_queue`) осталась в `app.py`.
**Шаг 3c.** `runner/presenters/main.py` — чистые функции: `format_project_label`, `status_visual`, `backend_states`, `project_state`, `project_ok`, `decide_button_state`, `build_starter_text`, `build_backend_for_config`, `build_session`, `plan_init_patches`, `next_language`.
**Шаг 3c.6.** `runner/views/main_window.py::MainWindow` — фабрика виджетов с callback-dict; `views/widgets.py` (перенос из `gui/widgets.py`); `app.py::run()` — ~100 строк вместо 200+.
**Шаг 3d.** CLI parity: `cli.py` default path идёт через `patch_runner.apply_patch`; legacy-путь через `--no-auto-rebuild`.

**Расширяемость — `REQUIREMENTS.md §6 «Extension seams»`.** Шесть точек: Rojo, новые индексы, Unity bridge, новые тулы, headless, agent mode. Таблица «holds / holds w/ prep» + определения. Зафиксировано для будущих расширений.

### Фиксы и улучшения тулов

- **`replace_unit(part="all", new_text="")` → удаление unit.** Было `empty_input_use_delete_block`. Обоснование: адрес уже говорит «что», пустой текст другого смысла не имеет, симметрия с `delete_file`. Защита — `_check_parses(expect_missing=True)`. Причина отмены: 6 повторов в одной сессии — защита мешала, не обучала. Тест `test_strictness.py`.
- **`replace_range`: порядок + after-write.** `Patcher.apply` делает pre-pass: `range_order` (не по убыванию `start_line`) и `range_after_write` (после другого write в тот же файл). Нарушитель отклоняется, предшествующие **применяются**. Тест `test_range_order.py` (11/11). Доки: `LLM_START §6/§13/§14` (ru+en), `TOOL_PRACTICE §6`.
- **Ложный WARN `total != received`** в lua-индексе — исправлено (`lua_runner.py`): сравнение с размером до `.mcpignore`-фильтра; факт скрытия логируется отдельно.
- **`metrics.py`: per-project формат.** `{projects: {name: {action: {ok, error, ...}}}}`; `set_context(project_name)` вызывается в `app.py::run()` и `cli.py::main()`. Legacy-формат не мигрируется (перезаписывается при первом bump).
- **`manual/verify_syntax.py`** — `py_compile` в subprocess без импорта. Расширен с GUI-only до generic file/dir.

### Что открыто

- **`settings_window.py` не вынесен** — `_menu_project_settings` всё ещё открывает `gui/settings_window.py`. Отдельная задача, если нужна.
- **Tooling improvements** (DECISIONS §2.3): `verify_syntax` как tool, `git_*` как tools, `error_code` для hidden paths, `get_index` path filter, LLM_START §7 про `run_python module=`. Приоритет — по фактам.
- **`.gitignore` для runtime-логов** — `bridge_timings.log` (547 KB), `last_*.{json,txt}` ездят в каждом коммите.
- **Rojo / Unity / agent mode** — открыто; extension seams держат, но не реализованы.
- **`TOOL_PRACTICE §2`** — устарел: несколько тулов из «ни разу» реально использовались (`replace_range` 11, `insert_block` 21, `move_file`+`copy_file` 5). Отдельная задача — обновить.


## Сессия: Settings window + tool polish (закрыта)

**Тема:** после Workspace refactor — довести GUI-окно управления проектом и закрыть накопившийся долг по инструментам из `TOOL_PRACTICE.md §8`.

### Что сделано

**GUI — Project settings (шаг 7.3, заменяет старую «дерево файлов» идею):**
- `runner/gui/tree.py` — чистая логика дерева каталогов. 26/26.
- `runner/gui/tree_view.py` — Tk-виджет `PolicyTree`: соед. глифы, пять колонок, реактивный `set_active_flags`, hidden = hard deny. 19/19.
- `runner/gui/settings_window.py` — модал: имя проекта, Sources сверху (docs / py + exec / MCP / luau-on-disk / Luau source radio), Roots снизу (ноутбук табов + `Add root` / `Remove root` / `Show hidden` / легенда), ignore-редакторы inline в Sources, реактивные правила (exec требует python, luau radio зависит от источников, колонки дерева зависят от источников). `Ctrl+C / Ctrl+A` в Entry работают в любой раскладке (по keycode).
- `app.py` — `_menu_project_settings` теперь тонкий шим; старая заглушка `open_settings_dialog` и кнопка ⚙ удалены; `roots=[...]` прокинуто в `set_status`.
- `cli.py` — то же прокидывание roots.
- Доки: `GUI_PROJECT_SETTINGS.md` — дизайн + статус; `GUI_TREE.md` — удалён, поглощён.

**Тулы (P1/P2/P3 из TOOL_PRACTICE):**
- ✅ P1: `insert_at_anchor` добавляет `\n` у границы; `replace_between` нормализует EOL anchor'ов.
- ✅ P2: `replace_in_file` — три tier (byte-exact / trailing-whitespace / no-match + похожие строки); `regex: true`.
- ✅ P2: `create_file` / `overwrite_file` — syntax check `.py` / `.json` (`content_syntax_error`).
- ✅ P2: `replace_unit` для md — `part="own_body"`.
- ✅ P3 → отменено 2026-10-12: `replace_unit` с пустым `new_text` (было `empty_input_use_delete_block`; теперь — удаление).
- ✅ P3: `get_status` показывает `roots:    a, b` для workspace.
- ✅ `⚠` в diff-header при любых удалениях (маркер аномалии).

**Модель:**
- `own_body` задокументирован в `MODEL.md §4` как «ярлык к body-with-own-scope», с заделом на переделку в честный параметр.
- `_check_parses` уже стоит как страховка от off-by-one в unit-модели (из прошлой сессии).

**Статистика и депрекейт (итог):**
- `metrics.json` за 21 час — 1030 действий. Escape hatch 14.2% (цель <15% — достигнута). Unit-модель 10.8%. Старая символьная модель 1.6% с 37.5% err.
- Удалены из `TOOL_MAP` **17 записей**: `list_symbols`, `read_symbol`, `replace_symbol*`, `replace_statement`, `delete_symbol`, `insert_symbol`, `move_symbol`, `replace_function*`, `list_symbols_lua`, `read_symbol_lua`, `replace_function_lua`, `replace_section`, `set_summary`, `verify_section`. Файлы в дереве, регистрация снята. `list-tools` — 35 тулов. Запись в `DECISIONS §2.1`.

**Docs:**
- `LLM_START §11` — cheat-sheet «задача → тул» (первая подсекция, таблица со ссылками на сценарии).
- `LLM_START §5` — блок «патч — ручная операция»: объединяй механически связанные действия, разделяй зависимые; проверяй `-N` + `⚠` в diff.
- `LLM_START §12` — короткая отсылка к §5.

**Работа с моделью:**
- `Unit.title` — новое поле, `section_title` матчит человеческий текст заголовка (не номер). `not_found` в unit-тулах возвращает `Did you mean: ...` top-5 + хинт `list_units`.
- `replace_in_file` tier 2 (trailing whitespace) и tier 3 (`Similar lines:` с маркерами `␣`) подтверждены вживую.
- `⚠` в diff-header сработал в реале при удалении двух файлов через `delete_file`.

**Унификация unit-API (после P-фиксов):**
- `replace_unit` теперь принимает `part` XOR `block`. Оба обязательны — нет дефолта, `scope_required` без одного, `scope_conflict` с обоими. Убирает класс ошибок «думал, что меняю блок, заменил body».
- `replace_block` / `delete_block` поглощены `replace_unit(block=...)` — сняты из `TOOL_MAP`. `list-tools` — 33 тула.
- Canonical address keys: `qualname` (единый для всех форматов) + `title_match` (матчер по подстроке в заголовке). Legacy-алиасы `section_number` / `section_title` принимаются, но не в новых патчах.
- `not_found` в unit-тулах возвращает top-5 `Did you mean: ...` (без полного перечисления файла — `list_units` для карты).
- `MODEL.md §3-4`, `LLM_START §7` (ru+en) — переписаны под эту модель.

### Что открыто

- **`_git.py` args** — при `commit` с `word: msg` иногда `unknown subcommand`. Fallback добавлен (любой первый arg → commit), но точная причина не найдена. Не критично, работать можно.
- **Tabs↔spaces auto в `replace_in_file`** — принципиально не делаем (indent значима).
- **`replace_range`** — оставлен как escape hatch для module-level top region и файлов без парсера; в этой сессии не использовался.
- **~~`grep_replace` на FS-стороне~~** — **реализован** (см. `DECISIONS §2.2`). Симметрия с `grep` через общий матчер `toolkit/matching/Pattern`, `word_boundary` добавлен и в FS-`grep`. Работает на `.md` / `.py` / `.luau`-на-диске. MCP-версия `grep_replace_mcp` отрефакторена: `grep.lua` и `grep_replace.lua` делят `_match.lua` через `-- include:`, оба переписаны per-line. Проверено на живом Studio (`AiTest`).
- **Символьный reverse для Lua / Symbol Graph depth>1** — только Python, задокументировано.
- **`Roots-line влияет на конфиг`** — не влияет: `set_context` чисто для `get_status`.
- **`_initialize_project` / `router.plan_rebuilds`** — уже смотрят на `index_docs` / `index_python` / `index_lua`, отключённый источник не строит индекс.

**Git log этой сессии:** от `ed6e2e2 pre-model` до `fb2dcd8 deprecate old symbol tools, cheat-sheet, big-patches advice` (~20 коммитов).


## Сессия: Workspace refactor (закрыта)

**Длительность:** одна большая сессия, ~22 коммита, от `ab09954 before refactor` до `9683bc9 docs: session tool-practice notes`.

**Тема:** переход от однокорневой модели (`project_dir` = `working_dir` = место state) к **multi-root Workspace** с per-root и per-path policy.

### Что сделано

**Дизайн:**
- `docs/WORKSPACE.md` — модель: roots, policy, state. Все открытые вопросы закрыты.
- `docs/WORKSPACE_BACKEND.md` — backends, рефакторинг протокола.
- `docs/TOOL_PRACTICE.md` — рецепты и наблюдения по тулам (новое).

**Модель:**
- `config/workspace.py` — `Workspace` + `Root` + `PathPolicy` (пять флагов: `read / write / index_docs / index_py / index_lua`). Per-path overrides через `Root.overrides: dict[path, PathPolicy]`, nearest-match. Тест `test_workspace.py` (30/30).
- Старая модель (`FilterSpec` / `Policy` / `RootPolicy`) **удалена целиком**. Никакой обратной совместимости.

**Backends:**
- `FilesystemBackend.working_dir` → приватный `_root`.
- `backends/workspace.py` — `WorkspaceBackend` с routing `<basename>/<rel>`, `list_roots()`, `list("")` (плоский список файлов с префиксами), state-префикс `.patch_applier/`. Read + write в корни. Тест `test_workspace_backend.py` (29/29).
- `Backend.filter_check(path, op)` — вместо `(path, spec)`. `op` = `read` / `write` / `index_docs` / `index_py` / `index_lua`.
- `FS.filter_check` и `MCP.filter_check` — no-op (policy не их уровень).
- `CompositeBackend.filter_check` — делегирует вниз.

**Indexers и tools:**
- `indexers/doc.py`, `indexers/code.py` — `filter_check(path, "index_docs"|"index_py")`, без `filter_spec` параметра.
- `indexers/lua_runner.py` — без `filter_spec`.
- `tools/index.py` — три тула с `op="index_docs"|"index_py"|"index_lua"`, без `_index_spec`.
- `tools/status.py` — `_render_policy(backend)` берёт policy из `backend.ws` (WorkspaceBackend), не из `set_context(policy=...)`.

**Runner:**
- `runner/cli.py` — `--project <folder>` вместо `--working-dir`, без `Policy`. `_build_policy` удалён.
- `runner/projects.py` (новое) — чистая логика проектов: `resolve_layout`, `is_project`, `create_project`, `load_workspace`, `save_workspace`, `list_roots`, `add_root`, `remove_root`, `update_root_policy`, `rename_project`. Без Tk.
- `runner/gui/app.py` — File menu (New / Open / Recent / Project settings / Exit), `recent.json` в `runtime/state/`. Диалог `open_settings_dialog` — заглушка с подсказкой.
- `runner/gui/policy_io.py` — **удалён** (модель ушла).

**Tests:**
- Все тесты переведены на новую модель (`Session(backend, fmt, tools)` без `policy=`).
- Удалены: `test_policy.py`, `smoke_fs.py`, `smoke_patcher.py`.
- Новые: `test_workspace.py`, `test_workspace_backend.py`, `_smoke_imports.py`, `_smoke_gui.py`.
- **Зелёные:** smoke, workspace (30), workspace_backend (29), composite (26), get_status (29), lua_tools (35), code_tools (39), fileops (18), run_python (44).

**Гигиена:**
- `.patch_applier/.gitignore` — индексы и рантайм исключены; `workspace.json`, `.patchignore`, `.mcpignore`, `config.json` — в гите.
- `toolkit/.gitignore` — `runtime/`, `__pycache__/`.
- `.patch_applier/workspace.json` создан для проекта `PatchApplier` (root `toolkit`).
- Мусор (`toolkit/.patch_applier/` от старого места state) удалён.

**Инфраструктура:**
- `toolkit/code/manual/_git.py` — обёртка над git (`commit`, `log`, `status`, `reset-hard`, `show-file`).
- `toolkit/code/manual/_smoke_imports.py` — проверка «все модули импортируются» без GUI.
- `toolkit/code/manual/_smoke_gui.py` — проверка импорта `app.py` без Tk.

### Что работает end-to-end

- GUI стартует, сессия composite поднимается, mcp подключается.
- File → New/Open/Recent/Project settings работают.
- Project settings показывает таблицу roots с пятью колонками.
- Индексы пересобираются (docs / code / lua), пути в индексе — `<basename>/<rel>`.
- `get_status` показывает policy по root'ам.

### Что открыто (следующие сессии)

**Большие блоки:**

1. **Дерево файлов в GUI (шаг 7.3).** Сейчас GUI **не имеет** file explorer вообще. Старое дерево было только в удалённом диалоге настроек. Нужен: canvas+tree по `list("<basename>")`, вкладка на root, контекстное меню (open, copy path, edit policy). Требует design-док перед кодом.

2. **Редактор per-path overrides.** Сейчас Project settings работает только с per-root default (`overrides["."]`). Path-level (`docs/generated: read=false`) — только через `workspace.json` руками. Нужен UI внутри Project settings: выбор root'а → дерево его путей → флаги.

3. ~~**Multi-root smoke на живом проекте.**~~ **Закрыто.** `test_multi_root_smoke.py` (16/16) — два корня `alpha`/`beta`, `rebuild_index` + `rebuild_code_index` собирают файлы обоих, per-root `PathPolicy` исключает корень из индекса при rebuild.

**Мелкие:**

4. **`DECISIONS.md` обновить.** §2.5 (Workspace refactor) — отразить 5-флаговую модель, шаги 7.1/7.2. Текущая summary устарела.

5. **`WORKSPACE_BACKEND.md §11`** — отметить шаги 3, 4, 6 закрытыми (сейчас 3 says «не подключён в рантайм» — это устарело).

6. **Кнопка ⚙ Настройки** — заглушка. Либо убрать, либо превратить в редактор `.patch_applier.json` (backend / mcp / exec).

7. **Temporary-скрипты cleanup.** `_recon.py`, `_cleanup.py`, `_final_cleanup.py`, `_git_status.py` — одноразовые, можно удалить. `_git.py`, `_smoke_imports.py`, `_smoke_gui.py` — оставить.

8. **`get_status` снимок в стартовый текст.** Проверить, что policy-секция показывает roots (не «no workspace»). На последнем скриншоте сессии не видно содержимого.

9. **P1-фиксы тулов** (см. `TOOL_PRACTICE.md §8`):
   - `insert_at_anchor` — добавить `\n` между anchor и `new_content`.
   - `replace_between` — нормализовать EOL anchor'ов (`\r\n` ↔ `\n`).

### Что **не** делалось и почему

- **Rojo-режим** — не трогали, `luau: mcp` всё ещё дефолт.
- **Native Roblox tools** — только `list_roblox_studios` + `search_game_tree` в самом начале для recon. Правил Lua-код через `replace_in_file` (файлы на диске). MCP-код не менял.
- **Multi-root policy enforcement** — формально работает (per-root PathPolicy), но на живом двух-корневом проекте не проверялось.
- **Чистка старых тулов** — устаревшие symbol-tools (`replace_symbol*`, `replace_section`, `set_summary`, `verify_section`) остались в `TOOL_MAP`, но не в `LLM_START`. Их удаление — отдельная задача.

## Что проверить в начале следующей сессии

1. **`get_status`** — что backend `composite`, mcp подключён, индексы свежие (`[vN]` не пустые). В снимке — `roots:    toolkit` и `Policy Filesystem`.
2. **`python -m toolkit.runner.cli --list-tools`** (cwd = `toolkit/code`) — 32 тула, среди них `read_unit` / `replace_unit` / `insert_block` и **нет** `replace_block` / `delete_block` / `replace_section` / `read_symbol*`.
3. **`File → Recent`** и **`File → Project settings`** — что проект `PatchApplier` в списке, root `toolkit` с пятью `✓`.
4. **`replace_unit(part="all", new_text="")`** на тестовом файле — должен **удалить** unit (не `empty_input_use_delete_block`).
5. **`git log --oneline | head`** — верхний коммит `6e0fb34 replace_range: order/after-write validation; docs updated` или новее.

## Как закрывать следующую сессию

1. Обновить **§ «Сессия: ...»** в этом файле — коротко что сделано, что открыто.
2. Закоммитить (`_git.py commit`).
3. Если что-то большое осталось незакрытым — вынести в § «Что открыто» следующего блока.
