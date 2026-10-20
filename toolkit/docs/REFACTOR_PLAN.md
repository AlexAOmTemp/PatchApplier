# Refactor Plan — Visibility, Args, Index

**Статус:** в работе, 2026-10-15
**Триггер:** `get_index` флудит (94 KB на 78 файлов, 26 подсекций в одном `AUDIT.md`);
`tree` не чтит `.patchignore` (`__pycache__` в счётчиках); аргументы тулов расколоты
(`file_path` vs `path` vs `directory` — док §5 расходится с кодом, LLM ошибается вслепую).

## Модель (зафиксирована, менять только явным решением)

Три слоя с разной жёсткостью:

| | `.patchignore` | `scope` | `PathPolicy` |
|---|---|---|---|
| **Адрес** (`read_file`, `stat`, `read_unit`, `list_units`) | нет | нет | да (hard) |
| **Обход** (`tree`, `list_files`, `grep`, `survey_dir`) | да | да (`scoped=true`) | да (hard) |
| **Запись** (`write`, `create`, `delete`, `replace_*`) | да, `force=true` | нет | да (hard) |
| **Индекс** (`rebuild_index`) | да | **нет** (динамика) | да (hard) |

Ключевые правила:

- **`.patchignore` применяется к потомкам корня запроса, не к самому корню.**
  `tree(".git")` открывает `.git`, но `.git/.somethinginner` — скрыт.
- **Адрес ≠ обход.** Явно названный путь — consent, фильтр не применяется.
  `read_file(".git/config")` работает.
- **`force=true`** нужен только на запись в hidden. `PathPolicy` при этом остаётся hard.
- **Индекс** уважает `.patchignore`, `scope` — нет (LLM-динамика не должна влиять на rebuild).
- **`filter=false`** на сканах (`tree`, `list_files`, `survey_dir`, `grep`) — отключает `.patchignore` целиком.
  Отдельно от `scoped=false`.
- **Хардкод скрытий в коде запрещён.** Скрывает только `.patchignore` и `scope`.
  Исключение: `STATE_DIR = .patch_applier` (иначе тулкит сломает сам себя).

### Аргументы (канон)

| Аргумент | Семантика |
|---|---|
| `path` | один путь: файл или каталог (по тулу) |
| `paths` | список: файлы и/или каталоги (ripgrep-модель, смешанный разрешён) |
| `recursive` | только там, где режим осмыслен: `list_files`, `grep`, `grep_replace`, `verify_syntax` |
| ~~`file_path`~~ | → `path` |
| ~~`directory`~~ | → `path` / `paths` |

- **Алиасы не оставляем** — `DECISIONS` §11: обратная совместимость не важна.
- `source_path`/`destination_path`, `source_file`/`target_file`, `manifest_path` — **не трогаем**,
  они про два разных пути, не под правило «один/много».
- **`grep` по ripgrep:** каждый элемент `paths` разбирается по типу: файл → address access;
  каталог → сканом (с `recursive`), с `.patchignore` и `scope`. `directory` удалён.

## Сделано

- **P1 — фундамент трёх слоёв**
  - `config/patchignore.py`: `is_hidden()` (алиас `path_hidden`)
  - `backends/multi_root_fs.py`: `hidden_path` снят с `read`; метод `is_hidden`
  - `backends/multi_domain.py`: `is_hidden` делегирует; `root_dir.py`: → False
  - `core/backend.py`: `is_hidden` в протоколе
  - `core/patcher.py`: `_filter_paths` читает `force`, пропускает `hidden_path` при `force=true`
  - `PatchApplier/.patch_applier/.patchignore`: `@.*` → `.*`

- **P2a — scan-тулы на `is_hidden`**
  - `tools/tree.py`: оба `n.startswith(".")` заменены на `backend.is_hidden(rel)`; футер
    `[N dir(s) hidden by .patchignore; pass filter=false]`; параметр `filter: bool = True`
  - `tools/read.py`: `ListFilesTool`, `SurveyDirTool`, `GrepTool` — `filter=` флаг

- **P2b — `force=true`** проверен smoke: без `force` → `blocked`/`hidden_path`; с `force` → `ok`

- **P3a — `read.py` канон**
  - `ReadFileTool`, `FileExistsTool`, `FileStatTool`: `file_path → path` (декларация, сигнатура, тело)
  - `ListFilesTool`: `directory → path` (вкл. `_list_too_many`)

- **P3b — `GrepTool` ripgrep-модель**
  - `paths: str | list[str] | None`, `recursive: bool = True`
  - смешанный список разрешён: explicit-файлы игнорируют `.patchignore`/scope; каталоги — уважают
  - `directory` удалён

- **P4 — сироты `.patchignore` удалены**
  - `PatchApplier/.patchignore`, `toolkit/code/toolkit/.patchignore` удалены
  - state-файл приведён к порядку: `.*` первым, `!` исключения после (иначе
    `.patchignore` скрывает сам себя — last match wins), добавлен `_reference`

- **P5 — `get_index` overview по умолчанию**
  - `GetIndexTool(..., sections: bool = False)`; `_get_snapshot(..., sections=True)`
  - docs-only: код/csharp/lua уже шли через `_get_structure`
  - overview: одна строка на файл `[N sections]`, без preamble-легенды
  - `sections=true` + `path=` — drill-down в один файл
  - **эффект:** `kind=["docs"], limit=5` — 5 строк вместо ~94 KB

- **`insert_block` — сигнатура**
  - `position: start|end` (границы контейнера) vs `before_anchor`/`after_anchor` (точка отсчёта)
  - взаимоисключающие якоря; `address` = контейнер, anchor = reference point внутри
  - `writer.py:358` дубль `return new_source` убран
  - тест `test_unit_model.py` обновлён

- **BFS в `tree`** ✓
  - `tree.py`: `list`+`pop()` (DFS) → `deque`+`popleft()` (BFS). `max_depth` удалён.
  - Причина: DFS с `max_dirs` вычерпывал первую ветку до дна и врал о структуре
    (`Data` + все подпапки, `Mods` — 23 из 30).
  - Теперь: полный уровень 1, потом уровень 2, и т.д. `max_dirs` режет самый глубокий
    видимый уровень, всё выше — полное.

- **`tree` — BFS по уровням, `max_lines`, `show_files`** ✓
  - `deque`+`popleft` (BFS). `max_dirs`/`max_depth` удалены → `max_lines` (бюджет строк).
  - Рендер: root-line, затем `N0: {каталоги depth 1}{файлы root}`, `N1: {каталоги depth 2}{файлы depth 1}`…
  - `show_files=true` → дефолт `max_lines=100`; внутреннего cap на файлы нет.
  - `filter` применяется и к файлам, и к каталогам (`is_hidden`).

- **`get_status` → секция `layout`** ✓
  - `tree(max_lines=20, show_files=true)` — каталоги + файлы корня одной командой.
  - Причина: `requirements.txt`/`AUDIT.md` — не docs и не code, в индексах не видны.
    Теперь видны с первого хода. `os.scandir` убран (дубль).

- **P10 — единый путь вызова тулов** ✓
  - `core/tool_call.py`: `validate_args` + `call_tool`, `PATCHER_ARGS={"force"}`.
  - `Patcher._validate_args` → тонкая обёртка; главный вызов — `call_tool`.
  - Переведены: `status.py` (`TreeTool`), `symbols/python.py` (2 делегата),
    `presenters/main.py` (`GetStatusTool`).
  - Причина: `status.py` звал `TreeTool().execute(max_dirs=12)` напрямую; после удаления
    `max_dirs` аргумент молча ушёл в `**_`. `get_status.layout` деградировал незаметно.
  - Открыто (P10.1): двойная валидация в `_apply_one` + `call_tool` — дёшево,
    но можно убрать первый вызов.
  - Открыто: `copy.py`, `tests/*` — прямые `.execute()`; тесты трогать не обязательно,
    `copy.py` — да.

- **`binaryornot`** *(в работе)*
  - Установлен (0.6.0, Python 3.14). Проверено: `cp1251 → False`, `utf16 → False`, `png → True`.
  - Добавить в `requirements.txt` (лежит в **корне проекта** `PatchApplier/`, не в `toolkit/`).
  - `matching/binary.py`: `is_binary(head)` с fallback (git-модель) на случай отсутствия.
  - `Backend.read_head(path, 8192)`, применение в `grep`/`grep_replace` (скан) и `read_file`.
  - **Замер:** RimWorld `grep` — 20 с, 14302 файла прочитаны впустую (`.png .dll .cache`).

## Открыто

- **P3c — переименования** ✓ *(закрыто)*
  - `read.py` (5 тулов), `fileops.py` (3 + `move`/`copy` не тронуты),
    `write.py` (7), `unit/tool.py` (9), `symbols/python.py` (9), `xml.py` (12)
  - все `file_path` → `path`; `directory` в `tools/` — ноль
  - `source_file`/`target_file`/`source_path`/`destination_path`/`manifest_path`
    и MCP-домены (`grep_mcp`, `grep_replace_mcp`) — **не тронуты** по решению
  - сноска про временный раскол убрана из §5

- **P6 — док §5** *(частично)*
  - ✓ `list_files(path)`, `grep(paths, recursive)`, `insert_block(before_anchor/after_anchor)`,
    `get_index(sections)`
  - ✓ сноска про временный раскол write/unit (`file_path` до P3c)
  - после P3c — убрать сноску, write/unit → `path`

- **P7 — `[hidden]`-пометка в `tree`**
  - сейчас скрытые каталоги не показываются вовсе (только счётчик в футере)
  - обсуждено: показывать `[hidden]` без обхода. Отложено, не блокирует.

- **P8 — MCP-корни** *(частично)*
  - ✓ `grep_replace` приведён к паритету с `grep`: `paths: str | list[str]`, `recursive`,
    `file_glob`/`exclude_glob`, `filter`, `scoped`, `force`; `directory` удалён.
  - открыто: `grep_mcp`, `grep_replace_mcp` — `directory` = dotted-root (`ReplicatedStorage.X`),
    не FS-путь. Отдельная семантика, решать отдельно.

## Мелкие баги / хвосты

- **P9a — валидация аргументов** ✓
  - `Patcher._validate_args`: неизвестный ключ → `unknown_arg`, обязательный без дефолта →
    `missing_arg`; в сообщении **полный список валидных** аргументов тула.
  - `force` в `_PATCHER_ARGS` (allow-list патчера, не тула).
  - `**_` больше не глотает опечатки. Подтверждено: `grep(directory=...)` → `unknown_arg`,
    `read_file(file_path=...)` → `unknown_arg`.

- **P9b — `grep` без пути** ✓
  - `paths` обязателен, `[]`/`None` → `missing_arg`. Ветка «искать весь воркспейс» удалена.
  - Причина 11–30 с: `grep(directory=...)` уходил в `**_`, `paths=None` → скан всех корней,
    включая `RimWorld` (30k файлов). После фикса — 0.02 с на явном пути.

- **P9c — `force` в списке валидных** *(мелочь)*
  - `force` показывается для всех тулов, включая read-only (`grep`, `read_file`).
    Показывать только когда `op == "write"`.

- **Перф-заметки**
  - `hidden_predicate()` — предзагрузка видимости для циклов (один stat вместо N).
  - Остались: `backend.list()` делает `rglob` без pruning (заходит в `.git`/`__pycache__`,
    потом отбрасывает); `grep` читает файлы целиком без лимита размера. Оба — кандидаты
    на оптимизацию, но 11 с были из-за P9b, не из-за них.
  - `runner/last_patch.json`/`last_output.txt` лежат в проектном дереве и находятся
    собственным grep'ом. Перенести в `.patch_applier/` или в `.patchignore`.
- `runner/last_output.txt`, `runner/last_patch.json` — мусор от сессий, чистить.
- `tools/tree.py`: `_walk_recursive_totals` не инкрементит `hidden_pi` — осознанно
  (тоталы не зависят от порядка), но помнить при доработках.

## Правила работы с этим проектом

- **GUI-рестарт** обязателен после каждого патча модулей, импортированных в живой процесс:
  `tools/*`, `backends/*`, `config/*`, `core/*`, `formats/*`, `indexers/*`, `runner/*`.
  Конфиг `.patchignore` — **не требует** (подхват по mtime).
- Читать актуальное перед правкой (R-READ-1).
- Алиасы не оставлять.
- Diff сверять с задумкой (R-WRITE-1).

## Файлы, затронутые в сессии

```
config/patchignore.py
backends/multi_root_fs.py
backends/multi_domain.py
backends/root_dir.py
core/backend.py
core/patcher.py
tools/tree.py
tools/read.py
tools/unit/writer.py
tools/unit/tool.py
tests/test_unit_model.py
.patch_applier/.patchignore
```

## Порядок, согласованный с пользователем

1. **P5** (индекс) — исходная задача, дешёвая, снимает главный флуд
2. **P4** (сироты) — без рестарта
3. **P6** (док) — честно про временный `file_path`
4. **P3c** — батчами по файлам, без спешки, каждый — с рестартом
5. **P7/P8** — по остаточному принципу
