# WorkspaceBackend — дизайн-док шага 3

<!-- summary: Замена FilesystemBackend на обёртку над N корней. Адресация <basename>/<rel>; state-файлы — state/<rel>. filter_check и working_dir убираются из Backend-протокола. Read-only на этом шаге. -->
<!-- tags: workspace, backend, design -->

## 1. Зачем

С `Workspace` (см. `WORKSPACE.md`) у проекта не один корень, а несколько. Сегодняшний `FilesystemBackend` знает один `working_dir`. Если добавить второй корень, кто-то должен решать:

- какой путь принадлежит какому корню (`docs/REQUIREMENTS.md` → `D:/docs/REQUIREMENTS.md`);
- куда писать `INDEX.md` — он **один** на workspace, а не на root;
- что возвращает `list("")` — список корней;
- где живут policy-проверки, если у каждого корня свои флаги;
- куда девается `working_dir`.

`WorkspaceBackend` — ответ. Это **обёртка над N × `FilesystemBackend`** с routing по basename'у корня. Не замена `FilesystemBackend` — слой над ним. Один `FilesystemBackend` = «один корень», N таких = «workspace».

**Не в этом шаге.** GUI, миграция, create/delete root в runtime, write вообще (только read).

## 2. API sketch

`WorkspaceBackend` реализует `Backend`-протокол. Все тулы работают без изменений: путь приходит строкой, резолв — внутри backend'а.

```python
class WorkspaceBackend:
    def __init__(self, workspace: Workspace, state_dir: Path):
        self.ws = workspace
        self.state_dir = state_dir
        self.roots: dict[str, FilesystemBackend] = {}

    def open(self) -> None: ...
    def close(self) -> None: ...
    def is_alive(self) -> bool: ...

    def read(self, path: str) -> str: ...
    def exists(self, path: str) -> bool: ...
    def stat(self, path: str) -> FileStat: ...
    def list(self, path: str = "") -> list[str]: ...
    # write/delete/move/copy — не на этом шаге
```

**`filter_check` убран из протокола.** Раньше он проверял `FilterSpec` на уровне backend'а, дублируя `Policy`. Теперь policy — забота `Patcher`. Подробности в §5.

**`working_dir` убран из протокола.** Был корнем проекта; с multi-root нет одного корня. Кому нужен `cwd` для `run_python` — использует `<basename>/rel`. Кому нужно писать индексы — `state/<rel>`.

## 3. Routing

**Путь в tool'ах — `<basename>/<rel>`.** `basename` — имя корневого каталога корня. `docs/REQUIREMENTS.md`, `src/toolkit/core/patcher.py`, `game/ServerScriptService/Foo/init.luau`.

**Алгоритм:**

1. Первый сегмент до `/` — это `basename`. Если не в `self.roots` — `not_found: root '<basename>' not in workspace`.
2. Остальное — `rel`. Передать `FilesystemBackend[basename].read(rel)` и т.п.
3. `list("")` — список basename'ов (см. §4). `list("<basename>")` — файлы внутри этого корня (не рекурсивно, как обычно).

**State-каталог — как сейчас.** `.patch_applier/` (или новый `state_dir`) адресуется либо через корневой путь, если он физически внутри корня (`my-project/.patch_applier/workspace.json`), либо напрямую по сохранённому пути — внутренним механизмом утилиты. LLM туда не ходит: индекс читается `get_index`, политики — `get_status`, конфиг — `get_status`. Прямой `read_file` по state-файлу возможен (он RW), но не рекомендуется. Правило не меняется от multi-root — что сейчас работает, то и продолжит.

**Регистр basename — case-insensitive.** `D:/Docs` и `D:/docs` — коллизия. Сравнение — приведением к нижнему регистру.

**Абсолютные пути — не для LLM.** Внутри утилиты (GUI при выборе каталога, CLI, внутренние тулы) абсолютные пути используются. В патчах LLM видит только `<basename>/<rel>`. Если прилетает абсолютный путь — `wrong_domain: absolute path not allowed in patches`.

**MCP-пути** (`ReplicatedStorage.X.Y`) — не наша забота. Их разбирает `CompositeBackend._owner`, `WorkspaceBackend` их не видит.

## 4. `list("")` — список basename'ов

`list("")` возвращает `["docs", "src", "game"]` — basename'ы корней. Аналогично `os.listdir("/")`. Никакого рекурсивного обхода — для этого есть `list("<basename>")` по каждому корню.

Workspace с нулём корней валиден — `list("")` вернёт `[]`. Штатный режим для чистого MCP (без FS-корней).

## 5. Policy — в Patcher, не в backend

**`filter_check` убирается из `Backend`-протокола.** Раньше `FilesystemBackend.filter_check` применял `FilterSpec`; `MCPBackend.filter_check` возвращал `None`. Это дублировало `Policy`, которая уже живёт в `Session`. С multi-root дублирование становится вредным: backend должен знать про `RootPolicy`, которую ему негде взять, кроме `Workspace`.

**Проверка переезжает в `Patcher._filter_paths`:**

```python
def _filter_paths(self, tool, action_dict):
    for arg_name in tool.path_args:
        path = action_dict.get("arguments", {}).get(arg_name)
        if not path:
            continue
        if is_mcp_path(path):
            continue  # DataModel не фильтруется
        spec = self.policy.for_op(tool.op)
        if not spec.resolve(path):
            return f"filter: {path} blocked for {tool.op}"
    return None
```

**Что удаляется:**

- `FilesystemBackend.filter_check` — логика уходит в `Patcher`.
- `MCPBackend.filter_check` — был no-op.
- `CompositeBackend.filter_check` — делегировал вниз.
- `Backend`-протокол (`core/backend.py`) — метод убирается.
- Тест `test_policy.py` — обновляется под новую форму.

**Multi-root policy** — следующий шаг (не этот). `Policy` в `Session` пока работает с одним ключом на путь; с `WorkspaceBackend` путь `<basename>/<rel>` будет резолвиться через `RootPolicy` в `Workspace`. Это правки в `core/models.py` и в `Patcher`. Отдельная задача.

**State-каталог — захардкоженная политика.** `.patch_applier/` (или новый `state_dir`) всегда RW для внутренних тулов и **никогда** не индексируется. Это не из `workspace.json`, не зависит от корня, не переопределяется. Так уже работает — правило сохраняется. Именно чтобы индексатор не пытался индексировать свои же артефакты (INDEX.md, CODE_INDEX.md, sidecar'ы) и не рекурсировал.

**`.patchignore` / `.mcpignore`** — фильтр видимости, лежат в `state_dir`, применяются в backend'е (не в `Patcher`). Один на workspace, применяется к каждому корню.

## 6. `CompositeBackend` — как сосуществовать

Сегодня:

```
CompositeBackend
  ├── FilesystemBackend (working_dir = project)
  └── MCPBackend (Roblox)
```

С `WorkspaceBackend`:

```
CompositeBackend
  ├── WorkspaceBackend (N FS-roots + state)
  └── MCPBackend (Roblox, как сейчас)
```

`CompositeBackend._owner(path)` уже есть — решает «FS или MCP» через `is_mcp_path`. Минимальное изменение: тип первого суб-бэкенда. `_owner`, `read_many`, `grep_replace_mcp` и прочее — не трогаются, делегируют вниз.

`CompositeBackend.working_dir` убирается вместе с протоколом. Если где-то нужен явный корень — передаётся через аргумент, а не через backend.

## 7. State dir — где что лежит
`state_dir` — каталог, где живут производные файлы. Один на workspace, не на корень:

- **External** (по умолчанию) — `<toolkit_root>/runtime/workspaces/<id>/`.
- **Embedded** — пользователь выбрал (например, внутри своего проекта).

Содержимое:

```
<state>/
  workspace.json
  .patchignore
  .mcpignore
  INDEX.md
  CODE_INDEX.md
  CODE_INDEX_LUA.md
  *.manifest.json
  *.version
  .index_meta.json
  runtime/
```

**Доступ.** Захардкоженная политика: RW для внутренних тулов, никогда не индексируется (см. §5). LLM к этим файлам обращается через спецметоды: `get_index` (индекс), `get_status` (политики, session), `get_status(sections=["indexes"])` (версии). Прямой `read_file` возможен, но не требуется.

**Индексатор пропускает `state_dir` всегда** — независимо от расположения, без `exclude` глобов. Это знание backend'а, не пользователя.

**Индексы** собираются со всех корней по флагам политики. Один набор `INDEX.md` / `CODE_INDEX.md` / `CODE_INDEX_LUA.md`. Путь в индексе — `<basename>/<rel>`.

**Куда пишутся индексы.** Внутренние тулы (`rebuild_index`, `rebuild_code_index`, `rebuild_lua_code_index`) знают `state_dir` из workspace-конфига. `INDEX.md`, `CODE_INDEX.md`, `CODE_INDEX_LUA.md` пишутся туда. Никаких `local_dir` из backend'а — путь берётся из workspace.
## 8. Что НЕ в этом шаге

- **Write.** Ни `write`, ни `delete`, ни `move`, ни `copy`. Все мутирующие методы возвращают `not_supported: write is not implemented in this step`. Включается на следующем шаге, целиком (все корни с `write=true`).
- **Multi-root policy.** `Policy` пока однослойная. Резолв `<basename>/<rel>` через `RootPolicy` — отдельная задача.
- **Индексаторы под multi-root.** `rebuild_*` пока ходят в один корень. Как переделать — в шаге 4.
- **GUI.** Шаг 5.
- **Миграция.** Шаг 6, не делается.
- **Path policy на подпути.** Только корень.

## 9. Открытые вопросы

Все закрыты:

1. `list("")` — список basename'ов (A). Закрыт.
2. `filter_check` — убран из протокола, policy в `Patcher`. Закрыт.
3. «Один write-корень» — снят. Write включается целиком на шаге 4. Закрыт.
4. Абсолютные пути для LLM — запрещены. Внутри утилиты — нужны (GUI). Закрыт.
5. `working_dir` — убран из протокола. Кому нужен `cwd` — `<basename>/rel`; кому индексы — `state/<rel>`. Закрыт.

## 10. Рефакторинг Backend-протокола

Этот шаг включает рефакторинг старого кода (чистота важнее совместимости):

- **`core/backend.py`** — из `Backend`-протокола убрать `filter_check`.
- **`backends/filesystem.py`** — убрать `filter_check` и `working_dir` (из публичного API).
- **`backends/mcp.py`** — убрать `filter_check` (был no-op).
- **`backends/composite.py`** — убрать `filter_check`, `working_dir`.
- **`core/patcher.py`** — `_filter_paths` переписать; проверка policy переезжает сюда.
- **`tools/index.py`** — `RebuildLuaCodeIndexTool` переписать: `local_dir` больше не из `backend.working_dir`, а из `state_dir` workspace-конфига.
- **`tools/shell.py`** — `run_python`: `script` и `cwd` — `<basename>/rel`, проверка «внутри этого корня».
- **Тесты:** `test_policy.py`, `test_live_studio.py`, `test_run_python.py` — обновить под новую форму.

Работа не «в одном патче» — по одному модулю, с прогоном тестов между шагами.

## 11. Порядок работы

1. **Дизайн (этот документ).** — Готово.
2. **Рефакторинг `Backend`-протокола.** Убрать `filter_check`, `working_dir`. Обновить `Patcher`, тесты.
3. **`WorkspaceBackend` read-only.** `open/close/is_alive/read/exists/stat/list`. Резолв путей `<basename>/rel` + `state/<rel>`.
4. **Интеграция в `CompositeBackend`.** Замена `FilesystemBackend` на `WorkspaceBackend` при наличии workspace.
5. **Индексаторы под multi-root.** `rebuild_*` ходят по всем корням, мёржат.
6. **Write (шаг 4 из WORKSPACE.md).** Все корни с `write=true`.
7. **GUI (шаг 5 из WORKSPACE.md).**

Каждый шаг самодостаточен, откатывается.
