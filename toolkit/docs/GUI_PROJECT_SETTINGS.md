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

Одна строка: `Entry` со значением `workspace.name`. Редактируется, сохраняется через `projects.rename_project`.

**Не путь.** Путь проекта — свойство сессии, не проекта. Он виден в главном окне (метка под логом) и в заголовке окна настроек серым.

### 2.2. Каталоги (roots) — центральный блок

**Табы по root'ам.** Один root = один таб. Заголовок таба = basename root'а.

**Внутри таба:**

- **Дерево каталогов** root'а. Только каталоги, без файлов (см. §3). У каждого каталога — пять флагов `R / W / Id / Ip / Il` (как в старом дереве политики, но 5 вместо 3). Клик по флагу циклит значение: `·` (inherit) → `+` (allow) → `−` (deny) → `·`. Shift+клик — на всё поддерево.
- **Строка `[root]`** — дефолт root'а (`overrides["."]`). Действует на всё, что не переопределено ниже.
- **Скрытые каталоги** (`.`-prefixed, `.patchignore`-скрытые) — не показываются по галке «show hidden» внизу.

**Рядом с табами:** кнопки `Add root…` и `Remove root` (удаляет активный root). Добавление вызывает `filedialog`, валидация через `projects.add_root` (уникальность basename, недопустимость вложенности, запрет имён Roblox-сервисов).

### 2.3. Исключения (exceptions)

Две кнопки, обе открывают небольшой редактор (listbox + add/remove + reset-to-default):

- **`.patchignore`** — правила видимости FS.
- **`.mcpignore`** — правила видимости MCP (активна только при `luau: mcp`).

Оба файла лежат в `state_dir` проекта. Кнопка показывает `<name>: N` (количество правил).

### 2.4. Источники и runtime

- **Index docs / python / lua** — три чекбокса. `lua` disabled если MCP выключен.
- **MCP** — чекбокс «включить MCP-бэкенд». При включении активны native_tools и luau-mode.
- **Luau mode** — radio: `mcp` / `rojo`.
- **Exec** — чекбокс «разрешить run_python».

Эти параметры живут в `.patch_applier.json` (tool-wide) и `<project>/.patch_applier/config.json` (per-project), но редактируются в этом окне без прямого доступа к JSON.

### 2.5. Кнопки

`OK` — применить (rename + add/remove roots + policy + исключения + toggles), перезапустить сессию.
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

**Удалить.** Один вход: `File → Project settings…`.

Workflow проекта: пользователь создаёт проект, задаёт настройки, дальше в них не заходит в 90% случаев. Настройки — отдельное окно, которое открывается осознанно. На экране — минимум того, что нужно постоянно (Выполнить, Повторить, лог, статус); периодическое — за раскрывающейся панелью; разовое — за окном.

Согласовано.

### 4a. Уточнение: что где живёт

| Данные | Где | Кто пишет |
|---|---|---|
| Путь к папке проекта | `recent.json` | GUI (при открытии) |
| Имя проекта, roots, policy, format | `<project>/.patch_applier/workspace.json` | GUI (это окно) |
| `.patchignore`, `.mcpignore` | `<project>/.patch_applier/` | GUI (редакторы) |
| Backend / index toggles / exec / mcp | `<project>/.patch_applier/config.json` + tool-wide | GUI (это окно) |
| UI-мелочи (если появятся) | `workspace.json`, поле `ui.*` | GUI |

### 5. Порядок записи в `workspace.json`

Сейчас `projects.update_root_policy` пишет только дефолт (`["."]`). Для per-path — нужна новая функция `set_override(folder, root, rel_path, PathPolicy)`. Добавляется по ходу.

## 8. Порядок работы

1. **Дизайн (этот документ).** Согласовать §7.
2. **`runner/gui/tree.py`** — чистая логика, тест.
3. **`runner/gui/tree_view.py`** — Tk-виджет с флагами.
4. **`runner/gui/settings_window.py`** — окно целиком: имя, табы, кнопки, редакторы, toggles.
5. **`app.py`** — подключение: File → Project settings → new window; удаление старой заглушки.
6. **`projects.set_override`** — для per-path.
7. **Проверка end-to-end:** открыть проект, добавить root, переключить флаг, OK, переоткрыть — состояние сохранилось.

Каждый шаг самодостаточен, откатывается.
