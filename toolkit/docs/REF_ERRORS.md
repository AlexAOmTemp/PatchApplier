# REF_ERRORS — коды ошибок
<!-- pa: suppress no-summary -->

`Result` содержит `error_code` — машиночитаемую метку. Что делать:

| Код | Что значит | Что делать |
|---|---|---|
| `not_found` | unit / секция / файл / адрес не найдены | Прочитай индекс или `read_unit` / `read_file`; не угадывай |
| `ambiguous_symbol` | адрес встречается N раз | Передай `occurrence=N` (L-диапазоны в сообщении) |
| `occurrence_out_of_range` | N вне диапазона | Смотри реальное число в сообщении |
| `no_match` | `replace_in_file`: `search` не найден | Прочитай `Similar lines` — обычно пробел/таб; копируй `search` из `read_file` |
| `no_annotation` | `replace_unit(part="annotation")` без annotation | Создать — `create_unit(part="annotation")` |
| `empty_input` | `new_text` пустой | Для удаления — `remove_unit` |
| `scope_required` / `scope_conflict` | `replace_unit` без `part`/`block` или с обоими | Ровно одно из двух |
| `syntax_error` / `result_syntax_error` | файл / новый текст не парсится | Файл не тронут; поправь `new_text` |
| `result_missing_symbol` | после правки unit исчез | Патч отменён; перечитай файл |
| `range_order` / `range_after_write` | `replace_range` сверху вниз или после другого write | Сначала `replace_range` снизу вверх, **до** других write на файл |
| `hidden_path` / `filter` / `sandbox` | `status=blocked`: политика / песочница | Не retry — сообщи пользователю |
| `backend_not_ready` | MCP (Roblox) не поднят | Попроси нажать `↻` в GUI |
| `native_tools_disabled` / `exec_disabled` | гейт в конфиге | Не ошибка — тул просто недоступен |
| `timeout` / `nonzero_exit` | `run_python` | Сообщение содержит `TIMED_OUT` / `exit=N` |
| `already_exists` | `create_file` / `create_unit(annotation)` | Файл уже есть; для annotation — `replace_unit` |
| `source_changed` (XML) | `source_hash` не совпал | Перечитай `xml_read`, повтори с новым хешем |

Код не в таблице — прочитай `message`: обычно объясняет причину. Не retry `blocked`. Не гадай адрес при `not_found` / `ambiguous_*`.

## Специфика старых правил

- `wrong_domain` — `grep` по Roblox-пути; используй `grep_mcp`.
- `bad_options` — неверная комбинация аргументов (например, `paths` содержит каталог, `numbered=true` + `escape=blob`).
- `bad_regex` — некорректная регулярка; проверь `pattern`.
