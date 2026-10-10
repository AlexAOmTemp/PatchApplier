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

**`working_dir` — концепция удаляется, не адаптируется.** В старой модели `project_dir` = `working_dir` = имя проекта = место state. Одно поле играло три роли, потому что проект был один каталог. В новой модели роли разъезжаются:

| Роль | Где живёт |
|---|---|
| Имя проекта | `Workspace.name` |
| Рабочие каталоги | `Workspace.roots` (список) |
| Место для state | `state_dir` (отдельная сущность) |

`working_dir` (единственное число) не может играть роль (2) — каталогов несколько. И не может играть роль (3) — state теперь отдельная сущность. Оставлять его «для совместимости» значит иметь два источника истины, которые рано или поздно разойдутся.

**Уточнение: внутренний корень FS-бэкенда остаётся, публичный `working_dir` уходит.**

`FilesystemBackend` продолжает знать свою директорию — без этого `_resolve` не преобразует `rel` в абсолютный путь. Меняется только видимость: раньше `working_dir` был публичным и к нему лезли `CompositeBackend`, тулы, раннеры; теперь корень — приватная деталь FS-бэкенда, наружу торчит только `WorkspaceBackend.roots`. Резолв не усложняется: каждый FS-бэкенд резолвит относительный путь у себя, `WorkspaceBackend` раздаёт по basename'у (dict-lookup, O(1)).

**Удаляется публичный `working_dir` и его использования:**

- `FilesystemBackend.working_dir` — публичный атрибут; внутри остаётся приватный `_root`.
- `CompositeBackend.working_dir` (property-прокси) — удаляется.
- Тулы, которым нужен «где писать» — берут `state_dir` из `Workspace`.
- Тулы, которым нужен «относительно чего» — работают с явными путями `<basename>/<rel>`.

**Кто заменяет старые использования:**

- `RebuildLuaCodeIndexTool` — `local_dir = state_dir` (из `workspace.json`), не из `backend.working_dir`.
- `run_python` — `cwd`: родитель `script`-файла (для `script=`) либо `state_dir` (для `module=`). Пользователь может указать `cwd` явно — тогда проверка «внутри одного из roots».
- GUI-дерево — вместо одного корня вкладка на каждый `roots[name]`.
- CLI `--working-dir` — принимается, но маппится в первый корень workspace или явно указанный `<basename>`.

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

**State-каталог — захардкоженная политика.**

**Write в state-префикс — всегда разрешён.** `WorkspaceBackend.write/create/delete` делегируют в FS-бэкенд корня только если путь под `<basename>/`. Путь под `.patch_applier/` (state-префикс) идёт в отдельный FS-бэкенд state и разрешён всегда — это нужно индексным тулам (`rebuild_index`, `rebuild_code_index`), которые пишут свои артефакты в state. Cross-root `move` запрещён (`RuntimeError`), cross-root `copy` разрешён (обе стороны локальные). См. `DECISIONS.md §2.5`. `.patch_applier/` (или новый `state_dir`) всегда RW для внутренних тулов и **никогда** не индексируется. Это не из `workspace.json`, не зависит от корня, не переопределяется. Так уже работает — правило сохраняется. Именно чтобы индексатор не пытался индексировать свои же артефакты (INDEX.md, CODE_INDEX.md, sidecar'ы) и не рекурсировал.

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
`state_dir` — папка проекта. Одна, выбрана пользователем при создании. Содержимое:

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

**Индексатор пропускает `state_dir` всегда** — независимо от расположения. Это знание backend'а, не пользователя.

**Индексы** собираются со всех корней по флагам политики. Один набор `INDEX.md` / `CODE_INDEX.md` / `CODE_INDEX_LUA.md`. Путь в индексе — `<basename>/<rel>`.

**Куда пишутся индексы.** В `state_dir`. Внутренние тулы (`rebuild_index`, `rebuild_code_index`, `rebuild_lua_code_index`) знают его из `workspace.json`. Никаких `local_dir` из backend'а.
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

**Backend-протокол и реализации:**

- **`core/backend.py`** — `filter_check` остаётся (см. §5: он делает больше, чем policy-проверку — sandbox, state-dir exemption, patchignore с explicit-override). `working_dir` в протоколе нет и не было.
- **`backends/filesystem.py`** — удалить `working_dir` (атрибут и все использования внутри). `_resolve` берёт абсолютный путь явно, а не через working_dir. Публичный `working_dir` тоже убрать.
- **`backends/composite.py`** — property `working_dir` **фиксится** (не удаляется) на этом шаге: смотрит `_root` (новое) → `working_dir` (legacy) → None. Удаление property переносится на шаг 3, когда `WorkspaceBackend` появится и сможет отдавать корень явно.

**Тулы и раннеры:**

- **`tools/index.py`** — `RebuildLuaCodeIndexTool.execute`: `local_dir` больше не из `backend.working_dir`, а из `state_dir` workspace-конфига. Параметр `local_root` — из `Workspace`, не из backend.
- **`tools/shell.py`** — `run_python`: `script` и `cwd` — явные пути. Проверка «внутри проекта» — «внутри одного из `Workspace.roots`». `cwd` по умолчанию — родитель `script`-файла; для `module=` — `state_dir`.
- **`runner/cli.py`** — `_resolve_working_dir` маппится в первый `Workspace.roots` или явно указанный `<basename>`.
- **`runner/gui/app.py`** — `working_dir` для дерева заменяется на `Workspace.roots` (вкладка на корень, как в `WORKSPACE.md §8`).

**Тесты:**

- `test_policy.py` — `filter_check` остаётся, тест не меняется концептуально (только если сигнатура `_explicitly_allowed` поменяется — не меняется).
- `test_composite_backend.py` — убрать `working_dir` из `FakeBackend`, если используется.
- `test_live_studio.py` — обновить точки, где `working_dir` вызывается.
- `test_run_python.py` — обновить ожидания по `cwd`.

**Что не делаем в этом шаге:** multi-root policy (это шаг 5 в §11). Пока `Policy` в `Session` — плоская, пути проверяются как строки. Резолв `<basename>/rel` → `RootPolicy` — отдельная задача.

Работа не «в одном патче» — по одному модулю, с прогоном тестов между шагами.
## 11. Порядок работы
1. **Дизайн.** ✅ **Готово** (`WORKSPACE.md`, `WORKSPACE_BACKEND.md`).

2. **Удаление `working_dir`.** ✅ **Готово.** `FilesystemBackend.working_dir` → приватный `_root`. `CompositeBackend.working_dir` — chain `_root → working_dir → None`. `RebuildLuaCodeIndexTool` — через chain. Тест `test_working_dir_removed.py` (9/9).

3. **`WorkspaceBackend` read-only.** ✅ **Готово.** `open/close/is_alive/read/exists/stat/list/filter_check`, routing `<basename>/<rel>`, `list("")` → плоский список файлов с префиксами, `list_roots()` → basenames, state-префикс `.patch_applier/`. Тест `test_workspace_backend.py` (29/29).

4. **Интеграция в `CompositeBackend`.** ✅ **Готово.** CLI `_create_backend` + GUI `_build_backend_for_config` строят `WorkspaceBackend` из `workspace.json`. `config.loader.load_workspace(cfg)`. Никакого fallback на старую модель. GUI File menu (New/Open/Recent/Project settings) работает.

5. **Индексаторы под multi-root.** ⚠️ **Формально работает.** `rebuild_*` ходят по `list("")`, который возвращает плоский список с префиксами `<basename>/<rel>`. На одном корне проверено. На двух — только `test_workspace_backend.py`, живого проекта не заводили.

6. **Write (шаг 4 из WORKSPACE.md).** ✅ **Готово.** `WorkspaceBackend.write/create/delete` делегируют в FS-бэкенд корня. Кросс-root `move` запрещён (`RuntimeError`), кросс-root `copy` разрешён через `FilesystemBackend.copy_to`. State-префикс — всегда RW.

7. **GUI (шаг 5 из WORKSPACE.md).** ⚠️ **Частично.** File menu + Project settings (roots, флаги, add/remove, rename) — **готово**. Дерево файлов по корням (7.3) — **открыто**. Редактор per-path overrides — **открыто**.

Плюс отдельно: **P1-фиксы тулов** (`insert_at_anchor` + `\n`, `replace_between` EOL-нормализация) — открыты, см. `TOOL_PRACTICE.md §8`.
