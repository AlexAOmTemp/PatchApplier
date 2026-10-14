# Архитектура

> **Статус:** принципы и контракты, не список фактов. Актуальные сигнатуры и состав тулов — в `CODE_INDEX.md`. Инструкция для LLM — в `LLM_START.{lang}.md`. Если этот документ расходится с кодом — верь коду.
>
> **Что здесь:** почему так устроено (слои, протоколы, инварианты). Чего здесь нет и не будет: полного списка тулов, дорожных карт, актуального file layout — они дрейфуют каждый день.

## 1. Слои

<!-- summary: Патч → Patcher → Tools → {Backend, Format, Indexer, Matching} → core models. -->
<!-- tags: architecture, layers -->

```
Патч (JSON) → Patcher → Tools → { Backend, Format, Indexer, Matching } → core models
```

- **Patcher** — dispatch, фильтрация по `op`, агрегация Result, `##RESULT:` для GUI.
- **Tools** — реестр действий.
- **Backend** — транспорт: `FilesystemBackend`, `MCPBackend`, `CompositeBackend`.
- **Format** — канонизация текста в `Section[]` (markdown) или `Module` (Python / Lua).
- **Indexer** — структуры → текст (`INDEX.md`, `CODE_INDEX.md`).
- **Matching** — чистый матчер строк, разделяемый между `grep` и `grep_replace` (`Pattern`, `is_word`). Не знает ни о backend, ни о формате, ни о патчах.

Tool — чистая функция над `(Backend, Format, **kwargs)`, возвращает `Result`.

## 2. Hardcore — фиксируется

<!-- summary: Модели, протоколы, diff, RESULT, Policy. -->
<!-- tags: architecture, hardcore -->

### 2.1 Модели

- `Section` — markdown-секция: level, number, title, summary, tags, body_start/end, children
- `Symbol` — код-символ (Python / Lua): name, qualname, kind, line_start/end, signature, docstring, decorators, parent
- `Module` — распарсенный файл: path, source, source_hash, source_len, symbols, imports
- `Delta` — lines, bytes, occurrences
- `Result` — status (`ok` / `error` / `skipped` / `blocked`), message, delta, verified, error_code, id_label (метка из `id` действия патча, для лога)
- `FilterSpec` — per-role policy: dict `{path: bool}` с наследованием
- `Policy` — три FilterSpec'а: `read`, `write`, `index`
- `FileStat` — size_bytes, lines, mtime, is_file

### 2.2 Роли маркеров (markdown)

`summary`, `tags`, `large_ok`, `flat` — фиксированные роли. Конфигурируется только их обозначение в тексте (через preset).

### 2.3 Протокол Backend

```python
class Backend(Protocol):
    # lifecycle
    def open(self) -> None: ...
    def close(self) -> None: ...
    def is_alive(self) -> bool: ...
    # data
    def read(self, path: str) -> str: ...
    def write(self, path: str, content: str) -> None: ...
    def exists(self, path: str) -> bool: ...
    def stat(self, path: str) -> FileStat: ...
    def list(self, root: str, glob: str = "*") -> list[str]: ...
    def delete(self, path: str) -> None: ...
    def move(self, src: str, dst: str) -> None: ...
    # filter (домен-специфично: FS-пути vs DataModel-пути)
    def filter_check(self, path: str, spec: FilterSpec) -> str | None: ...
```

`CompositeBackend` реализует тот же протокол, маршрутизируя вызовы по `_owner(path)`. `MCPBackend` дополнительно имеет `execute(code, datamodel_type)` — низкоуровневый доступ к `execute_luau` для операций, у которых нет высокоуровневого Tool'а.

### 2.4 Протокол Tool

```python
class Tool(Protocol):
    name: str
    op: str                      # "read" | "write" | "index"
    path_args: list[str]         # kwargs с одним путём
    path_list_args: list[str]    # kwargs со списком путей
    def execute(self, backend: Backend, fmt: Any, **kwargs) -> Result: ...
```

Tool не знает про sandbox, whitelist, session, GUI. Patcher по атрибуту `op` выбирает нужную роль `Policy` и проверяет `path_args` / `path_list_args`.

### 2.5 Diff

`~ / ⇅ / + / -` — универсальный алгоритм. Ключ сравнения (heading для доков, qualname для кода) — параметр. Diff возвращает структуру, а не готовый текст.

### 2.6 ##RESULT:

Финальная строка каждого патча для GUI. Структура: `{ok, errors, skipped, failed: [ids], blocked: [ids]}`. Опциональное поле `diagnostics` — сообщения парсера патча (см. `core/patchparse.py`): список `{kind, line, column, message}`. Появляется только при наличии диагностик.

### 2.7 Парсер патча

`core/patchparse.py` — толерантный парсер входного текста. Каждое действие обязано иметь поле `id` (любое JSON-значение). Формат — одно действие в `[...]` группе; группы идут подряд. Результат — `ParseResult(actions, diagnostics)`. Сломанный фрагмент, объект без `id`, дубликат `id` порождают `Diagnostic(kind, line, column, message)` и не мешают остальным. Рендер — `Patcher.print_diagnostics`.

### 2.8 Policy

```python
@dataclass
class FilterSpec:
    overrides: dict[str, bool]   # "." -> False, "toolkit" -> True, ...
    def resolve(self, path: str) -> bool: ...

@dataclass
class Policy:
    read: FilterSpec
    write: FilterSpec
    index: FilterSpec
    def for_op(self, op: str) -> FilterSpec: ...
```

- `overrides[path] = True` — путь явно разрешён
- `overrides[path] = False` — путь явно запрещён
- Отсутствующий путь наследует ближайшего предка, дефолт — разрешено
- `.` — корень. Легаси `mode=white` разворачивается в `{".": False, **{p: True}}`, `mode=black` — в `{**{p: False}}`

## 3. Правила зависимостей

<!-- summary: tools → backends/formats/indexers/matching → core. Обратных импортов нет. -->
<!-- tags: architecture, dependencies -->

`tools → {backends, formats, indexers, matching} → core`. Обратных импортов нет. `runner` знает обо всём, но не наоборот.

`matching/` — единственный слой, который импортируют два тула, чтобы иметь **общую** семантику матчинга. Он не должен зависеть ни от `backends`, ни от `formats`, ни от `tools`: только чистые функции над строкой. Если завтра ещё один тул захочет тот же матчер — он импортирует `matching`, а не копирует логику.

## 4. Инварианты

<!-- summary: 7 правил — Tool без sandbox, Result структурный, diff ключ-агностичен, core священный. -->
<!-- tags: architecture, invariants -->

1. Tool не знает про sandbox — проверки делает Patcher до вызова.
2. Indexer возвращает структуру, не текст.
3. Result всегда структурный.
4. Diff ключ-агностичен.
5. Config — декларация, не логика.
6. Presets — first-class.
7. `core/` — священный, изменения ломают всех.

## 5. Python vs Lua: где выполняется работа

<!-- summary: Данные парсятся там, где лежат. Roblox — на стороне Studio, всё локальное — Python. -->
<!-- tags: architecture, python-vs-lua -->

**Принцип.** Данные парсятся там, где они лежат. Roblox DataModel не локальный — обход и cross-module анализ выполняются на стороне Studio (`execute_luau`), одним round-trip'ом. Всё локальное (docs, Python-код, policy, sandbox, verify) — Python.

**На Lua (в Studio):**
- Обход DataModel для `rebuild_lua_code_index` — один `execute_luau` с циклом.
- Cross-module операции — `refactor_rename` теперь `grep_replace_mcp` (текстовый, не AST, per-line на Lua-стороне); marker scan по-прежнему открыт.

**На Python (локально):**
- Одиночные операции над модулем (`read_unit`, `replace_unit` на Luau-пути) — round trip всё равно один; оверхед Lua не окупается.
- Docs, Python-код, policy, sandbox, verify — ядро toolkit'а.

**Следствие.** `toolkit/formats/lua.py` (Python-парсер Lua) остаётся для одиночных операций и parity-тестов. Bulk-путь для Roblox-индекса — на Lua.
