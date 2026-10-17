# XML_START — инструкция для LLM
<!-- summary: Компактная инструкция по XML-тулсету: адресация, 10 тулов, xml_discriminators в workspace.json, различие адреса тула и XPath, типичные ошибки. Заменяет собой чтение XML_TOOLSET.md для операционной работы. -->
<!-- tags: xml, llm-start, reference -->

> **Для кого.** Этот файл — рабочий справочник LLM при работе с XML через Patch Applier. Дизайн и обоснования — в `XML_TOOLSET.md`. Здесь — только то, что нужно, чтобы **сделать патч**.
>
> **Когда этот файл приложен.** Пользователь включил `+ XML_START.md` в окне «Старт сессии» (по умолчанию выключено). Это единственный сигнал, что XML-тулсет входит в рабочую поверхность LLM. Если этот файл приложен — `xml_*` тулы доступны. **Если его нет — не используй `xml_*`**: пользователь работает в проекте, где XML-инструменты ему не нужны, и стартовый текст их не описывает.
>
> **Конфигурация дискриминаторов.** Если в `workspace.xml.discriminators` проекта что-то настроено, это видно в `get_status`. Если нет — тулсет работает на `DEFAULT_CHAIN` (см. §3), что для RimWorld и большинства data-centric XML достаточно.

## 1. Что поддерживается
<!-- summary: Data-centric XML: RimWorld Defs/Patch, Maven POM, MSBuild, SVG. Mixed content (XHTML) — не поддерживается. Один тулсет для всех — не единый с Python/Lua/MD. -->

- **RimWorld** Defs и Patch (основная цель).
- **Maven POM**, **MSBuild** `.csproj`/`.props`.
- **SVG** (без mixed content).
- Любой data-centric XML, где дети элемента — элементы, а не текст между ними.

**Не поддерживается:** XHTML, DOCX, любой document-centric XML с значимым текстом между элементами (`error_code="mixed_content_unsupported"`).

**Не использовать `read_unit` / `replace_unit` / `insert_block` для XML.** Это отдельная модель — XML-тулсет.

## 2. Адресация
<!-- summary: Путь через /. Сегмент — тег. [Square] — дискриминатор или позиция (1-based). Атрибуты через xml_modify, не через /@. Неоднозначность — occurrence. -->

```
Defs/ThingDef[Steel]/statBases/MarketValue
Patch/Operation[3]
ModMetaData/modDependencies/li[brrainz.harmony]
```

**Правила:**
- `/` — разделитель сегментов.
- **Сегмент — имя тега.** Не атрибут. `Defs` — тег, `Defs[1]` — первый `Defs` в корне.
- **`[Square]` — селектор.** Два вида:
  - `[N]`, где N — **только ASCII-цифры** → **позиционный** (1-based). `li[2]` — второй `li`, всегда.
  - `[value]` — всё остальное → **дискриминатор** (значение ребёнка или атрибута, см. §3). `ThingDef[Steel]` — ThingDef с `defName=Steel`.
- **Первое `[Square]` — только на не-корне** (корень адресуется как `<Tag>`, без селектора; если у файла несколько корней — ошибка парсера, XML так не бывает).
- **Атрибуты адресуются через `xml_modify`**, не через `/@attr`.
- **Экранирование в значении:** `\[`, `\]`, `\/`, `\\`. На практике в `defName` их нет.
- **Неоднозначность:** несколько кандидатов + без `occurrence` → `ambiguous_address` с L-диапазонами. С `occurrence=N` — N-й. `occurrence` только на **последнем** сегменте.
- **`:` и пробел в значении — литеральные.** `record_update[gamedata:PlayerBase]`, `bone[NPC Cape1]` — работают как есть.

## 3. Дискриминатор — откуда берётся имя
<!-- summary: Из workspace.xml.discriminators по суффиксу пути (comps/li) или тегу. Fallback DEFAULT_CHAIN: defName, @Name, @name, @id, @key, artifactId, text. Ничего не нашлось — not_found. -->

Для `ThingDef[Steel]` тул должен знать: «Steel» сравнивать с `defName` (ребёнок) или с `@Name` (атрибут)? Ответ:

1. **Конфиг** (`workspace.xml.discriminators`). Ключ — тег или суффикс пути (`comps/li`, `modDependencies/li`). Длинный суффикс выигрывает у короткого. Значение — строка (`"defName"` / `"@Name"`) или список для fallback-порядка.
2. **DEFAULT_CHAIN** если конфига нет: `defName` (ребёнок) → `@Name` → `@name` → `@id` → `@key` → `artifactId` (ребёнок) → **собственный текст элемента**.

Последнее звено (`text`) критично: `<li>1.4</li>` и `<li>Metallic</li>` находятся только через него.

**Если ничего не нашлось** — `not_found` с сообщением «N `<tag>` под `<parent>`, ни один не матчит `[value]` (tried: defName, @Name, ...)».

## 4. Десять тулов
<!-- summary: read, find, map, modify, append, delete, replace, copy, move, insert. Что принимают, что возвращают, когда отказывают. rebuild для XML не нужен. -->

### 4.1 `xml_read(file_path, address, occurrence?)`

Один элемент целиком как текст. Header: `<tag> L{first}-L{last} ({N} B)`.

- `ambiguous_address` без `occurrence`, если несколько кандидатов.
- `occurrence_out_of_range` если N больше числа кандидатов.

### 4.2 `xml_find(path, tag, where?, max_files?, max_results?)`

Schema-поиск по дереву. **`path` обязателен.** `tag` обязателен. `where` — dict `{child_name_or_@attr: glob_or_exact}`. Glob — только `*` и `?` (без `[seq]`).

- `too_many_files` если `path` слишком широкий (17k XML в RimWorld — дефолтный лимит 1000). Сужай путь или поднимай `max_files`.
- Возвращает список `file  <tag>[value]  L{first}-L{last}`.
- **Не ищет** в `<description>`, `<label>`, комментариях.

### 4.3 `xml_map(path, depth?, max_tags?, max_files?)`

Карта дерева XML: файлов по каталогам + агрегат по тегам **прямых детей корня**. `depth` (дефолт 2) группирует глубокие каталоги. Сэмпл из 3 имён через дискриминатор.

Когда использовать: незнакомый мод — «что вообще есть в дереве».

### 4.4 `xml_modify(file_path, address, ops, occurrence?)`

Атомарные правки одного элемента. `ops` — список операций, применяются по порядку. **Любая ошибка откатывает всё, файл не тронут.**

| `op` | Аргументы | Что делает |
|---|---|---|
| `set_attr` | `name`, `value` | Установить/обновить атрибут. Существующий — на месте, новый — в конец. Значение эскейпится (`&`, `<`, `>`, `"`). |
| `remove_attr` | `name` | Удалить. Нет атрибута → `attr_not_found` |
| `set_text` | `value` | Лист → текст. `has_children` если есть дети. `mixed_content_unsupported` если настоящий mixed. Self-closing → пара тегов. CDATA-обёртка сохраняется. |
| `set_annotation` | `value` | Вставить/заменить `<!-- summary: ... -->` первым ребёнком. `empty_element` если родитель self-closing. Идемпотентно: повторный вызов заменяет значение. |

**Удаление children нет.** Для удаления ребёнка — `xml_delete` (см. §4.6).

### 4.5 `xml_append(file_path, parent, fragment)`

Добавить один well-formed элемент в конец детей `parent`. Fragment — строка. Многострочный пересчитывается под отступ родителя.

- `bad_fragment` если malformed или multi-root.
- `mixed_content_unsupported` если parent с mixed content или текстовый лист.
- Self-closing parent раскрывается в пару.
- CRLF/EOL файла сохраняется.

### 4.6 `xml_delete(file_path, address, occurrence?)`

Удалить один элемент.

- Если элемент — единственное не-whitespace на своей строке — удаляется строка целиком (включая `\n`). Иначе — только span элемента.
- Нельзя удалить корень (`cannot_delete_root`). Для замены корня — `xml_replace`.
- Неоднозначность — через `occurrence`, как в `xml_read`.
- BOM / CRLF / кодировка сохраняются.

### 4.7 `xml_replace(file_path, address, fragment, occurrence?)`

Заменить элемент целиком на `fragment`.

- `fragment` — ровно один well-formed элемент (`bad_fragment` иначе).
- Reindent: первая строка без дополнительного отступа (splice-точка уже имеет отступ старого элемента), остальные — с отступом старого элемента.
- Работает на корне тоже.
- BOM / CRLF / кодировка сохраняются.

### 4.8 `xml_copy(source_file, source_address, target_file, position, renames?, …)`

Копирует элемент из одного файла в другой. `position`:

- `end` — добавить в конец детей `target_parent` (обязателен). Reindent по родителю, mixed content проверяется.
- `replace` — заменить элемент по `target_address` (обязателен). Reindent по старому элементу.

`renames` — dict `{old: new}`, применяется к тексту фрагмента через `str.replace`, **длинные ключи первыми**. Не regex, не word-boundary: передавай точные идентификаторы (`TM_WoodGolem`, `TM_Wood_Manipulator`), иначе `TM_Wood` сломает префикс `TM_WoodGolemLS`.

`source_occurrence` / `target_occurrence` — как везде. Сиблинговая вставка (before/after) — отдельный `xml_insert`.

**`register_in` / `register_as`.** Если заданы оба: после успешной копии в контейнер по адресу `register_in` добавляется `<li>{register_as}</li>` как последний ребёнок. Для `<upgrades><li>X</li>…</upgrades>`. Оба обязательны или ни один (`bad_input`).

**`renames`-warnings.** Ключ, который **не нашёлся** в тексте источника, попадает в `message` как `⚠ rename keys with no match in source: …`. Статус остаётся `ok` (это предупреждение, не ошибка). Причина: опечатка в ключе или длинный ключ съел вхождение короткого.

**`source_hash`** — опционально, см. §4.10.

### 4.9 `xml_move(source_file, source_address, target_file, …)`

Тот же pipeline, что `xml_copy` + удаление source после успешной записи target. **Same-file запрещено** (`same_file_move_unsupported`): удаление сдвигает offset, что ломает оставшиеся адреса. Для перемещения внутри файла — `xml_copy` + `xml_delete` двумя действиями.

Cross-file partial failure: target записан, source не удалён → `status=ok` с `⚠ WARN` в message (дубликат лучше потери).

### 4.10 `xml_insert(file_path, address, fragment, position, occurrence?, source_hash?)`

Вставить `fragment` как сиблинга целевого элемента. `position` — `before` или `after`. Родитель берётся из цели.

- `cannot_insert_root_sibling` если target — корень документа.
- `mixed_content_unsupported` если родитель смешанного типа.
- `bad_fragment` если fragment не well-formed или multi-root.
- Reindent по целевому элементу, EOL файла сохраняется.

**`source_hash`** (опционально) — если задан, проверяется против текущего хеша файла; несовпадение → `source_changed`. Хеш приходит в шапке `xml_read` (суффикс `#XXXXXXXX`).

### 4.11 `rebuild_*` для XML нет

XML-тулсет не поддерживает свой индекс (Step 4, отложено). Все операции читают файл целиком. На больших Defs (100 KB) это OK, потому что работает только когда ты явно вызвал `xml_read` / `xml_find` / `xml_modify`.

## 5. Два синтаксиса — адрес тула ≠ XPath
<!-- summary: `Defs/ThingDef[Steel]` (наш) vs `Defs/ThingDef[defName="Steel"]` (XPath в Patch-файлах). Никогда не подставлять адрес тула в <xpath>. -->

В RimWorld-Patch'ах внутри `<xpath>` лежит **настоящий XPath**:

```xml
<xpath>/Defs/ThingDef[defName="Steel"]/statBases/MarketValue</xpath>
```

Адрес тула:

```
Defs/ThingDef[Steel]/statBases/MarketValue
```

Выглядят похоже, **синтаксис разный**. Правило:

- **В `xml_read` / `xml_find` / `xml_modify` / `xml_append`** — адрес тула (`ThingDef[Steel]`).
- **В `<xpath>` внутри Patch-файла** — настоящий XPath (`ThingDef[defName="Steel"]`).
- **Никогда не подставлять адрес тула в `<xpath>`.** Это будет синтаксически валидный XPath (просто предикат `Steel` — «правда»), и Patch молча не сработает. Ошибка тихая и опасная.

## 6. Типичные ошибки и что делать
<!-- summary: ambiguous_address, too_many_files, mixed_content_unsupported, not_found, attr_not_found. Что каждый значит, что поправить в патче. -->

| `error_code` | Что случилось | Что делать |
|---|---|---|
| `ambiguous_address` | Несколько кандидатов, `occurrence` не задан | Прочитай L-диапазоны в сообщении. Добавь `occurrence=N` или уточни дискриминатор. |
| `occurrence_out_of_range` | N больше числа кандидатов | Проверь реальное число в сообщении. |
| `position_out_of_range` | `[N]` больше числа детей с этим тегом | Позиционный селектор считает только детей с этим тегом, не всех. |
| `too_many_files` | `xml_find(path=...)` захватывает слишком много | Сузь `path` (конкретный мод/каталог) или подними `max_files`. |
| `mixed_content_unsupported` | `set_text` / `append` на элементе с mixed content | Скорее всего, это `<description>` или другой документный узел. Используй `xml_replace` (Step 4) или работай через `set_text` на **родителе**. |
| `has_children` | `set_text` на элементе с детьми | Дети не удаляются неявно. Для замены содержимого — `xml_replace`. |
| `not_found` (дискриминатор) | Ни один ребёнок не матчит `[value]` по цепочке | Прочитай «tried: ...» в сообщении. Возможно, нужен конфиг `xml_discriminators`. |
| `not_found` (тег) | Нет такого тега под parent | Проверь `xml_read` родителя. |
| `attr_not_found` | `remove_attr` на отсутствующем | Не ошибка retry — атрибута реально нет. |
| `bad_fragment` | Fragment в `xml_append`/`xml_replace`/`xml_insert`/`xml_copy` не парсится или multi-root | Fragment — ровно один well-formed элемент. Проверь `&`, `<`, `>`. |
| `cannot_insert_root_sibling` | `xml_insert` на корне документа | Вставить сиблинга корню нельзя (контейнера нет). Используй `xml_append` в корень. |
| `dtd_unsupported` | В файле DTD с `<!ENTITY ...>` | Разверни entity вручную. ex. `&foo;` — в значение `bar` вручную. |
| `xml_space_preserve_unsupported` | `xml:space="preserve"` в файле | Правка через `set_text` не поддерживается. |
| `source_changed` | Файл изменился между read и write | Передавай `source_hash` из `xml_read` в write-тул. Если хеш не совпал — `source_changed`, файл не тронут. Перечитай и повтори. |

## 7. Workflow: типичная задача
<!-- summary: «Добавь SteelWall с рецептом» — шесть вызовов. Разведка → чтение образца → создание → добавление рецепта. -->

Задача: «добавь в мой мод блок SteelWall с крафтом».

```
1. xml_map("Mods/MyMod/")
   → структура мода

2. xml_find(path="Mods/MyMod/Defs", tag="ThingDef", where={"defName": "*Wall*"})
   → пример: vanilla Wall

3. xml_read("Defs/Buildings/Walls.xml", "Defs/ThingDef[Wall]")
   → образец

4. create_file("Defs/Buildings/SteelWall.xml", <ThingDef>…)

5. xml_find(path="Mods/MyMod/Defs", tag="RecipeDef", where={"product": "*Wall*"})
   → пример рецепта

6. xml_append("Defs/Recipes/WallRecipes.xml", "Defs",
              "<RecipeDef>…SteelWall…</RecipeDef>")
```

Шесть вызовов. Без `grep` по сотням XML. Без чтения vanilla-структуры целиком.

## 8. Открытые ограничения
<!-- summary: Что осталось: xml_insert (сиблинг), xml_patch_op, source_changed, xml_list, namespaces по URI. Что уже есть — перечислено для контраста. -->

**Уже есть (не ограничение):**

- `xml_read`, `xml_find`, `xml_map`, `xml_modify`, `xml_append`, `xml_delete`, `xml_replace`, `xml_copy`, `xml_move`, `xml_insert`.
- `xml_modify` ops: `set_attr` / `remove_attr` / `set_text` / `set_annotation`.
- `source_changed` — stale-source protection через `source_hash` (см. §4.10).

**Пока нет:**

- **`xml_patch_op`** — генерация `<xpath>` из адреса тула (RimWorld Patch). Пока пиши XPath руками.
- **`xml_list`** — плоский список файла (при наличии `xml_map` обычно не нужен).
- **`xml_move` внутри одного файла** — запрещено. `xml_copy` + `xml_delete` двумя действиями.
- **Batched `xml_copy`** (`addresses=[...]`) — сознательно не делаем: падение одного def'а не должно откатывать остальные.
- **Namespaces по URI** — только по префиксу как в файле.

## 9. Быстрый выбор тула
<!-- summary: Задача → тул. read/find/map для разведки; modify/append/delete/replace для записи. -->

| Задача | Тул |
|---|---|
| Прочитать элемент | `xml_read` |
| Найти все элементы по тегу+фильтру | `xml_find` |
| Карта каталогов | `xml_map` |
| Поменять атрибут / текст / summary | `xml_modify` (ops) |
| Добавить ребёнка | `xml_append` |
| Удалить элемент | `xml_delete` |
| Заменить элемент | `xml_replace` |
| Скопировать в другой файл (с переименованием) | `xml_copy` |
| Скопировать + добавить `<li>` в контейнер | `xml_copy` + `register_in`/`register_as` |
| Переместить между файлами | `xml_move` |
| Вставить сиблинга до/после | `xml_insert` |
| Массовая замена по `defName` (не XML-семантика) | `grep_replace` (FS) |

## 10. Что помнить
<!-- summary: Один фенс на патч. Не использовать replace_unit для XML. Проверять версию мода через tree перед разведкой. Читать перед правкой. Адрес ≠ XPath. -->

- **Один фенс на весь ответ** — как везде в утилите.
- **Разведка по C#/Java/TS — сначала `grep <имя_символа>`, потом `<как_работает>`.** Утилита индексирует Python и Lua; `symbol_graph` для C# недоступен. Рабочий приём: нашёл `TM_GolemEnergy` в XML — сразу `grep 'TM_GolemEnergy'` по всему корню. Там будут: определение need'а, harmony-патч `ShouldHaveNeed`, `GolemPawns.Contains`, часто — комментарий с указанием на проблему. Один grep вместо цепочки `grep method → read_file → grep callback → read_file`. Имена сильнее цепочек вызовов: `grep <symbol_name>` почти всегда за 1 вызов даёт ту же картину, что `symbol_graph` для Python.
- **Сначала `tree` по корню мода.** Моды часто содержат несколько `v1.3/ v1.4/ v1.5/ v1.6/` подкаталогов. `tree(path=корень_мода, max_depth=1)` покажет их за один вызов; **`About/About.xml` `<supportedVersions>`** — какой активный. `xml_find` слепо уважает `path` — если ткнул не в ту версию, найдёшь 0 совпадений и решишь, что «в моде этого нет». Реальный кейс: искал `DesecratedBone` в `RWoM-main/v1.5/Defs`, пусто; правильный путь — `v1.6/Defs/Desecrated/`. Ошибка не в `xml_find`, а в выборе `path`.
- **`replace_unit` для XML — нет.** Только `xml_*`.
- **Перед правкой — прочитай актуальное состояние** (`xml_read` / `xml_find`).
- **После write — проверь `xml_read`.** Не полагайся на память.
- **Адрес тула ≠ XPath.** Никогда не подставляй первый во второй.
- **`ambiguous_address` — не повторяй слепо.** Добавь `occurrence` или уточни значение.
- **`too_many_files` — не поднимай лимит вслепую.** Сузь путь.
- **`blocked` (policy) — не retry.** Сообщи пользователю.
