# Patch Applier — стартовая инструкция для LLM
<!-- pa: suppress no-summary -->

## 1. Что это
Patch Applier — правка проекта JSON-патчами. Один ответ = список действий (чтения и правки). Работает с docs, Python, C#, Luau-кодом и Roblox-сценой — что включено, см. `get_status` внизу (блок `## Session`).

## 2. Приоритеты
- Этот документ перебивает блоки `# Дополнение:`
- Унифицированный тул перебивает нативный MCP
- `blocked` ≠ `error`: политика/песочница vs transient

## 3. Правила

**Формат (R-FMT)**
- **R-FMT-1** — один фенс на ответ, внутри несколько JSON-массивов подряд
- **R-FMT-2** — у каждого действия уникальный `id` (по нему сопоставляешь с ответом)
- **R-FMT-3** — группы парсятся независимо; ошибка в одной не рушит остальные

**Пути (R-PATH)**
- **R-PATH-1** — путь всегда начинается с имени корня (`PatchAppliers/...`, `RimWorld/...`); не относительный от cwd и не bare-имя. Корни — в `## Session` (`roots:`)

**Правка (R-UNIT)**
- **R-UNIT-1** — `.py`/`.lua`/`.luau`/`.md` — unit-тулами (`replace_unit`/`insert_block`), не текстом
- **R-UNIT-2** — `replace_in_file`/`replace_range`/`replace_between`/`insert_at_anchor` — только если unit-модель не адресует (комментарии между unit'ами, отдельные строки, fenced-код)
- **R-UNIT-3** — `replace_range` — снизу вверх и до других write на тот же файл

**Безопасность (R-SAFE)**
- **R-SAFE-1** — `blocked` не retry: это политика, не transient
- **R-SAFE-2** — `not_found`/`ambiguous` → читать индекс/unit, не гадать
- **R-SAFE-3** — скрытое = закрытое (`.patchignore`, dotdirs, `.patch_applier/`)

**Scope (R-SCOPE)**
- **R-SCOPE-1** — `get_status` показывает текущий scope, если задан; прочитай до первого обзорного запроса
- **R-SCOPE-2** — обзорные тулы (`get_index`, `tree`, `grep`, `list_files`, `survey_dir`, `find_*`) соблюдают scope; `read_file`/`paths=[...]`/`scoped=false` обходят
- **R-SCOPE-3** — расширить/сузить: `include`/`exclude`; сбросить: `clear_scope`

**Чтение (R-READ)**
- **R-READ-1** — перед правкой прочитать актуальное
- **R-READ-2** — файлы >32 KB — секциями/unit'ами, не целиком

**После write (R-WRITE)**
- **R-WRITE-1** — diff честен, но не знает замысла; ты знаешь — сверь diff с задумкой

## 4. Старт сессии
1. `get_status` — что включено и какой scope задан (обычно приложен внизу)
2. `get_index(kind=["docs","code"])` (или с `csharp`/`lua`) — что есть
3. Читать → править → сверять diff с задумкой
4. Неясно — спросить, не гадать

## 5. Тулсет
`?` — опционально, `|` — одно из. Полные схемы и редкие аргументы — `REF_TOOLS.md`.

**Чтение**
- `read_file(path, [section_number|section_title|start_line+end_line], max_bytes?, numbered?, escape?)`
- `read_unit(path, address{qualname|title_match}, [part|block], max_bytes?)`
- `list_units(path)` · `file_stat(path)` · `file_exists(path)`
- `list_files(directory, glob?, show_size?, recursive?, show_hidden?, scoped?)`
- `survey_dir(path, ext?, top?, scoped?)` · `tree(path, max_dirs?, max_types?, max_depth?, scoped?)`
- `grep(pattern, [paths[]|directory+file_glob], regex?, ignore_case?, before?, after?, max_results?, scoped?)`
- `grep_mcp(pattern, directory, ignore_case?, before?, after?, max_results?)`

**Unit**
- `replace_unit(path, address, [part|block], new_text)`
- `insert_block(path, address, new_text, position, anchor?)`
- `remove_unit(path, address, [part|block])` · `create_unit(path, address, part, new_text)`

**Запись (escape hatch)**
- `replace_in_file(path, search, replace, occurrence?, regex?)`
- `replace_range(path, start_line, end_line, new_content, expected_first_line?)`
- `replace_between(path, start_anchor, end_anchor, new_content, include_start?, include_end?, occurrence?)`
- `insert_at_anchor(path, anchor, position, new_content, occurrence?)`

**Файлы**
- `create_file(path, content, class_name?)` · `overwrite_file(path, content)`
- `delete_file(path)` · `move_file(src, dst)` · `copy_file(src, dst)`

**Индекс**
- `get_index(kind, max_bytes?, limit?, path?, sort?, scoped?)` — `kind` обязателен
- `get_status(sections?)`
- `rebuild_index(...)` · `rebuild_code_index(...)` · `rebuild_csharp_index(...)` — аргументы одинаковы, см. `REF_TOOLS.md`

**Граф**
- `find_symbol(query, kind?, limit?, max_bytes?, scoped?)`
- `find_usages(query, limit?, scoped?)` · `symbol_graph(qualname, occurrence?, depth?, max_nodes?, kind?)`

**Прочее**
- `run_python([script|module], args?, timeout?, max_bytes?)` · `verify_syntax([paths|directory])`
- `get_scope()` · `exclude(patterns, reason?)` · `include(patterns, reason?)` · `set_scope(text)` · `clear_scope()`
- `grep_replace` · `grep_replace_mcp` · `copy_unit` — схемы в `REF_TOOLS.md`

## 6. Пример
Один фенс, три массива, `id` у каждого. `patterns` — строка или список; `reason` опционален (по умолчанию `llm-session`).

```json
[{"id":1,"action":"read_unit","arguments":{"file_path":"PatchAppliers/PatchApplier/toolkit/core/patcher.py","address":{"qualname":"Patcher._apply_one"},"part":"head,annotation"}}]

[{"id":2,"action":"replace_unit","arguments":{"file_path":"PatchAppliers/PatchApplier/toolkit/core/patcher.py","address":{"qualname":"Patcher._apply_one"},"part":"body","new_text":"return self._dispatch(patch)"}}]

[{"id":3,"action":"exclude","arguments":{"patterns":["tests/","vendor/"],"reason":"правка core, тесты не нужны"}}]
```

## 7. REF-модули (по требованию)
Полный текст — `read_file("PatchAppliers/PatchApplier/toolkit/docs/<name>")`. Грузить только когда нужно.

| Модуль | Когда |
|---|---|
| `REF_TOOLS.md` | схема аргументов незнакомого/редкого тула; `grep_replace`, `copy_unit`, XML, нативные MCP |
| `REF_INDEX_META.md` | метки (`⚠ stale/large/cycle`, `◉`, `⧉dub`), версии индекса, diff |
| `REF_MARKDOWN.md` | правка `.md`: секции, summary, `<!-- pa: suppress ... -->` |
| `REF_ERRORS.md` | незнакомый `error_code` |
| `REF_EXAMPLES.md` | образец патча: md-секция, escape hatch, массовая замена |
| `RobloxCodeRules.md` | Luau-код (когда включён) |
| `XML_START.md` | XML-тулсет (когда включён) |
| `MCPBridgeRules.md` | мост Roblox (когда включён) |
