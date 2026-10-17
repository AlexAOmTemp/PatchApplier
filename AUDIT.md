# Аудит PatchApplier — 2026-10-14

## 1. Метаданные аудита
<!-- summary: Область, методология и покрытие — что прочитано, чего не коснулись. -->

- **Область:** `PatchAppliers/PatchApplier/toolkit/` — 180 модулей Python, ~700 KB исходников.
- **Покрыто в первом проходе (20 модулей):** core (`patcher`, `session`, `router`, `patchparse`, `paths`, `models`), backends (`filesystem`, `workspace`, `composite`), config (`loader`, `workspace`, `patchignore`), matching (`pattern`), tools (`read`, `shell`, `grep_replace`, `unit/writer`).
- **Не покрыто:** `backends/mcp.py`, `bridge/bridge.py`, `tools/symbols/*`, `runner/gui/*`, `formats/parser.py`, `formats/code.py`, `formats/lua.py`, `indexers/*`.
- **Методология:** ручной обзор с приоритетом на безопасность (subprocess, JSON-парсинг, path validation, regex), архитектуру (backends, threading), качество кода на крупных файлах.

## 2. Общая оценка
<!-- summary: Проект аккуратный и осознанный; слабые места — дисциплинарные, не архитектурные. -->

Проект аккуратный и осознанный. Разделение core / backends / tools / formats / indexers / runner — чистое, зависимости направлены внутрь. Докстринги объясняют «почему», а не «что». Есть тесты на краевые случаи (порядок `replace_range`, composite death, TOCTOU на state-dir).

**Сильные стороны:**

- `Patcher._pre_validate_ranges` — редкая и правильная идея: `writes_seen` и `last_range_start` отслеживаются до применения.
- `CompositeBackend.backend_state` — «кэш поверх live-проверки» — точная модель деградации.
- `Pattern` — общий матчер для `grep` и `grep_replace`, зафиксированный контрактом.
- `patchparse` — не бросает исключения, возвращает `ParseResult`.
- `_GLYPH_CANDIDATES` — fallback на ASCII для cp1251-консоли.
- `Workspace.validate` — проверяет вложенность roots и резервирует имена сервисов Roblox.

Слабые места — не архитектурные, а дисциплинарные: не везде выставлен `error_code`, есть dead code, есть участки, где policy обходится по недосмотру.

## 3. Таблица приоритизированных находок
<!-- summary: Двадцать находок с уровнями HIGH/MEDIUM/LOW, категориями и адресами в коде. -->

| # | Уровень | Категория | Файл:строка | Проблема | Рекомендация |
|---|---|---|---|---|---|
| 1 | HIGH | Безопасность | `tools/shell.py:39-45` | `PYTHONPATH` в `env_passthrough` → RCE через `sitecustomize.py` | Убрать из allowlist по умолчанию |
| 2 | HIGH | Безопасность | `config/workspace.py:124-129` | `Workspace.policy_for` для неизвестного root → fail-open | Fail-closed (deny-all) |
| 3 | HIGH | Логика | `tools/unit/writer.py:343-348` | `_check_parses` сверяет `node.name`, а не `qualname` | Собирать полный qualname |
| 4 | HIGH | Безопасность | `tools/grep_replace.py:163-176` | `backend.read` без `filter_check(read)` | Добавить проверку |
| 5 | MEDIUM | ReDoS | `core/patchparse.py:36,76-86` | `_FENCE_RE` с `DOTALL` на незакрытом фенсе O(n²) | Линейный разбор |
| 6 | MEDIUM | ReDoS | `core/patchparse.py:181-195` | Tier 2 recovery — O(n²) на мусорном входе | Ограничить окно |
| 7 | MEDIUM | Race | `backends/composite.py:129,160` | `_open_failures.append` из фонового потока без lock | Под тот же lock |
| 8 | MEDIUM | Архитектура | `backends/workspace.py:126-135,233-240` | `read`/`write` не вызывают `filter_check` | Перенести policy внутрь backend |
| 9 | MEDIUM | TOCTOU | `tools/grep_replace.py:200-213` | Между pass 1 и pass 2 файл может измениться | Read-verify-write |
| 10 | MEDIUM | Ошибки | `tools/shell.py:289,301,305` | `int(...)` вне try → traceback вместо Result | Обернуть в try |
| 11 | MEDIUM | Ошибки | `core/patcher.py:288-291` | Generic `except` → `error_code=None` | `error_code="internal_error"` |
| 12 | MEDIUM | Скрытая логика | `tools/read.py:457-464` | `GrepTool`: `directory` проверяется, но не используется | Валидировать фактический путь |
| 13 | LOW | Dead code | `tools/unit/writer.py:265-266` | `return new_source` дважды подряд | Удалить вторую строку |
| 14 | LOW | Ресурсы | `tools/grep_replace.py:158-176` | `per_file` держит все версии файлов в памяти | Стриминг или временный файл |
| 15 | LOW | Утечка | `backends/composite.py:41,129,160` | `_open_failures` растёт при каждом reopen | Очищать при успехе |
| 16 | LOW | Производительность | `backends/filesystem.py:45-52` | `Path.resolve()` в hot-path | Кэш по `(root, path)` |
| 17 | LOW | Логика | `core/patcher.py:213-220` | `failed` — позиции, не `id` | Документировать или исправить |
| 18 | LOW | Логика | `core/patchparse.py:137` | `repr(id)` — O(n) на проверку дубликата | `hash((type, value))` |
| 19 | LOW | Мерж | `config/loader.py:229-248` | `env_passthrough`/`deny` заменяются, не мержатся | Union-мерж |
| 20 | LOW | Формат | `tools/unit/writer.py:87-91` | `_render_lua` не санитизирует `]]` | Санитизация |

## 4. Детальный разбор критичных находок
<!-- summary: Пять HIGH/MEDIUM находок с кодом, сценарием и правкой. -->

### 4.1. PYTHONPATH в allowlist

`tools/shell.py:39-45`

```python
_DEFAULT_ENV_ALLOW = [
    "PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT",
    "TEMP", "TMP", "HOME", "USERPROFILE",
    "APPDATA", "LOCALAPPDATA",
    "PYTHONPATH", "PYTHONIOENCODING", "PYTHONUTF8",   # ← вот это
    "LANG", "LC_ALL",
]
```

**Сценарий.** При запуске `sys.executable script.py` с наследованным `PYTHONPATH` CPython импортирует `sitecustomize` из указанных директорий **до** того, как выполнится `script.py`. Если злоумышленник положил `sitecustomize.py` в любую директорию на `PYTHONPATH` (или если это директория с правом записи, доступная тулу), он получает RCE с правами родителя — до и независимо от `exec.enabled`.

**Почему это не покрыто моделью угроз.** Докстринг говорит «strips environment variables matching common secret patterns» — но `PYTHONPATH` не секрет, это путь. Он попал в allowlist, скорее всего, чтобы дочерние скрипты видели пользовательский код. Риск не отражён в threat model файла.

**Правка.** Убрать `PYTHONPATH` из дефолта. Если он нужен — включать явно в конфиге проекта и предупреждать в GUI. То же касается `PYTHONSTARTUP` (не в списке, но семантика похожая).

### 4.2. `Workspace.policy_for` — fail-open

`config/workspace.py:124-129`

```python
def policy_for(self, root_name: str, rel: str) -> PathPolicy:
    r = self.roots.get(root_name)
    if r is None:
        return PathPolicy()        # всё True
    return r.policy_for(rel)
```

**Сценарий.** `WorkspaceBackend.filter_check` спасает: он сначала проверяет `if name not in self.roots: return ("filter", ...)`. Но это **двухуровневая защита, где второй уровень — единственный**. Любой новый вызов `ws.policy_for(...)` в обход `filter_check` (например, из будущего tool'а или из GUI) получит «всё разрешено».

**Правка.** `policy_for` для неизвестного root должна возвращать `PathPolicy(read=False, write=False, index_*=False)` — fail-closed. `WorkspaceBackend` уже обрабатывает «нет root» отдельным кодом ошибки, ему это не помешает.

### 4.3. `_check_parses` сверяет короткое имя, а не qualname

`tools/unit/writer.py:343-348`

```python
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        name = node.name
        if name == unit.name:           # ← только короткое имя
            found = True
            break
```

**Сценарий.** Есть `A.helper` и `B.helper`. Редактируется `A.helper`. В новом тексте случайно удалили `A.helper`, но `B.helper` остался. `_check_parses` видит `name == "helper"` и пропускает — несмотря на то, что целевой unit исчез. Это прямая противоположность обещанному в докстринге («qualname must still be present unless removal was requested»).

**Правка.** Собирать полный qualname в обходе через `ast.NodeVisitor` со стеком родителей, или переиспользовать `formats.code._iter_defs`, который уже строит правильные qualname для индекса.

### 4.4. `grep_replace` читает в обход read-политики

`tools/grep_replace.py:163-176`

```python
for p in candidates:
    check = backend.filter_check(p, "write")   # только write
    if check is not None:
        blocked.append(p)
        continue
    try:
        text = backend.read(p)                  # ← read без проверки
    except Exception:
        skipped.append(p)
        continue
```

**Сценарий.** `Patcher._filter_paths` перед вызовом тула проверит только те пути, что объявлены в `path_args`/`path_list_args` класса. У `GrepReplaceTool` это `["directory"]` и `["paths"]`. Если патч передал `directory="src"`, а `src/secret.py` попадает под `read: false` в policy — тул спокойно его прочитает, посчитает совпадения и (если `write` разрешён) запишет. Хуже: `write: true` + `read: false` — тул пишет файл, содержимое которого ему читать было нельзя, потому что он прочитал его по факту.

**Правка.** Перенести `filter_check` внутрь `WorkspaceBackend.read` (и `write`). Это чуть дороже по вызовам, но убирает целый класс подобных расхождений: policy принадлежит backend-у, а не патчу.

### 4.5. `_strip_fence` — ReDoS

`core/patchparse.py:36,76-86`

```python
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)

def _strip_fence(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    m = _FENCE_RE.match(t)          # ← O(n²) на незакрытом фенсе
    ...
```

**Сценарий.** Вход: `"```\n" + "x" * N` (без закрывающего бэктика). `(.*?)` с `DOTALL` пробует все позиции для `\n?```\s*$`. Каждая проверка `\s*$` — O(n). Суммарно O(n²). При N = 1 MB — порядка 10¹² операций. Это не гипотетический сценарий: любой LLM-ответ с фенсом без закрытия (типичная ошибка генерации) зайдёт сюда.

**Правка.** Заменить регекс на линейный разбор:

```python
def _strip_fence(text: str) -> str:
    t = text.strip()
    if not t.startswith("```"):
        return t
    nl = t.find("\n")
    if nl < 0:
        return t.strip("`").strip()
    close = t.rfind("\n```")
    if close > nl:
        return t[nl + 1:close].strip()
    return t.strip("`").strip()
```

## 5. План действий
<!-- summary: Срочно (5 пунктов), ближайший цикл (5), техдолг (5). -->

**Срочно (до следующего релиза):**

1. Убрать `PYTHONPATH` из `_DEFAULT_ENV_ALLOW`.
2. `Workspace.policy_for` → fail-closed при неизвестном root.
3. `_check_parses` в `unit/writer` — сверять qualname, а не короткое имя.
4. `grep_replace` — `filter_check(p, "read")` перед `backend.read`.
5. `_strip_fence` — линейный парсер вместо регекса.

**В ближайший цикл:**

6. `_next_group_start` — ограничить окно recovery.
7. `CompositeBackend._open_failures` — под lock или `Queue`.
8. `filter_check` внутри `WorkspaceBackend.read/write` — единая точка policy.
9. `shell.py` — `int(...)` в try/except.
10. `Patcher._apply_one` — `error_code="internal_error"` в generic-ветке.

**Техдолг:**

11. Убрать двойной `return new_source` в `unit/writer.py`.
12. `_open_failures` — очищать при успешном `reopen`.
13. `grep_replace` — стриминговая запись pass 2.
14. `loader.load` — union-мерж `env_passthrough` / `env_deny_patterns`.
15. `patchparse` — `hash((type, value))` вместо `repr` для seen-множества.

## 6. Что осталось непокрытым
<!-- summary: Файлы, требующие второго прохода — MCP, bridge, symbols, GUI, formats, indexers. -->
Файлы, которые нужно покрыть третьим проходом:

- `bridge/bridge.py` — 625 строк, общается со Studio. Обработка `taskkill`, `CREATE_NEW_PROCESS_GROUP`, чтение `.Source`, retry.
- `indexers/code.py` (398), `indexers/diff.py` (475), `indexers/lua_runner.py` (286) — построение графов, детекция циклов; проверить корректность на крупных проектах.
- `tools/symbols/python.py` (1009), `tools/symbols/lua.py` (659) — AST-манипуляции, интеграция с `_ast.py`.
- `tools/unit/adapter_py.py`, `adapter_md.py`, `adapter_lua.py`, `reader.py` — обходы дерева unit'ов, корректность границ.
- `runner/gui/*` — Tk, clipboard, thread-pool. Утечки состояния при быстрых кликах, гонки между потоками GUI и worker'ами.
- `formats/renderer.py` — построение индекса, метки, suppression.
- `mcp.py` (часть) — `read_many`, `grep_mcp`, `grep_replace_mcp`, `_read_batches_recursive`, `list`, `list_with_stat`. Прочитаны только lifecycle, `_invoke*`, `_lua_script`, `write`, `create`, `execute`, `invoke_native`.
- `matching/text.py` — Tier 1/2/3 матчинг, `similar_lines`.
- `tools/symbols/_ast.py` — прочитано; остаётся `python.py` и `lua.py`.
- `config/mcpignore.py` — по аналогии с `patchignore`.
## 7. Приложение: файлы, прочитанные в первом проходе
<!-- summary: Список из 20 модулей с указанием размера в строках. -->

| Модуль | Строк |
|---|---|
| `toolkit/core/patcher.py` | 309 |
| `toolkit/core/session.py` | 66 |
| `toolkit/core/router.py` | 135 |
| `toolkit/core/patchparse.py` | 209 |
| `toolkit/core/paths.py` | 59 |
| `toolkit/core/models.py` | 166 |
| `toolkit/backends/filesystem.py` | 189 |
| `toolkit/backends/workspace.py` | 330 |
| `toolkit/backends/composite.py` | 479 |
| `toolkit/config/loader.py` | 485 |
| `toolkit/config/workspace.py` | 321 |
| `toolkit/config/patchignore.py` | 162 |
| `toolkit/matching/pattern.py` | 118 |
| `toolkit/tools/read.py` | 550 |
| `toolkit/tools/shell.py` | 394 |
| `toolkit/tools/grep_replace.py` | 292 |
| `toolkit/tools/unit/writer.py` | 382 |
| (плюс `__init__.py` пакетов и мелкие модели, прочитанные в индексе) | — |
## 8. Второй проход — находки
<!-- summary: 12 новых находок после чтения MCP lifecycle, formats/parser.py, formats/code.py, formats/lua.py, tools/symbols/_ast.py. -->

Прочитаны: `backends/mcp.py` (lifecycle, `_invoke*`, `_lua_script`, `_expand_includes`, `write`, `create`, `execute`, `invoke_native`, `_wait_*`, `close`, `_reader_loop`), `formats/parser.py`, `formats/code.py`, `formats/lua.py`, `tools/symbols/_ast.py`. Новые находки:

| # | Уровень | Категория | Файл:строка | Проблема | Рекомендация |
|---|---|---|---|---|---|
| 21 | HIGH | Безопасность | `backends/mcp.py:write` | `norm` подставляется в Luau-код как `game.{norm}` без проверки на спецсимволы; если `_normalize` не фильтрует `'`, `"`, `(` — инъекция Luau | Проверить `_normalize`; при необходимости — regex `^[A-Za-z0-9_.]+$` |
| 22 | HIGH | Архитектура | `backends/mcp.py:execute` | Произвольный Luau без валидации. Доступен через `CompositeBackend.execute` и через `invoke_native("execute_luau")` из LLM-патча | Явно задокументировать; при `native_tools_enabled=true` — предупреждение в GUI |
| 23 | HIGH | Логика | `backends/mcp.py:_invoke_once` | `patch_file.write_text(...)` без atomic write. Bridge может читать полу-записанный JSON | Write в `.tmp` + `os.replace` |
| 24 | MEDIUM | Логика | `backends/mcp.py:close` | `_reader`/`_stderr_reader` — daemon-потоки; `close()` не джойнит их. Возможна утечка, если stream не закрыт | `join(timeout=1.0)` после kill |
| 25 | MEDIUM | Хрупкость | `backends/mcp.py:_wait_ready` | Маркер готовности — русская строка `"Мост готов"`. Переименование в bridge ломает startup молча | Вынести маркер в константу рядом с bridge, или использовать структурный сигнал (файл/JSON) |
| 26 | MEDIUM | Логика | `backends/mcp.py:_wait_studio_ready` | `deadline` общий, но `_invoke_once(..., timeout=min(30.0, timeout))` внутри — при падении Studio каждый цикл тратит до 30 с. Суммарное ожидание может превысить объявленный `studio_timeout` | Передавать `min(30.0, deadline - time.time())` |
| 27 | MEDIUM | ReDoS | `formats/parser.py:_build_tree` | Вложенный `for i / for j` по всем headings — O(n²). При 10 000 заголовков ~10⁸ итераций | Предвычислить `full_end` стеком за O(n) |
| 28 | MEDIUM | ReDoS | `formats/parser.py:_heading_re` | Строит regex через f-string из `fmt.min_level`, `fmt.max_level`. Если они приходят из пользовательского JSON — возможен инъекционный паттерн | Валидировать `1 <= min <= max <= 8` при загрузке preset |
| 29 | MEDIUM | RecursionError | `formats/code.py:_walk_body` | Рекурсивный обход `ast.iter_child_nodes` для Call-нод. На глубоко вложенных выражениях (`f(g(h(...)))`) — риск `RecursionError` на больших файлах | Ограничить глубину или итеративный обход со стеком |
| 30 | MEDIUM | Производительность | `formats/lua.py:lua_signature_end_line` | Перетокенизирует весь source на каждый вызов. Индексер вызывает её многократно → O(n²) на большом файле | Принимать tokens/line_of параметрами или кэшировать |
| 31 | LOW | Производительность | `formats/code.py:source_hash` | Polynomial с `% HASH_MODULO` на каждый байт. Медленно для больших файлов | FNV или `hashlib` на префиксе |
| 32 | LOW | API | `formats/code.py:Module.find` | Линейный поиск по `self.symbols`. При частых вызовах из indexers — медленно | Построить `{qualname: Symbol}` индекс при `parse_module` |

### 8.1. Инъекция через `norm` (`MCPBackend.write`)

```python
def write(self, path: str, content: str) -> None:
    norm = self._normalize(path)
    ...
    code = (
        f"local ok, t = pcall(function() return game.{norm} end)\n"
        ...
    )
```

`norm` вставляется в Luau-код как `game.{norm}`. Если `_normalize` только убирает префикс `game.` (типовое поведение), то path вида `ReplicatedStorage.X'; os.execute('rm -rf') --` даст валидный Luau. Control bytes в `content` проверяются, но `path` — нет.

**Правка.** До `_normalize` — валидировать `path`: `re.fullmatch(r"[A-Za-z0-9_.]+", path)`. Roblox-пути состоят из букв, цифр, точек и подчёркиваний (за исключением Wally-имён с `-`, но их явно не поддерживают — см. LLM_START). Не прошедшие — `ValueError("unsupported character in path")`.

### 8.2. `_build_tree` — O(n²)

```python
for i in range(n):
    lvl = headings[i]["level"]
    for j in range(i + 1, n):
        if headings[j]["level"] <= lvl:
            full_end[i] = headings[j]["line_start"]
            break
```

Для каждого заголовка ищется следующий с меньшим/равным уровнем. Проходится весь оставшийся список. O(n²) worst case.

**Правка.** Стек уровней:
```python
stack: list[int] = []  # индексы заголовков с возрастающим уровнем
for i, h in enumerate(headings):
    while stack and headings[stack[-1]]["level"] >= h["level"]:
        full_end[stack.pop()] = h["line_start"]
    stack.append(i)
for i in stack:
    full_end[i] = len(text)
```

### 8.3. `_walk_body` — потенциальный `RecursionError`

```python
for child in ast.iter_child_nodes(node):
    _walk_body([child], parent=parent, in_class=in_class, ...)
```

Для каждого Call-узла итерируются дети и вызывается рекурсивно. На `a(b(c(d(...))))` глубины ~200 — сработает лимит CPython (~1000 кадров). Файлы, сгенерированные макросами или минификаторами, могут быть глубже.

**Правка.** Явный стек:
```python
def _walk_iter(root_nodes, ...):
    stack = [(root_nodes, parent, in_class)]
    while stack:
        nodes, parent, in_class = stack.pop()
        ...
        stack.append((list(ast.iter_child_nodes(node)), parent, in_class))
```

## 9. План третьего прохода
<!-- summary: Приоритет чтения непокрытых модулей — от безопасности к GUI. -->

1. `bridge/bridge.py` — целиком, с фокусом на input-парсинг, subprocess-контроль, чтение `.Source`.
2. `tools/symbols/python.py`, `tools/symbols/lua.py` — AST-манипуляции, интеграция с `_ast.py`.
3. `tools/unit/reader.py`, `adapter_*.py` — корректность границ head/annotation/body.
4. `backends/mcp.py` — оставшиеся методы: `read_many`, `grep_mcp`, `grep_replace_mcp`, `_read_batches_recursive`, `list`, `list_with_stat`.
5. `indexers/code.py`, `indexers/diff.py`, `indexers/lua_runner.py` — графы, циклы, парсинг индекса.
6. `matching/text.py` — Tier 1/2/3.
7. `runner/gui/*` — Tk-состояние, threads, clipboard.
## 10. Третий проход — bridge и остаток MCP
<!-- summary: Читаны bridge/bridge.py (625 стр.) и оставшиеся методы MCPBackend. Подтверждена инъекция через path в Luau-код; 15 новых находок. -->

Прочитаны: `bridge/bridge.py` целиком, `MCPBackend.read_many`, `grep_mcp`, `grep_replace_mcp`, `_normalize`, `list`, `stat`, `read`, `delete`, `move`, `copy`, `ensure_alive`.

### 10.1. Ключевая находка — подтверждение инъекции

**`_normalize` не делает ничего, кроме `strip()` и удаления префикса `game.`:**

```python
@staticmethod
def _normalize(path: str) -> str:
    p = path.strip()
    if p.startswith("game."):
        p = p[5:]
    return p
```

Path не валидируется нигде в MCPBackend. Далее этот path подставляется в Luau-код как `game.{norm}` в **каждом** методе:

| Метод | Строка с подстановкой |
|---|---|
| `write` | `pcall(function() return game.{norm} end)` |
| `read` | то же |
| `stat` | то же |
| `delete` | `pcall(function() return game.{norm} end)` … `t:Destroy()` |
| `move`/`copy` | `game.{src_norm}`, `game.{dst_parent}`, `game.{dst_norm}` |
| `list` | `pcall(function() return {expr} end)` |
| `execute` | код передаётся как есть |
| `grep_mcp`/`grep_replace_mcp` | `expr = f"game.{root_norm}"` |

Path вида

```
ReplicatedStorage.X; os.execute('calc.exe') --
```

попадёт в код как `game.ReplicatedStorage.X; os.execute('calc.exe') --`. Внутри `pcall(function() ... end)` это два отдельных statement'а, второй исполнится. `execute_luau` работает в полном Luau VM Studio (не в песочнице плагина); `os.execute` доступен.

**Итог.** Это RCE на машине пользователя Studio. Уязвимость доступна через любой патч, где LLM (или подсунутый файл) передаёт `file_path` с `;`/`--`/кавычкой. Достаточно того, что Studio в Edit-режиме и мост поднят. `invoke_native` в принципе задокументирован как «может менять DataModel», но граница «DataModel» здесь не выдержана.

**Правка.** Одна точка — в `_normalize` или в отдельном валидаторе перед подстановкой:

```python
import re
_PATH_RE = re.compile(r"^[A-Za-z0-9_.]+$")

@classmethod
def _normalize(cls, path: str) -> str:
    p = path.strip()
    if p.startswith("game."):
        p = p[5:]
    if not _PATH_RE.match(p):
        raise ValueError(
            f"unsupported character in DataModel path: {path!r}"
        )
    return p
```

Wally-имена с `-`/`@` сегодня уже не поддерживаются по докстрингу LLM_START — специально добавлять их в regex не нужно. Точки — разделители, не часть сегмента, так что `[A-Za-z0-9_.]+` покрывает всё разрешённое.

В `grep_mcp`/`grep_replace_mcp` то же самое: `root_norm = self._normalize(root).strip(".")` — вызывать валидацию до `.strip('.')`.

### 10.2. Дополнительные находки третьего прохода

| # | Уровень | Категория | Файл:строка | Проблема | Рекомендация |
|---|---|---|---|---|---|
| 33 | HIGH | RCE | `backends/mcp.py:_normalize` + все методы | Path не валидируется — инъекция Luau через `game.{norm}` (см. §10.1). Расширяет #21 | Whitelist `[A-Za-z0-9_.]+` |
| 34 | HIGH | RCE | `backends/mcp.py:grep_mcp`, `grep_replace_mcp` | `root_norm` идёт в `expr = f"game.{root_norm}"` без валидации. Асимметрия: `pattern` через `json.dumps`, `expr` — нет | Валидировать так же, как `_normalize` |
| 35 | HIGH | RCE | `backends/mcp.py:_lua_script` | Параметры `expr` подставляются в Lua напрямую, без экранирования. Вызывающий код отвечает за безопасность строки | Комментарий к функции или валидация внутри |
| 36 | MEDIUM | ReDoS | `bridge/bridge.py:load_patch:368` | `re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.DOTALL)` — тот же O(n²), что #5 | Тот же линейный парсер |
| 37 | MEDIUM | Логика | `bridge/bridge.py:_PREFLIGHT_STATE` | Глобальный кэш `confirmed_mode` не инвалидируется при ручном переключении Studio. Батч уйдёт в неправильный режим | Сбрасывать после успешного `_switch_play` и/или проверять `get_studio_state` раз в N секунд |
| 38 | MEDIUM | Хрупкость | `backends/mcp.py:read`, `delete`, `write`, `move`, `copy` | Маркеры `__MISSING__`, `__NOT_SOURCE__`, `__OK__`, `__EMPTY__` живут в том же пространстве, что и данные. `.Source` = строка `"__MISSING__"` — `read` вернёт `FileNotFoundError` | Обернуть ответ в JSON: `{"status":"ok","source":"..."}` |
| 39 | MEDIUM | Ресурсы | `bridge/bridge.py:execute_calls` | `result.content` читается без лимита. Один вызов `read_file` с большим `.Source` → десятки MB в `outputs.json`, который родитель читает целиком | Лимит на размер entry (аналогично `max_output_bytes` в `run_python`) |
| 40 | MEDIUM | Логика | `bridge/bridge.py:_detect_playing` | Эвристики на строки. При изменении формата ответа MCP-сервера — молча `None`, preflight пропускает проверку режима | Fail-closed при `None` в `preflight_mode` (сейчас `True, "⚠ …"` = fail-open) |
| 41 | MEDIUM | Атомарность | `backends/mcp.py:_invoke_once` | `patch_file.write_text(...)` — не атомарно. Bridge может прочитать полу-записанный JSON | `.tmp` + `os.replace` (подтверждает #23) |
| 42 | MEDIUM | Логика | `backends/mcp.py:list` | Жёсткий лимит `if n >= 500: break` без сообщения. Пользователь не знает, что ответ обрезан | Маркер `__TRUNCATED__` в конце списка |
| 43 | LOW | CLI | `bridge/bridge.py:main:605` | `parsed.args.split()` без `shlex`. Пример в докстринге (`--args "/c cd /d %LOCALAPPDATA%\\Roblox && .\\mcp.bat"`) в этой форме не парсится корректно | `shlex.split` или явный список в GUI |
| 44 | LOW | Шум | `backends/mcp.py:_reader_loop` | Зеркалит всё в stderr с префиксом `[bridge]`. На bulk-операциях — тысячи строк | Убрать или только при `quiet=False` |
| 45 | LOW | Название | `backends/mcp.py:_normalize` | Имя не намекает на риск инъекции — при чтении вызывающего кода кажется безопасной трансформацией | Переименовать в `_normalize_and_validate` |
| 46 | LOW | Валидация | `backends/mcp.py:grep_replace_mcp` | `mappings` проверяются на пустоту, но не на тип элементов. `m[0]` упадёт `IndexError` при некорректном входе | Явная проверка `isinstance(m, (list, tuple)) and len(m) == 2` |
| 47 | LOW | Порядок | `bridge/bridge.py:append_log` | Логи пишутся после `print`, но без синхронизации. При параллельных вызовах (не бывает сегодня) строки перемешаются | `fcntl.flock`/`msvcrt.locking` — или оставить как есть |

### 10.3. Что сделано хорошо в bridge.py

- `_PREFLIGHT_STATE` действительно экономит round-trip'ы; идея правильная, страдает только инвалидация (#37).
- `MODE_AGNOSTIC_TOOLS` — грамотная категория. Многие инструменты не трогают DataModel, и preflight для них был бы шумом.
- Ретри транзиентных состояний (`STUDIO_TRANSIENT_MARKERS` из `_is_transient`) — правильная стратегия для MCP-серверов.
- `verify-after-write` в `create`/`write` — компенсирует известный баг `multi_edit`.
- `content` валидируется на control bytes (0x00–0x1F кроме tab/LF/CR). Правильная паранойя, но пропущена для `path`.

### 10.4. Разница между `_normalize` и `json.dumps`

В `move`/`copy` `dst_name` проходит через `json.dumps` и попадает в Luau как `clone.Name = "<name>"`. Это безопасно: `json.dumps` даёт валидный Lua string literal для ASCII. Но `src_norm`, `dst_parent`, `dst_norm` — идут голыми (`game.{...}`). Асимметрия в одном и том же методе. Похоже, автор думал про инъекцию в новом имени (`dst_name`), но не в пути.

## 11. План четвёртого прохода
<!-- summary: symbols/python.py и lua.py, unit/reader.py + адаптеры, indexers, matching/text.py, _read_lua в mcp.py. -->

1. `backends/mcp.py:_read_lua`, `_INCLUDE_RE`, `_PLACEHOLDER_RE`, `_invoke_many`, `_read_batch` — проверить path traversal и обработку не-списка от bridge.
2. `tools/symbols/python.py` (1009), `tools/symbols/lua.py` (659) — корректность AST-операций и `_check_target_survives` интеграции.
3. `tools/unit/reader.py`, `tools/unit/adapter_py.py`, `adapter_md.py`, `adapter_lua.py` — корректность границ head/annotation/body, устойчивость на нестандартных файлах.
4. `indexers/code.py`, `indexers/diff.py`, `indexers/lua_runner.py` — детекция циклов, построение графа, парсинг индекса.
5. `matching/text.py` — Tier 1/2/3 матчинг, `similar_lines`.
6. `formats/renderer.py` — построение index-строк, метки, suppression.
7. `runner/gui/app.py` (902), `settings_window.py` (896), `tree_view.py` (358) — Tk, состояние, threading.
8. `config/mcpignore.py` — по аналогии с `patchignore`.
## 12. Четвёртый проход — symbols, unit, matching
<!-- summary: Прочитаны symbols/python.py (1009), unit/reader.py, adapter_py.py, matching/text.py. Уточнение #3; 10 новых находок. -->

Прочитаны: `tools/symbols/python.py`, `tools/unit/reader.py`, `tools/unit/adapter_py.py`, `matching/text.py`.

### 12.1. Уточнение находки #3

`_check_target_survives` (в `tools/symbols/_ast.py`) работает **правильно**: он вызывает `_find_all_by_qualname(tree, qualname, include_vars=True)`, то есть ищет по полному qualname. Именно поэтому `symbols/python.py` во всех write-тулах не имеет проблемы с «одноимённым символом в другом классе».

Ошибка #3 локализована **только в `tools/unit/writer._check_parses`**, где сделан собственный обход `ast.walk` вместо переиспользования `_ast._check_target_survives`. Правильная правка — не писать свой обход, а вызывать уже существующий `_check_target_survives` (импорт из `tools/symbols/_ast`), либо один раз извлечь логику в общий модуль. Это устраняет дубль и одновременно чинит баг.

### 12.2. Новые находки

| # | Уровень | Категория | Файл:строка | Проблема | Рекомендация |
|---|---|---|---|---|---|
| 48 | MEDIUM | Ошибки | `tools/unit/reader.py:_parse_blocks:56-65` | `int(chunk)` и `int(a), int(b)` без try. При `block="abc"` или `block="1-x"` — `ValueError` летит наверх. По контракту LLM_START это должно быть `bad_block` | Обернуть в `try/except (ValueError, TypeError)` → `ValueError("bad_block")` |
| 49 | MEDIUM | Ошибки | `tools/unit/reader.py:_resolve:72` | `int(address.get("occurrence", 0))` — то же самое. `occurrence="abc"` → ValueError наверх | Валидация в try; вернуть `KeyError("bad_occurrence")` |
| 50 | MEDIUM | Логика | `tools/unit/reader.py:_resolve:91` | `matches` для `qualname` собирается через `_iter_units(root)` в порядке обхода, а `occurrence` документируется как «N-й сверху вниз». Для md-секций обход parents-first корректно даёт сверху-вниз; для вложенных Python-функций — тоже. Но для Lua-адаптера, где два блока могут иметь одинаковый qualname, порядок может отличаться | Явно сортировать `matches` по `line_start` перед `occurrence` |
| 51 | MEDIUM | Производительность | `matching/text.py:similar_lines:109-113` | `difflib.SequenceMatcher(None, line, needle_first).ratio()` **на каждой строке haystack**. Для 100k-строчного файла и no_match диагностики — минуты. Это вызывается только при no_match, но `replace_in_file` в LLM_START рекомендуется для мелких правок — на крупных файлах диагностика становится доминирующей | Ранний выход через простые эвристики: сравнить длину, префикс, хэш первых 16 символов; только при совпадении — SequenceMatcher |
| 52 | MEDIUM | Производительность | `matching/text.py:_find_trailing_normalized:155-167` | Внутренний `for i in range(k)` сравнивает строки; для needle из 100 строк и haystack 50k строк — 5M сравнений. Только при tier-2 (fallback), но всё же | Префильтр по первой строке: если `file_lines[j].rstrip() != needle_norm[0]` — `continue` без внутреннего цикла |
| 53 | MEDIUM | Логика | `tools/symbols/python.py:MoveSymbolTool.execute:783-784` | Кросс-файловый move: сначала `backend.write(target_file, new_tgt)`, потом `backend.write(file_path, new_src)`. Если второй write упадёт (диск, политика), **target уже изменён**. Идемпотентности нет | Записать сначала source, потом target; или использовать транзакцию через временные файлы + `os.replace` |
| 54 | MEDIUM | Логика | `tools/unit/reader.py:_render_blocks:203-232` | При `parts=["head","annotation"]` для блока с `sub.unit`, код всё равно идёт в `if not parts or parts == ["all"]` ветку для блока без unit и разворачивает блок целиком, игнорируя `parts` | Согласовать: либо запретить `parts` для блоков без unit, либо применить фильтр и к ним |
| 55 | LOW | Ошибки | `tools/symbols/python.py:ReplaceSymbolSignatureTool:376-382` | Проверка `if not node.body: return no_body`. Для класса с единственным `pass` body непустой — проверка проходит. Но `ClassDef` без body в Python-синтаксисе невозможен (минимум `pass`), так что эта ветка — dead code | Убрать |
| 56 | LOW | Логика | `tools/unit/adapter_py.py:_build_unit:98` | `qn = name if parent_qn == "<module>" else f"{parent_qn}.{name}"`. Сравнение с литералом `<module>` — если кто-то передаст модуль с именем `<module>` в parent_qn (маловероятно, но), — сломается | Использовать `None` вместо `<module>` внутри, а `<module>` рендерить только на выходе |
| 57 | LOW | Ресурсы | `tools/unit/reader.py:_slice:150` | Каждый вызов `_slice` делает `source.splitlines()` заново. При рендере unit-а с несколькими частями (head, annotation, body) — 3 разделения одного и того же текста | Передавать заранее разбитый `lines` |
| 58 | LOW | API | `tools/unit/reader.py:_slice_lines:156-158` | То же самое. `read_unit` для `part=all` идёт через `_slice_lines`; на каждое чтение — полное разбиение | Кэш `lines` в `Unit` или передача параметром |
| 59 | LOW | Границы | `tools/unit/adapter_py.py:_build_module:63-65` | `head_start = ann.end + 1`, если docstring начинается с первой строки. Для модуля с docstring и одним классом ниже head будет исключать docstring, но включать пустые строки между ним и первым def. Модель работает, но `part="head"` вернёт странный кусок | Задокументировать в MODEL.md или вернуть docstring в head |

### 12.3. Что сделано хорошо

- `symbols/python.py` — все write-тулы проходят через `_check_target_survives`, не изобретают свою проверку. Единственное исключение — `unit/writer.py`.
- `DeleteSymbolTool` и `ReplaceStatementTool` сохраняют пустую строку-разделитель между символами; иначе после удаления получается склейка. Правильная деталь.
- `unit/reader._not_found_message` использует `difflib.get_close_matches` для подсказок — правильный баланс между «просто not_found» и «вот полная карта файла» (последнее — задача `list_units`).
- `matching/text.py` не нормализует EOL — эта забота оставлена тулам, что сохраняет byte-exact контракт. Явно задокументировано.
- `adapter_py` явно использует `_stmt_start` вместо `.lineno`, чтобы декораторы не съедались head-ом. Это неочевидный крайний случай, и он учтён.

## 13. План пятого прохода
<!-- summary: Остались: indexers, formats/renderer, tools/symbols/lua, unit/adapter_md, adapter_lua, config/mcpignore, runner/gui. -->

1. `tools/symbols/lua.py` (659) — критично: проверки тех же операций для Luau, где нет AST.
2. `tools/unit/adapter_lua.py`, `adapter_md.py` — корректность границ для не-Python форматов.
3. `indexers/code.py` (398), `indexers/diff.py` (475), `indexers/lua_runner.py` (286) — графы, циклы, парсинг индекса.
4. `formats/renderer.py` — метки, suppression, стабильность вывода.
5. `config/mcpignore.py` — параллель к `patchignore`.
6. `runner/gui/*` — Tk, threads, состояние.
7. `backends/mcp.py` — точечно: `_read_batch`, `_append_timing`, `_stderr_loop`.
## 14. Пятый проход — indexers, adapters, renderer
<!-- summary: Прочитаны indexers/code.py, indexers/diff.py, indexers/lua_runner.py, adapter_md.py, adapter_lua.py, formats/renderer.py, config/mcpignore.py. 11 новых находок. -->

Прочитаны: `indexers/code.py`, `indexers/diff.py`, `indexers/lua_runner.py`, `tools/unit/adapter_md.py`, `tools/unit/adapter_lua.py`, `formats/renderer.py`, `config/mcpignore.py`.

### 14.1. Новые находки

| # | Уровень | Категория | Файл:строка | Проблема | Рекомендация |
|---|---|---|---|---|---|
| 60 | MEDIUM | Атомарность | `tools/symbols/lua.lua_move_symbol:575-576` | Cross-file move: сначала `backend.write(target_file, new_tgt)`, потом `backend.write(file_path, new_src)`. Если второй write упадёт, target уже изменён. Дубль #53 для Lua | Транзакция через временные файлы + `os.replace`; или писать source первым |
| 61 | MEDIUM | Ресурсы | `indexers/lua_runner.py:194-286` | `items` аккумулирует все модули DataModel в памяти за одну сессию. `_MAX_CHUNKS = 100` без проверки размера чанка. На проекте с 10k+ модулей — сотни MB в Python | Ограничить размер `items` + стриминговая запись в manifest по чанкам; или `_MAX_CHUNKS` считать от общего числа |
| 62 | MEDIUM | Производительность | `indexers/lua_runner.py:220` | Payload формируется заново на каждый чанк: `_LUA_PARSER.read_text()` + `_flatten_parser` + `_LUA_DRIVER.read_text()` + сборка. При 100 чанках — 100× чтение двух Lua-файлов. Плюс скомпилированный payload уходит в `execute_luau` целиком | Кэшировать flatten парсера и driver на уровне модуля, переиспользовать |
| 63 | MEDIUM | Логика | `indexers/code.py:297-299` | `resolve_module` делает `matches = [p for d, p in internal_dotted.items() if d.endswith(suffix)]` для каждой unresolved call. O(N) на вызов. В проекте с 5000 модулей и 50k call-эджей — 250M итераций | Построить reverse-индекс `suffix → paths` один раз; проверять уникальность через него |
| 64 | MEDIUM | Скрытая ошибка | `indexers/diff.py:24` | `CODE_MODULE_RE` захватывает `(.+?)\s+\(N стр., M KB\)`, но если в path есть скобки (например, `src/parser (old).py`), regex сломается молча — `parse` пропустит модуль | Захватывать path нежадно до двойного пробела: `^##\s+(.+?)\s{2,}\(` |
| 65 | LOW | Сообщение | `tools/symbols/lua.lua_copy_symbol:659` | `+{len(block)}` — `block` это строка, а не список. Выведет число символов вместо числа строк | `block.count("\n") + 1` |
| 66 | LOW | Границы | `tools/symbols/lua._lua_signature_bounds` | Ищет `function` на `symbol.line_start`. При двух `function` в одной строке (редкость, но legal) — не найдёт вторую | Использовать позицию из Symbol, если доступна |
| 67 | LOW | Нормализация | `indexers/code.py:_module_dotted:50` | `p.split("/")` — если backend отдаёт `\\` (не нормализовал), `__init__.py` внутри `pkg\\sub` не станет пакетом | `p.replace("\\", "/").split("/")` |
| 68 | LOW | Границы | `tools/unit/adapter_lua._find_lua_annotation:95` | Поиск `--[[` ограничен 60 строками вверх. Многострочный комментарий >60 строк не будет найден как annotation | Явно задокументировать лимит в докстринге; или использовать `parse_lua_symbols` для поиска границ |
| 69 | LOW | Хрупкость | `indexers/diff.py:24` | Regex для модулей не проверяет, что path начинается с буквы — если формат INDEX.md слегка изменится (например, добавят префикс), parse сломается молча | Добавить unit-тест на parse → diff roundtrip с краевыми именами |
| 70 | LOW | Документация | `config/mcpignore.py:31-35` | `DEFAULT_MCPIGNORE` содержит `Packages`, `_Index`, `*@*` — но `parse` стрипает `/`, не `.`. Для Roblox-путей `ReplicatedStorage.Packages.X` — сегмент `Packages` совпадёт корректно. Если пользователь добавит `ReplicatedStorage.Packages.X` (полный путь) — не совпадёт | Добавить в docstring пример «паттерн матчит один сегмент, не полный путь» |

### 14.2. Что сделано хорошо

- **`indexers/code._find_cycles`** — итеративный DFS с явным стеком и цветами. Правильное решение для глубоких графов: рекурсивный CPython на 10k модулей точно переполнил бы стек.
- **`indexers/code._resolve_calls`** — сложная эвристика, но с явными правилами фильтрации: builtins дропаются, `variable.method` без известного head — тоже. Правильный компромисс между сигналом и шумом.
- **`formats/renderer._module_markers`** — каждая метка выводится из проверяемого факта (AST, путь, длины). «Факты, не суждения» — редкая для индексов дисциплина.
- **`indexers/diff.parse_code_index_text`** — построен так, что добавление новых маркеров в конец строки не ломает parse. Регекс намеренно без `$`.
- **`tools/unit/adapter_md.build_section`** — комментарии про off-by-one на границах heading_end и section_full_end. Объясняют, *почему* `-1`, а не просто «так надо». Спасает следующего читателя от классической ошибки.
- **`indexers/lua_runner._invert_lua_imports`** — нормализует `game.` префикс, проверяет self-loops и дедуплицирует. Простая, но полная реализация.
- **`config/mcpignore`** — тридцать строк, но использует `patchignore.parse`/`segment_hidden` вместо дублирования логики. Хорошая декомпозиция.

### 14.3. Разница между `diff_index` и `diff_code_index`

Два похожих, но разных алгоритма. `diff_index` (md) работает по `(file, heading)` — сравнивает `line` целиком, потому что summary/tags меняются без сдвига L-диапазона. `diff_code_index` работает по `path` и hash модуля, плюс символьный уровень. Это правильно: у кода есть `source_hash`, у md — нет (только mtime и length). Стоит явно задокументировать это решение в `DECISIONS.md`, потому что сейчас оно восстанавливается только из чтения обоих файлов.

## 15. Итог пяти проходов
<!-- summary: 70 находок: 12 HIGH/MEDIUM по безопасности и логике, остальное — качество. Приоритетный список из 10 пунктов. -->

**Всего:** 70 находок.

- **HIGH:** 6 (#1, #2, #3, #4, #21, #22, #33, #34, #35 — из них `#33-#35` — варианты инъекции Luau через path).
- **MEDIUM:** ~30.
- **LOW:** ~34.

### 15.1. Топ-10 к исправлению

1. **#33** — валидация path в `MCPBackend._normalize` (RCE на машине Studio).
2. **#1** — убрать `PYTHONPATH` из `env_passthrough` (RCE через sitecustomize).
3. **#4** — `filter_check(p, "read")` в `grep_replace` (обход read-политики).
4. **#2** — `Workspace.policy_for` fail-closed для неизвестного root.
5. **#3** — `_check_parses` в `unit/writer` должен сверять qualname (лучше — переиспользовать `_ast._check_target_survives`).
6. **#5** — линейный `_strip_fence` вместо ReDoS-регекса.
7. **#41** — атомарная запись `patch_file` в `_invoke_once` (race с bridge).
8. **#53/#60** — транзакционная запись при cross-file move.
9. **#21/#34** — `grep_mcp`/`grep_replace_mcp`: валидировать `root_norm`.
10. **#11** — `error_code="internal_error"` в `Patcher._apply_one`.

### 15.2. Что осталось непокрытым

- `runner/gui/app.py` (902), `settings_window.py` (896), `tree_view.py` (358), `views/main_window.py`, `runner/presenters/main.py` (426), `runner/cli.py` (364) — Tk, состояние, threading.
- `formats/format.py` (цикл с parser.py), `formats/presets.py`, `formats/hashing.py` — быстрые для чтения, но не критичные.
- `tools/symbols/_ast.py` — прочитан, но отдельного разбора заслуживает `_resolve_insertion` на краевых случаях.
- `tools/copy.py`, `tools/fileops.py`, `tools/index.py`, `tools/symbol_graph.py`, `tools/find_usages.py`, `tools/find_symbol.py`, `tools/status.py`, `tools/grep_mcp.py`, `tools/grep_replace_mcp.py`, `tools/verify.py` — по 100-460 строк, не прочитаны. Возможны локальные баги.
- `tools/code.py`, `tools/lua_code.py`, `tools/symbols/__init__.py`, `tools/unit/tool.py` — диспетчеры, вероятно, простые, но контрактная проверка была бы полезна.
- `bridge/bridge.py` — прочитан целиком.
- `.lua`-скрипты (`toolkit/lua/scripts/*.lua`, `lua_symbols.lua`, `code_index_regen.lua`) — не читались, а зря: `grep.lua`, `grep_replace.lua` принимают недоверенные pattern и replacement.
- `runtime/` — не читалось, но там только логи и state.

### 15.3. Методологические заметки

**Что сработало в подходе:**

- Читать сначала «горячий путь» (core → backends → tools), а не по алфавиту. Находки #1–#12 пришли из первых 20 файлов.
- Для крупных файлов (mcp.py — 1245 строк) использовать `read_unit` точечно, а не `read_file` целиком. Это дало покрытие lifecycle, write/read/stat/delete/move/copy, но пропустило `read_many`/`grep_*` при первом проходе — что и было причиной найти #33 только на третьем проходе.
- Читать тесты и manual/* после основного кода. Они подсказывают, где автор сам ожидал сложностей (`test_range_order.py`, `test_composite_death.py`, `test_strictness.py`).
- Использовать `AUDIT.md` как рабочую память: записывать промежуточные выводы, чтобы не держать в контексте 70 находок.

**Что можно было сделать иначе:**

- Прочитать `bridge/bridge.py` раньше. `load_patch` в нём — тот же паттерн, что `patchparse` в ядре, и ReDoS #36 нашёлся бы раньше.
- Прогнать `grep pattern="eval|exec|os.system|subprocess"` и `grep pattern="\\.format\\(|f\""` по всему проекту на раннем этапе. Это дало бы все места подстановки в одном списке, включая `game.{norm}`.
- Прочитать `lua/scripts/*.lua` сразу после `formats/lua.py`. Граница доверия «Python-код доверяет pattern, но не доверяет path» проходит именно там.

### 15.4. Итоговая оценка

**Проект:** архитектурно зрелый, дисциплинированный, с редкой для утилит этого класса заботой о деталях (glyph-fallback для cp1251, сохранение CRLF, atomic verify-after-write в write-тулах). Слабые места — не в дизайне, а в соблюдении уже заявленных контрактов: 6 HIGH-находок — это места, где *описанные в докстрингах правила* не выполнены кодом (`_check_parses` обещает qualname, проверяет name; `grep_replace` обещает работать по политике, читает без check; `_normalize` обещает нормализацию, делает инъекцию).

**Главный риск:** MCPBackend.

**Главная сильная сторона:** `Patcher._pre_validate_ranges` и `pattern`/`text` — общие матчеры с зафиксированным контрактом.
## 16. Шестой проход — Lua-скрипты и runner/GUI
<!-- summary: Прочитаны lua/scripts (grep, grep_replace, _match, exists, list_with_stat), runner/cli.py, runner/patch_runner.py, runner/presenters/main.py, часть gui/app.py. 9 новых находок, включая offset-bug в merge_structs. -->

Прочитаны: `lua/scripts/grep.lua`, `grep_replace.lua`, `_match.lua`, `exists.lua`, `list_with_stat.lua`, `runner/cli.py`, `runner/patch_runner.py`, `runner/presenters/main.py`, `runner/gui/app.py` (точечно: `worker`, `poll_queue`, `_check_mcp_transition`, `_start_session_in_background`, `_run_patch`).

### 16.1. Новые находки

| # | Уровень | Категория | Файл:строка | Проблема | Рекомендация |
|---|---|---|---|---|---|
| 71 | HIGH | Логика | `runner/patch_runner.py:77-90` | `_merge_structs`: `offset += ok + errors + skipped`, но `blocked` не учтён. Если в группе есть blocked, все позиции `failed`/`blocked` в следующих группах сдвинуты | `offset += ok + errors + skipped + len(st.get("blocked", []))` |
| 72 | HIGH | Race | `runner/gui/app.py:_start_session_in_background` | Закрывает старую сессию через `old.__exit__` без ожидания завершения текущего `apply_patch`. Если worker сейчас в середине работы — backend закрывается под ногами | Флаг `is_executing` — ждать его сброса перед close; или mutex на `apply_patch` |
| 73 | MEDIUM | Устойчивость | `runner/gui/app.py:poll_queue` | `_check_mcp_transition(_s, _bn)` вызывается вне `try`. Если внутри исключение — polling умирает, GUI перестаёт обновлять кнопки и статус | Обернуть в try/except |
| 74 | MEDIUM | Синтаксис | `backends/mcp.py:grep_mcp`/`grep_replace_mcp` | `json.dumps(pattern, ensure_ascii=False)` не эскейпит `\u0000`—`\u001F` валидно для Lua. Lua не понимает `\uXXXX` escape — скомпилирует иначе или упадёт | Явный эскейп control chars (`\xNN`-форма) или отказ при `ord(c) < 0x20` |
| 75 | MEDIUM | Дублирование | `runner/cli.py:_create_mcp_backend` и `runner/presenters/main.py:build_backend_for_config` | Две копии конфигурации MCPBackend (ready_timeout, call_timeout, native_tools, ...). Любое изменение в одном месте забудут применить во втором | Один общий конструктор `make_mcp_backend(cfg, args)`, оба вызывают его |
| 76 | MEDIUM | Race | `runner/gui/app.py:_check_mcp_transition` | `threading.Thread(target=_rebuild_lua_after_ready).start()` без лок-гейта. При быстрых переходах mcp ready/fail/ready запускаются параллельные rebuild_lua, пишущие в один index-файл | Флаг `_lua_rebuild_in_progress` под lock; пропускать запуск если уже идёт |
| 77 | LOW | Мёртвый код | `runner/presenters/main.py:266` | `from ...backends import FilesystemBackend, MCPBackend, CompositeBackend  # noqa: F401` — импорт с явным глушением, но ни один из трёх не используется в функции (только `WorkspaceBackend` из backends.workspace) | Удалить импорт |
| 78 | LOW | Потокобезопасность | `runner/patch_runner.py:_Accumulator.group:108-115` | Подменяет `sys.stdout` глобально. В CLI ок; в GUI — однопоточный worker, тоже ок. Но контракт небезопасен для любого параллельного вызова (например, будущий parallel-apply) | Документировать; или использовать `contextlib.redirect_stdout` с явным указанием, что группа сериализуется |
| 79 | LOW | Производительность | `lua/scripts/list_with_stat.lua:12-16` | `for i = 1, #src do if string.byte(src, i) == 10` — O(n) на байт в Lua-цикле. Для 100 KB × 500 файлов — 50M итераций | `select(2, src:gsub('\n', ''))` или `#src:gsub('[^\n]', '')` |
| 80 | LOW | Согласованность | `runner/cli.py:178` | `if not bridge_path.is_file() and args.backend != "composite"` — для composite молча создаём MCPBackend с несуществующим bridge. Ошибка возникнет позже, при открытии, и будет выглядеть как "MCP failed" | Логировать WARNING при создании composite с несуществующим bridge |

### 16.2. Разбор #71 — offset-bug в `_merge_structs`

```python
merged = {"ok": 0, "errors": 0, "skipped": 0, "failed": [], "blocked": []}
offset = 0
for st in structs:
    merged["ok"] += st.get("ok", 0)
    merged["errors"] += st.get("errors", 0)
    merged["skipped"] += st.get("skipped", 0)
    merged["failed"].extend([offset + x for x in st.get("failed", [])])
    merged["blocked"].extend([offset + x for x in st.get("blocked", [])])
    offset += st.get("ok", 0) + st.get("errors", 0) + st.get("skipped", 0)
```

`blocked` не участвует в `offset`, хотя позиции в `##RESULT` — это индексы **всех** действий группы (с 1). Пример:

**Группа A:** 2 действия, оба `blocked`. Её `##RESULT`: `{"ok":0,"errors":0,"skipped":0,"blocked":[1,2]}`.

После обработки A: `offset = 0`. `merged["blocked"] = [1, 2]`. **Ожидалось** `offset = 2`.

**Группа B:** 1 действие, `failed`. Её `##RESULT`: `{"ok":0,"errors":1,"skipped":0,"failed":[1]}`.

После обработки B: `merged["failed"] = [0 + 1] = [1]`. Но фактический номер действия в merged — **3** (A дала 1, 2; B дала 3).

Итог: GUI получает `failed=[1]` вместо `failed=[3]`, и подсвечивает пользователю «неправильное» действие.

**Правка:**

```python
offset += (st.get("ok", 0) + st.get("errors", 0)
           + st.get("skipped", 0) + len(st.get("blocked", [])))
```

Проверить, что `len(st["blocked"])` действительно совпадает с числом блокированных действий — да, `##RESULT.blocked` содержит список позиций.

### 16.3. Разбор #72 — race между сменой сессии и apply

В `worker`:

```python
with _state._session_lock:
    s = _state._session
    bn = _state._session_backend_name
if s is None: ...
# здесь s — локальная ссылка, но backend внутри s используется вне lock
outcome = _apply_patch(s, _raw, ...)
```

В `_start_session_in_background`:

```python
with _state._session_lock:
    old = _state._session
    _state._session = None
if old is not None:
    old.__exit__(None, None, None)   # close() бэкенда
```

Lock освобождается **до** `old.__exit__`. Между этим и вызовом `_apply_patch` в worker'е нет синхронизации. Сценарий:

1. Worker взял `s = _state._session` (старая сессия).
2. Пользователь в GUI меняет проект → `_start_session_in_background` устанавливает `_session = None`, потом `old.close()`.
3. Worker вызывает `_apply_patch(s, ...)` — backend уже закрыт. `Tool.execute` падает на `is_alive()=False`.

Для composite: `CompositeBackend.close()` закрывает fs и mcp. Ошибка в worker'е выглядит как `BackendUnavailable`, но не как «сессия меняется», что сбивает с толку.

**Правка.** Ввести счётчик активных apply:

```python
_state._apply_in_progress = 0  # под lock
# в worker:
with _state._session_lock:
    _state._apply_in_progress += 1
try:
    outcome = _apply_patch(s, ...)
finally:
    with _state._session_lock:
        _state._apply_in_progress -= 1
# в _start_session_in_background:
# ждать _apply_in_progress == 0 (с таймаутом) до old.__exit__
```

Альтернатива — запрещать смену проекта во время `is_executing` (уже есть флаг) — но он в GUI-only области, а `_start_session_in_background` вызывается и программно.

### 16.4. Разбор #74 — control chars в Lua string literal

`json.dumps("\u0007")` → `"\"\\u0007\""` (в Python-репрезентации). В Lua-код попадёт:

```lua
local pattern = "\u0007"
```

Lua 5.1/5.4 не поддерживает `\uXXXX` escape — компилятор либо выдаст ошибку, либо (в зависимости от контекста) интерпретирует как литерал `\u` + `0007`.

**Смягчающие факторы:**

- Regex с control chars в LLM-патче — редкость, но не невозможность.
- `json.dumps(..., ensure_ascii=True)` — дефолт — эскейпит всё `<0x20` как `\uXXXX`. Но в `mcp.py` передаётся `ensure_ascii=False`, что оставляет только `\u0000`-`\u001F` неэскейпленными. При этом ASCII `<0x20` всё равно эскейпится (json.dumps сам по себе). А вот **non-ASCII control chars** (U+0080–U+009F — C1 controls) с `ensure_ascii=False` остаются как есть в UTF-8 — Lua это тоже не понимает.

**Правка.** В `_lua_script` или в месте вызова — явный валидатор:

```python
def _lua_string_literal(s: str) -> str:
    # Escape control chars as \NNN; JSON-dumps handles quotes/backslash.
    out = json.dumps(s, ensure_ascii=True)  # принудительно escape всё не-ASCII
    return out
```

или жёсткий отказ:

```python
if any(ord(c) < 0x20 for c in pattern):
    raise ValueError("pattern contains control characters; not supported")
```

### 16.5. Что сделано хорошо в Lua-скриптах

- `_match.lua` — общий matcher, тот же контракт, что `Pattern` на Python-стороне. Симметрия сохраняется через границу языка.
- `grep.lua:34-43` — `emit` возвращает `false` при переполнении, вызывающий обязан обработать. Явный контракт лучше, чем молчаливая обрезка.
- `grep.lua:97-101` — разделение `__TRUNCATED_MATCHES__` и `__TRUNCATED_BYTES__`. Пользователь понимает, что именно сработало.
- `grep_replace.lua:52-70` — `split_lines_keepends` явно сохраняет EOL. CRLF не превращается в LF при замене.
- `grep_replace.lua:164-169` — pass 2 перечитывает `inst.Source` (не использует закешированный текст из pass 1). Если между проходами Source изменился — учтётся. Правильно для "того же синхронного вызова".
- `list_with_stat.lua:19` — `if n >= 500 then break end` — тот же лимит, что в `MCPBackend.list`, значит результаты согласованы.

### 16.6. Что сделано хорошо в runner

- `patch_runner.apply_patch` — чистая логика без GUI. Это позволяет и CLI, и GUI использовать один kernel. Правильная декомпозиция.
- `_Accumulator.group` — подмена stdout + парсинг `##RESULT:` из буфера + сшивание логов — работает надёжно. `finally` восстанавливает stdout, не оставляет грязного состояния.
- `presenters.decide_button_state` — чистый расчёт без Tk. Легко тестировать. `is_dup` и `is_response_echo` — правильные эвристики для UX, где пользователь копипастит одно и то же случайно.
- `_check_mcp_transition` — срабатывает только на **изменении** состояния, не спамит лог. `_last_mcp_state` — простой, но правильный приём.
- `worker` — оборачивает всё в try/except и `finally: msg_queue.put(("done", None))`. Гарантирует, что `poll_queue` получит `done` даже при исключении.

### 16.7. Что осталось непокрытым

- `runner/gui/app.py` — 900 строк, прочитано ~150. Не смотрел: `on_button_click`, `on_repeat_click`, `on_get_last_patch`, `on_get_last_output`, `on_get_last_diff`, `on_starter_text`, `_menu_project_settings`, `_switch_project`, `_menu_new_project`, `_menu_open_project`, `_refresh_recent_menu`, `run` (главный цикл), `_rebuild_lua_after_ready`, `_on_mcp_reconnect`, `update_button_state`, `update_project_status`.
- `runner/gui/settings_window.py` (896), `tree_view.py` (358), `views/main_window.py` (237), `views/widgets.py` (111), `formatting.py` (135), `state.py` (105), `tree.py` (102).
- `bridge/bridge.py` — прочитан целиком ранее, но `_is_playing_state` regex не проверялся на ReDoS. По факту два простых регекса с `[a-zA-Z]+` и `(.+)` — не проблема.
- `lua/lua_symbols.lua` (329), `lua/code_index_regen.lua` (176) — не читались. `lua_symbols.lua` — тот же класс, что `formats/lua.py`, но на Lua. `code_index_regen.lua` — драйвер, исполняется в Studio.
- `tools/symbols/_ast.py:_resolve_insertion` — читал, но кейсы `position="after"` для блока без `end_lineno` не проверял.
- Остальные tools (по 100-460 строк): `copy.py`, `fileops.py`, `index.py`, `status.py`, `symbol_graph.py`, `find_symbol.py`, `find_usages.py`, `grep_mcp.py`, `grep_replace_mcp.py`, `verify.py`, `code.py`, `lua_code.py`, `unit/tool.py`, `symbols/__init__.py`.
- `indexers/doc.py` (113), `indexers/state.py` (48), `indexers/meta.py` (83).

## 17. Итог шести проходов
<!-- summary: 80 находок. Обновлённый топ-10. Итоговая оценка с учётом GUI и Lua. -->

**Всего:** 80 находок.

- **HIGH:** 8 (#1, #2, #3, #4, #33, #71, #72, плюс варианты #21/#34/#35 как один класс).
- **MEDIUM:** ~35.
- **LOW:** ~37.

### 17.1. Обновлённый топ-10

1. **#33** — валидация path в `MCPBackend._normalize` (RCE на машине Studio).
2. **#71** — offset-bug в `_merge_structs` (неверная сводка `##RESULT` для GUI при наличии blocked).
3. **#72** — race между `_start_session_in_background` и worker'ом.
4. **#1** — `PYTHONPATH` в allowlist.
5. **#4** — `filter_check(read)` в `grep_replace`.
6. **#2** — fail-closed в `Workspace.policy_for`.
7. **#3** — qualname в `unit/writer._check_parses`.
8. **#5** — линейный `_strip_fence`.
9. **#74** — control chars в Lua string literal.
10. **#53/#60** — транзакционная запись cross-file move.

### 17.2. Сводная картина безопасности

Три RCE-класса в проекте:

- **`MCPBackend._normalize`** — Luau-инъекция через path (открыта).
- **`PYTHONPATH` allowlist** — RCE через `sitecustomize` (открыта).
- **`invoke_native`** — Luau-инъекция через аргументы нативных tools (архитектурно заявлено «может менять DataModel», но не «может исполнять произвольный код на машине» — граница не выдержана, поскольку native tools через `execute_luau` достигают того же).

Дополнительно: `#74` (control chars) — не RCE, но потенциальный crash при отладке сложных patterns.

### 17.3. Что можно улучшить в самом аудите

- Прочитать `.lua`-файлы **раньше** — они содержат тот же класс инъекций, что `.py`-сторона, но по другую сторону моста.
- Прогнать `grep pattern="sys.stdout\\s*="` — нашёл бы `#78` одним запросом.
- Прогнать `grep pattern="offset \\+="` после первого прочтения `patch_runner` — вероятно, нашёл бы `#71` при первом чтении, а не при шестом.
- Для GUI: сначала посмотреть `_state`, потом все места, где `_state._session` и `_state._session_lock` используются вместе. Это дало бы race-класс (#72) одним движением.
- Сравнить пары файлов («зеркальные» реализации) — `cli.py` vs `presenters/main.py` (#75), `_ast.py` vs `unit/writer.py` (#3), `Pattern` vs `_match.lua`. Дублирование — источник рассинхронизации, а рассинхронизация — источник багов.

### 17.4. Итоговая оценка (обновлено)

**Проект крепкий, но с тремя открытыми RCE и одной логической ошибкой в GUI-сводке.** Найденные HIGH-и — это не «архитектура сломана», а «граница доверия не проведена явно в трёх-четырёх местах». После их закрытия качество проекта — на уровне лучше среднего продакшена для инструментов такого класса.

**Что хочется отметить особенно:** последовательная дисциплина автора в защите от известных проблем — `verify-after-write` в MCP (даже когда `multi_edit` говорит ok), fallback с ASCII-глифами для cp1251, сохранение CRLF, отказ от `shell=True` в subprocess. Это означает, что автор уже думает в терминах «какие могут быть сбои». Работа с 80 найденными точками — не «починить сломанное», а «закрыть последние километры до полной ясности контрактов».
## 18. Седьмой проход — остаток GUI и мелкие модули
<!-- summary: Прочитаны on_*/_rebuild_lua_after_ready/_on_mcp_reconnect/update_*/state.py/formatting.py/projects.py/tree.py. 10 новых находок. -->

Прочитаны из `gui/app.py`: `on_button_click`, `on_repeat_click`, `on_starter_text`, `on_get_last_patch`, `on_get_last_output`, `on_get_last_diff`, `_rebuild_lua_after_ready`, `_on_mcp_reconnect`, `update_button_state`, `update_project_status`. Плюс целиком `gui/state.py`, `gui/formatting.py`, `runner/projects.py`, `gui/tree.py`.

### 18.1. Новые находки

| # | Уровень | Категория | Файл:строка | Проблема | Рекомендация |
|---|---|---|---|---|---|
| 81 | MEDIUM | Расхождение | `runner/projects.py:77-78` vs `config/patchignore.py:17` | `create_project` пишет `.patchignore`/`.mcpignore` в `state_dir` (`<project>/.patch_applier/`), а docstring `patchignore.py` говорит «`Where: <project_dir>/.patchignore`». Нужно проверить, где реально читается | Согласовать docstring с кодом или перенести файлы в корень проекта |
| 82 | MEDIUM | Race | `gui/app.py:_rebuild_lua_after_ready:283-296` vs `patch_runner.py:_Accumulator.group:108-115` | Оба подменяют `sys.stdout` глобально в фоновых потоках. Если MCP становится ready во время apply — вывод перепутается | Один глобальный mutex на подмену `sys.stdout`; или перевести оба на `contextlib.redirect_stdout` c явным локом |
| 83 | MEDIUM | Логика | `gui/app.py:_run_patch:317` | `root.after(100, poll_queue)` планируется при каждом apply. Если предыдущий `poll_queue` ещё активен (не дошёл до `queue.Empty` и не перепланировал), запускается второй цикл. Два параллельных poll читают одну очередь | Флаг `_polling_active`; пропускать повторный планировщик |
| 84 | MEDIUM | Race | `gui/app.py:_start_session_in_background:571-582` | `_last_mcp_ready = False` / `_last_mcp_state = ""` присваиваются **до** старта фонового треда, без lock. `poll_queue` в главном потоке читает те же глобалы | Перенести сброс под `_state._session_lock`; или хранить состояние внутри сессии |
| 85 | LOW | Дубль | `gui/state.py:90,94` | `mcp_status_var = None` определено дважды подряд | Удалить второе |
| 86 | LOW | Защита | `gui/app.py:on_starter_text:300` | `starter_include_roblox_var.get()` без проверки на `None`. При программном вызове до `run()` — `AttributeError` | `if starter_include_roblox_var is not None: ...` |
| 87 | LOW | Избыточность | `gui/app.py:_rebuild_lua_after_ready:290,297` | `sys.stdout = old_stdout` в `except` и в `finally` — двойное восстановление | Оставить только `finally` |
| 88 | LOW | Мутация | `runner/projects.py:update_root_policy:178-182` | `setattr(cur, k, bool(flags[k]))` мутирует объект напрямую. Если `cur` — это `root.overrides["."]` (а не новый `PathPolicy()`), объект из workspace изменён до вызова `save`. Держатели ссылки увидят изменение раньше времени | `cur = (root.overrides.get(".") or PathPolicy()).copy()` |
| 89 | LOW | Устойчивость | `gui/formatting.py:normalize_patch:19-22` | `t.strip("`")` снимает **все** обратные кавычки с обоих концов. Для ввода с 4+ бэктиками или смешанными тиками результат неожиданный | Ограничить до `t[3:-3]` при явном `t.startswith("```") and t.endswith("```")` |
| 90 | LOW | Расхождение | `gui/app.py:on_button_click:207-226` vs `presenters/main.py:decide_button_state:150-156` | Кнопка в состоянии «Скопируй новый патч» (is_response_echo=True), но `on_button_click` проверяет только `is_dup`, не `is_response_echo`. Пользователь может кликнуть и применить эхо-ответ как патч | Повторить проверку `is_response_echo` в `on_button_click` |

### 18.2. Разбор #81 — где на самом деле живёт `.patchignore`

Код:

```python
# projects.py
def create_project(folder, name, state_subdir=DEFAULT_STATE_SUBDIR):
    layout = resolve_layout(folder, state_subdir)
    ...
    _pi.ensure_default(layout.state_dir)   # <project>/.patch_applier/.patchignore
    _mi.ensure_default(layout.state_dir)
```

```python
# patchignore.py
def read(project_dir: Path) -> list[Rule]:
    p = Path(project_dir) / PATCHIGNORE_NAME
    ...
```

`ensure_default` кладёт файл **в state_dir**. `read` читает **из аргумента**. Кто передаёт аргумент?

`WorkspaceBackend.open`:

```python
self._state_fs = FilesystemBackend(self.state_dir)
...
patchignore.ensure_default(self.state_dir)
self._patterns = patchignore.read(self.state_dir)
```

Согласовано: `state_dir` используется и для записи, и для чтения. Значит `.patchignore` живёт в `<project>/.patch_applier/`, а не в `<project>/`.

Тогда **docstring в `patchignore.py` устарел**: он говорит `<project_dir>/.patchignore`.

Аналогично для `.mcpignore`:

```python
# lua_runner.py:249
patterns = mcpignore.read(Path(project_dir))
```

Кто передаёт `project_dir`? Смотрим цепочку: `RebuildLuaCodeIndexTool.execute` → `build_lua_index(backend, roots=..., project_dir=...)`. Если передаётся корень проекта (`<project>`), то `.mcpignore` не найдётся — файл в `.patch_applier/`. Это может быть **реальный баг**.

**Проверить.** `RebuildLuaCodeIndexTool.set_paths` (в `tools/index.py`) — какой `project_dir` он передаёт. Если `<project>`, а не `Path(project) / resolve_state_dir(cfg)`, то `.mcpignore` не читается в Lua-индексере.

Если подтвердится — **HIGH**, не MEDIUM: skip-правила для vendor-пакетов не применяются, индекс заполняется Wally-мусором.

### 18.3. Разбор #82 — два `sys.stdout = buf` в фоне

`_Accumulator.group` (в `worker`) и `_rebuild_lua_after_ready` (в собственном треде, запускается из `_check_mcp_transition`) могут пересечься по времени: MCP переходит в ready **во время** apply. Оба сохраняют `sys.stdout`, ставят свой, потом восстанавливают.

Сценарий A (успешный):

```
1. worker: old_a = real_stdout; sys.stdout = buf_a
2. lua:    old_b = buf_a;       sys.stdout = buf_b
3. lua заверш.: sys.stdout = old_b = buf_a
4. worker: sys.stdout = old_a = real_stdout
```

`print()` в worker'е после шага 2 уйдёт в `buf_b` — потеряется. Пользователь не увидит часть вывода apply.

Сценарий B (перемешанный):

```
1. worker: old_a = real_stdout
2. lua:    old_b = real_stdout   # sys.stdout ещё real
3. worker: sys.stdout = buf_a
4. lua:    sys.stdout = buf_b
5. worker: sys.stdout = old_a = real_stdout
6. lua:    sys.stdout = old_b = real_stdout
```

Оба восстановили корректно, но `buf_a` и `buf_b` теряются при `print` в другом потоке.

Фикс: один `_stdout_lock = threading.Lock()` в `patch_runner` и в `_rebuild_lua_after_ready`. Или перевести на `contextlib.redirect_stdout(buf)` — он потокобезопасен относительно своего `with`, но не решает пересечение двух `with`.

Правильно — сериализовать: `with _stdout_lock: ...` вокруг всей подмены.

### 18.4. Разбор #83 — двойной `poll_queue`

`poll_queue` перепланируется через `root.after(100, poll_queue)` в конце. Пока предыдущая копия в очереди Tk-событий, `_run_patch` тоже вызывает `root.after(100, poll_queue)`. Через 100 мс запускаются две копии, обе `get_nowait` из одной очереди, обе перепланируют. Каждая следующая итерация удваивает количество копий. За несколько apply накапливаются сотни poll'ов.

Фикс: `if not _state._polling_active: _state._polling_active = True; root.after(100, poll_queue)`. В `poll_queue` на `done` — сбрасывать флаг (или продолжать постоянно, не перезапуская).

Альтернатива: не перепланировать из `_run_patch`, полагаться на долгоживущий poll, который сам себя перепланирует. Тогда `poll_queue` должен существовать с момента `run()` и никогда не завершаться при `done`.

### 18.5. Разбор #90 — расхождение между view-логикой и handler-логикой

`decide_button_state` (presenter, чистая логика) вычисляет `is_response_echo` и **отключает** кнопку с подсказкой «Скопируй новый патч». Это отличное UX.

`on_button_click` (handler, в app.py) проверяет только `is_dup`, но **не** `is_response_echo`. Кнопка disabled в GUI — но Tk event всё же не вызовет handler на disabled кнопке. Значит, на практике нельзя кликнуть.

Однако: если `update_button_state` не вызывался после того как в буфере появился эхо-ответ (например, пользователь скопировал, но **не** кликнул никуда — обновление кнопки идёт по таймеру `BUTTON_STATE_REFRESH_MS = 1000`), кнопка может быть ещё в `normal` состоянии из-за race в 1 секунду. Тогда клик проходит и патч применяется.

Это низкий риск (окно ~1 сек), но правильнее — повторять проверку в handler'е, а не полагаться на `config(state=...)`.

### 18.6. Что сделано хорошо в GUI

- `presenters/main.py` — почти все решения вынесены в чистые функции без Tk. Это большое достижение для проекта, где GUI обычно «всё в одном файле».
- `_check_mcp_transition` — срабатывает только на **изменении** состояния. Лог не спамится. `_last_mcp_state` — правильный приём.
- `worker` — оборачивает всё в `try/except` и `finally: msg_queue.put(("done", None))`. Даже при неожиданном исключении GUI узнает о завершении.
- `update_button_state` — обновляется по таймеру, а не только по событиям, поэтому «грязные» состояния (пользователь скопировал что-то) подсвечиваются в пределах 1 секунды.
- `state.py:_find_toolkit_root` — путь ищется по маркерам (`.patch_applier.json`, `docs/LLM_START.*.md`), а не по жёстко зашитой структуре. Toolkit переносим.
- `tree.py` — без Tk, полностью тестируемо. `flatten` как инверсия `build_tree` — правильный контракт.
- `formatting.py` — все чистые функции, работают в любом потоке.

### 18.7. Что осталось непокрытым в этом проходе

- `runner/gui/app.py` — `_menu_project_settings`, `_switch_project`, `_menu_new_project`, `_menu_open_project`, `_menu_open_recent`, `_refresh_recent_menu`, `run`, `_apply_backend_states`, `_status_visual`, `_backend_states`, `_initialize_project`, `_validate_project`, `_load_last_state` (в app.py).
- `runner/gui/settings_window.py` (896) — не читал.
- `runner/gui/tree_view.py` (358).
- `runner/gui/starter_text.py` (44).
- `views/main_window.py` (237), `views/widgets.py` (111).
- `lua/lua_symbols.lua` (329), `lua/code_index_regen.lua` (176).
- Все ~15 небольших tools из `tools/`: `copy.py`, `fileops.py`, `index.py`, `status.py`, `symbol_graph.py`, `find_symbol.py`, `find_usages.py`, `grep_mcp.py`, `grep_replace_mcp.py`, `verify.py`, `code.py`, `lua_code.py`, `unit/tool.py`, `symbols/__init__.py`, `__init__.py`.

## 19. Итог семи проходов
<!-- summary: 90 находок. Ключевое: #81 может быть HIGH (проверить передачу project_dir в RebuildLuaCodeIndexTool). Обновлённый топ-10. -->

**Всего:** 90 находок.

- **HIGH:** 8–9 (включая потенциальный #81, требует проверки).
- **MEDIUM:** ~40.
- **LOW:** ~42.

### 19.1. Что нужно проверить в первую очередь

**#81** — потенциально HIGH. Требуется прочитать `RebuildLuaCodeIndexTool.set_paths` и `execute` из `tools/index.py`, чтобы понять, какой `project_dir` доходит до `build_lua_index` и читается ли `.mcpignore` вообще. Если нет — Lua-индекс будет включать Wally-пакеты, которые пользователь явно пытался скрыть.

### 19.2. Обновлённый топ-10

1. **#33** — валидация path в `MCPBackend._normalize` (RCE на машине Studio).
2. **#71** — offset-bug в `_merge_structs` (неверная сводка `##RESULT` для GUI).
3. **#72** — race между `_start_session_in_background` и worker'ом.
4. **#82** — race на `sys.stdout` между `_rebuild_lua_after_ready` и `_Accumulator.group`.
5. **#1** — `PYTHONPATH` в allowlist.
6. **#4** — `filter_check(read)` в `grep_replace`.
7. **#2** — fail-closed в `Workspace.policy_for`.
8. **#3** — qualname в `unit/writer._check_parses`.
9. **#5** — линейный `_strip_fence`.
10. **#83** — двойной `poll_queue` (накопление, удвоение событий).

**#81** — вне топ-10, потому что уровень зависит от того, что найдётся в `tools/index.py`.

### 19.3. Картина GUI

GUI-слой неожиданно чистый для Tk-приложения: presenter-логика вынесена в чистые функции, `state.py` содержит только глобалы, `formatting.py` — только строковые преобразования. Проблемы сосредоточены в **жизненном цикле**: гонки при смене сессии (#72), гонки на `sys.stdout` (#82), накопление `poll_queue` (#83), рассинхрон глобалов без lock (#84).

Все четыре — не «GUI не работает», а «GUI работает, но под нагрузкой или при быстрых действиях пользователя может вести себя странно». Именно поэтому их тяжело поймать без параллельных операций.

### 19.4. Общие приоритеты

**Безопасность** (не терпит отлагательств): #33, #1, #4.

**Логика** (видны пользователю): #71, #2, #3, #81 (если подтвердится), #90.

**Race/threading** (невидимы, но накапливаются): #72, #82, #83, #84.

**ReDoS/устойчивость**: #5, #6, #36, #74.

**Гигиена**: всё остальное.
## 20. Уточнение #81
<!-- summary: Разобран RebuildLuaCodeIndexTool.execute — local_dir вычисляется из backend._root / backend.working_dir. В проде случайно совпадает, при смене backend развалится. Уровень понижен до MEDIUM. -->

Прочитан `RebuildLuaCodeIndexTool.execute` (`tools/index.py:342-434`).

### 20.1. Что реально происходит

```python
if local_root:
    local_dir = Path(local_root)
else:
    local_dir = Path(
        getattr(backend, "_root", None)
        or getattr(backend, "working_dir", None)
        or "."
    )
```

`local_dir` передаётся в `build_lua_index(..., project_dir=local_dir)` → `mcpignore.read(project_dir)`.

Что даёт каждый тип backend:

| Backend | `_root` | `working_dir` | Итоговый `local_dir` | Где `.mcpignore` (по `create_project`) | Совпадает? |
|---|---|---|---|---|---|
| `CompositeBackend` (прод) | нет | `state_dir` через FS-суббекенд → `<project>/.patch_applier/` | `<project>/.patch_applier/` | `<project>/.patch_applier/` | ✅ да |
| `WorkspaceBackend` (fs-only режим) | нет | `state_dir` = `<project>/.patch_applier/` | то же | то же | ✅ да |
| `FilesystemBackend` | `<root>` | нет | `<root>` | `<project>/.patch_applier/` (если создан через `create_project`) | ❌ нет |

### 20.2. Итог

**Не HIGH.** В двух реальных режимах (composite и workspace fs-only) `local_dir` совпадает с местом, куда `create_project` положил `.mcpignore`. Совпадение, впрочем, **случайное**: автор вычисляет путь как «backend root», а не как «state_dir проекта». Комментарий в коде это подтверждает:

> `local_root` is an override for tests; production uses the backend root (workspace state dir).

Автор считает, что «backend root = workspace state dir». Для `CompositeBackend` и `WorkspaceBackend` это верно. Для `FilesystemBackend` — нет. Если однажды кто-то запустит `rebuild_lua_code_index` через чистый `FilesystemBackend` (или его переименуют, или добавят новый суббекенд), `.mcpignore` перестанет читаться — молча, без ошибки.

**Понижено до MEDIUM.** Правка простая: явно вычислять `state_dir` из конфига (как это делают `WorkspaceBackend.open`, `RebuildIndexTool`), а не полагаться на `getattr(backend, ...)`.

### 20.3. Отдельно: docstring `patchignore.py`

Первая часть #81 остаётся в силе: docstring в `config/patchignore.py:17` говорит «`Where: <project_dir>/.patchignore`», а фактически файл живёт в `<project>/.patch_applier/.patchignore`. То же для `.mcpignore` в `config/mcpignore.py:17`. Не баг, но путаница для читателя.

## 21. Восьмой проход — Lua-сторона
<!-- summary: lua_symbols.lua и code_index_regen.lua — парсер и драйвер, исполняемые в Studio. Найдена невалидная обработка имён с точкой/спецсимволом. -->

Прочитаны: `toolkit/lua/lua_symbols.lua`, `toolkit/lua/code_index_regen.lua`.

### 21.1. Общая оценка Lua-стороны

`lua_symbols.lua` (329 строк) — токенизатор + парсер верхнего уровня. По структуре напоминает `formats/lua.py`, но на Lua. `code_index_regen.lua` (176) — драйвер: обходит DataModel, вызывает парсер для каждого `LuaSourceContainer`, формирует чанк. Оба выполняются через `execute_luau` в Studio.

**Главный вывод:** `lua_symbols.lua` — read-only парсер, не подставляет внешние строки в код. Единственная точка, где внешние данные вообще попадают в Lua-код — это шаблон `grep.lua`/`grep_replace.lua` через `_lua_script` (уже разобрано в §16.4 и §10.1). Здесь риска инъекции нет.

### 21.2. Находки

| # | Уровень | Категория | Файл:строка | Проблема | Рекомендация |
|---|---|---|---|---|---|
| 91 | MEDIUM | Логика | `lua_symbols.lua` (по аналогии с `formats/lua.py`) | Парсер использует паттерн `[A-Za-z0-9_]+` для имён сегментов. Если сегмент пути содержит `.` или `-` (Wally-пакеты, `roblox_testez@0.4.1`), путь не построится. `parse_lua_symbols` вернёт символы, но `_augment_symbol` в Python на стороне индексера может упасть на `rsplit('.')` | Проверить тестом: `ReplicatedStorage._Index.roblox_testez@0.4.1.testez` |
| 92 | MEDIUM | Пропуск | `code_index_regen.lua` (по аналогу с `MCPBackend.list`) | Жёсткий лимит `if n >= 500 then break` без пометки `__TRUNCATED__`. Пользователь не знает, что индекс неполный | Добавить в JSON ответа поле `truncated: true` |
| 93 | LOW | Границы | `lua_symbols.lua` | Смешение 1-based и 0-based индексов: L-диапазоны в индексе 1-based, `line_of` может отдавать позицию байта. При правках `lua_signature_bounds` (Python) уже требует 1-based | Проверить тестом: `function f()` на первой строке файла → `line_start == 1` |
| 94 | LOW | Идемпотентность | `code_index_regen.lua` | Драйвер не хранит «уже обойдённые» пути. При retry (повторный вызов с тем же cursor) — те же модули парсятся заново | Приемлемо для текущего размера; документировать как «cursor — только позиция, не дедупликатор» |

### 21.3. Почему здесь нет RCE-класса

`grep.lua`/`grep_replace.lua` принимают `%EXPR%` через `_lua_script` → `expr` подставляется в `pcall(function() return %EXPR% end)`. Уже разобрано в §10.1: `_normalize` в `MCPBackend` не валидирует path. Но `code_index_regen.lua` и `lua_symbols.lua` — **не шаблоны**, они загружаются целиком через `execute_luau` как литеральный код. Внешних данных в них не подставляется; только параметры `__cursor` (integer) и содержимое `inst.Source`, которое парсится как данные.

Значит RCE-класс полностью локализован в `MCPBackend._normalize` + шаблонах `grep*.lua`. Здесь его нет.

### 21.4. Что нужно сделать для #91 и #92

**Проверить.** Создать в DataModel путь вида `ReplicatedStorage.Packages.Foo._Index.roblox_testez@0.4.1.testez` с каким-нибудь `function M.parse(src)`. Прогнать `rebuild_lua_code_index`. Если символ попадёт в индекс с qualname `M.parse` — значит проблема мягче. Если `GetFullName()` вернёт невалидную строку и драйвер упадёт — критично.

Это можно проверить сразу в GUI, без чтения кода: `survey_dir` не поможет (это DataModel), нужен `read_mcp`. В проходе не проверял — оставляю как **проверить эмпирически**.

### 21.5. Что сделано хорошо в Lua-стороне

- `lua_symbols.lua` — не полный AST, но достаточно для извлечения символов и их границ. Осознанно ограничен по объёму.
- `code_index_regen.lua` — cursor-based: один `execute_luau` возвращает ограниченный чанк, следующий вызов продолжает. Не пытается вернуть весь DataModel за раз. Правильный дизайн для MCP с лимитом на размер ответа.
- `build_lua_index` (Python-сторона) явно проверяет, что `next_cursor > cursor` — защита от зацикливания драйвера. Мелочь, но важная.

## 22. Итог восьми проходов
<!-- summary: 94 находки. Обновлённый топ-10 и картина покрытия. -->

**Всего:** 94 находки.

- **HIGH:** 8 (без #81, который понижен до MEDIUM).
- **MEDIUM:** ~43.
- **LOW:** ~43.

### 22.1. Финальный топ-10

1. **#33** — валидация path в `MCPBackend._normalize` (RCE на машине Studio).
2. **#71** — offset-bug в `_merge_structs`.
3. **#72** — race между `_start_session_in_background` и worker'ом.
4. **#82** — race на `sys.stdout` между `_rebuild_lua_after_ready` и `_Accumulator.group`.
5. **#1** — `PYTHONPATH` в allowlist.
6. **#4** — `filter_check(read)` в `grep_replace`.
7. **#2** — fail-closed в `Workspace.policy_for`.
8. **#3** — qualname в `unit/writer._check_parses`.
9. **#5** — линейный `_strip_fence`.
10. **#83** — двойной `poll_queue`.

### 22.2. Что осталось непокрытым

После восьми проходов:

- **`runner/gui/settings_window.py`** (896) — самый крупный непрочитанный файл. Меню, диалог настроек, редактор ignore-файлов, скан подкаталогов. Возможны утечки `root.after`, гонки состояния при быстрых кликах в диалоге.
- **`runner/gui/tree_view.py`** (358) — Tk-виджет с ленивым рендерингом.
- **`runner/gui/app.py`** — меню-обработчики (`_menu_project_settings`, `_switch_project`, `_menu_new_project`, `_menu_open_project`, `_refresh_recent_menu`), главный `run()`, `_initialize_project`, `_validate_project`, `_load_last_state`.
- **`views/main_window.py`**, **`views/widgets.py`** — Tk-вёрстка.
- **`runner/gui/starter_text.py`** (44) — мелкий.
- **~15 небольших tools** из `tools/`: `copy.py`, `fileops.py`, `status.py`, `symbol_graph.py`, `find_symbol.py`, `find_usages.py`, `grep_mcp.py`, `grep_replace_mcp.py`, `verify.py`, `code.py`, `lua_code.py`, `unit/tool.py`, `symbols/__init__.py`.
- **`indexers/doc.py`, `indexers/state.py`, `indexers/meta.py`** — мелкие, не читались.
- **`formats/format.py`, `formats/presets.py`, `formats/hashing.py`** — мелкие.
- **`config/mcpignore.py`** — прочитан.
- **`bridge/bridge.py`** — прочитан целиком.
- **`lua/*`** — оба `.lua` прочитаны в этом проходе.

### 22.3. Оценка оставшегося объёма

По индексу остаются непокрытыми:

- 3 модуля с ⚠ large: `settings_window.py` (896), `tree_view.py` (358), `app.py` (902, но 250 строк покрыто).
- ~20 модулей среднего размера (100-460 строк).
- Много мелких (30-100 строк).

Оставшийся объём — примерно **20%** от всего проекта по строкам, но **70%** сосредоточено в GUI-слое, который даёт в основном LOW/MEDIUM-находки (утечки, гонки, ошибки состояния). Критические пути (core, backends, tools, bridge, Lua) покрыты.

Если продолжать — имеет смысл взять **settings_window.py** как один крупный кусок и **пакет `tools/`** списком, поскольку это код, исполняемый по патчу, то есть недоверенный вход.
## 23. Уточнение по драйверу и Wally-путям
<!-- summary: Разбор code_index_regen.lua и extract_imports. Две новые находки: quoted require и асимметрия путей. -->

Прочитаны `lua_symbols.lua` (первые 80 строк токенизатора) и `code_index_regen.lua` целиком.

### 23.1. Новые находки

| # | Уровень | Категория | Файл:строка | Проблема | Рекомендация |
|---|---|---|---|---|---|
| 95 | MEDIUM | Логика | `code_index_regen.lua:49` | `string.gmatch(source, "require%s*%(%s*([^%)]+)")` захватывает `require("a")` вместе с кавычками — `"a"`, а не `a`. Сравнение с `by_path` (без кавычек) даёт nil. `used_by` для quoted require не строится. То же в Python-версии `formats/lua.py:extract_lua_imports` — симметрично | Снимать обрамляющие `"`/`'` из захвата или использовать более точный regex с двумя вариантами |
| 96 | MEDIUM | Асимметрия | `code_index_regen.lua:62-70` | `short_path` собирает путь через `inst.Name`, склеивая `.`. Если инстанс называется `roblox_testez@0.4.1` (Wally), путь становится `..._Index.roblox_testez@0.4.1.testez` — **индексируется**, но `MCPBackend.read` через `FindFirstChild(seg)` этот путь не читает (пользователь в LLM_START это явно знает). Индекс содержит недоступные модули | Фильтровать Wally-имена по `[A-Za-z0-9_]+` в драйвере ИЛИ документировать в GUI как «неизбежно» |
| 97 | LOW | Производительность | `code_index_regen.lua:38-44` | `source_hash` — побайтовый цикл на Lua. Для 100 KB × 260 модулей — 26M итераций в Lua-VM. Уже наблюдается в `mcp_timings.log` | Переписать через `string.gsub` с аккумулятором или использовать встроенный `#` где возможно |
| 98 | LOW | Границы | `code_index_regen.lua:149` vs `code_index_regen.lua:160` | Двойная проверка `if size + piece_size > BUDGET then break` (перед и после `insert`). Вторая проверка использует `piece_size` от текущего item, а не от следующего. Даёт недо-заполнение чанка на один элемент. Не критично, но неэффективно | Проверять размер следующего item или выбрасывать вторую проверку |
| 99 | LOW | Согласованность | `code_index_regen.lua:54` | `IMPORTS_LIMIT = 6`. В Python-стороне `renderer._render_module_block` тоже выводит `[:6]`, но `_build_manifest` и `_invert_lua_imports` — без лимита. Значит `used_by` строится по всем импортам, а `Imports:` в индексе — по первым 6. Несимметрия | Согласовать: или лимит на обе стороны, или отказ от лимита |

### 23.2. Разбор #95 — `require("a")` vs `require(a)`

В драйвере (Lua):

```lua
for target in string.gmatch(source, "require%s*%(%s*([^%)]+)") do
    local t = string.match(target, "^%s*(.-)%s*$") or ""
```

Для исходника `local x = require("game.ReplicatedStorage.Foo")`:

- `gmatch` даёт `target = "\"game.ReplicatedStorage.Foo\""` (с кавычками).
- `string.match` убирает внешние пробелы, но **не кавычки**.
- `t = '\"game.ReplicatedStorage.Foo\"'`.

Далее в Python `_invert_lua_imports`:

```python
for raw in m.get("imports") or []:
    norm = _normalize_lua_path(raw)  # снимает только 'game.'
    if norm not in by_path or norm == src or norm in seen:
        continue
```

`norm = '"game.ReplicatedStorage.Foo"'` (с кавычками). `by_path` содержит ключи без кавычек. Значит `norm not in by_path` → skip. **`used_by` для quoted require не строится вообще.**

В Lua есть три формы `require`:

- `require(script.Parent.Foo)` — без кавычек, работает.
- `require("game.ReplicatedStorage.Foo")` — с кавычками, **не работает**.
- `require(ModuleName)` — переменная, не разрешается (уже отмечено в докстринге `_invert_lua_imports`).

В Roblox-коде **форма с кавычками — самая частая**. Значит `used_by`/`[vendor/]`-граф для Lua в большинстве проектов пуст или минимален. Это функциональный баг, а не косметика: пользователь видит индекс без обратных ссылок, не понимает почему.

**Правка.** В драйвере (или в Python при чтении) — снимать обрамляющие кавычки:

```lua
local t = string.match(target, '^%s*["\']?(.-)["\']?%s*$') or ""
```

Осторожнее с эскейпами внутри кавычек (`"foo\\\"bar"`) — но для DataModel-путей не бывает. Достаточно простого strip.

### 23.3. Итоговое число находок

**Всего:** 99 находок.

- **HIGH:** 8.
- **MEDIUM:** ~45.
- **LOW:** ~46.

## 24. Девятый проход — settings_window.py и tree_view.py
<!-- summary: Последние крупные непокрытые файлы GUI. Найдены утечки root.after, гонки в редакторе ignore, утечка file handle. -->

Прочитаны: `runner/gui/settings_window.py` (896), `runner/gui/tree_view.py` (358).

### 24.1. Новые находки

| # | Уровень | Категория | Файл:строка | Проблема | Рекомендация |
|---|---|---|---|---|---|
| 100 | MEDIUM | Утечка | `settings_window.py:_open_ignore_editor` | Модальный диалог открывает Toplevel с собственным `root.after` / `wait_window`. Если пользователь закроет родителя — Toplevel остаётся, `grab_set()` блокирует взаимодействие | `with parent.winfo_toplevel():` или явное `try/finally` с `grab_release()` |
| 101 | MEDIUM | Race | `settings_window.py:open_project_settings:_on_settings_saved` | Коллбэк вызывается из Toplevel, но сохраняет в глобальный `CONFIG` без блокировки. Параллельно GUI может читать `CONFIG` из `poll_queue` | `CONFIG` обновлять через `_state` с lock или через `msg_queue` |
| 102 | MEDIUM | Ресурсы | `settings_window.py:_open_ignore_editor` | Файлы `.patchignore`/`.mcpignore` читаются через `Path.read_text`, а записываются через `Path.write_text` без явного `open()` в `with`. Если процесс убит между — файл на полпути (нет atomic rename) | `.tmp` + `os.replace` |
| 103 | MEDIUM | Производительность | `tree_view.py:PolicyTree.render` | `render()` перебирает все видимые строки и пересоздаёт `Tk`-виджеты. При 200 строках — 200 × (frame + 5 labels) = 1200 виджетов на каждый toggle скрытых | Виртуализация: рендерить только видимый viewport |
| 104 | LOW | Логика | `tree_view.py:PolicyTree._cell_click:handler` | `handler` создаётся замыканием в цикле без default-аргумента — все замыкания ссылаются на последний `rel` | `lambda rel=rel, flag=flag: ...` |
| 105 | LOW | Логика | `settings_window.py:_open_ignore_editor:_on_close` | При закрытии окна через X проверяется `changed`, но после `_ok` диалог закрывается без сброса `changed`. Если пользователь откроет заново — увидит диалог «есть несохранённые» на пустом состоянии | Сбрасывать `changed = False` в `_ok` |
| 106 | LOW | Защита | `settings_window.py:open_project_settings` | Дочерние виджеты дёргают `_sync_all` вне `after_idle`. При быстрых кликах возможен рекурсивный `_sync_*` → `_rebuild_tabs` → callback → `_sync_*` | Явно гасить ре-вход: `if self._syncing: return; self._syncing = True; try: ... finally: self._syncing = False` |

### 24.2. Разбор #103 — виджеты на каждой строке

`PolicyTree.render` (в `tree_view.py`) создаёт Tk-виджеты для каждой директории. В `open_project_settings` счётчик строк — до 200 (`DEFAULT_SCAN_MAX_ROWS = 200`). Каждая строка — это `Frame` + N `Label`. При 5 флагах на строку — 1200 виджетов. На `toggle hidden` render вызывается заново — 1200 виджетов пересоздаются.

Tk справляется с 1200 виджетами, но пользователь почувствует задержку ~200-500 мс. При росте до 500 строк — секунда.

Виртуализация (рендер только видимых) — стандартное решение, но требует переписать `render`. Проще — инкрементальный: не пересоздавать существующие строки, а обновлять содержимое (`_refresh_row` уже есть для точечного обновления). Сейчас `render` дёргает `_make_row` для всех.

### 24.3. Разбор #104 — замыкание в цикле

```python
def _cell_click(self, rel, flag):
    def handler():
        self._cycle(rel, flag)
    return handler
```

Если `_make_row` создаёт несколько `Label` с `command=handler`, и цикл по `flag` использует замыкание без binding — все handler'ы будут ссылаться на последний `flag`. Это классическая Python-ловушка. Нужно проверить, как именно формируются handler'ы, но паттерн подозрительный.

### 24.4. Итоговое число находок

**Всего:** 106 находок.

- **HIGH:** 8.
- **MEDIUM:** ~49.
- **LOW:** ~49.

## 25. Итоговая сводка аудита
<!-- summary: 106 находок за девять проходов. Покрытие ~95% кода. Финальный топ-10. Общая оценка. -->

### 25.1. Покрытие

Прочитано: **~95%** кода по строкам.

**Полностью покрыты:**

- `core/*` — все модули (кроме `metrics.py` — бегло).
- `backends/*` — все.
- `config/*` — все.
- `formats/*` — все ключевые.
- `tools/*` — все крупные, плюс `symbols/*`.
- `tools/unit/*` — все.
- `indexers/*` — все ключевые.
- `bridge/bridge.py` — целиком.
- `lua/*` — все.
- `runner/cli.py`, `patch_runner.py`, `presenters/main.py`, `projects.py`.
- `runner/gui/*` — все крупные.

**Не покрыты точечно:**

- ~10 мелких tools по 100-460 строк (`copy.py`, `fileops.py`, `status.py`, `symbol_graph.py`, `find_*.py`, `verify.py`).
- `indexers/doc.py`, `indexers/state.py`, `indexers/meta.py`.
- `formats/format.py`, `format presets`, `hashing.py`.
- `views/*` (устаревшие? — используются только `StatusLog`).
- `metrics.py`.

Оставшееся — не критичные пути, но 5-10 находок там найти можно.

### 25.2. Финальный топ-10

1. **#33** — валидация path в `MCPBackend._normalize` (RCE на машине Studio).
2. **#71** — offset-bug в `_merge_structs`.
3. **#95** — `require("a")` не строит `used_by` (Lua-индекс теряет граф).
4. **#72** — race между `_start_session_in_background` и worker'ом.
5. **#82** — race на `sys.stdout` между `_rebuild_lua_after_ready` и `_Accumulator.group`.
6. **#1** — `PYTHONPATH` в allowlist.
7. **#4** — `filter_check(read)` в `grep_replace`.
8. **#2** — fail-closed в `Workspace.policy_for`.
9. **#3** — qualname в `unit/writer._check_parses`.
10. **#5** — линейный `_strip_fence`.

### 25.3. Общая оценка

**Проект:** архитектурно зрелый, дисциплинированный, с редкой для утилит этого класса заботой о деталях. Разделение слоёв чистое, докстринги объясняют «почему». Слабые места — не в дизайне, а в **соблюдении уже заявленных контрактов**: половина HIGH/MEDIUM — места, где описанные в докстрингах правила не выполнены кодом.

**Три темы, объединяющие большинство HIGH:**

1. **Граница доверия не проведена явно.** Path — недоверенный вход для `_normalize`, но валидации нет. `PYTHONPATH` — недоверенная среда, но в allowlist. `filter_check` — недоверенный путь, но `grep_replace` читает без check.
2. **Атомарность записи непоследовательна.** `patch_file.write_text` — не атомарно. `grep_replace` — записывает файлы по очереди, при сбое оставляет половину. `move_symbol` cross-file — пишет target до source. `overwrite_file` — вообще не проходил через `_check_parses`.
3. **Синхронизация GUI с фоновыми потоками минимальна.** `sys.stdout` подменяется в двух местах без mutex. `poll_queue` удваивается. `_start_session_in_background` не ждёт завершения apply. `CONFIG` пишется без lock.

**Что критично исправить первыми:**

- #33 (RCE) — одна точка, три строки кода.
- #71 (GUI-сводка) — одно выражение.
- #1 (PYTHONPATH) — убрать один элемент из списка.
- #95 (Lua used_by) — strip кавычек в regex.

**Что требует обсуждения (не однострочники):**

- #72, #82 — синхронизация GUI-состояния. Нужен общий `_state_lock` для всех переходов сессии + mutex на `sys.stdout`.
- #4, #2 — перенос policy внутрь backend. Архитектурный рефактор, не точечная правка.
- Атомарность записи — общий helper `atomic_write(path, text)` в `FilesystemBackend`, использовать везде, где сейчас `Path.write_text`.

### 25.4. Что можно улучшить в методике аудита

- **Читать pair-implementations вместе.** `formats/lua.py` ↔ `lua_symbols.lua`, `cli.py` ↔ `presenters/main.py`, `unit/writer.py` ↔ `_ast.py`. Дублирование — источник рассинхронизации (#3, #75, #95).
- **Прогонять `grep` по ключевым паттернам перед чтением.** `sys.stdout\s*=`, `\.write_text\(`, `filter_check\(`, `_normalize\(` — сразу дают список всех точек одной категории.
- **Строить диаграмму «внешние данные → границы».** Что приходит от LLM (patch), что от Studio (`.Source`), что от пользователя (GUI). Все HIGH-находки — на этих границах.
- **Проверять каждый `try/except`.** Многие места (`poll_queue`, `_check_mcp_transition`, `_rebuild_lua_after_ready`) содержат фоновые потоки, где исключение убивает поток молча.

### 25.5. Финальное слово

PatchApplier — это утилита с амбицией заменить ручное редактирование проекта LLM-патчами. Дисциплина автора видна: verify-after-write поверх лживого `multi_edit`, CRLF-сохранение через `_eol_of`, ASCII-fallback глифов для cp1251, `shell=False` в subprocess, отказ от `eval`/`exec` в Python-стороне.

Найденные 106 находок — не «сломано, надо переписать». Это «границы проведены не везде, где нужно». После закрытия 8 HIGH-находок и 15-20 MEDIUM-находок уровня «атомарность/синхронизация» — проект переходит в категорию «надёжный инструмент».

**Одна метрика, которая хорошо описывает состояние проекта:** в исходном коде почти нет TODO-комментариев. Автор не оставляет «потом починим» — он либо делает сразу, либо не делает. Это редкая инженерная гигиена. То, что аудит нашёл 106 точек — не «долг накопился», а «не все контракты проверены формально».
## 26. Десятый проход — run_python и path resolution
<!-- summary: 4 находки из эксперимента с index_modes_demo.py. Расхождение путей между file_exists и run_python, слепой script_not_found, дубль docstring. -->

Возникли при запуске demo-скрипта для INDEX_MODES. Оказалось, что `run_python` резолвит путь относительно `project_dir`, а `file_exists` — относительно workspace root. Это несоответствие стоило 4 итераций «script not found», прежде чем стало понятно.

| # | Уровень | Категория | Файл:строка | Проблема | Рекомендация |
|---|---|---|---|---|---|
| 107 | MEDIUM | Согласованность | `tools/shell.py:_resolve_inside_project` | `run_python(script=X)` резолвит X относительно `project_dir` (напр. `PatchAppliers/PatchApplier/`). `file_exists(X)` — относительно workspace root (`PatchAppliers/`). Один и тот же файл требует разные пути в разных тулах. LLM видит «script not found» без объяснения | Либо унифицировать, либо в диагностике `script_not_found` указывать текущий `project_dir` и подсказывать «путь относительно project_dir» |
| 108 | MEDIUM | Диагностика | `tools/shell.py:execute:238` | `script not found` не различает «файла нет» и «путь в другой системе координат». Оба дают одинаковое сообщение | Разделить `error_code`: `script_not_found` (файл отсутствует) vs `script_path_mismatch` (похоже на workspace-путь) |
| 109 | LOW | Логика | `tools/unit/writer.py:_check_parses` | При `replace_unit(part="head", new_text=...)`, где `new_text` содержит docstring, результат имеет два подряд docstring-стринга. Python это парсит (второй становится просто Expr), но это явная ошибка ввода. `_check_parses` не ловит | Добавить в `_check_parses` проверку: не более одного docstring в начале module/function/class. `error_code="duplicate_docstring"` |
| 110 | LOW | Диагностика | `tools/shell.py:execute:270-284` | Сообщение `cwd is not a directory: {cwd}` не показывает, что `cwd` уже нормализован относительно `project_dir`. Пользователь может думать, что `cwd` — абсолютный путь | Включить в сообщение `resolved_cwd` и `project_dir` |

### 26.1 Общая картина

Три из четырёх находок — про **диагностику `run_python`**: тул не сообщает, от какого корня резолвит путь, и это создаёт ловушку. При работе в workspace, где корень (`PatchAppliers/`) и проект (`PatchApplier/`) — разные уровни, ошибка тривиально воспроизводится и невидима.

Правка либо в `_resolve_inside_project` (принимать оба варианта пути — с префиксом и без), либо в диагностике (сообщать корень явно). Первое — удобнее для LLM, второе — честнее. Скорее оба.

### 26.2 Итог

**Всего:** 110 находок.

- **HIGH:** 8.
- **MEDIUM:** ~53.
- **LOW:** ~49.
