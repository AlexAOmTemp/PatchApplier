# XML_TOOLSET — отдельный тулсет для XML
<!-- summary: XML не натягивается на unit-модель, потому что разница не в адресации, а в операциях. Отдельный тулсет: карта, schema-поиск, чтение, append, точечные правки. Data-centric only. Дискриминаторы в конфиге проекта, путь с [Square]/[N]. Порядок: сначала прогон на реальных файлах, потом код. -->

> **Статус:** проект. Заменяет идею «адаптер XML в unit-модель». Отдельный документ, потому что это отдельная модель работы.
>
> **Аудитория:** автор утилиты.

## 1. Почему отдельный тулсет, а не unit-модель
<!-- summary: Разница не в адресации, а в операциях. В XML правит точечно (attr, text, append), в Python/Lua/MD — заменяет тело целиком. Mixed content не представим в unit. -->

Unit-модель (`read_unit` / `replace_unit` / `insert_block`) неявно предполагает три свойства, которых у XML нет:

**Именованные узлы.** В Python/Lua/MD имя — часть синтаксиса: `def foo`, `function M.bar`, `## 3. Заголовок`. В XML `<statBases>` имени не имеет; `defName` — данные внутри, а не свойство. Профиль возвращает имени статус, но это надстройка над языком, не свойство.

**Тело с границами.** В Python тело функции — statements. В MD тело секции — текст до заголовка. В XML тело элемента — **mixed content**: текст, дочерние элементы, комментарии, CDATA вперемешку. Unit-модель не умеет представлять «текст между блоками».

**Атрибуты в head.** Правка одного атрибута — самая частая операция в XML. Unit-модель заставляет делать её через замену всего head (read-modify-write открывающего тега). Для Python/Lua такой операции нет — там у head нет «полей».

**Следствие: другая модель операций.** В Python/Lua/MD основные операции — «заменить тело», «вставить block». В XML — «найти Def», «добавить ребёнка», «поменять атрибут». `replace_unit(part="body")` с пересборкой тела — редкий случай; для RimWorld-мода его почти нет, потому что vanilla никто не редактирует, работа идёт через Patch-файлы.

## 2. Границы применимости
<!-- summary: Data-centric only. Document-centric (XHTML, DOCX с текстом между элементами) — error_code=mixed_content_unsupported. Первая цель — RimWorld Defs и Patch. -->

**Поддерживается:**

- RimWorld Defs и Patch.
- Maven POM, MSBuild `csproj`/`props`.
- SVG (без mixed content, только атрибуты и структура).
- Любой XML, где дети элемента — элементы, а не текст между ними.

**Не поддерживается:**

- XHTML, DOCX, где текст между элементами — значимый контент. `error_code="mixed_content_unsupported"`.
- Полный XPath как язык адресации.
- Namespaces по URI (по префиксу как в файле, нормализация — TODO).
- DTD с entity declarations (`error_code="dtd_unsupported"`).
- `xml:space="preserve"` (отступы пересчитываются по единице файла).

## 3. Адресация
<!-- summary: Путь с разделителем /, сегмент — тег, дискриминатор в [Square] или [N]. 1-based везде. Атрибуты — через xml_modify, не через путь. -->
Один ключ, как `qualname` для unit'ов.

```
Defs/ThingDef[Steel]/statBases/MarketValue
Defs/ThingDef[Steel]/comps/li[CompProperties_Foo]
Patch/Operation[3]
```

**Правила:**

- `/` — разделитель сегментов.
- Сегмент — имя тега элемента. **Сейчас — буквальный префикс из файла** (`xs:element` как `xs:element`). Namespace-нормализация по URI отложена (§13), но решение зафиксировано: буквальный префикс, не локальное имя. Это значит, что `xs:element` и `xsd:element` с одинаковым URI сейчас неразличимы — известное ограничение, снимается при появлении реального кейса.
- `[Square]` — дискриминатор: значение дочернего элемента (`defName=Steel`) или атрибута (`@Name=BaseResource`).
- `[N]` — fallback, **1-based**, если дискриминатора нет.
- Атрибуты адресуются через `xml_modify(set_attr=...)`, **не** через `/@attr`.

### Неоднозначность — `occurrence`, как в `replace_in_file`

Тот же механизм, что в `replace_in_file`. Если дискриминатор матчится на несколько детей:

- **Без `occurrence`** — `error_code="ambiguous_address"`, никаких изменений. Сообщение перечисляет все вхождения с L-диапазонами, как `replace_in_file` для неоднозначного `search`.
- **С `occurrence=N`** — выбирается N-е вхождение (1-based, сверху вниз).
- **`occurrence` вне диапазона** — `error_code="occurrence_out_of_range"`.

Не молчаливый first-match. Не новый механизм. Симметрия с существующим контрактом.

**`[N]` и `occurrence` — разные вещи.** `[N]` — позиционный адрес при отсутствии дискриминатора (`li[3]` = третий `li`). `occurrence` — выбор при неоднозначном дискриминаторе (`ThingDef[Steel]` + `occurrence=2` = второй ThingDef с `defName=Steel`). Не путать, не смешивать в одном аргументе.

### Формальная грамматика

Парсер адресов — отдельный модуль, не `split("/")`. Грамматика:

```
address     := segment ("/" segment)*
segment     := tagname selector?
selector    := "[" (discriminator | index) "]"
discriminator := "@"? value | "N"
value       := escaped-string
tagname     := any char except / [ ]
```

Экранирование в значениях: `\[`, `\]`, `\/`, `\\`. На практике в `defName` их нет (`[A-Za-z0-9_]`), но правило зафиксировано — иначе парсер постепенно накопит краевые случаи.

### Не путать с XPath

В Patch-файлах RimWorld внутри `<xpath>` лежит настоящий XPath (`Defs/ThingDef[defName="Steel"]/statBases`). Адрес тула выглядит похоже, но это другой синтаксис. Подставлять адреса тула в `<xpath>` — ошибка. См. §9.
## 4. Дискриминаторы
<!-- summary: Конфиг в workspace.json, одна-две строки на тег. Fallback-списки, контекст через суффикс пути. Abstract-Def'ы через @Name. -->
Не профиль с наследованием и auto-detection. Просто mapping в `workspace.json`:

```yaml
xml_discriminators:
  ThingDef: [defName, "@Name"]      # обычные и Abstract-Def'ы
  RecipeDef: [defName, "@Name"]
  FactionDef: [defName, "@Name"]
  Project: "@artifactId"
  Package: "@name"
  comps/li: "@Class"                # контекст через суффикс пути
  stuffCategories/li: null          # text-only, [N] fallback
```

### Единый порядок fallback

Значение — строка или список строк. **Порядок проверки фиксирован:** первый элемент списка пробуется первым. Если найден — используется. Не найден — следующий. Никаких «в зависимости от порядка» или «по схеме».

**Единое правило для всего проекта:** `[defName, "@Name"]` — сначала дочерний элемент `defName`, потом атрибут `@Name`. Для всех Def'ов RimWorld этот порядок одинаков. `Abstract=True` Def'ы не имеют `defName`, но имеют `@Name` — сработает второй.

**Дефолт без настройки:** `@name`, `@id`, `@key`, `defName`, `artifactId`, `Include` (как дети). Если ничего не найдено — `[N]`.

### Дискриминатор ≠ уникальный ID

**Критично.** Дискриминатор помогает **построить** адрес, но не гарантирует **уникальность**. `li[@Class=CompProperties_Foo]` может встретиться дважды — два компонента одного класса с разными параметрами. `ThingDef[Steel]` — если два мода определяют Steel, будет два кандидата.

**Уникальность проверяется при разрешении адреса**, не в конфиге. Механизм — `occurrence` (§3), как в `replace_in_file`.

Не настраивать «этот дискриминатор уникален» — такой гарантии не бывает в общем случае, и её нельзя проверить статически.

### Контекст через суффикс пути

Ключ маппинга — тег или суффикс пути. `comps/li: "@Class"` даёт `li[CompProperties_Foo]` внутри `comps`, а `li` внутри `stuffCategories` останется `[N]` (правильно — там текст `Metallic`, дискриминатора нет).

Суффикс — не regex, не glob. Просто `path.endswith(key)` по сегментам. Порядок проверки: сначала самые длинные суффиксы, потом короткие, потом тег, потом дефолт.
## 5. Тулсет
<!-- summary: xml_map, xml_find, xml_read, xml_list, xml_append, xml_insert, xml_delete, xml_replace, xml_modify. Шесть в срез, три по факту. -->

### 5.1 Чтение

#### `xml_map(path, depth?, budget?)`

Карта директорий и файлов с агрегатами по XML-тегам. Тот же формат, что `tree` для FS.

```
Mods/MyMod/Defs/          12 files, 234 ThingDef, 89 RecipeDef
  Items/                  12 files, 156 ThingDef
    Resources.xml         18 ThingDef: Steel, Wood, Cloth, … (+15)
  Buildings/               8 files,  78 ThingDef
```

- Директории — узлы, файлы — листья с агрегатом по тегам детей.
- Агрегат считается одним проходом, без профиля.
- Сэмпл с дискриминатором — 3–5 имён + `(+N)`.
- Без дискриминатора — `tag[N]` в сэмпле.
- Раскрытие best-first по бюджету, не по `depth` вслепую.

#### `xml_list(file, tag?)`

Плоский список элементов файла.

```
Mods/MyMod/Defs/Items/Resources.xml
  ThingDef Steel         L12–L45   [ParentName=BaseResource]
  ThingDef Wood          L48–L78   [ParentName=BaseResource]
  RecipeDef SteelBar    L82–L120   [product=Steel]
```

- Верхнеуровневые элементы корня (или конкретный `tag`).
- L-диапазоны для ориентации.
- 1–2 ключевых атрибута в `[…]`.

#### `xml_find(path?, tag?, where?)`

Schema-осведомлённый поиск. Не `grep` — ищет по структуре, не по тексту.

```
xml_find(path="Defs/", tag="ThingDef", where={"defName": "*Block*"})
→ 5 matches in 3 files:
  Defs/Buildings/Walls.xml   ThingDef[BlockWall]
  Defs/Buildings/Floors.xml  ThingDef[BlockFloor]
```

- `where` — dict: ключ — имя ребёнка или `@attr`, значение — glob (`*Block*`) или точная строка.
- Не ищет в `<description>`, `<label>`, комментариях.

#### `xml_read(file, address)`

Элемент целиком как текст.

```
Mods/MyMod/Defs/Items/Resources.xml  ThingDef[Steel]  L12–L45

<ThingDef ParentName="BaseResource">
  <defName>Steel</defName>
  <label>steel</label>
  <statBases>
    <MarketValue>1.5</MarketValue>
  </statBases>
</ThingDef>
```

Оригинальные отступы, порядок атрибутов, комментарии внутри.

### 5.2 Запись

#### `xml_append(file, parent, fragment)`

Добавить ребёнка в конец. Основная операция для Patch'ей и новых Def'ов.

```json
{"action": "xml_append", "arguments": {
  "file": "Patches/SteelPatch.xml",
  "parent": "Patch",
  "fragment": "<Operation Class=\"PatchOperationReplace\">...</Operation>"
}}
```

- Fragment — строка XML, один корневой элемент.
- Отступ родителя применяется к фрагменту: определяется единица отступа файла (табы/пробелы, ширина) и относительные отступы пересчитываются.
- Валидируется: well-formed, один корень.

#### `xml_modify(file, address, ops)`

Точечные правки, атомарно (все или ни одна).

| Op | Аргументы | Что делает |
|---|---|---|
| `set_attr` | `{name, value}` | Установить атрибут (добавить если нет) |
| `remove_attr` | `{name}` | Удалить атрибут |
| `set_text` | `{value}` | Заменить текст (для листьев) |
| `set_annotation` | `{text}` | `<!-- summary: ... -->` первым ребёнком |

- `set_text` принимает **сырой** текст, тул сам эскейпит `&`, `<`, `>`. `A & B` → `A &amp; B`.
- Self-closing `<a/>` при `set_text` → `<a>value</a>`. При `set_attr` — остаётся `<a attr="v"/>`.
- `set_annotation` — `<!-- summary: -->` как первый ребёнок. Если он уже есть — заменить.

#### `xml_insert(file, address, fragment, position)`

Вставить сиблинга рядом с адресом. `position` — `before` / `after`.

- Сдвигает `[N]` индексы у следующих сиблингов. В ответе: `warning="sibling_indices_shifted"` и новые адреса для затронутых.

#### `xml_delete(file, address)`

Удалить элемент. Если родитель остаётся пустым — `warning="empty_parent"`, не ошибка.

#### `xml_replace(file, address, fragment)`

Заменить элемент целиком. Для случаев, где проще переписать.

## 6. Верификация
<!-- summary: Re-parse (well-formed), дискриминатор сохранился с учётом rename, mixed content не появился. При rename — вернуть new_address. -->
### Атомарность — по единой политике утилиты

**Не изобретать отдельную для XML.** Политика атомарности уже определена для `replace_unit`, `replace_in_file`, `grep_replace` и других write-тулов. XML-тулсет следует той же политике:

1. **Валидация до записи.** Все адреса разрешены, все preconditions проверены. Ошибка любого — файл не тронут, ничего не записано.
2. **Verify-after-write.** После записи — re-parse, проверка инвариантов. Ошибка — файл восстанавливается (или не перезаписывается, если возможно).
3. **Единая политика для одной операции и для батча.** Если `xml_modify` принимает несколько `ops`, применяется всё или ничего — как `replace_unit` с `block=[...]` применяет диапазон целиком или отклоняет.

Это не «три уровня», а один контракт, который уже действует в утилите. XML-тулсет его наследует.

### Verify-инварианты для XML

После записи:

1. **Re-parse** — well-formed? Если нет — `error_code="result_syntax_error"`, файл не тронут.
2. **Адрес разрешается** — если был и операция не `delete`/`xml_replace`/`set_attr` с изменением самого дискриминатора. Иначе `error_code="result_missing_symbol"`.
3. **Mixed content не появился** — если в результате появился текст между элементами в структурном родителе — `error_code="mixed_content_unsupported"`. Определение — §7.2.

### Rename — не ошибка, а новый адрес

Если `set_attr` меняет `@Name` или `xml_replace` меняет `defName` — это легитимное переименование. Проверка по старому адресу даст ложную `result_missing_symbol`.

**Решение:** тул вычисляет новый адрес из нового состояния, возвращает `new_address=...` в `Result`. Это успех, не потеря символа.

Для `xml_insert` с `[N]` — то же: вернуть новые адреса затронутых сиблингов в `new_addresses=[...]`.

### Stale source protection

Если файл изменился между `read` и `write` — не перезаписывать молча. Механика:

- Перед write тул читает текущий файл.
- Сравнивает хеш содержимого с тем, что был при `xml_read` (или при разрешении адреса).
- Хеши не совпали — `error_code="source_changed"`, никаких изменений.

`mtime` недостаточно для строгой гарантии — хеш.

### Что наследуется от утилиты

- Path policy — та же.
- Result-структура — та же (`status`, `delta`, `verified`, `error_code`).
- Логирование — то же.
- Diff — XML-специфичный рендер, но в общей рамке.

XML-слой отвечает за семантику XML. Всё остальное — общая инфраструктура.
## 7. Парсер и write
<!-- summary: Expat с CurrentByteIndex, не lxml/ElementTree. Write по спанам, сохраняет BOM, кодировку, CDATA, комментарии, порядок атрибутов. -->

### 7.1 Парсер

**`xml.parsers.expat` с `CurrentByteIndex`.** Не lxml, не ElementTree.

Причины:

- **Byte offsets** для правки по текстовым спанам. `sourceline` у lxml/ET недостаточно — для замены элемента нужно знать точные байты.
- **Порядок атрибутов** сохраняется (важно для diff и для `part="head"`).
- **CDATA, комментарии, self-closing, PI** — сохраняются.
- **BOM** учитывается в offsets.

Это тот же «token-парсер», что для Lua. XML лексически простой, expat даёт всё нужное.

### 7.2 Write

Запись идёт **по спанам**: правка затрагивает только байты элемента, остальное не трогается. Следствия:

- **BOM** сохраняется как был.
- **Кодировка** определяется из `<?xml encoding="..."?>` или BOM, write в той же.
- **CDATA** в других элементах не трогается, только в том, которому делают `set_text`.
- **Entity references** — если в файле есть DTD, отказ (`error_code="dtd_unsupported"`). Без DTD `&amp;` и т.п. сохраняются как есть.
- **Порядок атрибутов** сохраняется, если операция не `set_attr`/`remove_attr`.

### 7.3 Отступ фрагмента

При `xml_append` / `xml_insert` / `xml_replace` фрагмент — строка. Нужно:

- Определить единицу отступа файла (табы vs пробелы, ширина).
- Пересчитать относительные отступы фрагмента под единицу файла.
- Приклеить к отступу родителя (или сиблинга при `insert`).

Не «приклеить первую строку» — многострочный фрагмент должен сохранить внутреннюю структуру с учётом единицы файла.

### 7.4 Mixed content — три случая, не один

**Наивная проверка «между элементами есть текст → отклонить» отклоняет обычный форматированный XML**, потому что whitespace между детьми — тоже текстовый узел. Три разных случая:

**Структурные пробелы — допустимо.**
```xml
<statBases>
  <MarketValue>1.5</MarketValue>
  <Mass>2.0</Mass>
</statBases>
```
Между `<MarketValue>` и `<Mass>` — whitespace. Это форматирование, не контент. `xml_modify`/`xml_append` работают с этим нормально.

**Текстовый лист — допустимо для `set_text`.**
```xml
<MarketValue>1.5</MarketValue>
```
Текст есть, детей нет. `set_text` — законная операция.

**Настоящий mixed content — отклонять.**
```xml
<prefix>Hello <b>world</b>!</prefix>
```
Текст чередуется с элементами. Структурные операции (`xml_append`, `xml_insert`) приведут к непредсказуемому результату. `error_code="mixed_content_unsupported"`.

**Проверка:** элемент считается mixed, если (а) есть хотя бы один дочерний элемент, (б) есть хотя бы один текстовый узел с **не-whitespace** содержимым. Whitespace-only текстовые узлы при наличии детей — структурные.

**`xml:space="preserve"`** — обнаруживать и отклонять `error_code="xml_space_preserve_unsupported"`. Не переформатировать молча: этот атрибут явно говорит, что whitespace значим.

### 7.5 `set_text` на элементе с детьми — запрещено

Неявное уничтожение потомков — слишком неожиданное поведение для LLM. `xml_modify(set_text=...)` на элементе, у которого есть дети, — `error_code="has_children"`.

Если нужно заменить содержимое элемента с детьми на текст — это `xml_replace` (явное действие, возвращает новый адрес).

### 7.6 Четыре контракта сохранения

Все четыре — бесплатны при записи по спанам, но должны быть зафиксированы, иначе write будет тихо ломать нетронутые части.

**Кодировка.** Определяется из `<?xml encoding="..."?>` или BOM. Write — в **той же** кодировке. UTF-16-файл остаётся UTF-16, Latin-1 остаётся Latin-1. Иначе молчаливая перекодировка.

**Комментарии внутри элемента.** Сохраняются. Запись по спанам это даёт бесплатно, но контракт: `xml_modify`/`xml_append`/`xml_insert` не трогают комментарии в нетронутых спанах. `set_annotation` **добавляет** `<!-- summary: -->` первым ребёнком, не удаляя существующие.

**Порядок атрибутов.** `set_attr` на существующий атрибут **сохраняет позицию**. `set_attr` на новый — добавляет в конец. Не переупорядочивает. Для diff-стабильности.

**Line endings.** Untouched spans сохраняют свои (CRLF остаётся CRLF). Новый контент использует доминирующий в файле. Иначе правка CRLF-файла даст смешанные концовки.

### 7.7 Атрибуты — эскейпинг и позиция

`set_attr(name, value)` принимает **сырой** текст, тул эскейпит `"`, `&`, `<`, `>` для двойных кавычек. Симметрично `set_text`.

Если существующий атрибут записан с одинарными кавычками — `set_attr` сохраняет стиль (одинарные), не переключает на двойные. Минимальная инвазивность.
### 7.8 Безопасность парсера

Expat по умолчанию не тянет внешние сущности, но контракт надо зафиксировать явно.

**Запрещено:**

- Загрузка внешних entity references (XXE). `setParamEntityParsing(XML_PARAM_ENTITY_PARSING_NEVER)`.
- Сетевые обращения из-за содержимого XML.
- Внешние DTD.

**Лимиты:**

- Размер файла: **warn на >10 MB, hard-limit 50 MB**. `error_code="file_too_large"`.
- Глубина вложенности: **100**. Реальные Def'ы редко глубже 10, `error_code="depth_too_deep"`.
- Количество элементов: **1 000 000**. `error_code="too_many_elements"`.

Это не «универсальная защита», а разумные границы для data-centric XML. При реальном кейсе за пределами — поднять лимит осознанно.

**DTD с entity declarations** — `error_code="dtd_unsupported"`. Не пытаться развернуть `&foo;` в значение.
## 8. Ограничения
<!-- summary: Не делать: mixed content, полный XPath, профили с наследованием, transparent, namespaces по URI, entity. Не использовать replace_unit для XML. -->

Что **не делаем** в этом тулсете:

- **Mixed content.** Document-centric XML не поддерживается (`mixed_content_unsupported`).
- **Полный XPath** как язык адресации.
- **Профили** с наследованием, scoped-переопределением, auto-detection. Только mapping в конфиге.
- **Transparent-теги.** `Defs/ThingDef[Steel]` — полный путь.
- **Namespaces по URI.** По префиксу как в файле. Нормализация — TODO.
- **DTD с entity.** `dtd_unsupported`.
- **`xml:space="preserve"`.** Обнаруживается и отклоняется (`xml_space_preserve_unsupported`), не переформатируется молча.
- **`replace_unit` / `insert_block` / `set_annotation` для XML.** Отдельный тулсет, не смешивать.

## 9. Два синтаксиса — развести явно
<!-- summary: Адрес тула (Defs/ThingDef[Steel]) и XPath в Patch (Defs/ThingDef[defName="Steel"]) — разные. В XML_START показать рядом. Не подставлять адрес тула в xpath. -->

В Patch-файлах RimWorld внутри `<xpath>` лежит настоящий XPath:

```xml
<xpath>/Defs/ThingDef[defName="Steel"]/statBases/MarketValue</xpath>
```

Адрес тула выглядит похоже, но это **другой синтаксис**:

```
Defs/ThingDef[Steel]/statBases/MarketValue
```

**Правило для LLM:** адрес тула ≠ XPath. Не подставлять адреса тула в `<xpath>`. В `XML_START.md` показать оба варианта рядом, чтобы контраст был явным.

**Задел на будущее:** `xml_patch_op(op="replace", xpath_target=..., value=...)` — тул сам генерирует `<xpath>` из адреса тула в XPath-форме. Тогда LLM пишет один синтаксис, тул конвертирует. Не в первую версию, но снимет проблему в корне.

## 10. Интеграция с существующей инфраструктурой
<!-- summary: Переиспользуется: expat, path policy, diff, verify, create_file. Новое: toolkit/xml/, toolkit/tools/xml/, workspace.xml_discriminators. -->

**Переиспользуется:**

- Expat-парсер (общий подход с Lua).
- Path policy — та же.
- Diff — отдельный XML-рендер, показывает изменения по адресам.
- `create_file` / `overwrite_file` — для новых файлов целиком.
- Рамка верификации — общая, XML-специфичная проверка внутри.

**Новое:**

- `toolkit/xml/` — парсер, адресация, writer.
- `toolkit/tools/xml/` — 9 тулов.
- Секция `xml_discriminators` в `workspace.json`.
- `XML_START.md` — инструкция для LLM (или секция в LLM_START).

## 11. Порядок реализации
<!-- summary: Шаг 0 — fixtures до кода. Шаг 1 — read-only (map/find/read). Шаг 2 — span writer prototype. Шаг 3 — первая запись (modify/append). Шаг 4 — документ. Шаг 5 — остальное. -->

### Шаг 0 — fixtures до кода

Не «посмотреть глазами», а **таблица ожидаемых результатов**. Взять реальные файлы из ванильного RimWorld `Core/Defs` и один-два реальных Patch'а. Составить fixtures:

| Сценарий | Ожидаемый результат |
|---|---|
| Обычный `ThingDef` | Уникальный адрес по `defName` |
| Abstract-Def с `@Name` | Адрес по `@Name` (fallback) |
| Два одинаковых дискриминатора | `ambiguous_address` без `occurrence`; выбор с `occurrence=N` |
| `li` в `comps` и `stuffCategories` | Правильный контекстный дискриминатор |
| Адрес с `]` в значении | Экранирование работает |
| Namespace префикс | Буквальный префикс в qualname |
| Вставка перед существующим `[N]` | Корректные новые `[N]` |
| `set_text` у self-closing | Парный тег, текст экранирован |
| `set_text` у элемента с детьми | `has_children` |
| Ошибка одной ops в `xml_modify` | Файл не тронут |
| Mixed content (`<a>x<b>y</b></a>`) | `mixed_content_unsupported` |
| Структурные пробелы | Не mixed, работает |
| BOM, CRLF, CDATA, комментарии | Сохранены в нетронутых спанах |
| UTF-16 файл | Остаётся UTF-16 |
| `xml:space="preserve"` | Отклонено |
| Stale source (файл изменён между read/write) | `source_changed` |

Это не «тесты после реализации», а **fixtures до парсера** — определяют контракт.

### Шаг 1 — read-only (три тула)

- `xml_map` — карта.
- `xml_find` — schema-поиск.
- `xml_read` — чтение элемента.

**Почему сначала read-only, а не writer, как советует ревью.** У пользователя сейчас болит именно карта («сотни XML, искать сложно»). Начинать с writer — месяцы без user value. Read-only работает на существующих данных, безопасно (ничего не пишет), и решает immediate pain.

### Шаг 2 — span writer prototype

Отдельный скрипт, не тул. Доказывает корректность:

- offsets для всех конструкций (теги, CDATA, комментарии, PI, self-closing);
- BOM, CRLF, кодировки;
- порядок атрибутов.

Прогнать на fixtures. Если writer ненадёжен — вернуться к нему до Шага 3. Если надёжен — двигаться.

### Шаг 3 — первая запись (два тула)

- `xml_modify` с `set_attr` / `set_text` только — самая частая правка.
- `xml_append` — для Patch и новых Def'ов.

К этому моменту writer проверен прототипом, адресация проверена на Шаге 1.

### Шаг 4 — документ

Описывает то, что работает. Уточняет формулировки §3–5 после реального прогона.

### Шаг 5 — остальное

- `xml_list` — если `xml_map` на уровне файла недостаточно.
- `xml_insert` / `xml_delete` / `xml_replace`.
- Полный `xml_modify` с `remove_attr` / `set_annotation`.
- Namespaces по URI — когда упрётся.

## 12. Пример полного workflow
<!-- summary: Задача «добавь SteelWall с крафтом» — шесть вызовов, без grep по 100 файлам. -->

Задача: «добавь в мой мод блок SteelWall с крафтом».

```
1. xml_map("Mods/MyMod/")                                    → структура мода
2. xml_find(tag="ThingDef", where={"defName": "*Wall*"})     → пример: vanilla Wall
3. xml_read("Defs/Buildings/Walls.xml", "Defs/ThingDef[Wall]")  → образец
4. create_file("Defs/Buildings/SteelWall.xml", <ThingDef>…)
5. xml_find(tag="RecipeDef", where={"product": "*Wall*"})     → пример рецепта
6. xml_append("Defs/Recipes/WallRecipes.xml", "Defs",
              "<RecipeDef>…SteelWall…</RecipeDef>")
```

Шесть вызовов. Без `grep` по 100 файлам. Без чтения vanilla-структуры.

## 13. Что осталось непроработанным
<!-- summary: Namespaces по URI, CDATA как unit (mount point), xml_patch_op, документ после прогона. -->

- **Namespaces по URI.** Сейчас по префиксу. Если один URI с разными префиксами в разных частях файла — qualname неоднозначен.
- **CDATA как unit.** Если в CDATA лежит Lua или MD, это могло бы быть mount point на другой адаптер. Отложено до реальной потребности.
- **`xml_patch_op`** — генерация XPath из адреса тула. Снимает проблему двух синтаксисов в корне, но не в первую версию.
- **Кодировки кроме UTF-8/UTF-16.** Latin-1, Shift-JIS — expat читает, write должен сохранять. Решается в парсере, но не проверено.
- **Документ после прогона.** §3–5 — гипотеза до шага 0. После прогона на реальных файлах формулировки могут измениться.