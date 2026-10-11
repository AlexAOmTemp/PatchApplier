# GUI: окно управления проектом

<!-- summary: Отдельное окно Project settings — имя проекта, табы по root'ам (дерево каталогов + пять флагов policy), редакторы .patchignore/.mcpignore, MCP и exec toggle. Заменяет текущую заглушку и старый open_settings_dialog. Read-only на первом шаге. -->
<!-- tags: gui, project-settings, design, workspace -->

## 1. Зачем

Сейчас в GUI две разных заглушки и устаревший диалог:

- **File → Project settings…** — маленькая таблица roots (имя, путь, 5 флагов). Работает, но не покрывает остального.
- **⚙ Настройки** (правый panel) — заглушка «edit .patch_applier.json». Раньше это был большой диалог с путём проекта, backend, MCP, exec, .patchignore и деревом политики.

Оба надо объединить в **одно окно «Project settings»**, которое управляет проектом целиком. Открывается из `File → Project settings…`.

## 2. Что в окне
### 2.1. Имя проекта (top)

Одна строка: `Entry` со значением `workspace.name`. Редактируется, сохраняется при `OK`. Правый клик → «Копировать»; Ctrl+C работает в любой раскладке.

**Не путь.** Путь проекта — свойство сессии, не проекта. Виден в заголовке окна настроек серым.

### 2.2. Порядок секций

Сверху вниз, по логике «выбрал с чем работаю → убрал шум → настроил политику»:

1. **Sources** — что в проекте.
2. **Roots** — какие каталоги и какая политика внутри.

Visibility-редакторы живут внутри **Sources**, у соответствующих источников — не отдельным блоком. Roots **скрывается целиком**, если ни Documentation, ни Python не включены (нет FS-режимов — нечего настраивать).

### 2.3. Sources

Пять строк, каждая — про свой источник:

- **Documentation (.md)** — чекбокс. Справа — кнопка `Hide paths…` и счётчик правил `.patchignore`.
- **Python (.py)** — чекбокс. Под ним, с отступом, **Allow Python scripts (run_python)** — серая и выключенная, если Python off. Hint `(requires Python)`.
- **MCP (Roblox bridge: …)** — чекбокс. Label меняется по Luau source: `scene + code` при MCP-режиме, `scene only` при Rojo. Справа — кнопка `Hide modules…` и счётчик `.mcpignore`.
- **Lua files on disk (.luau)** — чекбокс.
- **Luau source:** radio `MCP` / `Rojo`. Правило: ни один источник — radio disabled; только MCP — forced `mcp`; только Rojo — forced `rojo`; оба — оба radio активны, дефолт **Rojo**.

Кнопки visibility **серые**, когда соответствующий источник закрыт:
- `Hide paths…` — серая если нет ни Documentation, ни Python.
- `Hide modules…` — серая если MCP off или Luau source = Rojo.

### 2.4. Roots

**Табы по root'ам.** Один root = один таб. Заголовок таба = basename.

**Внутри таба:**

- **Дерево каталогов** root'а. Только каталоги, без файлов (см. §3). Соединительные глифы `├── └── │` показывают иерархию.
- **Виртуальная строка `[root]`** сверху — дефолт root'а (`overrides["."]`). На неё можно задать политику на весь корень.
- **Пять флагов** `R / W / Id / Ip / Il`. **Колонки реактивны к Sources:** `R`, `W` — всегда; `Id` — при Documentation; `Ip` — при Python; `Il` — при Lua-on-disk (Rojo). Отключённый источник — колонка исчезает, override не удаляется и вернётся при включении.
- **Клик по флагу** — три состояния `·` / `+` / `−`. Из `·` → создать override (инверсия effective), из `+` ↔ `−` → флип одного флага. Возврат в `·` — не в этой итерации.
- **Скрытые строки** (`.`-prefixed, `.patchignore`) — видимы только при галке «Show hidden», и у них **все пять флагов жёстко `−`** — `.patchignore` = hard deny, override не открывает.

**Под табами:** `Add root…`, `Remove root`, `Show hidden`, короткая легенда про `R/W/Id/Ip/Il` и `· + −`.

Добавление root'а — через `filedialog`, валидация `projects.add_root` (уникальность basename, недопустимость вложенности, запрет имён Roblox-сервисов).

### 2.5. Ignore-редакторы

Один модал на два файла. Открывается из `Hide paths…` и `Hide modules…`. Внутри — listbox, add/remove, reset-to-default, open-all.

- **Hide paths** правит `.patchignore` — правила видимости FS.
- **Hide modules** правит `.mcpignore` — правила видимости Roblox-модулей.

Оба файла лежат в `state_dir` проекта. Счётчик правил обновляется после закрытия модала.

### 2.6. Кнопки

`OK` — сохранить всё: `workspace.json` (имя, roots, policy, overrides) + `CONFIG` (источники, MCP, exec), перезапустить сессию.
`Cancel` — закрыть без изменений.
## 3. Только каталоги, без файлов

**Решение:** дерево показывает **только каталоги**. Файлы не показываются никогда.

**Почему:**

- **Наследование policy.** `PathPolicy` на каталоге действует на всё поддерево. Пользователь ставит «выключить `docs/generated`» один раз, а не для 200 файлов. Per-file управление — вырожденный случай, реального сценария нет.
- **Шум.** Каталог с 1000 файлов невозможно просматривать без полного file-browser (виртуализация, поиск, фильтры). Это отдельная большая задача.
- **Так было раньше.** Старое дерево в `open_settings_dialog` показывало только каталоги и работало.

**Глубина** — 3 (`max_depth=3`): видно до `toolkit/code/toolkit/tools/`, не до `manual/unit_proto/`. Фиксировано.

**Данные** — `loader.scan_subdirs(root_path, max_depth=3, patterns=.patchignore, show_hidden)`.

## 4. Что **не** в этом окне

- **Дерево файлов** (не каталогов) — принципиально нет.
- **Показ содержимого файла.** Нет.
- **Открытие в редакторе.** Нет.
- **MCP-сторона** (`ReplicatedStorage.X.Y`) — своя нотация, отдельная логика. Только `.patchignore` и `.mcpignore` как текстовые редакторы.
- **Backend** — не показывается явно; выводится из md/py/mcp чекбоксов, как раньше.

## 5. Модули

**`runner/gui/settings_window.py`** — окно целиком. Открывается из `app.py` через `open_project_settings()`.

**`runner/gui/tree.py`** — чистая логика, без Tk:

```python
def build_tree(paths: list[tuple[str, bool]]) -> list[dict]:
    """[(rel_path, is_hidden)] → nested tree dicts.

    [{'name': 'code', 'hidden': False, 'children': [...]}]
    """

def filter_hidden(tree: list[dict]) -> list[dict]: ...
```

**`runner/gui/tree_view.py`** — Tk-виджет дерева с флагами:

```python
class PolicyTree(tk.Frame):
    """Scrollable list of directories with five flag cells per row.

    Click cycles · → + → − → ·. Shift+click applies to subtree.
    """
    def __init__(self, parent, overrides: dict[str, PathPolicy]): ...
    def render(self, paths: list[tuple[str, bool]]) -> None: ...
    def get_overrides(self) -> dict[str, PathPolicy]: ...
```

Виджет — переработка старого `_make_view`/`_make_row`/`_cycle` из удалённого `open_settings_dialog`, но с 5 флагами и `PathPolicy` (dict вместо ролей).

**`app.py`** — `open_settings_dialog` заглушка удаляется; `File → Project settings` открывает новое окно; кнопка ⚙ в правом панели либо удаляется, либо тоже открывает это окно.

## 6. Как читает данные

Для активного таба (root):

```python
ws = projects.load_workspace(project_dir)  # Workspace
root = ws.roots[basename]
paths = loader.scan_subdirs(root.path, max_depth=3, patterns=..., show_hidden=...)
policy = root.overrides  # dict[str, PathPolicy]
```

Дерево строится из `paths`, флаги — из `overrides`. При сохранении — `projects.update_root_policy` для `["."]` или набор `overrides` пишется в `workspace.json`.

**`.patchignore` / `.mcpignore`** — читаются и пишутся напрямую (как в старом `open_pi_editor`).

**MCP / Exec** — через `CONFIG` (per-project overlay).

## 7. Открытые вопросы

### 1. Где живёт state активного таба

**Не храним.** По алфавиту корней — первая вкладка. Согласовано.

Если в будущем понадобится — хранить **в `workspace.json`** (`ui.active_root`), а не в `CONFIG` и не в `recent.json`. Обоснование: это свойство проекта, при переключении между проектами должно восстанавливаться само. `recent.json` — только путь к папке проекта, туда UI-мелочи не пишем.

### 2. Автообновление дерева

**Не авто.** Обновление:
- при открытии окна,
- при переключении таба (если данные разошлись — не должно),
- по кнопке `↻` в заголовке таба.

Согласовано.

### 3. Клик на каталог (не на флаг)

**Ничего.** Только просмотр. Двойной клик — тоже ничего. Копирование пути — если попросят, отдельным шагом.

Согласовано.

### 4. Что делать с кнопкой ⚙ в правом панели

**✅ Сделано.** Кнопка ⚙ удалена из правого panel. Один вход: `File → Project settings…`.

Workflow проекта: пользователь создаёт проект, задаёт настройки, дальше в них не заходит в 90% случаев. Настройки — отдельное окно, которое открывается осознанно. На экране — минимум того, что нужно постоянно (Выполнить, Повторить, лог, статус); периодическое — за раскрывающейся панелью; разовое — за окном.

### 4a. Уточнение: что где живёт

| Данные | Где | Кто пишет |
|---|---|---|
| Путь к папке проекта | `recent.json` | GUI (при открытии) |
| Имя проекта, roots, policy, format | `<project>/.patch_applier/workspace.json` | GUI (это окно) |
| `.patchignore`, `.mcpignore` | `<project>/.patch_applier/` | GUI (редакторы) |
| Backend / index toggles / exec / mcp | `<project>/.patch_applier/config.json` + tool-wide | GUI (это окно) |
| UI-мелочи (если появятся) | `workspace.json`, поле `ui.*` | GUI |

### 5. Порядок записи в `workspace.json`

**✅ Закрыто.** `save_workspace(project_dir, w, state_subdir)` пишет весь `Workspace` целиком, включая все per-path `overrides`. Отдельный `set_override` не нужен: `PolicyTree` мутирует `root.overrides` in-place, `OK` вызывает `save_workspace`. Реактивные колонки не удаляют overrides при скрытии — они перерисовывают представление, а данные остаются.

## 8. Порядок работы
1. **Дизайн (этот документ).** ✅
2. **`runner/gui/tree.py`** — чистая логика, юнит-тесты (26/26). ✅
3. **`runner/gui/tree_view.py`** — Tk-виджет, тесты 19/19. ✅
4. **`runner/gui/settings_window.py`** — окно целиком. ✅
5. **`app.py`** — подключение, удаление старой заглушки и кнопки ⚙. ✅
6. **`projects.set_override`** — не нужен, `save_workspace` сохраняет всё. ✅
7. **`projects` + `app` — подключение roots в `get_status`.** ✅ (roots line в `_render_session`)
8. **Проверка end-to-end** — визуально подтверждено пользователем.

**Осталось открытым:**
- `.mcpignore` редактор существует, но реально не влияет на MCP-индекс (см. `WORKSPACE_BACKEND.md` / `lua_runner.py`) — фильтр работает, потому что `mcpignore.path_hidden` вызывается в `build_lua_index` через `project_dir`. Проверено косвенно.
- Ctrl+клик / Shift+клик на поддерево — не в этой итерации.
