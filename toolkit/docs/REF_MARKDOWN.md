# REF_MARKDOWN — формат md и suppression
<!-- pa: suppress no-summary -->

## Скелет секций

```
## N. Название              ← секция верхнего уровня (min_level=2)
<!-- summary: одна строка -->  ← обязательно для ##
<!-- tags: a, b -->           ← опционально

teло

### N.M Название           ← подсекция
<!-- summary: ... -->        ← опционально
```

- Заголовки: `## N.`, `### N.M`, `#### N.M.K` (пробел после номера, точка только у `##`).
- `summary` — одна строка, без переносов.
- `tags` — через запятую, опционально.

## Suppression маркеров

Если документ **читается целиком** (стартовая инструкция, аудит, манифест), маркер `⚠ no summary` на каждой секции — шум. Подавляется флагом в преамбуле документа (первые 20 строк):

```
# Заголовок документа
<!-- pa: suppress no-summary -->

## 1. Первая секция без summary
```

Что подавляется:
- `no-summary` — не ставить `⚠ no summary` на секциях этого файла

Маркер `⚠ large` не подавляется — он про размер, а не про summary.

## Правка md

- Тело секции: `replace_unit(address={"qualname": "3"}, part="own_body", new_text=...)` — без подсекций.
- Целиком: `replace_unit(part="all")`.
- Аннотация: `replace_unit(part="annotation")` или `create_unit(part="annotation")`.
- Подсекции: `insert_block(address={"qualname": "3"}, position="end")`.
- Заголовки могут повторяться — `section_number` надёжнее, чем `section_title`.
