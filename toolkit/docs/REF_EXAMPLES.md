# REF_EXAMPLES — образцы патчей
<!-- pa: suppress no-summary -->

Один фенс = один патч. Все группы — в одном блоке кода.

## Python — заменить тело, сохранив сигнатуру

```json
[{"id":1,"action":"read_unit","arguments":{"file_path":"PatchAppliers/PatchApplier/toolkit/core/patcher.py","address":{"qualname":"Patcher._apply_one"},"part":"head,annotation"}}]

[{"id":2,"action":"replace_unit","arguments":{"file_path":"PatchAppliers/PatchApplier/toolkit/core/patcher.py","address":{"qualname":"Patcher._apply_one"},"part":"body","new_text":"return self._dispatch(patch)"}}]
```

`part="body"` сохраняет head и annotation.

## md — обновить body и annotation

```json
[{"id":1,"action":"replace_unit","arguments":{"file_path":"PatchAppliers/PatchApplier/toolkit/docs/ARCHITECTURE.md","address":{"qualname":"3"},"part":"body","new_text":"Новое тело секции."}}]

[{"id":2,"action":"replace_unit","arguments":{"file_path":"PatchAppliers/PatchApplier/toolkit/docs/ARCHITECTURE.md","address":{"qualname":"3"},"part":"annotation","new_text":"Обновлённое описание"}}]
```

У md-секций `address={"qualname": "N"}` — номер секции без точки.

## Escape hatch — точная замена строки

```json
[{"id":1,"action":"read_file","arguments":{"file_path":"PatchAppliers/PatchApplier/toolkit/core/patcher.py","start_line":42,"end_line":44}}]

[{"id":2,"action":"replace_in_file","arguments":{"file_path":"PatchAppliers/PatchApplier/toolkit/core/patcher.py","search":"        return None\n","replace":"        return self._default()\n","search_repr":true}}]
```

`search` копируй из `read_file` (per-line repr) — иначе промах по пробелам.

## Массовая замена — dry_run → apply

```json
[{"id":1,"action":"grep_replace","arguments":{"pattern":"old_function","replacement":"new_function","directory":"PatchAppliers/PatchApplier/toolkit","file_glob":"*.py","dry_run":true}}]
```

Проверил `total` — если ожидаемо:

```json
[{"id":2,"action":"grep_replace","arguments":{"pattern":"old_function","replacement":"new_function","directory":"PatchAppliers/PatchApplier/toolkit","file_glob":"*.py","dry_run":false,"max_replacements":50}}]
```

## Scope — сузить / вернуть

```json
[{"id":1,"action":"exclude","arguments":{"patterns":["tests/","vendor/"],"reason":"правка core, тесты не нужны"}}]

[{"id":2,"action":"get_status","arguments":{"sections":"scope"}}]
```

Возврат: `include(patterns=["tests/"])` или `clear_scope()`.

## Найти все символы execute и прочитать один

```json
[{"id":1,"action":"find_symbol","arguments":{"query":"execute","limit":20,"max_bytes":2000}}]

[{"id":2,"action":"read_unit","arguments":{"file_path":"PatchAppliers/PatchApplier/toolkit/tools/read.py","address":{"qualname":"GrepTool.execute"},"part":"body"}}]
```
