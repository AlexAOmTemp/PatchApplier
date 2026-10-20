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
- **R-UNIT-4** — адрес: `{"qualname": "Foo.bar"}` (py/lua), `{"qualname": "3"}` (md), `{"qualname": "<module>"}`. Неоднозначность → `occurrence` **внутри** `address`, не аргумент тула
- **R-UNIT-5** — `replace_unit`: ровно одно из `part`/`block` (иначе `scope_required`/`scope_conflict`); `part="body"` сохраняет head+annotation, `"all"` — целиком. Пустой `new_text` = `empty_input`, не удаление — удалять `remove_unit(part="all")`
- **R-UNIT-6** — `block` — только внутри body (`not_applicable` иначе); в Lua blocks внутри функций не нумеруются (`blocks=0`) — править `part="body"`

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
`?` — опционально. Блок ниже генерируется из `TOOL_MAP` скриптом `toolkit/code/manual/gen_toolset_doc.py` (источник истины — код). Правь код, затем перегенерируй; `--check` падает при расхождении. XML-тулы — в `XML_START.md`, MCP-тулы — в `MCPBridgeRules.md` (подключаются отдельно); редкие аргументы — `REF_TOOLS.md`.

<!-- tools:auto:begin -->
**Чтение**
- `read_file(path?, section_number?, section_title?, start_line?, end_line?, max_bytes?, numbered?, escape?, raw?)`
- `read_unit(path?, address?, part?, block?, max_bytes?)`
- `list_units(path?, max_bytes?)`
- `file_stat(path?)`
- `file_exists(path?)`
- `list_files(path?, glob?, show_size?, scoped?, recursive?, show_hidden?, filter?)`
- `survey_dir(path?, ext?, top?, max_files?, scoped?, filter?)`
- `tree(path?, max_lines?, show_files?, max_types?, show_types?, scoped?, recursive_sizes?, filter?)`
- `grep(pattern, paths, recursive?, file_glob?, exclude_glob?, regex?, fixed_strings?, ignore_case?, word_boundary?, before?, after?, max_results?, scoped?, filter?, debug_timing?)` — `paths` обязателен

**Unit**
- `replace_unit(path?, address?, new_text?, part?, block?)`
- `insert_block(path?, address?, new_text?, position?, before_anchor?, after_anchor?)` — `position` = `start`\|`end`; якоря взаимоисключающие, `address` = контейнер, якорь = точка внутри
- `remove_unit(path?, address?, part?, block?)`
- `create_unit(path?, address?, part?, new_text?)`
- `copy_unit(source_file, target_file, selector?, position?, anchor?, container?)`

**Запись (escape hatch)**
- `replace_in_file(path, search, replace, occurrence?, search_repr?, regex?)`
- `replace_range(path, start_line, end_line, new_content, expected_first_line?)`
- `replace_between(path, start_anchor, end_anchor, new_content, include_start?, include_end?, occurrence?)`
- `insert_at_anchor(path, anchor, position, new_content, occurrence?)`

**Файлы**
- `create_file(path, file_content, class_name?)`
- `overwrite_file(path, file_content)`
- `delete_file(path)`
- `move_file(source_path, destination_path)`
- `copy_file(source_path, destination_path)`

**Индекс**
- `get_index(kind, max_bytes?, limit?, path?, sort?, scoped?, sections?)` — `kind` обязателен (в сигнатуре; без него `missing_arg`); по умолчанию overview, `sections=true` — полный список секций
- `get_status(sections?)`
- `rebuild_index(docs_dir?, output?, skip_files?)`
- `rebuild_code_index(code_dir?, output?, manifest_output?, skip_files?, skip_dirs?)`
- `rebuild_csharp_index(...)` — те же аргументы
- `rebuild_lua_code_index(output?, manifest_output?, roots?, local_root?)`

**Граф**
- `find_symbol(query, manifest_path?, kind?, limit?, local?, scoped?)`
- `find_usages(query, manifest_path?, kind?, limit?, local?, scoped?)`
- `symbol_graph(qualname, occurrence?, depth?, max_nodes?, manifest_path?, kind?, local?)`

**Прочее**
- `run_python(path\|module\|code, args?, cwd?, timeout?, max_bytes?, env?)` — ровно один из `path`/`module`/`code`
- `verify_syntax(paths?, directory?)`
- `get_scope()`
- `exclude(patterns?, reason?)`
- `include(patterns?, reason?)`
- `set_scope(text?)`
- `clear_scope()`
- `grep_replace(pattern?, replacement?, mappings?, paths?, recursive?, file_glob?, exclude_glob?, regex?, fixed_strings?, ignore_case?, word_boundary?, max_replacements?, dry_run?, scoped?, filter?, force?)`

> **Аргументы:** один путь — `path`, много — `paths`. Неверный аргумент — явная ошибка `unknown_arg` со списком валидных.
<!-- tools:auto:end -->

## 6. Пример
Один фенс, три массива, `id` у каждого. `patterns` — строка или список; `reason` опционален (по умолчанию `llm-session`).

```json
[{"id":1,"action":"read_unit","arguments":{"path":"PatchAppliers/PatchApplier/toolkit/code/toolkit/core/patcher.py","address":{"qualname":"Patcher._apply_one"},"part":"head,annotation"}}]

[{"id":2,"action":"replace_unit","arguments":{"path":"PatchAppliers/PatchApplier/toolkit/code/toolkit/core/patcher.py","address":{"qualname":"Patcher._apply_one"},"part":"body","new_text":"return self._dispatch(patch)"}}]

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
