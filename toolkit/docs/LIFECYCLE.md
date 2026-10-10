# Lifecycle

> **Статус:** принципы жизненного цикла Backend и Session. Конкретные таймауты — в `backends/mcp.py` и `.patch_applier.json`. Если документ расходится с кодом — верь коду.

## 1. Проблема

<!-- summary: Filesystem открывается мгновенно, MCP — секунды. Composite решает через async. -->
<!-- tags: lifecycle, problem -->

Backend'ы имеют разную стоимость открытия:

| | Filesystem | MCP |
|---|---|---|
| `open()` | мгновенно | секунды: spawn bridge, MCP handshake, ожидание Studio |
| `close()` | no-op | `exit` → wait → kill при таймауте |
| Транспорт | прямой доступ к FS | stdin/stdout, `patch.json`, `outputs.json` |
| Transient-сбои | нет | «No Roblox Studio instances» — retry |

Наивное решение — два разных runner'а. Правильное — **Session** с явным lifecycle, плюс **асинхронное открытие**: FS работает сразу, MCP догоняет в фоне.

## 2. Session

<!-- summary: Обёртка над Backend с __enter__/__exit__ и open_async. -->
<!-- tags: lifecycle, session -->

```python
class Session:
    def __init__(self, backend, fmt, tools, policy=None): ...
    def __enter__(self): self.backend.open(); return self
    def open_async(self): ...   # неблокирующий вариант для GUI
    def __exit__(self, *exc): self.backend.close()
    def apply_patches(self, patches) -> list[Result]: ...
    def is_alive(self) -> bool: ...
```

`open_async()` использует `Backend.open_async()`, если он есть; иначе падает на синхронный `open()`. `CompositeBackend.open_async()` открывает FS синхронно, остальные подбэкенды — в фоновых потоках. Состояние каждого подбэкенда читается через `backend_state(name)` / `backend_state_all()`: `not_started` / `starting` / `ready` / `failed: <err>`.

**Patcher stateless.** Backend stateful (для MCP). Session — lifecycle wrapper.

## 3. Паттерны использования

<!-- summary: CLI one-shot (FS) vs GUI persistent (composite). -->
<!-- tags: lifecycle, patterns -->

**CLI one-shot (FS):**

```python
with Session(FilesystemBackend(root), fmt, tools, policy) as s:
    s.apply_patches(patches)
```

**GUI persistent (composite):**

```python
session = Session(CompositeBackend([...]), fmt, tools, policy)
session.open_async()             # FS готов сразу, MCP в фоне
# ... on_button: session.apply_patches(from_clipboard())
```

Один код, разное время жизни. Composite открывает FS моментально — даже если Studio недоступна, FS-патчи работают. MCP-патчи возвращают `error_code="backend_not_ready"`, пока соответствующий backend не поднимется.

## 4. Что делает MCPBackend

<!-- summary: Spawn bridge, wait ready, wait studio, retry, verify, control-char guard. -->
<!-- tags: lifecycle, mcp-backend -->

`open()`:
1. Спавнит `bridge.py` через `python -u` (unbuffered — иначе stdout не флашится).
2. Читает stdout через reader-поток (без него pipe переполняется).
3. Ждёт строку «Мост готов» (`ready_timeout`).
4. `_wait_studio_ready` — поллит `execute_luau return '__studio_ready__'` до `studio_timeout`.

`_invoke(tool, args)`:
1. Удаляет `outputs.json`.
2. Пишет `patch.json`, шлёт `accept\n` в stdin.
3. Ждёт `outputs.json` + валидный JSON + непустой список.
4. Возвращает `data[0]`.
5. При transient-маркере — retry до `max_retries + 1` раз с `retry_delay`.

`write(path, content)`:
1. Control-char guard (только `\t`, `\n`, `\r`; иначе `ValueError`).
2. `json.dumps(content)` → валидный Lua-литерал.
3. `execute_luau` устанавливает `t.Source = <literal>`.
4. **Verify-after-write**: `read(path)` обратно, сравнение с `content`. Расхождение → `RuntimeError`.

`read(path)` использует `pcall` + маркеры `__MISSING__` / `__NOT_SOURCE__`, чтобы отличить «нет пути» от «не скрипт».

## 5. Verify-after-write

<!-- summary: read → write → read → compare. Filesystem не нуждается. -->
<!-- tags: lifecycle, verify -->

```
1. before = backend.read(path)      # опционально
2. backend.write(path, new_content)
3. after = backend.read(path)
4. verify: after == new_content
5. при расхождении — RuntimeError с указанием длин
```

Filesystem не нуждается (write атомарен). MCP — обязателен из-за багов моста.

## 6. Composite: два независимых состояния

<!-- summary: FS и MCP — раздельные лампочки, ручной реконнект MCP. -->
<!-- tags: lifecycle, composite -->

`CompositeBackend` держит состояние для каждого подбэкенда. GUI отображает их как две лампочки:

- `fs ●` — FS готов.
- `mcp ⏳` (тёмно-жёлтый) — starting; `mcp ●` (зелёный) — ready; `mcp ✗` (красный) — failed.

Реконнект MCP — вручную через кнопку `↻` рядом с лампочкой (`backend.reopen("mcp")` в фоне). Auto-reconnect не делаем: пользователь сам решает, когда пробовать.

## 7. Passthrough MCP-инструментов

<!-- summary: Реализовано через backend.invoke_native. Гейт mcp.native_tools.enabled. -->
<!-- tags: lifecycle, passthrough -->

Реализовано через `MCPBackend.invoke_native(name, args)`. В `Patcher._apply_one`, если action не найден в `TOOL_MAP`, вызывается `backend.invoke_native(action, args)`:

- backend без `invoke_native` (FilesystemBackend) или не знающий имени → `None` → прежнее `status=skipped, «неизвестное действие»`.
- `MCPBackend` с `native_tools_enabled=false` → `Result(status="blocked", error_code="native_tools_disabled")`.
- иначе — вызов `_invoke(name, args)` (та же retry-политика, что у унифицированных тулов), результат заворачивается в `Result` со префиксом `[native]`.

`CompositeBackend` делегирует вызов MCP-подбэкенду (если он есть и готов), иначе `None`.

Схема доступных bridge-инструментов — внешняя (`RobloxCodeRules.md`), подмешивается в стартовый текст LLM по чекбоксу в GUI.

## 8. Поток применения патча

<!-- summary: parse_patches → dispatch → filter → execute → Result → diagnostics → ##RESULT:. -->
<!-- tags: lifecycle, flows -->

```
1. Runner загружает config, создаёт Backend + Format + Policy.
2. Runner парсит текст патча через core.patchparse.parse_patches — получает ParseResult(actions, diagnostics).
3. Session.open() / open_async().
4. Patcher для каждого action:
   a. Находит Tool в реестре.
   b. Определяет op из tool_cls.op.
   c. Проверяет policy.for_op(op) против path_args/path_list_args.
      Для op="index" — не фильтрует, передаёт спеку через `_index_spec`.
   d. Tool.execute(backend, fmt, **args) -> Result.
4. Агрегация Result[], печать лога, печать diagnostics (если есть), ##RESULT:.
5. Session.close().
```

Rebuild индексов — отдельные тулы (`rebuild_index`, `rebuild_code_index`, `rebuild_lua_code_index`). Каждый после успешной записи инкрементирует `<index>.version` и возвращает `[vN]` + diff против того, что лежало на диске до rebuild.

## 9. Что не решаем сейчас

<!-- summary: Concurrent sessions, concurrent patches, persistence, auto-reconnect. -->
<!-- tags: lifecycle, out-of-scope -->

- Concurrent sessions — одна Session = один Backend.
- Concurrent patches — один за раз.
- Session persistence между запусками GUI — bridge стартует при старте GUI.
- Auto-reconnect MCP при падении — есть ручной `↻`.
