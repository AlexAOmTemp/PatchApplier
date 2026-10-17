# XML_FIXTURES — контракт до кода
<!-- summary: Таблица ожидаемых результатов для XML-тулсета. Реальные сэмплы (RimWorld, Cyberpunk, Skyrim) и синтетические edge cases. Фиксирует контракт до появления парсера. Шаг 0 из XML_TOOLSET §11. -->
<!-- tags: xml, fixtures, contract, step0 -->

> **Статус:** Шаг 0 из `XML_TOOLSET.md §11` — контракт до кода. Фиксирует, что **должен** делать парсер, до того как он написан. Тесты появятся на Шаге 1–3, но их ожидания уже определены здесь.
>
> **Связь с XML_TOOLSET.** §3–5 дизайна (`XML_TOOLSET.md`) — гипотеза. Этот документ — конкретика: какие реальные файлы, что проверяют, что ожидается. После прогона на реальных файлах §3–5 могут быть уточнены.

## 1. Зачем отдельный документ
<!-- summary: Контракт до кода. Тесты после реализации проверяют то, что решил парсер; fixtures до реализации — то, что парсер должен решать. Разные вопросы. -->

Обычный порядок «сначала код, потом тесты» фиксирует **текущее поведение**, а не **желаемое**. Для XML-тулсета это опасно: парсер адресов, writer по спанам и mixed-content-проверка — три места, где «как получилось» легко становится контрактом по инерции.

Fixtures до кода отвечают на вопрос «что должен делать парсер», а не «что он сейчас делает». Тесты после — на второй вопрос.

## 2. Реальные сэмплы в проекте
<!-- summary: Шесть файлов из RimWorld/Data и RimWorld/Mods покрывают все шесть диалектов, найденных при разведке. Путь → что проверяет → ожидаемый результат. -->

Все пути — относительно корня `RimWorld`.

### 2.1 RimWorld vanilla Def

**Файл:** `Data/Anomaly/Defs/Misc/Roofs.xml` (13 строк, 0.3 KB)

**Что проверяет:**
- `defName` как дискриминатор для `RoofDef`.
- **BOM** (`\ufeff`) в начале файла — не должен попасть в qualname и не должен потеряться при write.
- **CRLF** (`\r\n`) — не должен превратиться в `\n`.

**Ожидаемый результат:**
- `xml_read("Data/Anomaly/Defs/Misc/Roofs.xml", "Defs/RoofDef[VoidmetalRoof]")` → текст элемента с оригинальными `\r\n`.
- `xml_modify(..., set_text=..., ...)` на `label` → файл остаётся с BOM и CRLF, меняется только целевая строка.

### 2.2 RimWorld Abstract-Def

**Файл:** `Data/Anomaly/Defs/AbilityDefs/Abilities.xml` L6–L17

```xml
<AbilityDef Name="SpikeLaunchBase" Abstract="True">
```

**Что проверяет:**
- `@Name` как fallback-дискриминатор, когда `defName` нет (`Abstract="True"`).
- Порядок fallback `[defName, "@Name"]`: сначала пробуем `defName`, если нет — `@Name`.

**Ожидаемый результат:**
- `xml_read(..., "Defs/AbilityDef[SpikeLaunchBase]")` → элемент L6–L17.
- Адрес по `defName` тоже работает (для не-Abstract Def'ов, например L34 `SpikeLaunch_Toughspike`).

### 2.3 RimWorld: неоднозначный дискриминатор

**Файл:** `Data/Anomaly/Defs/AbilityDefs/Abilities.xml` L118, L147, L305, L346, L384

`<li Class="...">` внутри `<comps>`. Класс `CompProperties_AbilityFleckOnTarget` встречается **дважды** (L305, L346).

**Что проверяет:**
- Контекстный дискриминатор `comps/li → @Class`.
- Неоднозначность при повторе класса.
- `occurrence` как селектор.

**Ожидаемый результат:**
- `xml_read(..., ".../comps/li[CompProperties_AbilityFleckOnTarget]")` без `occurrence` → `ambiguous_address` с перечислением L305 и L346.
- С `occurrence=1` → L305. С `occurrence=2` → L346.
- С `occurrence=3` → `occurrence_out_of_range`.

### 2.4 RimWorld Patch

**Файл:** `Mods/1123043922/1.0/Patches/Patch_GeneticRimPatchReplaceToNeutroglycerin_SparklingWorlds.xml` (219 строк)

**Что проверяет:**
- `Patch/Operation` как структурный адрес (10+ `Operation`, все с `@Class`).
- `<xpath>` — **настоящий XPath**, не адрес тула. Содержимое `xpath` не парсится парсером адресов.
- `success`, `operations` — вложенные элементы `Operation`.

**Ожидаемый результат:**
- `xml_read(..., "Patch/Operation[PatchOperationSequence]")` без `occurrence` → `ambiguous_address` с 10+ кандидатами.
- `xml_read(..., "Patch/Operation[PatchOperationSequence]", occurrence=3)` → третий `Operation`.
- Содержимое `<xpath>*/ThingDef[defName="GR_AlphaBoomalope"]/comps/li[resourceDef="Chemfuel"]</xpath>` — **не** разбирается парсером адресов. Оно уходит в `xml_read` как текст.

### 2.5 RimWorld About + CDATA + контекстные дискриминаторы

**Файл:** `Mods/3014915404/About/About.xml` (36 строк)

**Что проверяет:**
- **CDATA** внутри `<description>`: `<![CDATA[Framework which allows the creation of vehicles in RimWorld.]]>`.
- Контекстный дискриминатор **ребёнок, не атрибут**: `modDependencies/li` → `packageId`.
- **Текстовые** `li` без дискриминатора: `supportedVersions/li`, `loadAfter/li`, `forceLoadAfter/li`, `incompatibleWith/li` → `[N]` fallback.

**Ожидаемый результат:**
- `xml_read(..., "ModMetaData/modDependencies/li[brrainz.harmony]")` → элемент с `<packageId>brrainz.harmony</packageId>`.
- `xml_read(..., "ModMetaData/supportedVersions/li[2]")` → `<li>1.5</li>` (1-based).
- `xml_modify(..., set_text="...", ...)` на `description` (с CDATA) → **открытый вопрос** (§6): заменить CDATA на экранированный текст с warning или сохранить CDATA-обёртку.

### 2.6 Cyberpunk tweakdb — `:` в значении

**Файл:** `PatchApplier/AnotherXML/Cyberpunk.xml` (20 строк)

```xml
<record_update dbid="gamedataStatModifierGroup_Record:PlayerBaseCarryCapacity">
```

**Что проверяет:**
- `@dbid` как дискриминатор (`record_update`).
- Значение содержит `:` — **не** разделитель namespace, **не** разделитель сегментов. Просто часть значения.
- `item` внутри `statModifiers` — `@dbid` с `:` тоже.

**Ожидаемый результат:**
- `xml_read(..., "tweakdb/record_update[gamedataStatModifierGroup_Record:PlayerBaseCarryCapacity]")` → корректно.
- Парсер адресов **не** пытается трактовать `:` как что-либо особенное.
- `xml_read(..., "tweakdb/record_update[...]/statModifiers/item[gamedataConstantStatModifier_Record:BaseWeightLimit]")` → корректно.

### 2.7 Skyrim physics — пробелы в значении и namespace-префикс

**Файл:** `PatchApplier/AnotherXML/Scyrim.xml` (23 строки)

```xml
<physics xmlns:xsi="http://w3.org" xsi:noNamespaceSchemaLocation="space.xsd">
  <bone name="NPC Cape1">
    <inertia x="0.1" y="0.1" z="0.1"/>
  </bone>
```

**Что проверяет:**
- `@name` со **пробелом** в значении: `"NPC Cape1"` — пробел не разделитель, не часть грамматики адреса.
- Namespace-префикс `xsi:` в атрибуте (`xsi:noNamespaceSchemaLocation`) — по контракту **буквальный префикс**, не нормализация.
- Self-closing `<inertia .../>` — не ломает `read`.

**Ожидаемый результат:**
- `xml_read(..., "physics/bones/bone[NPC Cape1]")` → корректно (пробел в значении).
- `xml_modify(..., set_attr={name: "xsi:noNamespaceSchemaLocation", value: "..."}, ...)` → добавляет атрибут с буквальным префиксом. **Открытый вопрос** (§6): `set_attr` на существующий `xsi:`-атрибут — сохранять ли префикс.
- `xml_read(..., "physics/bones/bone[NPC Cape1]/inertia")` → self-closing прочитан, L9.

### 2.8 RimWorld: stuffCategories — текст и self-closing
<!-- summary: Текстовые li без дискриминатора — [N] fallback. Self-closing с атрибутом — read работает, set_attr сохраняет форму. -->

**Файлы:** `Data/Anomaly/Defs/ThingDefs_Misc/Apparel_Cult.xml` L14, L100 (с текстовыми `<li>`), `Data/Anomaly/Defs/HediffDefs/Hediffs_BodyParts_Prosthetic.xml` L251, `Data/Anomaly/Defs/ThingDefs_Buildings/Buildings_Misc.xml` L771 (self-closing с `Inherit`).

**Что проверяет:**
- Текстовые `li` без дискриминатора: `<stuffCategories><li>Metallic</li><li>Woody</li></stuffCategories>` — `[N]` fallback (дискриминатор `null` в конфиге).
- Self-closing `<stuffCategories Inherit="false"/>` — атрибут есть, детей нет.

**Ожидаемый результат:**
- `xml_read(..., ".../stuffCategories/li[1]")` → первый `<li>` (`Metallic`).
- `xml_read(..., ".../stuffCategories/li[2]")` → второй `<li>` (`Woody`).
- `xml_read(..., ".../stuffCategories")` на self-closing → прочитан, `Inherit="false"`.
- `xml_modify(..., set_attr {name: "Inherit", value: "true"})` на self-closing → `<stuffCategories Inherit="true"/>`, форма не меняется.

## 3. Синтетические фикстуры
<!-- summary: Edge cases, которых нет в реальных данных. Mixed content, xml:space, DTD, UTF-16, self-closing + set_text, stale source. Каждый — минимальный XML. -->

Создаются в `toolkit/tests/fixtures/xml/` на Шаге 1 (когда появится первый тул). Здесь — только контракт.

### 3.1 Mixed content — отклонять

```xml
<prefix>Hello <b>world</b>!</prefix>
```

**Ожидаемый результат:** `xml_read` → OK (чтение работает). `xml_modify` с `set_text`, `xml_append`, `xml_insert` → `error_code="mixed_content_unsupported"`. Структурные операции невозможны.

### 3.2 Структурные пробелы — допустимо

```xml
<statBases>
  <MarketValue>1.5</MarketValue>
  <Mass>2.0</Mass>
</statBases>
```

**Ожидаемый результат:** не mixed. `xml_append`, `xml_insert`, `xml_modify` работают нормально.

### 3.3 Текстовый лист — допустимо для `set_text`

```xml
<MarketValue>1.5</MarketValue>
```

**Ожидаемый результат:** `set_text` заменяет текст. Детей нет — `has_children` не срабатывает.

### 3.4 `set_text` на элементе с детьми — отклонять

```xml
<verbProperties>
  <verbClass>Verb_AbilityShoot</verbClass>
</verbProperties>
```

**Ожидаемый результат:** `xml_modify(set_text=..., ...)` → `error_code="has_children"`. Файл не тронут. Для замены содержимого — `xml_replace`.

### 3.5 `xml:space="preserve"` — отклонять

```xml
<pre xml:space="preserve">  two  spaces  </pre>
```

**Ожидаемый результат:** `error_code="xml_space_preserve_unsupported"`. Не переформатировать молча.

### 3.6 DTD с entity — отклонять

```xml
<!DOCTYPE root [ <!ENTITY foo "bar"> ]>
<root>&foo;</root>
```

**Ожидаемый результат:** `error_code="dtd_unsupported"`. Не разворачивать `&foo;` в `bar`.

### 3.7 UTF-16 BOM

Файл с BOM `\xff\xfe` и UTF-16LE-кодировкой, содержащий `<root><a>x</a></root>`.

**Ожидаемый результат:** read → текст. Write — **в той же кодировке**, BOM сохраняется.

### 3.8 Self-closing + set_text

```xml
<a/>
```

**Ожидаемый результат:** `set_text="v"` → `<a>v</a>` (парный тег). `set_attr="x", "y"` → `<a x="y"/>` (остаётся self-closing).

### 3.9 Stale source

Сценарий: `xml_read` → файл меняется на диске → `xml_modify` по старому адресу.

**Ожидаемый результат:** `error_code="source_changed"`. Никаких изменений. Механика — сравнение хеша содержимого (не `mtime`).

### 3.10 `[N]` сдвиг при insert

```xml
<comps>
  <li Class="A"/>
  <li Class="B"/>
</comps>
```

`xml_insert(..., ".../comps/li[A]", position="before", fragment="<li Class=\"Z\"/>")`.

**Ожидаемый результат:** `Z` вставлен перед `A`. Новые адреса: `li[Z]` (позиция 1), `li[A]` (позиция 2), `li[B]` (позиция 3). В ответе — `warning="sibling_indices_shifted"` и `new_addresses=[...]`.

### 3.11 Экранирование `]` в значении
<!-- summary: Значение с `]`, `[`, `\`, `/` — экранируются обратным слэшем. Без escape парсер путает закрытие селектора с частью значения. -->

**Что проверяет:** `]` внутри значения дискриминатора. Без escape селектор закрывается на первом `]` (`[Weird]Name]` парсится как `[Weird]` + остаток `Name]`); с escape (`Weird\]Name` — обратный слэш перед `]`) — парсится как значение `Weird]Name`.

**Ожидаемый результат:**
- Адрес с escape → корректно, разрешается в элемент с `defName=Weird]Name`.
- Адрес без escape → `bad_address`.
- Все четыре escape из грамматики §3 работают: `\[`, `\]`, `\/`, `\\`.

### 3.12 `xml_modify` — атомарность на `ops`
<!-- summary: Несколько ops в одном вызове — всё или ничего. Сбой одного op откатывает все. -->

**Что проверяет:** `xml_modify` с несколькими `ops` на одном элементе. Один op невалиден (`set_text` на элементе с детьми) — второй op (`set_attr`) валиден.

**Ожидаемый результат:** `error_code="has_children"`, файл не тронут — ни `set_attr` не применился, ни `set_text` не изменил. Атомарность на уровне всего списка `ops`.

## 4. Дискриминаторы по умолчанию
<!-- summary: Mapping из реальных данных. Контекстные суффиксы, fallback-порядок, что проверено на реальных файлах. -->

В `workspace.json` (`.patch_applier/workspace.json`) — секция `xml_discriminators`. Значения по умолчанию, выверенные на реальных файлах:

```yaml
xml_discriminators:
  # Def'ы RimWorld: defName → @Name (для Abstract)
  ThingDef:    [defName, "@Name"]
  AbilityDef:  [defName, "@Name"]
  RecipeDef:   [defName, "@Name"]
  FactionDef:  [defName, "@Name"]
  HairDef:     [defName, "@Name"]
  BodyPartDef: [defName, "@Name"]
  RoofDef:     [defName, "@Name"]

  # Patch (RimWorld)
  Operation:   "@Class"

  # About.xml
  modDependencies/li:     "packageId"        # ребёнок, не атрибут
  supportedVersions/li:   null               # текст, [N]
  loadAfter/li:           null               # текст, [N]
  forceLoadAfter/li:      null               # текст, [N]
  incompatibleWith/li:    null               # текст, [N]

  # comps → @Class
  comps/li:               "@Class"

  # Cyberpunk
  record_update:          "@dbid"
  statModifiers/item:     "@dbid"

  # Skyrim physics
  bone:                   "@name"
  constraint:             "@type"
```

Проверено на реальных файлах (§2): `RoofDef`, `AbilityDef` (abstract + concrete), `comps/li` (двойное вхождение), `Operation` (10+ вхождение), `modDependencies/li` (ребёнок), `supportedVersions/li` (текст), `record_update` (`:` в значении), `bone` (пробел в значении). Не проверено вживую: `ThingDef`, `RecipeDef`, `FactionDef`, `HairDef`, `BodyPartDef`, `statModifiers/item`, `constraint` — синтаксически аналогичны проверенным, но fixtures на них появятся на Шаге 1.

## 5. Куда копируются фикстуры
<!-- summary: Реальные сэмплы остаются в RimWorld (внешний корень). Синтетические — в toolkit/tests/fixtures/xml/. Именование, стабильность. -->

**Реальные сэмплы** (§2) — остаются на месте, в `RimWorld/`. Не копируются в репозиторий утилиты: это внешний мир, объём 1.5 GB, копирование нецелесообразно. Интеграционные прогоны используют их напрямую, пока корень доступен.

**Синтетические фикстуры** (§3) — копируются в `toolkit/tests/fixtures/xml/`:

```
toolkit/tests/fixtures/xml/
  mixed_content.xml
  structural_whitespace.xml
  text_leaf.xml
  has_children.xml
  xml_space_preserve.xml
  dtd_entity.xml
  utf16_bom.xml
  self_closing.xml
  sibling_shift.xml
```

Именование — по сценарию, не по содержимому. Один файл — один сценарий. Тесты на Шаге 1 читают фикстуру и проверяют ожидаемый результат из таблицы выше.

**Реальные сэмплы как integration fixtures** — на Шаге 2 (writer prototype) и Шаге 3 (первая запись) прогоняются **вручную** на реальных файлах из §2. Автотесты на них не пишутся: файлы могут измениться, RimWorld-корень может отсутствовать в CI.

## 6. Открытые вопросы
<!-- summary: CDATA + set_text; @attr с namespace-префиксом; [N] в контексте. Пока не блокируют Шаг 1, но требуют решения до Шага 3. -->

Три вопроса, которые fixtures фиксируют, но не решают. Решение — при появлении первого writer-тула (Шаг 3).

**CDATA + `set_text`.** `<description><![CDATA[...]]></description>` в `About.xml` (§2.5). Что должен делать `set_text`: (a) заменить CDATA-блок на экранированный текст (`&amp;` и т.п.) с warning `cdata_replaced_with_escaped`, или (b) сохранить CDATA-обёртку и заменить только содержимое? Вариант (a) проще и семантически честнее (CDATA — деталь сериализации), но теряет исходную форму. Вариант (b) инвазивнее, но точнее. **Предложение:** (a) с warning, для случаев, где CDATA содержит `<` или `&`; если нет — оставить CDATA. Решение — на Шаге 3.

**`set_attr` на существующий атрибут с namespace-префиксом.** `xsi:noNamespaceSchemaLocation` в `Scyrim.xml` (§2.7). По контракту «буквальный префикс» — `set_attr(name="xsi:noNamespaceSchemaLocation")` работает. Но что если пользователь передаст `name="noNamespaceSchemaLocation"` без префикса? Ошибка `attr_not_found` или матч по локальному имени? **Предложение:** буквальный матч, `attr_not_found` при несовпадении. Namespace-нормализация — TODO (§13 XML_TOOLSET).

**`[N]` — позиционный или по значению?** **Решение (Шаг 1).** `[N]`, где N — последовательность ASCII-цифр (`0-9`), — **всегда позиционный** (1-based). `li[2]` = второй `li` **независимо** от того, есть ли у тега дискриминатор в конфиге. Всё остальное — `[value]`, идёт через дискриминатор. `li[1.5]` = `li` со значением `1.5` (не `.` — не цифра, `isdigit()` вернёт False). `li[Metallic]` = `li` со значением `Metallic`. **Следствие:** `<li>2</li>` позиционно выбрать нельзя — `[2]` перехватывается как позиция. В реальных данных это не встречается (`About.xml` содержит `<li>1.4</li>`, `<li>1.5</li>`, `<li>1.6</li>` — `.` отделяет). Для `<li>2</li>` в будущем — явный `name=value` (не реализован в первой версии, см. §13 XML_TOOLSET).

**Дискриминатор: откуда берётся имя.** Только из конфига (`workspace.json` → `xml_discriminators`) или дефолтной fallback-цепочки. В самом адресе форма `name=value` **не поддерживается** в первой версии — ни одного fixture на неё нет. Префикс `@` в значении (`[@Name]`) — не «атрибут `Name`», а литеральная строка `@Name` (ни один fixture на такое не полагается).

**Fallback без конфига.** Если тег не в конфиге — пробуем по порядку: `defName` (ребёнок), `@Name`, `@name`, `@id`, `@key`, `artifactId` (ребёнок), затем — **собственный текст элемента**. Последнее звено критично для `<li>1.4</li>` и `<li>Metallic</li>` (текстовые `li` без атрибутов). Для `<li Class="A"/>` внутри `<comps>` собственный текст пуст (self-closing) — без конфига `comps/li: "@Class"` не резолвится.

**`null` в конфиге = дефолт.** `supportedVersions/li: null` означает тот же fallback, что и без записи. Разницы между `null` и отсутствием записи **нет** — это документирующая запись, не отдельный режим.
