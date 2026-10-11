# Решения

> **Статус:** принципы и обоснования, не список фактов. Актуальное состояние — `CODE_INDEX.md`. Что сделано — видно из кода. Если документ расходится с кодом — верь коду.
>
> **Что здесь:** почему приняты те или иные решения, что сознательно оставлено открытым. Чего здесь нет: дорожных карт, списков сделанного, отчётов о миграции.

## 1. Зафиксировано

<!-- summary: 44 решения + Workspace refactor — toolkit, Result, Session, Policy, verify, symbol-tools, replace_between, Python vs Lua, copy, auto-rebuild, domain routing, grep, LLM_START, unified node model, dependency graph, replace_symbol_signature multiline, config split, state_dir, tools_schema global, suppression, markers, replace_statement, replace_symbol part, read_file axes, CRLF, source_hash, grep paths, транспортный нейминг, grep_replace_mcp, снимок как config, толерантный парсер патча, read_file без границ только для малых, чтение перед правкой, парсинг строк по явному маркеру; Workspace refactor — multi-root, WorkspaceBackend, state-префикс. -->
<!-- tags: decisions, fixed -->

1. **Единый toolkit** — один фреймворк, три concrete backend'а (Filesystem, MCP, Composite), одна схема действий.
2. **Hardcore vs extensions** — ядро (`Section`, `Symbol`, `Result`, `Backend`, `Tool`, diff) фиксировано; format, indexer, tools, policy — расширяемо.
3. **Result структурный** — `status`, `delta`, `verified`, `error_code`. Никаких `startswith('Ошибка')`.
4. **Diff — ключ-агностичен** — один алгоритм для секций и символов.
5. **Session оборачивает Backend** — даёт lifecycle. MCP держит bridge открытым между патчами.
6. **Verify-after-write в MCPBackend** — `write` читает `.Source` обратно и сравнивает, `verified=False` при расхождении.
7. **Transient-retry в MCPBackend** — `_invoke` ретраит при `No Roblox Studio instances`. `_wait_studio_ready` при `open()`.
8. **Policy — три роли** (read / write / index) с dict overrides и наследованием от ближайшего предка. Заменила `mode=white/black`.
9. **Legacy-совместимость Policy** — `Policy.from_dict` понимает и новый формат (`overrides`), и старый (`mode` + `paths`).
10. **Tool объявляет `op`** — `read` / `write` / `index`. Patcher применяет соответствующую роль Policy.
11. **Symbol-tools для Python и Lua** — параллельные семейства (`read_symbol` / `read_symbol_lua`), общий формат ответа.
12. **Читать vs писать — разные роли** — можно расширить `read` не расширяя `write` (что мы и сделали для `bridge.py`).
13. **`op="index"` — отдельный путь** — Patcher не фильтрует `path_args`, спека передаётся через `_index_spec` в Tool.
14. **Доки и код — раздельные плоскости** — связь doc ↔ code (единый module-aware документ) вне scope.
15. **Python vs Lua: где выполняется работа.** Данные парсятся там, где лежат: Roblox DataModel — на стороне Studio (`execute_luau`), всё локальное — Python. Правило: bulk-обход и cross-module анализ — Lua; одиночные операции над модулем — Python.
16. **Python-парсер Lua — для одиночных операций.** `toolkit/formats/lua.py` используется для `read_symbol_lua`, `replace_function_lua`, parity-тестов. Bulk-путь индекса — на Lua.
17. **Почему split случился — историческое.** Изначально Lua-парсер сделан по аналогии с markdown/Python («парсим в Python единообразно»). Но Lua не локальный — аналогия сломалась. На будущее: если данные не локальные, парсер — на их стороне.
18. **Политики путей не применяются к Roblox.** Roblox DataModel — не файловая система; фильтр путей на унифицированных тулах обходится нативным инструментом bridge (`execute_luau` делает то же, что и `replace_symbol_lua`). Поэтому `MCPBackend.filter_check` всегда возвращает `None`, а доступ гейтится на уровне backend: включён ли `mcp` и включены ли `native_tools`. Ложная безопасность хуже отсутствия.
19. **`replace_between` и `insert_at_anchor` — основные инструменты блочной правки.** `replace_between` заменяет текст между двумя короткими уникальными якорями; `insert_at_anchor` вставляет без замены. Оба принимают `occurrence` для выбора вхождения. `replace_in_file` отходит на второй план: остаётся для однострочных замен с гарантированно уникальным `search`. `replace_range` получает `expected_first_line` — сверку первой строки диапазона до правки, чтобы сдвиг строк давал `content_mismatch`, а не портил файл.
20. **Копирование — отдельные тулы.** `copy_file` (байтовая копия) и `copy_unit` (структурная единица: секция `.md` или символ `.py`/`.lua`). Оба **не трогают source** — в этом их отличие от `move_file`/`move_symbol`. `copy_unit` — первый опыт унификации: тип единицы определяется ключом в `selector` (`section_number` / `section_title` / `qualname`), а не отдельным тулом. Если схема приживётся — кандидат на объединение `replace_section` / `replace_symbol` под общим `replace_unit`. `copy_file` работает на любых файлах (бинарники тоже); `copy_unit` — только на текстовых (markdown / Python / Lua), потому что ему нужен структурный парсер.

21. **Авто-ребилд после успешного write.** Триггер — только `op="write"` тул с `Result.status="ok"`. Читающие тулы, индекс-тулы и пустой патч не триггерят. Обоснование: раньше триггер был формальным (наличие `file_path` в патче), от чего страдали чтения — любой `read_file` пересобирал индексы впустую. `run_python` — write без объявленных `path_args`, «мог тронуть что угодно» → все включённые домены. Нативные тулы: read-only whitelist не триггерит, всё остальное → только `lua`; неизвестный native — safe default → `lua`. Принцип: актуальность индекса приоритетнее секунды на пересборку, но только для тулов, которые реально могли что-то изменить.

22. **Классификация по домену, а не по транспорту.** Три индекса — docs (`.md`), code (`.py`), lua (Roblox-путь) — три независимых домена; каждый включается своим флагом (`index_docs` / `index_python` / `index_lua`). Маршрутизация ребилда — по расширению пути, а не по «FS vs MCP». Обоснование: FS-путь может быть и `.md`, и `.py` — это два разных индекса при одном транспорте. `is_mcp_path` / `ROBLOX_SERVICES` вынесены в `core/paths.py`; `plan_rebuilds` — в `core/router.py` (чистая функция, тестируемая без tkinter). GUI перестал держать эту политику. `CompositeBackend.is_alive = any` следует из того же принципа: degraded (MCP упал, FS жив) — поддержанное состояние, правка документов не требует поднимать Studio.

23. **`grep`: `regex=True` по умолчанию, `fixed_strings` — для литеральной подстроки.** Соответствует стандарту grep / ripgrep (`-F`). Обоснование: старый дефолт (`regex=False`) приводил к «тихим промахам» — LLM пишет `a|b`, grep молча ищет литерал `a|b`, возвращает пусто, ошибка невидима. Смена дефолта — осознанный breaking change, без депрекейта: утилита в закрытой разработке.

24. **`LLM_START` — документ утилиты, не проекта.** Живёт в `toolkit/docs/`, не перечислен в `INDEX.md` проекта, не правится обычными патчами проекта. Расширение — `.ru.md` / `.en.md`. Обоснование: содержимое LLM_START приходит в стартовом сообщении; попытка «прочитать его из проекта» — семантическая ошибка (его там нет). Правится только осознанно, в репозитории утилиты.

25. **Единая структурная модель узла (секция / класс / функция).** Иерархический узел — оболочка + аннотация + тело. Секция: `## N. Title` + `<!-- summary -->` + тело (включая подсекции). Класс: `class Foo:` + docstring + тело (методы — дети). Функция: `def f():` + docstring + тело (лист). Модель одна; различие «где в тексте живёт аннотация» (после заголовка или сразу после сигнатуры) — это выбор форматтера, а не структурное различие. Точно так же `set_summary` и «установить docstring» — суть одна операция «записать аннотацию к узлу», формат — детали реализации.

Что специфично для типа узла (параметры общей формы, а не поводы не объединять):

- **Семантика `body`.** У секции тело **включает** детей (подсекции); у класса — нет (методы — siblings, не «внутри тела»). Единственное реальное семантическое расхождение; должно выражаться явным параметром (`with_children` / `mode=body|all`).
- **`tags`** — есть у секции; у символа аналога нет. Расширение аннотационной модели, а не отдельный слой.
- **`occurrence`** — нужен **и там, и там**. У символов уже есть; у секций — нет, хотя номера не гарантированно уникальны: двухчастный документ с нумерацией по новой в каждой главе даёт `1. Введение` дважды, плюс банальные опечатки. Отсутствие `occurrence` для секций — текущий пробел, а не следствие «секции уникальны».
- **`container`** — только у символа: где внутри файла разместить определение. У секции «место вставки» = позиция в иерархии узлов.
- **Форматтеры** — разные (markdown / Python / Lua). Прячутся за `Format`; наружу модель одна.

Почему это зафиксировано как решение, а не как «идея»: структурный изоморфизм проверен прототипом (`manual/unit_proto/`, тестовая сессия без контекста — 6/6) и подтверждён как рабочий принцип. Модель используется не как «план миграции» существующих тулов (см. §2.1 — миграция отменена), а как основа для нового тулсета, который добавляется рядом со старыми.

26. **Граф зависимостей — часть индекса, обе половины.** Forward (`Imports:`) и reverse (`Used by:`) — обе половины графа живут в индексе (`.md` + manifest). «Карта» без рёбер — не карта, а список. Строитель — rebuild, не отдельный тул; `find_usages` — accessor. Модульный reverse реализован для Python и Lua; символьный (phase 2) — §2.2.

27. **`replace_symbol_signature` на многострочных `def` — починено.** Раньше `end = node.lineno` брал только строку `def foo(`, оставляя в файле хвост параметров (`a: int, b: int, ) -> bool:`) как мусор. Теперь `end = node.body[0].lineno - 1` — вся сигнатура до первой строки тела. Работает и для одно-, и для многострочных сигнатур; регрессия закрыта тестом `test_symbol_indent.py` (кейс multi-line).

28. **Конфиг разделён на два файла: tool-wide + per-project.** `<toolkit_root>/.patch_applier.json` — tool-wide: `project_dir`, `recent_projects`, `ui_language`, `format*`, `mcp`, `exec`. `<project>/.patch_applier/config.json` — per-project: `backend`, `filter`, `skip_files`, `code_*`, `lua_*`, `state_dir`, `luau_mode`, `index_*`. `TOOL_FIELDS` (frozenset) определяет границу. `load()` мержит: tool-wide база + per-project overlay; `save()` разбивает merged dict обратно на два. Обоснование: политики, индексы, `state_dir` — per-project; переключение проекта не должно их терять или переносить в чужой проект. GUI при смене пути реактивно перечитывает `config.json` нового проекта в виджеты — никаких диалогов «перенести/загрузить», путь и есть определитель проекта.

29. **`state_dir` вместо `service_subdir`.** Единый служебный каталог (`.patch_applier` по умолчанию) внутри проекта: индексы (`INDEX.md`, `CODE_INDEX*.md`), их `.version` и `.manifest.json`, sidecar `.index_meta.json`, рантайм MCP (`patch.json`, `outputs.json`, `bridge_log.jsonl`).

### Workspace refactor

<!-- summary: Завершён. Однокорневая модель удалена целиком; единая модель Workspace с пятью флагами PathPolicy (read / write / index_docs / index_py / index_lua) и per-path overrides. Шаги 1-4, 6 закрыты. GUI: File menu + Project settings + recent.json. Открыто: 7.3 (дерево файлов), редактор per-path, multi-root smoke, P1-фиксы тулов. -->
**Что это.** Переход от однокорневой модели (`project_dir` = `working_dir` = место state) к multi-root workspace. Дизайн: `docs/WORKSPACE.md`, `docs/WORKSPACE_BACKEND.md`.

**Сделано (шаги 1–4 + 6):**

- **Шаг 1 — дизайн.** `WORKSPACE.md` + `WORKSPACE_BACKEND.md`. Все открытые вопросы закрыты.
- **Шаг 2 — `config/workspace.py`.** `Workspace` + `Root` + `RootPolicy` + JSON round-trip + валидация. Тест `test_workspace.py` (23/23).
- **Шаг 2.5 — `working_dir` refactor.** Публичный `FilesystemBackend.working_dir` → `_root`. `CompositeBackend.working_dir` — property через chain. Тест `test_working_dir_removed.py` (9/9). Урок: `getattr(obj, name, default)` не спасает, когда атрибут **есть**, но вернул None — нужен chain через `or`.
- **Шаг 3 — `backends/workspace.py`.** `WorkspaceBackend` с routing `<basename>/<rel>`, `list_roots()`, `filter_check` (policy на полном пути + `.patchignore` из `state_dir`), state-префикс `.patch_applier/` для state-файлов. Тест `test_workspace_backend.py` (33/33).
- **Шаг 4 — интеграция.** CLI `_create_backend` + GUI `_build_backend_for_config` строят `WorkspaceBackend` из `workspace.json`. `config.loader.load_workspace(cfg)`. Ошибка, если `workspace.json` нет — никакого fallback на старую модель.
- **Шаг 6 (частично) — write в корни.** `WorkspaceBackend.write/create/delete` делегируют в FS-бэкенд корня. `move/copy` — кросс-корень запрещён для move, разрешён для copy (через `FilesystemBackend.copy_to`). State-префикс — всегда RW. Policy-проверка — на `Patcher` через `filter_check`, не в backend.

**Ключевые решения сессии:**

- **`list("")`** — все файлы всех корней с префиксами `<basename>/<rel>`. Это контракт для индексаторов. `list_roots()` — basenames. State внутри корня исключается через `_state_rel_for`.
- **State-префикс `.patch_applier/`** — адресуется наравне с корнями. В фильтре всегда OK (захардкоженная политика). В `list("")` не попадает.
- **Никаких external/embedded.** Один алгоритм: пользователь выбирает папку проекта, туда кладётся `workspace.json`, `.patchignore`, `.mcpignore`, индексы, `runtime/`. `recent.json` — единственное место про «последнее».

**Инфраструктура.** `toolkit/code/manual/_git.py` — обёртка над git для чекпоинтов между большими патчами.

**P1-фиксы тулов (следующая сессия после Workspace).** `insert_at_anchor` — auto-`\n` между anchor и `new_content`, чтобы не склеивать строки (`from a import b` + `from c import d` → сломанный синтаксис). `replace_between` — EOL-нормализация anchor'ов, чтобы LF-anchor находился в CRLF-файле. Оба фикса — из `TOOL_PRACTICE.md §8`, регрессии в `test_tool_edge_cases.py`. См. также §2.5.

**Git hygiene.** `.patch_applier/.gitignore` — индексируемые артефакты исключены; `workspace.json`, `.patchignore`, `.mcpignore`, `config.json` — в гите. `toolkit/.gitignore` — `runtime/`, `__pycache__/`. Раньше индексы и рантайм утекали в коммиты — теперь изолированы.

**Модель policy — пять флагов (не три).** `PathPolicy` (`read` / `write` / `index_docs` / `index_py` / `index_lua`) вместо старого `FilterSpec`. Каждый root имеет `overrides: dict[path, PathPolicy]`; ключ `.` — дефолт root'а, остальные ключи — относительные пути внутри. Nearest-match. Override — **полная замена**, не частичный мерж. Старые `FilterSpec` / `Policy` / `RootPolicy` удалены целиком.

**Открыто (следующие сессии):**

- **Дерево файлов в GUI (7.3).** Сейчас GUI не имеет file explorer вообще. Нужен design-док перед кодом.
- **Редактор per-path overrides.** Сейчас Project settings работает только с per-root default. Path-level — через `workspace.json` руками.
- **Multi-root smoke на живом проекте.** Формально покрыто `test_workspace_backend.py`, но 2+ roots в реальном проекте не запускали.
- **Шаг 5 (индексаторы).** Работают через `list("")` — контракт один-в-многие. На двух корнях не проверяли.
- **P1-фиксы тулов** (`insert_at_anchor` + `\n`, `replace_between` EOL). См. `TOOL_PRACTICE.md §8`.
- **Уборка:** временные `_recon.py` / `_cleanup.py` / `_final_cleanup.py` / `_git_status.py`; устаревшие symbol-tools из `TOOL_MAP`.

**Root внутри state.** Сейчас `state_dir` (`.patch_applier/`) физически внутри корня `toolkit/`. Работает через `_state_rel_for`, но при создании нового проекта через GUI root'ы будут отдельные, state — сбоку.
## 2. Открыто

<!-- summary: Три группы — унификация тулов, граф и анализ, инфраструктура; плюс гигиена сессии и её хвосты. -->
<!-- tags: decisions, open -->

### 2.1 Унификация тулов

<!-- summary: Миграция отменена. Новый тулсет структурных тулов (read_unit / list_units / replace_unit / insert_block / set_annotation) добавлен рядом со старыми. Старые символьные тулы вытеснены: 17 записей удалены из TOOL_MAP 2026-10-11. Позже replace_block / delete_block поглощены replace_unit(block=...); canonical address keys — qualname + title_match, старые section_number / section_title принимаются как алиасы. -->

**Стратегия: расширение тулсета без миграции.** Старый план (объединить `replace_section` / `replace_symbol*` / `insert_symbol` в единый `replace_unit` / `insert_unit`) отменён. Причины:

- **Цена миграции высокая.** Переписать `write.py` + `symbols/python.py` + `symbols/lua.py` + `copy.py` + тесты + LLM_START. 2–3 сессии работы, риск регрессий в базовом write-пути.
- **Выигрыш неочевиден.** Унифицированный `part=body` для секции и метода всё равно имеет per-type ветки — то же разнообразие, но внутри тула, а не в имени. Уменьшение номенклатуры компенсируется ростом сложности каждого вызова.
- **Escape hatch остаётся.** Если новый тул не покрывает место, LLM возвращается к старому — но это уже не «откат миграции», а нормальная работа двух наборов параллельно.

Вместо миграции — **новый тулсет структурных тулов рядом со старыми.** Старые остаются в `TOOL_MAP` (совместимость со старыми патчами), из `LLM_START` они **убираются**. Модель видит только новые + текстовый escape hatch. Через 1–2 месяца статистика по `metrics.jsonl` покажет, кто победил.

**Модель.** Зафиксирована в §1 п.25 и подробно расписана в `manual/unit_proto/MODEL.md` (прототип). Ключевые понятия:

- **Unit** — `module` / `function` / `method` / `class` / `section`. Единый адрес — ключ `{qualname}` (для секций: номер или заголовок; для модуля: `<module>`). Legacy-алиасы `section_number` → `qualname`, `section_title` → `title_match` принимаются, но в новых патчах не используются.
- **Parts** — `head` (сигнатура / заголовок), `annotation` (docstring / summary / `--[[ ]]`), `body`.
- **Blocks** — нумерованные элементы внутри body. `block=3`, `block="1-10"`, `block=[1, 3, 7]`. В head и annotation блоков нет.
- **Module head** — до первого def/class. Глобал между классами — блок в body, не head.
- **Граница модели** — комментарии между unit'ами не адресуются (нужен текстовый тул).

**Новый тулсет — волна 1 (read).**

- `read_unit` — единое чтение. Адрес + `part` + `block`. Работает на `.py` / `.lua` / `.luau` / `.md`.
- `list_units` — карта unit'ов в файле: qualname + kind + line-range + число блоков.

Переносятся из `manual/unit_proto/` в `toolkit/tools/`. Логика уже проверена — тестовая сессия без контекста дала 6/6, включая определение границы модели (комментарии не адресуются).

**Волна 2 (минимальный write).**

- `replace_unit` — замена unit'а целиком или по частям (`part=head|annotation|body`). Заменяет `replace_symbol`, `replace_symbol_body`, `replace_symbol_signature`, `replace_section`.
- `replace_unit(block=N)` — замена блоков в body (`block=3`, `block="1-4"`). Заменяет `replace_statement` (только Python), `replace_block`, `delete_block` (пустой `new_text` = удалить) и структурные случаи `replace_between`. Кросс-форматно. `part` и `block` взаимоисключающие и обязательные (`scope_required` / `scope_conflict`).
- `insert_block` — вставка блока: `position=start|end|before|after` + `anchor` (индекс блока или qualname соседа). Заменяет `insert_symbol` и структурные случаи `insert_at_anchor`.
- `set_annotation` — установить docstring / summary / `--[[ ]]` одной операцией. Заменяет `set_summary` и установку docstring через `replace_symbol`.
- `verify_annotation` — подтвердить annotation без правки файла. Заменяет `verify_section`.

**Правило: новый тул даёт то, чего в старых НЕТ.** Не «то же самое, но иначе». `replace_unit` параллельно с `replace_symbol` для одного формата — не делаем. `set_annotation` — да, потому что кросс-форматный annotation в старых отсутствует.

**Не делать сейчас.** `move_unit` / `move_block` — покрываются комбинацией `replace_unit(block=N, new_text="")` + `insert_block`. Если комбинация окажется частой и неудобной — добавить отдельный тул по факту, не заранее.

**Статистика.** `Patcher.apply` бампает счётчики в `metrics.json` (toolkit runtime state dir) после каждого действия: `counts[action][status] += 1` плюс `errors[action][error_code] += 1`. Не журнал, а агрегат — размер ограничен набором `action × status × error_code`, не растёт линейно со временем. `since` / `updated` показывают окно. Анализ — `manual/metrics_report.py` (печатает топ действий, доли по группам, ошибки), reset — удалить файл или `metrics_report.py --reset`. Через 1–2 месяца смотреть:

- доля `text escape hatch` (`replace_in_file` + `replace_range` + `replace_between` + `insert_at_anchor`) от всех write-операций — целевой индикатор провала модели (>40%) или победы (<15%);
- доля `old symbol model` (все тулы, убранные из LLM_START) — насколько модель вытесняет старые;
- ошибки по новым тулам (`block_out_of_range`, `not_applicable`) — если часты, модель неудобна в этих местах.

**Порядок реализации.**

1. `read_unit` + `list_units` в `toolkit/tools/` — перенос прототипа, тесты, регистрация.
2. Лог `metrics.jsonl` в `Patcher.apply` — инфраструктура для статистики (данные собираем сразу).
3. Волна 2 — по одному тулу за раз, каждый самодостаточен.
4. Переписать `LLM_START §7` — старые тулы исчезают, новые появляются, escape hatch остаётся явно.

**Что остаётся из старых в LLM_START.**

- Текстовый escape hatch: `replace_in_file`, `replace_between`, `insert_at_anchor`, `replace_range`.
- Ортогональные: файловые операции, индексы, граф (`find_symbol`, `find_usages`, `symbol_graph`), exec, Roblox-специфика, утилитарные (`read_file`, `grep`, `file_stat`).
- `copy_unit` — уже кросс-форматный, остаётся как есть.

**Что скрывается из LLM_START §7.** `list_symbols`, `read_symbol`, `read_symbol_lua`, `replace_symbol`, `replace_symbol_body`, `replace_symbol_signature`, `replace_statement`, `replace_section`, `set_summary`, `verify_section`, `insert_symbol`, `delete_symbol`, `move_symbol`. Все они остаются в `TOOL_MAP` для совместимости.

**Итог по статистике (2026-10-11).** Metrics за 21 час работы (1030 действий): old symbol model — 16 вызовов (1.6% от всех), 6 из них с ошибками (37.5%). Unit model — 111 вызовов (10.8%). Text escape hatch — 146 (14.2%). Целевой индикатор победы модели (<15% escape hatch) достигнут. **Решение: удалены из `TOOL_MAP` 17 записей** — `list_symbols`, `read_symbol`, `replace_symbol`, `replace_symbol_body`, `replace_symbol_signature`, `replace_statement`, `delete_symbol`, `insert_symbol`, `move_symbol`, `replace_function`, `replace_function_body` (алиасы), `list_symbols_lua`, `read_symbol_lua`, `replace_function_lua`, `replace_section`, `set_summary`, `verify_section`. Файлы остаются в дереве (`tools/symbols/`, `tools/code.py`, `tools/lua_code.py`, `tools/write.py`) — если понадобится вернуть, раскомментировать одну строку в `tools/__init__.py`.

**Открыто** потому, что тулы волны 2 ещё не написаны, а решение о судьбе старых — по статистике после нескольких недель работы.

### 2.2 Граф и анализ

<!-- summary: Реализовано: маркеры (факты), suppression `# pa:`, модульный reverse, `find_usages`, source_hash в diff, `grep_replace_mcp` (rename MCP-side). Открыто: символьный reverse, diff edges, новые маркеры, FS-side `grep_replace`, `read_symbol include=callees`/`callers`, `⚠ no summary` для подсекций. -->

**Обратные зависимости (depends by) — модульный уровень готов.** Реализовано для Python (`indexers/code.py`) и Lua (`indexers/lua_runner.py`). Форма данных:

- **Python.** `Module.imported_modules` — сырые модульные части без имён сущностей; собираются в `_walk_body` параллельно с `imports` (без второго AST-прохода). `ast.Import` → имя модуля, `ast.ImportFrom` → base с уровнем, при `module is None` (`from . import a`) — каждый alias как подмодуль (`{base}.{alias}`). `_build_import_graph` резолвит relative-форму (`..core.errors`) от dotted-имени импортёра и оставляет только внутренние модули; absolute с неполным совпадением пробует suffix-match (кейс `from toolkit.X` при вложенном root). Возвращает **обе половины графа** одним проходом: `used_by` (кто импортирует) и `uses` (кого импортирует). Место: `.md` (строки `Imports:` и `Used by:`) + manifest (`used_by`).
- **Lua.** Luau-драйвер возвращает `imports` структурированно — абсолютные DataModel-пути (`game.ReplicatedStorage.X`). `_normalize_lua_path` снимает `game.`, `_invert_lua_imports` матчит exact. Никаких `execute_luau` в Python-слое. Место: `CODE_INDEX_LUA.md` + manifest. Ограничение: динамические `require("x" .. suffix)` не видны драйверу — граф приблизителен (оценка снизу).
- **Рендер.** `Used by: path1, path2 (+N)` после `Imports:`. В Python-индексе обрезка до 6, как у `Imports:`; в Lua — без обрезки.

**Marker layer — реализовано.** Все маркеры — **факты**, не суждения (см. §1 п.32). Вычисляются на rebuild, рендерятся в `.md` суффиксом к строке модуля/символа:

- `◉` — AST: есть `if __name__ == "__main__"`. Python-only.
- `← N imp` / `→ N users (M tests)` — из графа импортов. Показывается только при N ≥ 1 (стена `→ 0 users` на standalone-скриптах была шумом).
- `[tests/]` / `[vendor/]` — path regex (`tests/`, `test_*`; `vendor/`, `_Index/`, `node_modules/`).
- `⚠ large` — файл > 300 строк или > 16 KB; символ > 100 строк. Пороги сейчас hard-coded в `renderer.py` (см. §2.3 «пороги в конфиг»).
- `⚠ cycle` — back-edge в графе импортов (iterative DFS).

**Suppression — реализовано.** `# pa: <name>, <name>` в шапке файла (первые 20 строк), `# pa: all` глушит всё. Имена совпадают с маркерами. `Module.suppress: frozenset[str]`, парсится в `formats/code.py:_parse_suppress`.

**Символьный reverse (phase 2) — открыто.** «Где вызывается `X.foo`». Проход по телам символов: `Attribute(value=Name(...), attr=...)`, матч по квалифайд-именам импортированного. **Эвристика, не разрешение имён**: локальные переменные и параметры пропускаются; `getattr`, `from X import *`, динамические атрибуты — промахи. Уровень `pyflakes` (полное разрешение scope) вне scope. Место: только manifest (в `.md` раздуло бы). Требует замера перед реализацией: текущий rebuild 0.42 с на 115 модулей, символьный проход — второй обход уже распарсенных деревьев; если >2 с — оставить только модульный.

**`read_symbol include=callees` / `include=callers` — открыто.** Обсуждалось как способ сократить навигацию: символ + список вызываемых им функций (callees) / список вызывающих его мест (callers). `include=callees` — обход `ast.Call` внутри символа, маппинг на `find_symbol`; `include=callers` — обёртка над `find_usages` (символьный уровень, см. выше). Для Lua — только если Lua-парсер даёт Call-узлы (проверить перед реализацией; иначе Python-only). **Зачем:** сейчас после чтения символа LLM не знает, что ещё важно в этом файле; тул говорит «вот соседние символы одного шага графа».

**Diff edges — открыто.** `Used by:` показывается в diff'е **только если изменилось**. Это фича: появление или исчезновение ребра = изменение blast radius, видимое сразу. Правило согласовано, реализация — TODO.

**`find_usages` — реализовано (модульный уровень).** Accessor к индексу: возвращает `imports` и `used_by` для модулей, матчащихся по подстроке пути. Читает тот же manifest, что и `find_symbol`; для Lua — через `manifest_path="CODE_INDEX_LUA.manifest.json"`. Символьный уровень («где вызывается `X.foo`») остаётся в phase 2.

**Ограничения.** Python: `getattr`, `from X import *`, динамические атрибуты — промахи на символьном уровне (на модульном всё точно). Lua: dynamic `require("x" .. suffix)` не виден драйверу; символьный уровень слабее.
**Lua: `symbol_graph kind="lua"` — только модульный уровень.** Манифест Lua (`lua_runner._build_manifest`) не содержит поля `calls` — драйвер на стороне Studio возвращает только `imports` (по `require`) и `symbols`. Значит `symbol_graph kind="lua"` вернёт модуль символа без callees/callers; `find_usages` работает по `require` (модульный уровень). Символьный reverse для Lua не реализован.

**Lua reverse-dep graph пуст: `script.*`-формы не резолвятся.** Импорты Lua-драйвера приходят script-relative (`script.Parent._Index[...]`, `script.Expectation`), а `_invert_lua_imports` ожидает абсолютные DataModel-пути (`game.ReplicatedStorage.X` → `ReplicatedStorage.X`) и матчит по exact. `script.*` молча пропускается, `used by` пуст у всех модулей. Наблюдалось на `ReplicatedStorage.Packages.TestEZ` (`find_usages query="TestEZ"`, 16 модулей, у всех `used by: (none)`). Направление фикса: либо драйвер резолвит `script.*` до полного DataModel-пути, либо `_invert_lua_imports` получает путь импортёра и разворачивает `script.Parent` от него.


**Новые маркеры — открыто.** Кандидаты после первой партии:
- Структурные: `⚠ large-class` (аналог `⚠ large` для классов, ещё нет), `⚠ god-module` (слишком много символов).
- Графовые (сейчас есть только `⚠ cycle`): `⚠ unused-import` (импорт не используется в теле), `⚠ unused-symbol` (символ нигде не вызывается) — требуют символьного reverse.
- Паттерны (AST): `⚠ mutable-default`, `⚠ bare-except`, `⚠ async-no-await`.
- Docstring: `⚠ stale-docstring` (тело менялось после последнего обновления docstring) — параллель к `⚠ stale` для секций.
- Doc↔code: `⚠ broken-ref` (документ ссылается на удалённый символ), `⚠ undocumented`.

**Разделение по стоимости.** Inline (в `.md`, дёшево, на rebuild): структурные, паттерны, `stale-docstring`. On-demand (отдельный анализ, дорого): графовые расширенные, doc↔code.

**`refactor_rename` — закрыто для MCP-side как `grep_replace_mcp`.** Текстовый уровень, не AST: глобальный find-replace по идентификаторам с `word_boundary=true` и пачкой `mappings`. Двухпроходный гейт (`__EMPTY__` / `__OVERFLOW__`) до записи; Source не покидает Studio. Ограничения: не различает `local X` от глобального `X`, не покрывает табличную форму `obj["field"]`, Wally-пакеты в `_Index` защищены от случайной правки тем, что их имена с `.`/`-`/`@` не адресуются dotted-путём. **FS-side вариант `grep_replace`** (Python regex, полноценный dry-run, temp-файловый откат, работает в Rojo-mode) — отдельная задача. Семантически-точный rename на символьном уровне (нужен символьный reverse) — по-прежнему открыт как отдельная ниша.

**`⚠ no summary` для подсекций — открыто.** Сейчас метка ставится на все секции без summary, включая `###` и `####`. В проекте, где summary только у `##`, это даёт 90% шума. Варианты: (a) не помечать подсекции; (b) оставить как есть — метка честно говорит, где summary нет. Открыто потому, что решение зависит от конвенции проекта.

### 2.3 Инфраструктура

<!-- summary: Passthrough MCP-инструментов, sync CompositeBackend._state, пороги маркеров в конфиг, get_index overview, Rojo backend, ремастер GUI под MVP. -->

<!-- summary: Passthrough MCP-инструментов, sync CompositeBackend._state, пороги маркеров в конфиг, get_index overview, Rojo backend, ремастер GUI под MVP. -->

**Passthrough MCP-инструментов.** `insert_asset`, `generate_mesh`, `screen_capture` — регистрировать в `TOOL_MAP` при `MCPBackend.open()`, или оставить как есть (доступ через `MCPBackend.execute`)?

**`CompositeBackend._state` и смерть суббекенда.** `is_alive = any(sub.is_alive())` — правильный контракт (degraded = поддержанное состояние). Но `backend_state(name)` читает `_state[name]`, который обновляется только через `_set_state` (вызывается из `open` / `close` / `reopen`). Если MCP-процесс умер сам — `backend_state("mcp")` продолжает врать «ready». Сейчас это не критично: GUI опрашивает per-backend state и переоткрывает MCP сам при следующем патче. Варианты: (a) периодический sync `_state` с `sub.is_alive()`; (b) subscription — суббекенд уведомляет композит о смерти; (c) не менять — считать `is_alive` ответом на «стоит ли пробовать», а точный per-backend state получать у самого суббекенда. Скорее всего (c) достаточно.

**Пороги маркеров в конфиг — открыто.** `_LARGE_FILE_LINES = 300`, `_LARGE_FILE_KB = 16.0`, `_LARGE_SYMBOL_LINES = 100` сейчас hard-coded в `formats/renderer.py`. Обсуждалось вынести в конфиг (`large_file_lines`, `large_file_kb`, `large_symbol_lines`). Зачем: у разных проектов разная норма; «16 KB» для кода — одно, для данных — другое. Открыто потому, что до первой реальной жалобы на неверный порог менять смысла нет.

**`get_index overview` — открыто.** Сейчас `get_index` возвращает либо полный индекс (44–150 KB), либо обрезанный по `max_bytes` — оба плохи для первого контакта. Идея: режим `overview` (grouped или flat) — одна строка на файл/модуль, ~5 KB. Данные для него уже есть: маркеры, граф импортов, размеры, одна строка summary. Примерный формат:

```
toolkit/code/toolkit/backends/  (3 files, 1691 строк)
  mcp.py  1115 стр., 20 sym  ◉  ← 17 imp  → 5 users (2 tests)
  composite.py  414 стр., 5 sym  ← 6 imp  → 2 users
```

Два режима — `grouped` (по папкам, компактнее) и `flat` (одна строка на файл). Дефолт — `grouped`. Зачем: 5 KB против 150 KB, и видно отношения (кто hub по числу users, кто entry по `◉`), которых в детальном индексе не видно. **Открыто** потому, что нужно решить, что показывать для docs-индекса (там граф не применим) и как показывать символы (одной строкой на модуль или топ-N крупных символов).

**Rojo backend — открыто.** Обсуждалось в сессии. Третий namespace рядом с FS и MCP: Luau-код на диске (`.luau`/`.lua`). Дизайн:
- Выбор режима — один селектор в GUI: `Luau source: ( ) Studio (MCP)  (•) Disk (Rojo)`. Не две отдельные галочки — они могут разойтись.
- Формулировка про источник истины: в Rojo-mode Studio-копия существует, но **зеркалит диск** и не является источником истины. Правки идут в файлы, Studio подхватывает через Rojo-синк.
- Формат пути: обычный файловый (`src/ServerScriptService/Foo/init.luau`), не dot-notation.
- `rebuild_lua_code_index` в Rojo-mode строит индекс с диска через AST (не через MCP).
- Возможность использовать Python AST и regex на диске, что даёт более сильный инструментарий, чем MCP-путь (у которого `execute_luau` с песочницей).

Сцена (Parts, GUI, Folders) в обоих режимах идёт через MCP — ортогонально режиму Luau-кода. **Открыто** потому, что это большая задача (третий backend + переключение в GUI + параллельная логика в индексере), и делать её имеет смысл после того, как стабилизируется текущий Rojo-независимый контур.

**Ремастер GUI под MVP — открыто.** Шаг 1 (разрезание монолита) сделан: `runner/gui/` — пакет из `state.py` (константы + глобалы), `formatting.py` (чистые строковые хелперы), `widgets.py` (`StatusLog`), `starter_text.py` (поиск `LLM_START.<lang>.md`), `policy_io.py` (load/save policy) и `app.py` (~1600 строк, всё остальное). Шаг 2 (вынос мёртвого subprocess-пути `_run_apply_patches` и сирот-импортов) тоже сделан.

Осталось **шаг 3 — MVP-развязка**. Парадигма — **MVP (Model-View-Presenter)**, не MVVM и не классический MVC.

**Почему MVP.** Tkinter не имеет data binding — MVVM пришлось бы эмулировать через `trace_add`, что размазывает логику по View (антипаттерн для десктопа). Классический MVC на десктопе путается в вопросе «кто обновляет View»; MVP явнее: Presenter владеет реактивной логикой, View пассивна (только виджеты + события).

**Зачем.** Главная цель — сделать GUI **необязательным**. Вся логика в Presenter не зависит от Tk → можно подставить headless-view (CLI), и всё работает без дублирования кода. Уже есть `runner/cli.py` как один headless-view; Presenter даст второму потребителю ту же логику. `run_python` и MCP-мост перестают быть привязаны к GUI.

**Конкретный план.**
1. **3a.** `_session`, `_session_lock`, `_session_backend_name`, `msg_queue` — из `app.py` в `state.py` (или отдельный `session_store.py`).
2. **3b.** `worker` (применение патча с авто-rebuild) — в `runner/patch_runner.py`. Сейчас `worker` дублирует то, что делает CLI subprocess'ом; станет одной общей точкой.
3. **3c.** `app.py` — на `presenters/main.py` (логика) + `views/main_window.py` (виджеты). Presenter возвращает строки статуса колбэком, View их отображает.
4. **3d.** `open_settings_dialog` — на `presenters/settings.py` + `views/settings.py` + `views/policy_tree.py`.

**Открыто** потому, что это большая задача на несколько сессий. Делать её имеет смысл после того, как устаканится общий контур (Rojo-режим, символьный граф).

### 2.4 Гигиена и хвосты
<!-- summary: Хвосты сессии — гигиена файлов и документов, смоуки, .gitignore, переразбиение §1. -->

**_lua_script кэш без mtime.** Правки Lua-скриптов видны только после рестарта GUI. В штатной работе не критично.

**`adapter_lua` — границы внутри Lua-функции не покрыты тестом.** Блоки внутри Lua-функций не нумеруются (`blocks=[]`): token-парсер `formats/lua.py` не даёт statement-границ. Тест `tests/test_unit_bounds.py` проверяет только верхний уровень — что функции не пересекаются. Границы `head` / `body` внутри одной функции (`lua_signature_bounds` / `lua_body_bounds`) не покрыты — потенциальный третий off-by-one того же класса, что нашли в `adapter_md` и `adapter_py`. При доработке Lua-парсера (statement-границы) — добавить проверки на пересечения.

**Unit-тесты на list_with_stat / grep_mcp.** Только live-проверка.

**Batch verify / batch edit одного модуля.** Reliability > speed.

**`_check_target_survives` для move_symbol cross-file Lua** использует упрощённый `find_all_lua_symbols`.

---

**Гигиена файловой системы (хвосты сессии):**

- **`_reference/`** — старая копия утилиты в проекте MCPBridge, не индексируется (в `code_skip_dirs`), но физически лежит. Решение: удалить или оставить как исторический референс.
- **`toolkit/code/bridge/bridge_timings.log`** — старый лог, не пишется. Удалить.
- **`test2.json`** в корне проекта — заблокирован (открыт в другом процессе). Удалить после разблокировки.
- **`%SystemDrive%/`** в корне проекта — Windows Search cache, попал из внешнего процесса (не из кода утилиты). Уже удалён пользователем; если появится снова — искать источник (вероятно, сторонний скрипт с `%VAR%` без раскрытия).

**Гигиена документов:**

- **`CONFIG.md` §4 (Policy) и §6 (MCP)** — не перечитаны после config split. Возможно, устарели.
- **`ARCHITECTURE.md` / `LIFECYCLE.md`** — не трогали после config split и `state_dir`. Описание слоёв могло устареть.
- **`README.md`** — описание раскладки (`toolkit/runtime/state/`, `.patch_applier/`) могло устареть.
- **`DECISIONS.md` §1** стал `⚠ large` (20 KB, 37 решений). Кандидат на разбиение на подсекции (e.g., «Core», «Indexes», «Tools», «Config», «Markers»).

**Гигиена тестов:**

- **Смоуки `verify_*.py` в `manual/`** — их шесть с лишним (config_split, crlf_symbols, grep_paths, luau_mode, markers, read_axes, replace_part, replace_statement, repr_read, suppress, symbol_hash, symbol_indent). Обсуждалось: перенести в `tests/` как регрессионные или оставить ручными. Не решено.

**`.gitignore`:**

- `.patch_applier/` — служебный каталог проекта (индексы, sidecar, рантайм MCP). Решение о коммите/игноре не принято. Возможный вариант: игнорировать всё, кроме `config.json` (он описывает проект). Или наоборот — коммитить индексы, игнорировать рантайм (`patch.json`, `outputs.json`, `bridge_log.jsonl`).
