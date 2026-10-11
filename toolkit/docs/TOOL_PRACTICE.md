# Практика работы с тулами — заметки сессии

<!-- summary: Наблюдения за одну большую сессию рефактора. Рецепты «задача → тул», обязательные случаи pre-read, разбор неиспользованных тулов. Не заменяет LLM_START — это опыт поверх него. -->
<!-- tags: tools, practice, session-notes -->

## 1. Зачем этот документ

LLM_START описывает тулы **принципиально** (что умеет каждый). Здесь — **практика**: какой тул выбрать для какой задачи, где нужен предварительный read, какие грабли ловятся только на живом материале.

Источник — одна большая сессия (рефакторинг Workspace, ~50 патчей). Наблюдения — не opinion, а следствия конкретных инцидентов.

## 2. Инвентарь: что использовалось

### Часто и без трения

| Тул | Сколько раз | Роль |
|---|---|---|
| `run_python` | 40+ | smoke, тесты, git-обёртка, recon-скрипты |
| `read_file` | 50+ | почти каждое действие начиналось с него |
| `replace_in_file` | 40+ | точечные однострочные/двустрочные правки |
| `overwrite_file` | 10 | переписывание файла целиком |
| `grep` | 8 | карта правок перед крупным патчем |
| `replace_unit` | 15 | замена функции/класса/секции |
| `insert_at_anchor` | 12 | вставка до/после маркера |
| `create_file` | 8 | новые модули |
| `delete_file` | 5 | удаление старых модулей |
| `replace_between` | 6 | удаление диапазона между маркерами |
| `list_units` | 4 | карта секций md / символов py |
| `read_unit` | 3 | чтение секции md |
| `get_status` | 5 | проверка сессии |
| `set_annotation` | 2 | обновление summary секции |
| `symbol_graph` | 2 | проверка графа Lua vs Python |
| `find_usages` | 1 | один reverse-граф для Lua |

### Ни разу не использовались

| Тул | Почему |
|---|---|
| `replace_range` | Не возникло задачи, где он лучше остальных |
| `replace_block` | Замену метода делал через `replace_between` / `overwrite` — следовало использовать этот |
| `delete_block` | Удаление метода делал через `replace_between` — следовало использовать этот |
| `insert_block` | Новый statement в функцию вставлял через `replace_in_file` |
| `copy_unit` | Не копировал unit'ы между файлами |
| `move_file` / `copy_file` | Не перемещал/копировал файлы (git делает это) |
| `file_stat` | Размеры файлов видел через `read_file`/`list_files` |
| `replace_section` / `set_summary` / `verify_section` | **Устаревшие** — заменены `replace_unit`/`set_annotation` |
| `list_symbols` / `read_symbol` / `replace_symbol*` / `delete_symbol` / `insert_symbol` / `move_symbol` / `replace_statement` | **Устаревшие** — заменены unit-моделью |
| `find_symbol` | Не искал символ по имени — знал qualname из read_file |
| `grep_mcp` / `grep_replace_mcp` / `list_symbols_lua` / `read_symbol_lua` / `replace_function_lua` | Roblox-сторона не правила в этой сессии |
| Native MCP tools (кроме `list_roblox_studios`, `search_game_tree` в recon) | Не было задач с DataModel |

**Главный вывод по неиспользованным:** unit-write тулы (`replace_block` / `delete_block` / `insert_block`) — **есть, работают, но я их не применил** потому что думал старыми категориями. Метод удалить → `replace_between`, statement вставить → `replace_in_file`. Хотя semantic-wise правильнее unit-тул. Это не пробел тулсета, а привычка.

## 3. Рецепты: задача → тул

Ниже — конкретные сценарии из сессии, с пометкой «работало» / «проблема».

### Заменить тело функции (Python)

```
read_unit(qualname, part="body")  →  replace_unit(qualname, part="body", new_text)
```

**Работало:** замена `_build` в `reader.py`, `_apply_one` в `patcher.py` — 100% попаданий. `part="body"` сохраняет `def` и docstring.

**Проблема:** если функция большая, `read_unit` тоже большой. Можно `read_unit(part="head,annotation")` — если уверен, что тело не потеряешь.

### Удалить метод из класса

```
read_unit(qualname="Class.method")  →  list_units(file)  →  delete_block(address=Class, block=N)
```

**Не делал так** — использовал `replace_between` от метода до следующего метода. Сработало, но: нужны два anchor'а, оба должны быть уникальны. `delete_block` был бы одним вызовом.

**Когда всё же `replace_between`:** если между методами есть комментарий, который тоже надо съесть, а `delete_block` его сохранит (block исключает комментарий сверху).

### Заменить сигнатуру функции

```
replace_unit(qualname, part="head", new_text="def f(a, b, c):")
```

Работало. Не путать с `part="body"` — тело остаётся на месте, меняется только объявление.

### Переписать файл целиком

```
overwrite_file(file_path, file_content=<весь файл>)
```

**Работало всегда, когда знал полный текст.** Использовал для `models.py`, `workspace.py` × 2, `projects.py`, `cli.py`, `mcpignore.py`. Единственный тул без граблей.

**Когда НЕ использовать:** если правишь 3 строки в 500-строчном файле — `overwrite_file` заставит тебя прочитать всё и переписать, риск опечатки в неизменённых частях выше, чем 3 точных `replace_in_file`.

### Вставить строку/блок в файл

```
insert_at_anchor(anchor="...", position="after", new_content="\n<содержимое>")
```

**Внимание:** `new_content` вставляется **как есть**. Если первая строка `new_content` начинается с буквы, а anchor — тоже с буквы (без `\n` в конце), они склеятся:

```
# Строка 1: from .model import Block, Part
# Вставили "from .paths import x" как after
# Результат: from .model import Block, Partfrom .paths import x
```

**Правило:** всегда начинай `new_content` с `\n` (или заканчивай anchor на `\n`). Дважды наступал.

### Удалить диапазон между маркерами

```
replace_between(start_anchor="# --- A ---", end_anchor="# --- B ---", new_content="")
```

**Работало:** удаление `filter_check` из `filesystem.py`, `save_policy` из `app.py`, дерева политики из `app.py` (682 строки).

**Проблемы:**

- Anchor должен быть **точным**. Если anchor — `@dataclass\nclass Foo:` с `\n` внутри, `replace_between` **не нормализует EOL**. Файл может быть CRLF, а anchor — LF; промах.
- Односстрочные anchor'ы без EOL (`def foo():`) — работают 100%.

**Правило:** для anchor'ов без `\n` внутри — можно. Со `\n` — использовать `read_file` + `replace_in_file` или `overwrite_file`.

### Заменить участок по точной строке

```
read_file → скопировать точную строку → replace_in_file(search=<скопированная>, replace=...)
```

**Работало 100%, когда копировал строку из вывода.** Падало 3 раза, когда набирал руками — пробелы, CRLF, trailing spaces.

**Правило:** **никогда** не набирать `search` руками. Только копирование из `read_file`.

### Точечное дополнение `__init__.py`

```
replace_in_file(search='"RootPolicy",', replace='"PathPolicy", "RootPolicy",')
```

Двухстрочные правки без контекста — быстро, работает. Но если фраза встречается несколько раз — `occurrence` или контекст.

### Прогон «всё ли импортируется»

```python
run_python(script="toolkit/code/manual/_smoke_imports.py")
```

Скрипт-однострочник, печатает `[OK]` / `[FAIL]` для каждого модуля. Позволяет **не запускать GUI** после каждой волны правок. Сэкономил десятки рестартов.

### Прогон теста

```python
run_python(script="toolkit/code/toolkit/tests/test_X.py")
```

Каждый тест — самодостаточный скрипт с `main()`. Печатает `[OK]` / `[FAIL]` построчно. Единственный способ поймать регрессии до GUI.

### Git-чекпоинт

```python
run_python(script="toolkit/code/manual/_git.py", args=["commit", "<msg>"])
```

`_git.py` — обёртка над git. `commit`, `log`, `status`, `reset-hard`, `show-file`. Использую `commit` перед каждой большой волной; `reset-hard HEAD~1` при катастрофе (не пригодилось, но держу в резерве).

## 4. Когда предварительное чтение **обязательно**

Ниже — конкретные случаи, где я пытался править без `read_file` и получил ошибку.

### Перед `replace_in_file` — обязательно

**Симптом:** `no_match`, `search not found`.

**Причина:** `search` набран руками, пробелы/EOL не совпадают с файлом.

**Правило:** `read_file(search_target_range)` → скопировать **точную** строку из numbered repr → `replace_in_file`.

### Перед `replace_between` — обязательно

**Симптом:** `start_anchor не найден`.

**Причина:** anchor содержит `\n` (многострочный) или EOL другой (CRLF vs LF).

**Правило:** `read_file` весь регион → проверить, что оба anchor'а уникальны и **не содержат `\n`** → тогда `replace_between`. Иначе — `replace_in_file` по точной границе или `overwrite_file`.

### Перед `insert_at_anchor` — обязательно

**Симптом:** сломанный синтаксис файла (склейка строк).

**Причина:** `new_content` не начинается с `\n`, anchor не заканчивается `\n` — склеивается с соседом.

**Правило:** `read_file` строку anchor'а → убедиться, что `\n` в `new_content` есть → `insert_at_anchor`.

### Перед `replace_unit` — **обязательно**

**Симптом:** упавший файл (съедены соседние unit'ы, off-by-one в границах).

**Причина:** до фиксов `adapter_md` границы `body` включали следующий заголовок. Сейчас исправлено, но семантика `part="body"` для **секций с подсекциями** — body включает подсекции.

**Правило:** `list_units(file)` **всегда** перед `replace_unit` на `.md` — увидеть, есть ли подсекции. Если есть и хочешь заменить только «свой» текст — `part="own_body"` (когда появится) или `replace_between` по точным маркерам.

### Перед `overwrite_file` — **обязательно**

**Симптом:** потеря содержимого.

**Причина:** `overwrite_file` не читает старое, пишет новое целиком.

**Правило:** `read_file(escape="none", numbered=false)` → весь файл → вычитать → сохранить как план → `overwrite_file`.

### Перед **любым** write в `.py` — **желательно**

Проверить `list_units(file)` — увидеть текущие символы. Если функция, которую ты правишь, называется не так, как ты помнишь — падение будет до записи (хорошо) или после (плохо, если меняешь несколько тулов подряд).

## 5. Что работало хорошо

### `read_file` со всеми осями

- `numbered=true` (дефолт) — навигация.
- `escape="none"` — читать целиком без repr, для понимания.
- `escape="blob"` — точные байты для anchor'ов.
- `start_line`/`end_line` — узкие окна вокруг правки.

Переключение между осями — быстро и без ошибок.

### `grep` перед большой волной

`grep(pattern="Policy|RootPolicy", directory="toolkit/code/toolkit", file_glob="*.py")` — 155 совпадений — полная карта правок. Это превратило хаос «где ещё лежит старая модель» в один проход. Без grep — десятки blind-патчей.

### `list_units` на `.md` с подсекциями

Показал, что `## 2. Модель` имеет `### Unit`, `### Границы unit`, `### Module как unit`. Это спасло от «replace_unit part=body съест подсекции» — увидел до правки.

### `run_python` с логикой в скрипте

Каждый recon/smoke — маленький `.py` в `manual/`. Скрипты печатают структурированный отчёт, не гадают. `run_python` даёт stdout полностью (без обрезки на типичных размерах).

## 6. Что работало плохо

### `insert_at_anchor` без `\n` — сломал GUI

**Инцидент:** Вставил `from ...core.paths import is_mcp_path` после `from .model import Block, Part, Unit, UnitKind` без `\n`. Результат — склейка, `SyntaxError`, GUI не стартовал.

**Мораль:** `<tool>` `insert_at_anchor` **доверяет** `new_content` целиком. Не добавляет границы. Это ответственность вызывающего. **Всегда** `\n` в начале `new_content` — после этого инцидента ни одного промаха.

### `replace_between` с `\n` в anchor'е

**Инцидент:** Дважды `replace_between` не находил anchor `@dataclass\nclass FilterSpec:`. Файл CRLF, anchor LF, или наоборот — матч по байтам, не по нормализованному тексту.

**Мораль:** anchor'ы без `\n` внутри. Или полный `overwrite_file`.

### `replace_unit §2 body` съел соседей

**Инцидент (до фикса):** `replace_unit` на секции md с ошибкой off-by-one в `adapter_md` включал следующий заголовок. §3, §5, §7, §10 исчезли.

**Мораль:** unit-модель для md — сначала `list_units`. И семантика `body` на секции с подсекциями неочевидна.

### JSON-эскейпинг `"""` в `create_file`

**Инцидент:** Первая строка `mcpignore.py` была `"` вместо `"""`. Создалось, но импорт падал.

**Мораль:** при создании `.py` через `create_file` — двойная проверка кавычек/эскейпов. Если сомневаешься — создать пустой, потом `replace_in_file`.

### `replace_unit` для удаления не работает

**Инцидент:** `replace_unit(qualname="Class.method", new_text="")` → `result_missing_symbol`, файл не тронут.

**Мораль:** это **фича** (защита), но неочевидная. Для удаления — `delete_block` (метод как блок в классе) или `replace_between`.

## 7. Что не использовалось и почему

### Unit-write тулы (`replace_block`, `delete_block`, `insert_block`)

Использовал бы вместо них `replace_between` / `replace_in_file` из привычки к текстовым тулам. Каждый раз это работало, но требовало 2 anchor'а или точных строк. `delete_block(Class, block=N)` или `insert_block(qualname, position="start")` были бы одним вызовом без угадывания.

**Вывод:** не пробел тулсета, а моя нерешительность. В следующей сессии — сознательно попробовать.

### `find_symbol`

Не искал символ по имени — знал qualname из `read_file`. Если бы стартовая позиция была «найти функцию X», без индекса — использовал бы.

**Когда использовать:** когда файл неизвестен, а имя символа известно. `find_symbol(query="parse_patches")` → путь + L-диапазон за один вызов.

### `symbol_graph`

Дважды: `Expectation.new` (Lua, пусто — модульный only) и `Patcher._apply_one` (Python, 2 callees + 1 caller + 4 unresolved). Тест на одном символе.

**Когда использовать:** диагностика «кто ещё сломается, если я поменяю X». В этой сессии я просто делал grep по имени — работало, но без учёта графа.

### `copy_unit`

Не копировал целые функции между файлами. Если бы копировал `PathPolicy` из прототипа в боевой модуль — использовал бы.

### `move_file` / `copy_file`

Файлы перемещаю через git (переименования в коммите). `move_file` из тулсета — для runtime-задач, не для рефактора.

### `replace_range`

Не возникло. Замены по номерам строк — плохая практика (сам LLM_START это говорит), а `replace_in_file` / `replace_unit` / `overwrite_file` покрывают.

### MCP-специфичные (`grep_mcp`, `grep_replace_mcp`, native tools)

Roblox-сторона не правила в этой сессии. Native — только `list_roblox_studios`, `search_game_tree` в самом начале, для recon.

## 8. Предложения по улучшению тулов

По убыванию приоритета — из реальных инцидентов.

### P1: `insert_at_anchor` — добавлять `\n`

Если `new_content` не начинается с `\n` и anchor не заканчивается `\n` — вставить один `\n`. Или вернуть `error_code="needs_newline"` с явным сообщением «добавь `\n`». Сейчас склеивает молча.

### P1: `replace_between` — нормализовать EOL anchor'ов

Матчить `\r\n` и `\n` одинаково. Реализация: перед матчингом `text.replace("\r\n", "\n")` для сравнения, но позиции — по оригиналу. Уберёт 90% промахов.

### ✅ P2 (закрыто): `replace_in_file` — tier-2 tolerance + tier-3 диагностика

Реализовано в следующей сессии. Итог: три tier'а — byte-exact (как Ctrl+F), trailing-whitespace tolerance (indent не трогается), no-match с top-3 похожих строк и маркерами `␣ ⇥ ⏎`. Плюс `regex: true` для паттернов с `\1`-backrefs. Тесты `test_replace_in_file.py` — 25/25.

### P2: `create_file` / `overwrite_file` — syntax check

Для `.py` — `ast.parse(content)`. Для `.json` — `json.loads(content)`. Ошибка с `error_code="syntax_error"`, файл не создан. Спасает от JSON-escape промахов.

### P2: `replace_unit` для md — `part="own_body"`

Сейчас `part="body"` включает подсекции. Добавить `part="own_body"` — только текст секции до первой `###`-подсекции. Либо явное `part="body", with_children=false`.

### P3: `replace_unit` с пустым `new_text` — явный error_code

Сейчас `result_missing_symbol` (сбивает). Лучше `empty_input_use_delete_block` с инструкцией. Или отдельный `delete_unit`.

### P3: `get_status` — показывать roots для WorkspaceBackend

Сейчас `project: PatchApplier`. Можно `project: PatchApplier [toolkit]` — basename'ы корней. Помогает быстро понять «в каком workspace я».

### P3: LLM_START cheat-sheet «задача → тул»

Раздел в LLM_START: 10-15 типовых задач с recommended tool path. Не заменяет описание, но ускоряет выбор.

## 9. Общий вывод

Тулсет **работает**. Большинство операций — без трения. Проблемы — не в тулах, а в:

1. **Моих привычках.** Текстовые тулы вместо unit-write. `replace_between` вместо `delete_block`.
2. **Мелких footgun'ах** (`insert_at_anchor` без `\n`, `replace_between` с EOL). Каждый — 5-15 минут сессии.
3. **Отсутствии cheat-sheet.** Выбор тула под задачу — думал, а не знал.

Если исправить P1 (два мелких фикса) и добавить cheat-sheet — следующая сессия пойдёт заметно ровнее при том же наборе тулов.
