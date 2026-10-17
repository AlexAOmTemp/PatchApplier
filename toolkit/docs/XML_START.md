# XML_START — инструкция для LLM
<!-- summary: Компактная инструкция по XML-тулсету: адресация, шесть тулов, xml_discriminators в workspace.json, различие адреса тула и XPath, типичные ошибки. Заменяет собой чтение XML_TOOLSET.md для операционной работы. -->
<!-- tags: xml, llm-start, reference -->

> **Для кого.** Этот файл — рабочий справочник LLM при работе с XML через Patch Applier. Дизайн и обоснования — в `XML_TOOLSET.md`. Здесь — только то, что нужно, чтобы **сделать патч**.
>
> **Что приходит в стартовом сообщении.** Если пользователь включил XML-источник и в проекте есть `workspace.xml.discriminators`, они видны в `get_status`. Если нет — тулсет работает на `DEFAULT_CHAIN` (см. §3), что для RimWorld и большинства data-centric XML достаточно.

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

## 4. Шесть тулов
<!-- summary: xml_read, xml_find, xml_map, xml_modify, xml_append, rebuild не нужен. Что принимают, что возвращают, когда отказывают. -->

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

**Удаление children нет.** Если нужно удалить ребёнка — `xml_modify` не подойдёт (Step 4 — `xml_delete`).

### 4.5 `xml_append(file_path, parent, fragment)`

Добавить один well-formed элемент в конец детей `parent`. Fragment — строка. Многострочный пересчитывается под отступ родителя.

- `bad_fragment` если malformed или multi-root.
- `mixed_content_unsupported` если parent с mixed content или текстовый лист.
- Self-closing parent раскрывается в пару.
- CRLF/EOL файла сохраняется.

### 4.6 `rebuild_*` для XML нет

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
| `bad_fragment` | Fragment в `xml_append` не парсится или multi-root | Fragment — ровно один well-formed элемент. Проверь `&`, `<`, `>`. |
| `dtd_unsupported` | В файле DTD с `<!ENTITY ...>` | Разверни entity вручную. ex. `&foo;` — в значение `bar` вручную. |
| `xml_space_preserve_unsupported` | `xml:space="preserve"` в файле | Правка через `set_text` не поддерживается. |
| `source_changed` | Файл изменился между read и write | **Пока не реализовано** (Step 4). При гонке `xml_modify` не поймает — читай аккуратнее. |

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

## 8. Открытые ограничения (Step 4+)
<!-- summary: xml_insert, xml_delete, xml_replace, xml_patch_op, source_changed, namespaces по URI. Пока нет — обход через grep_replace_mcp и ручные правки. -->

Пока не реализовано, обходись существующим:

- **`xml_delete` / `xml_insert` / `xml_replace`** — для удаления/вставки-сиблинга/замены элемента целиком. Обход: `xml_read` → точечный `replace_in_file` по уникальному anchor или `grep_replace_mcp`.
- **`source_changed`** — stale-source protection. Обход: работай быстро или перечитай файл перед write.
- **`xml_patch_op`** — генерация `<xpath>` из адреса тула. Пока пиши XPath руками.
- **Namespaces по URI** — только по префиксу как в файле.
- **`set_annotation`** (`<!-- summary: ... -->` первым ребёнком) — Step 4.

## 9. Что помнить
<!-- summary: Один фенс на патч. Не использовать replace_unit для XML. Читать перед правкой. Проверять diff после rebuild. Проверять адрес ≠ XPath. -->

- **Один фенс на весь ответ** — как везде в утилите.
- **`replace_unit` для XML — нет.** Только `xml_*`.
- **Перед правкой — прочитай актуальное состояние** (`xml_read` / `xml_find`).
- **После write — проверь `xml_read`.** Не полагайся на память.
- **Адрес тула ≠ XPath.** Никогда не подставляй первый во второй.
- **`ambiguous_address` — не повторяй слепо.** Добавь `occurrence` или уточни значение.
- **`too_many_files` — не поднимай лимит вслепую.** Сузь путь.
- **`blocked` (policy) — не retry.** Сообщи пользователю.
