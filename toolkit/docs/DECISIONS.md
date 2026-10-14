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

<!-- summary: Завершён. Однокорневая модель удалена целиком; единая модель Workspace с пятью флагами PathPolicy (read / write / index_docs / index_py / index_lua) и per-path overrides. Шаги 1-4, 6 закрыты. GUI: File menu + Project settings + recent.json; Project settings оптимизирован (lazy render, кэш скана, cap по числу директорий). Проверено live на двух корнях (PatchApplier: toolkit + RimWorld). Открыто: 7.3 (дерево файлов), редактор per-path, единый текстовый матчинг. -->
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

**P1-фиксы тулов (сделано).** `insert_at_anchor` — auto-`\n` между anchor и `new_content`. `replace_between` — EOL-нормализация anchor'ов. Регрессии в `test_tool_edge_cases.py`.

**Пост-рефакторинг (2026-10-13).** Закрыты последствия перехода на multi-root:

- **`FilesystemBackend` больше не знает про `.patchignore`.** Раньше `open()` делал `patchignore.ensure_default(self._root)` — побочный эффект однокорневой модели, оставлявший дефолтный `.patchignore` в каждом корне. Поле `self._patterns` и метод `reload_patterns` не использовались вовсе (`filter_check` — `None`, policy в `WorkspaceBackend`). Всё удалено; авторитетный `.patchignore` — один, в `state_dir`.
- **GUI Project settings оптимизирован.** Три уровня: (1) `scan_subdirs_ex` с уровнем-за-уровнем обходом и `DEFAULT_SCAN_MAX_ROWS=200` (RimWorld `Mods/` останавливается на depth 2, не уходит в глубину каждого мода); (2) скан всегда с `show_hidden=True` (superset), фильтр в памяти — toggle show hidden без повторного диска; (3) чанковый рендер строк через `after` + кэш подписи в `PolicyTree.render`. Плюс census в корневой строке (`[RimWorld] (115 dirs, 3 hidden) (truncated at depth 3)`).
- **Отображение корневой политики.** `_flag_state` выводил состояние из наличия override (`.` → показывал точку, если `overrides["."]` отсутствовал). Для корня точки нет — наследовать не от чего. Теперь корневая строка всегда показывает эффективную политику. Два корня с идентичной политикой выглядят одинаково.
- **Multi-root проверен live.** Проект PatchApplier, корни `toolkit` + `RimWorld`. `test_workspace_backend.py` — 29/29.

**Git hygiene.** `.patch_applier/.gitignore` — индексируемые артефакты исключены; `workspace.json`, `.patchignore`, `.mcpignore`, `config.json` — в гите. `toolkit/.gitignore` — `runtime/`, `__pycache__/`. Раньше индексы и рантайм утекали в коммиты — теперь изолированы.

**Модель policy — пять флагов (не три).** `PathPolicy` (`read` / `write` / `index_docs` / `index_py` / `index_lua`) вместо старого `FilterSpec`. Каждый root имеет `overrides: dict[path, PathPolicy]`; ключ `.` — дефолт root'а, остальные ключи — относительные пути внутри. Nearest-match. Override — **полная замена**, не частичный мерж. Старые `FilterSpec` / `Policy` / `RootPolicy` удалены целиком.

**Открыто (следующие сессии):**

- **Дерево файлов в GUI (7.3).** Сейчас GUI не имеет file explorer вообще. Нужен design-док перед кодом.
- **Редактор per-path overrides.** Сейчас Project settings работает только с per-root default. Path-level — через `workspace.json` руками.
- **Шаг 5 (индексаторы).** Работают через `list("")`. На двух корнях в живом проекте проверено.
- **Уборка:** временные `_recon.py` / `_cleanup.py` / `_final_cleanup.py` / `_git_status.py`; устаревшие symbol-tools из `TOOL_MAP`.

**Root внутри state — снято.** В проекте PatchApplier `state_dir` (`.patch_applier/`) лежит рядом с корнями, не внутри. `_state_rel_for` остаётся для случая embedded-проектов, где root и state вложены друг в друга.

### Единый текстовый матчинг (открыто)

<!-- summary: Семантика матчинга строк размазана по четырём текстовым тулам. `replace_in_file` имеет tier'ы (byte-exact / trailing-whitespace); `replace_between` / `insert_at_anchor` / `replace_range` — byte-exact без нормализации. CRLF-файл + LF-anchor = no_match. Направление: единый модуль `toolkit/matching/text.py`, общий для всех четырёх тулов. -->

**Проблема.** Один и тот же текст в файле и в аргументе патча может отличаться EOL (`\r\n` vs `\n`) или trailing whitespace. Сейчас каждый тул решает это сам или не решает вовсе:

| Тул | Byte-exact | Trailing WS | EOL | Диагностика no_match |
|---|---|---|---|---|
| `replace_in_file` | ✅ | ✅ (tier 2) | ❌ | tier 3: top-3 похожих с маркерами |
| `replace_between` | ✅ | ❌ | ❌ | общая, без деталей |
| `insert_at_anchor` | ✅ | ❌ | ❌ | общая, без деталей |
| `replace_range` | ✅ (`expected_first_line`) | ❌ | ❌ | `content_mismatch` без деталей |

Практическое следствие: патч из LF-скрипта, применённый к CRLF-файлу, падает с `no_match` там, где инструмент мог бы найти с оговоркой. Замечено на живом проекте (RimWorld XML, `.Source`).

**Направление.** Единый модуль `toolkit/matching/text.py`, рядом с существующим `Pattern`:

```python
class TextMatch:
    start: int
    end: int
    normalization: str        # "none" | "trailing" | "eol" | "eol+trailing"
    candidates: list[str]     # при no_match — top-N похожих

def find_text(haystack, needle, *,
              normalize_eol=True,
              normalize_trailing=True) -> TextMatch | None
```

Все четыре тула ходят только сюда. `Result` получает поле `normalized: str | None` — чтобы LLM видел, что матч был не byte-exact. `no_match` отдаёт кандидатов с маркерами невидимых (`␣`, `⇥`, `⏎`).

**Почему отдельно от `Pattern`.** `Pattern` — регулярки/литералы для `grep`/`grep_replace`. `find_text` — byte-exact с tolerance для write-тулов. Разные задачи, разная семантика (в grep нормализация строк — вредная фича).

**Не в этой сессии.** Полезно всем Windows-проектам, но переписывание четырёх тулов + тесты + документация — отдельная задача на сессию.

### Внешние проекты: reconnaissance-driven workflow (2026-10-13)

<!-- summary: Первый живой кейс работы с чужим проектом (RimWorld, 86 модов, 30k файлов). Что подтвердилось, что добавили, что открыто. -->

**Кейс.** RimWorld как второй корень рядом с toolkit. 86 модов, 29 712 файлов, 1.5 GB. Задача — поправить поведение големов в моде «A RimWorld of Magic».

**Что сработало без изменений в утилите.** `grep`, `read_file`, `run_python`, `create_file` — весь путь от разведки до патча XML. Никаких расширений формата не понадобилось.

**Что добавили.** `survey_dir` — агрегат по расширениям и подкаталогам первого уровня; первый контакт с незнакомым корнем. `list_files` при >2000 файлов возвращает счётчик и подсказку вместо плоского списка. Оба — общие для любого домена, не только RimWorld.

**Что узнали про домен.** RimWorld — это `Defs/*.xml` с наследованием (`ParentName`) и overlay-патчами через `<Patches>/<Operation xpath=...>`. Структура принципиально та же, что `extends` в Factorio, `m_SourcePrefab` в Unity, `inherit` в k8s. Общая модель: именованная сущность + ссылка на родителя + патч поверх.

**Что открыто.**

- **XML как формат** — `list_units` / `read_unit` / `replace_unit` для `.xml`. Адресация по `defName`. Файл вроде `Golem_Race_Base.xml` (3180 строк, 104 KB) сейчас читается целиком — unit-модель его не покрывает.
- **`find_def`** — обёртка над XML-индексом. Cross-mod вопросы («кто ещё патчит этот def») требуют индекса, которого нет.
- **C# / декомпиляция** — отложено. Для RimWorld моды распространяются как `.dll`; без `ilspycmd` не видно, что внутри. Когда появится реальная задача на логику, которой нет в XML — вернуться.
- **Версионирование.** Моды вида `v1.0/` ... `v1.6/` — активна одна версия, остальные шум. Решение: `grep` по корню мода требует явного `directory=` на активную версию. Автоопределение — не делать, пока не увидим третий-четвёртый кейс.

**Не делать сейчас.** Обобщённая «декларативная модель сущностей» для всех форматов. Один сэмпл (RimWorld XML) не даёт достаточной базы. Factorio / Unity покажут, что общего, что специфично.

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
- ~~`verify_annotation`~~ — подтвердить annotation без правки файла. Заменяет `verify_section`. **Не реализован**; остаётся открытой нишей после сворачивания `verify_section`.

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

**Что скрывается из LLM_START §7.** `list_symbols`, `read_symbol`, `read_symbol_lua`, `replace_symbol`, `replace_symbol_body`, `replace_symbol_signature`, `replace_statement`, `replace_section`, `set_summary`, `verify_section`, `insert_symbol`, `delete_symbol`, `move_symbol`. Все они **удалены из `TOOL_MAP`** (см. абзац ниже) — определения остаются только в дереве для возможной реактивации.

**Итог по статистике (2026-10-11).** Metrics за 21 час работы (1030 действий): old symbol model — 16 вызовов (1.6% от всех), 6 из них с ошибками (37.5%). Unit model — 111 вызовов (10.8%). Text escape hatch — 146 (14.2%). Целевой индикатор победы модели (<15% escape hatch) достигнут. **Решение: удалены из `TOOL_MAP` 17 записей** — `list_symbols`, `read_symbol`, `replace_symbol`, `replace_symbol_body`, `replace_symbol_signature`, `replace_statement`, `delete_symbol`, `insert_symbol`, `move_symbol`, `replace_function`, `replace_function_body` (алиасы), `list_symbols_lua`, `read_symbol_lua`, `replace_function_lua`, `replace_section`, `set_summary`, `verify_section`. Файлы остаются в дереве (`tools/symbols/`, `tools/code.py`, `tools/lua_code.py`, `tools/write.py`) — если понадобится вернуть, раскомментировать одну строку в `tools/__init__.py`.

**Открыто** потому, что тулы волны 2 ещё не написаны, а решение о судьбе старых — по статистике после нескольких недель работы.

### 2.2 Граф и анализ

<!-- summary: Реализовано: маркеры (факты), suppression `# pa:`, модульный reverse, `find_usages`, source_hash в diff (лимит 2048 снят 2026-10-14, двойной префикс в Lua-индексе исправлен), `grep_replace_mcp` (MCP-side rename), `grep_replace` (FS-side, shared matcher, симметрия с `grep`), `⚠ no summary` только на `##`. Открыто: символьный reverse, diff edges, новые маркеры. -->

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

**`read_symbol include=callees` / `include=callers` — закрыто (2026-10-13).** Идея была сократить навигацию: символ + список вызываемых / вызывающих. Вместо этого есть `symbol_graph qualname=...` — тот же ответ одним вызовом, явное имя тула под задачу. `read_symbol` как таковой удалён ещё раньше (устаревшая символьная модель); открытая ниша закрыта, дублировать не нужно.

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

**`refactor_rename` — закрыто для обоих доменов.** Текстовый уровень, не AST: глобальный find-replace по идентификаторам с `word_boundary=true` и пачкой `mappings`. Двухпроходный гейт до записи; на MCP-стороне Source не покидает Studio (`grep_replace_mcp`, `__EMPTY__` / `__OVERFLOW__`); на FS-стороне — `grep_replace` с `dry_run=true` по умолчанию и per-file atomic write (без all-or-nothing отката: падение N-го файла не откатывает 1..N-1). Ограничения общие для обоих доменов: не различает `local X` от глобального `X`, не покрывает табличную форму `obj["field"]`, Wally-пакеты в `_Index` защищены от случайной правки тем, что их имена с `.`/`-`/`@` не адресуются dotted-путём.

**Симметрия с `grep` — контракт.** FS-side: общий матчер `toolkit/matching/Pattern`, `GrepTool` и `GrepReplaceTool` дергают его; `word_boundary` добавлен в существующий FS-`grep`, чтобы не было флага, доступного одному и недоступного другому. Scope-аргументы (`paths` / `directory` / `file_glob` / `exclude_glob`) и match-аргументы (`pattern` / `regex` / `fixed_strings` / `ignore_case` / `word_boundary`) — 1-в-1 с `grep`; дефолт `regex=true` совпадает. `no_matches` — `ok` с нулевым дельта (как у `grep`), а не `error` (как в MCP-версии). MCP-side: `grep.lua` и `grep_replace.lua` делят `_match.lua` через директиву `-- include:` в `_lua_script`; оба переписаны как per-line (было: grep per-line, replace whole-source — расходились на `^`/`$`). `require` не используется: `execute_luau` работает в изолированной VM, где `require` даёт свежую копию модуля, а не shared instance.

**FS vs MCP — параллельные домены, не унифицируются.** Разный язык паттернов (Python `re` vs Lua patterns), разный транспорт. Симметрия гарантируется **внутри** каждого домена, не между ними. `grep_replace` и `grep_replace_mcp` — соседи по назначению, не реализации.

Семантически-точный rename на символьном уровне (нужен символьный reverse) — по-прежнему открыт как отдельная ниша.

**`⚠ no summary` для подсекций — закрыто (2026-10-13).** Метка теперь ставится только на секции уровня `##` (`s.level <= 2`). Подсекции `###`/`####` наследуют контекст от родителя; шум в 90% случаев был ровно от них. Если для конкретного проекта нужна обратная политика — отдельная задача, включать при появлении реального кейса.

**Scope — LLM-editable область видимости (обсуждено 2026-10-14, отложено).** Отдельный файл `.llmscope` в `state_dir`. Include-only белый список: пустой или отсутствующий файл = «видно всё»; непустой — «показывай только то, что подходит под паттерны».

**Мотивация — три разные боли, не одна.**

1. **Handoff через контекстные окна.** Контекст LLM может оборваться в середине задачи (лимит). Новая сессия — новая LLM в новом окне. Открыть `.llmscope` и увидеть «работаю над модом 1201382956, фикс крафта» — это способ передать состояние между сессиями. Не только ограничение, но и **записка себе**.

2. **Индексы на больших корнях.** Пользователь-новичок указывает корень `RimWorld/` и говорит «сделай мод». Индекс по 30k файлов нечитаем и долго строится. LLM через scope сужает до `Mods/1201382956/v1.6/` — и работает локально, **не меняя корневой каталог**.

3. **Повторение `directory=`.** LLM в большом корне вынуждена повторять путь в каждом вызове. Забыть один раз — получить 29 000 путей. Обходной путь есть (писать явно), но он требует дисциплины.

Изначально рассматривалась только боль 3 — от неё можно было отмахнуться «правилом в LLM_START». Боль 1 и 2 правилом не решаются.

**Почему файл, а не поле в config.** Scope должен переживать рестарт GUI (юзер работает 2 часа, закрывает, возвращается на следующий день — LLM об этом не знает). Но и LLM должна уметь его менять — конфиг она не редактирует. Файл — единственный вариант, решающий оба требования. **Комментарии в файле — first-class контент**, не шум: `#` строки сохраняются в `get_scope` и служат памятью для следующей сессии.

**Не путать с `.patchignore`.** Разные задачи, разные файлы:

| | `.patchignore` | `.llmscope` |
|---|---|---|
| Логика | исключить перечисленное | оставить только перечисленное |
| Кто пишет | человек | LLM (или человек) |
| Природа | security — `refused before policy` | UX — область видимости |
| Поведение | отклоняет операцию | фильтрует вывод |
| Применение | всегда | поверх `.patchignore` |
| Комментарии | для человека | **память для LLM** |

Оба работают параллельно: `.patchignore` режет `__pycache__`, `.llmscope` сужает до конкретной папки.

**Вариант A: scope режет и build индекса, и read-тулы.**

**Контракт.** Три тула:

- `get_scope` (`op="read"`) — текущее содержимое `.llmscope` (текст как есть, включая комментарии).
- `set_scope` (`op="write"`) — заменить целиком. **Только replace, не append.**
- `clear_scope` (`op="write"`) — очистить (эквивалент «видно всё»).

**Секция в `get_status`:**

```
## Scope
# Работаю над модом 1201382956 — фикс крафта блоков
RimWorld/Mods/1201382956/v1.6/**
```

Показывается **всегда при непустом файле**, независимо от `sections=`. Пустой/отсутствующий `.llmscope` — секции нет. Слишком важный контекст, чтобы его скрывать параметром.

**Фильтрация build индекса.** `rebuild_index` / `rebuild_code_index` / `rebuild_lua_code_index` собирают **только то, что попадает в scope**. Это ключевое отличие от «soft filter»: индекс реально маленький и быстрый. Если scope указывает на подкаталог `RimWorld/Mods/1201382956/` — индекс включает только его, а не 30k файлов корня.

**Фильтрация read-тулов.** Параметр `respect_scope=True` (дефолт):

- `list_files`, `survey_dir`, `grep` — да.
- `grep_replace`, `grep_replace_mcp` — да. Самый опасный mass-replace — забыть `directory=` и заменить по всему проекту; scope как страховка.
- `read_file`, `read_unit`, `file_stat` — **нет**. Точечное чтение всегда явное: LLM назвала путь — хочет этот путь.
- `replace_in_file`, `replace_unit`, `insert_block`, `set_annotation`, `delete_file`, `move_file` — **нет**. По той же логике явного адреса.
- `get_index`, `get_status` — **нет**. Индекс уже собран по scope (см. выше), повторно фильтровать нечего. `get_status` показывает `## Scope` как контекст.

`respect_scope=False` доступен во всех scope-aware тулах — если LLM осознанно хочет обойти scope, она может.

**Формат файла.** Один glob на строку, как `.patchignore`. `#` — комментарий (сохраняется), пустые строки игнорируются. Несколько строк = union («показывай то, что подходит под любой из паттернов»). Пустой файл или отсутствующий = нет фильтра.

**Path-форма.** Root-relative с basename, как везде в FS-тулах: `RimWorld/Mods/1201382956/v1.6/**`. Единообразие с `list_files` важнее «относительно project_dir».

**Не блокирует.** Scope — не security-граница. LLM может расширить себе scope одним `set_scope("**")`. Это не дыра: scope — область видимости, а не песочница. Пользователь увидит в `get_status`, что scope не тот, и поправит. Подтверждение не требуется.

**Инвалидация при смене корней — тихо игнорировать.** Если scope ссылается на удалённый корень, правило просто не матчится. Scope может переживать временное отсутствие корня — когда корень вернётся, правила снова начнут работать.

**Где это будет.** `toolkit/config/llmscope.py` (parse / read / write / matches — по аналогии с `patchignore.py`); `toolkit/tools/scope.py` (три тула); секция в `tools/status.py`; `respect_scope` в `read.py` и в `grep_replace.py` / `grep_replace_mcp.py`; фильтр в `indexers/doc.py` / `indexers/code.py` / `indexers/lua_runner.py`; три тула в LLM_START §7 (ru+en).

**Минус.** Новый файл в `state_dir` (третий после `.patchignore` / `.mcpignore`). Пользователь может запутаться в семантике трёх файлов. Митигация: `.llmscope` — единственный, который LLM правит сама; в GUI его можно вообще не показывать (или показывать как read-only индикатор в главном окне).

**Вариант B (альтернатива): индекс строится полностью, фильтруется только отображение.**

Индекс — как сейчас, по всему корню. Scope фильтрует:
- **diff** — показывать только изменения в scope.
- **`get_index`** — вернуть только блоки, попадающие в scope.
- **read-тулы** (`grep` / `list_files` / `survey_dir`) — как в A.

Плюсы:
- Проще: не трогаем build-логику, только фильтруем представление.
- Индекс по-прежнему полный — можно посмотреть за пределами scope через `path_filter` или `respect_scope=False`.
- Diff показывает изменения вне scope — LLM видит, что там что-то произошло (может пригодиться).

Минусы:
- **Не решает боль №2** — индекс по 30k файлов всё равно нечитаем и долго строится. Фильтрация вывода не уменьшает rebuild.
- Компромисс между нагрузкой и удобством.

**Промежуточный вариант B+:** индекс строится полностью, но `get_index` по умолчанию возвращает scope-представление. `get_index(scope="full")` — полный. Это то же, что открытый `get_index overview` (см. §2.3), но через scope.

**Статус: отложено.**

**Почему не делаем сейчас.**

- Дизайн нетривиален (персистентность, комментарии, связь с build-логикой).
- Реального кейса в текущих сессиях не было — мы обошлись `directory=`.
- Метрика готовности: **сколько раз за сессию LLM была бы рада «записке себе» в `.llmscope`?** Если 3+ раза — делаем. Пока — 0.

**Когда возвращаться.** При первых признаках одного из трёх:
- Пользователь жалуется, что индекс не влезает в контекст.
- Rebuild большого кодового проекта (не 181 модуль, а 2000+) идёт минутами.
- Задача переживает контекстное окно чаще одного раза за сессию (реальный handoff).

**Что решать при реализации:**
- Как именно индексируется scope в A — отфильтровать вход или отфильтровать выход? Вход (не скармливать файлы вне scope в parser) — быстрее, но требует правки walk-логики в 3 индексаторах. Выход (собрать всё, отфильтровать при рендере) — проще, но не решает rebuild-время.
- B vs A: тестировать на реальном большом проекте.
- Union vs один путь. Для MVP — union, как `.patchignore`.

**`source_hash` — снят лимит 2048 байт (2026-10-14).** Раньше полиномиальный хеш считался только по первым 2048 байтам и модуля, и символа (Python `formats/code.py:HASH_LIMIT_BYTES`, Lua `lua_symbols.lua` и `code_index_regen.lua`). Следствие: правка в файле длиннее 2 KB **не меняла модульный хеш**, если была за пределами первых 2048 байт. Diff не видел изменений (`[без изменений]`), хотя файл реально менялся. Observed на `tools/write.py` (37 KB): правки в `ReplaceBetweenTool` (~L270) и `_find_all` (~L770) не отражались в `CODE_INDEX.md`.

**Мотивации лимита не нашли.** Ни в коде (нет использования кросс-сравнения Python↔Lua хешей — grep пуст), ни в документации (DECISIONS/ARCHITECTURE/REQUIREMENTS лимит не упоминают), ни в истории обсуждений. Докстринг говорит «matches Lua-side impl» — но это требование согласованности алгоритма, а не мотивация усечения. Считаем техническим долгом, а не осознанным решением.

**Фикс:** лимит убран во всех трёх местах; хеш считается по всему источнику. Совпадение Python ↔ Lua сохраняется (один алгоритм: `h = h*31 + byte`, mod 2³¹−1, seed 17) — теперь согласованно и без усечения. Тест `test_code_parser.py` инвертирован: было `hash ignores bytes past limit`, стало `hash covers whole source`. Первый rebuild после фикса показал `~N` для всех модулей >2 KB — ожидаемое одноразовое событие.

**Двойной префикс `.patch_applier/.patch_applier/` (2026-10-14).** `RebuildLuaCodeIndexTool` строил путь как `local_dir / out_name`, где `out_name` уже содержал `.patch_applier/`. Результат: файлы писались в `.patch_applier/.patch_applier/CODE_INDEX_LUA.md`, а читались из `.patch_applier/CODE_INDEX_LUA.md`. Diff видел изменение в одном файле, `get_index` читал другой — рассогласование.

**Дополнительная проблема в том же туле:** индекс писался через `Path.write_text` (в обход backend), а version-файл — через `bump_seq(backend, ...)`. Два разных способа записи в одном туле. `RebuildIndexTool` и `RebuildCodeIndexTool` пишут через `backend.write(out_path, ...)` — Lua-тул был единственным исключением.

**Фикс:** Lua-тул приведён к тому же способу, что и два других — `backend.write(out_path, text)` / `backend.write(manifest_path, ...)`. Прямая запись в FS убрана. Все три rebuild-тула пишут единообразно, `WorkspaceBackend._state_write_target` резолвит `.patch_applier/...` правильно. Тест `test_lua_indexer.py` проходит без изменений (аргумент `output` работает как раньше).

### 2.3 Инфраструктура

<!-- summary: sync CompositeBackend._state, пороги маркеров в конфиг, get_index overview, Rojo backend, ремастер GUI (Functional Core). Закрыто: Passthrough MCP-инструментов, error_code hidden_path, verify_syntax как тул, LLM_START module= warning. -->

**Passthrough MCP-инструментов — закрыто.** Работает через `MCPBackend.invoke_native` (`native_tools_enabled=true` в конфиге). Нативные тулы (`insert_asset`, `generate_mesh`, `screen_capture`, ...) вызываются тем же патч-форматом под их оригинальными именами; схемы — в `tools_schema.json`. Гейтится флагом `native_tools_enabled`; при выключенном флаге — `error_code="native_tools_disabled"`. См. LLM_START §Native Roblox tools.

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

**Умный рестарт сессии после сохранения настроек — открыто.** Сейчас `_on_settings_saved` всегда вызывает `_switch_project`, который пересоздаёт Session целиком: закрывает старую, строит новую, гоняет `_initialize_project` (rebuild docs + py), ждёт MCP, дёргает `_rebuild_lua_after_ready`. На выходе — три строки в логе (`Lua индекс перестроен`, `Session готова`, `Проект инициализирован`) даже когда пользователь только переименовал проект или подкрутил policy в одном корне. На текущем проекте это ~2 секунды + MCP roundtrip; на большом было бы заметнее.

**Что нужно.** Сравнивать CONFIG до открытия диалога и после Save. Пересоздавать сессию, только если изменилось что-то из списка: `backend`, `luau_mode`, `index_docs` / `index_python` / `index_lua` / `index_rojo`, `exec.enabled`, состав roots (`w.root_names()`), `project_dir`. Остальное (переименование, per-path policy, `.patchignore`-правила) применяется без рестарта — часть на лету, часть требует только `_cfg.save` + `update_project_status`.

**Сложность.** Не все поля одинаковы. `backend` / `luau_mode` действительно требуют пересборки бэкенда и Session. Roots policy живёт в `Workspace`, который загружается при старте сессии — менять на лету можно, но нужна аккуратная работа с `root.overrides` в памяти. Rename — только `save_workspace` без сессии. Нужно продумать, какие поля относятся к какой категории, иначе появятся состояния «настройки сохранены, но в памяти применились частично».

**Почему отложено.** Раздражает мало (2 секунды на нашем проекте), правильная реализация требует аккуратной классификации полей и теста на «частичный рестарт». Метрика возврата: пользователь жалуется, что сохранение настроек «долгое», или переключение проектов становится частым сценарием.

**Ремастер GUI — закрыт (3a-3d).** Шаг 1 (разрезание монолита) сделан: `runner/gui/` — пакет из `state.py`, `formatting.py`, `widgets.py`, `starter_text.py`, `policy_io.py`, `app.py` (остаток Tk-оболочки). Шаг 2 (вынос мёртвого subprocess-пути) сделан. Шаг 3 (парадигма) закрыт.

**Парадигма — Functional Core / Imperative Shell**, не MVP и не MVC. Изначально планировался MVP (Model-View-Presenter), но на реальном коде Tk-приложения он выродился в другую форму: ядро — модуль чистых функций, оболочка — Tk-виджеты и callback'и, связь односторонняя View → Core. Обратных ссылок нет.

**Почему не MVP.** MVP потребовал бы: (а) класса Presenter со ссылкой на View и циклическим `View ↔ Presenter` — в Tk с его callback-моделью это ловушка; (б) абстрактного интерфейса View для подмены на CLI-View с 20 методами-заглушками. Functional Core снимает обе проблемы: `decide_button_state(...)` тестируется как чистая функция без мока View, а CLI зовёт тот же `patch_runner.apply_patch` напрямую — второй View не нужен.

**Граница.** Ядро (`patch_runner.py`, `presenters/main.py`) — без Tk, без `pyperclip`, без чтения `msg_queue`. Принимает `config` аргументом, возвращает dataclass'ы (`ApplyOutcome`, `ButtonDecision`). Оболочка (`app.py`) — построение виджетов, Tk-callback'и, `msg_queue`, `pyperclip`, запись `last_*.{json,txt}`. Связь: `app.py` → ядро; ядро про `app.py` не знает.

**Что вынесено.**
1. **3a.** `_session`, `_session_lock`, `_session_backend_name`, `msg_queue` → `state.py`.
2. **3b.** `worker` → `runner/patch_runner.py` (`apply_patch`, `ApplyOutcome`, `ApplyError`).
3. **3c.** `presenters/main.py` — helpers, state updaters, starter text, session lifecycle. `app.py` оставлен как Tk-оболочка.
4. **3d.** `cli.py` — default path через `patch_runner` (headless parity с GUI), legacy-путь через `--no-auto-rebuild`.

**Что осталось (не блокирует).** `views/main_window.py` — вынос 200-строчного `run()` из `app.py`. Чистое разложение View, логика уже в ядре. Отдельной сессией.

**Точки расширения** (см. `REQUIREMENTS.md` → «Extension seams») держат: Rojo, Unity, новые индексы, новые тулы, headless, agent-mode. Две (новые индексы, Unity bridge) потребуют локальных правок при добавлении, но не ломают архитектуру.

**Tooling improvements from the 3a-3d session (открыто).** Наблюдения из сессии рефактора GUI. Приоритет — по убыванию пользы.

1. ~~`verify_syntax` как tool.~~ **Закрыто (2026-10-13).** `toolkit/tools/verify.py` — `VerifySyntaxTool`, `paths` (список `.py` файлов/каталогов) или `directory`. Компиляция через `compile(src, path, "exec")` по тексту, прочитанному через backend (работает и на Roblox `.Source`). `error_code="syntax_error"` с L:C и текстом ошибки при провале.

2. **`git_*` как tools.** `_git.py` — пользовательский скрипт в `manual/`, фактически критичен для workflow (10 коммитов за сессию). Как нативные tools (`git_commit`, `git_status`, `git_diff`, `git_log`) — стандартный Result, verify-after-write, не надо помнить путь.

3. ~~`error_code` для скрытых путей.~~ **Закрыто (2026-10-13).** `filter_check` сменил сигнатуру с `str | None` на `(error_code, message) | None`. `WorkspaceBackend` различает `hidden_path` (совпал `.patchignore` или dot-dir) и `filter` (per-path policy / unknown root). `Patcher._filter_paths` пробрасывает код в `Result.error_code`. Тесты `test_workspace_backend.py` обновлены.

4. **`get_index` path_filter.** `kind` обязателен, но нет фильтра по путям. Когда работаешь с одним файлом — 33 KB doc-индекса избыточны. `{"kind": "docs", "path_filter": "toolkit/docs/TOOL_PRACTICE.md"}`.

5. ~~LLM_START: `run_python module=` — предупреждение.~~ **Закрыто (2026-10-13).** В LLM_START §Execution (ru + en) добавлено предупреждение: `module=` = `python -m` = `__main__`; импорт модуля с `if __name__ == "__main__":` запустит его; инцидент с `toolkit.runner.gui.app` упомянут явно. Для проверки синтаксиса без запуска — `verify_syntax`.

6. **`settings_window.py` не вынесен.** `_menu_project_settings` всё ещё открывает `gui/settings_window.py` напрямую (581 строка Tk). В Functional-Core парадигму не завернут. Отдельная задача, если понадобится headless-доступ к настройкам проекта — сейчас это чисто GUI-операция.

7. **`.gitignore` для runtime-логов.** `toolkit/code/bridge/bridge_timings.log` (547 KB на момент сессии) и `toolkit/code/toolkit/runner/last_*.{json,txt}` ездят в каждом коммите. Кандидаты: `runtime/logs/`, `last_*.{json,txt}`, `*.log`. Решение: добавить в `toolkit/.gitignore` (или `.patchignore`, если это runtime, не история).

8. **`TOOL_PRACTICE §2` устарел.** Таблица «Инвентарь: что использовалось» — снимок прошлой сессии. Три тула из «ни разу» реально использовались: `replace_range` (11 раз), `insert_block` (21), `move_file` + `copy_file` (5). Обновить таблицу реальными цифрами из `metrics.json`, пометить, что «не использовался» ≠ «не рекомендован». Отдельная задача.

**Unused tools — inventory from the session.** Из 32 тулов в `TOOL_MAP` не использовались:

- **`copy_unit`, `find_symbol`, `find_usages`, `symbol_graph`, `set_annotation`, `grep_lua`, `grep_replace_mcp`, `file_stat`** — не было задачи: рефакторинг шёл по горизонтали (вынос кода), не по графу (навигация, анализ, массовые замены). **Не удалять** — это резерв под другие задачи. См. TOOL_PRACTICE §3 «Ни разу не использовались» и §7 — список растёт, но по фактам это не мёртвый груз.
- **Native Roblox tools** (`execute_luau`, `script_read`, `multi_edit`, `inspect_instance`, `search_game_tree`, генеративные) — не звал: всё делалось через унифицированные тулы, а `rebuild_lua_code_index` сам зовёт `execute_luau` под капотом. Единственный кандидат, где бы пригодился `inspect_instance` — диагностика дубля `ServerScriptService.Server.Main.server` в lua-индексе. Не стал тратить время.

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
