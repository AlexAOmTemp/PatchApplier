"""Regenerate the toolset block in LLM_START from TOOL_MAP.

Usage:
  run_python(path="toolkit/code/manual/gen_toolset_doc.py")            # rewrite
  run_python(path="toolkit/code/manual/gen_toolset_doc.py",
             args=["--check"])                                        # verify only

Source of truth is the code: signatures come from each tool's
``execute`` via ``inspect.signature``. The doc block lives between
``<!-- tools:auto:begin -->`` and ``<!-- tools:auto:end -->``; text
outside the markers is never touched.

--check exits 1 if the file differs from what the generator would write.
Wire it into the pre-commit path (or run_all.py) so the docs cannot drift
silently.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # toolkit/code

from toolkit.tools import TOOL_MAP  # noqa: E402

DOC = HERE.parents[1] / "docs" / "LLM_START.ru.md"
BEGIN = "<!-- tools:auto:begin -->"
END = "<!-- tools:auto:end -->"

SKIP = {"self", "backend", "fmt"}

# Which tools go in which section, in order. `None` = render `name(...)`
# shorthand with a note (conditionally enabled groups).
SPEC: list[tuple[str, list[str]]] = [
    ("**Чтение**", [
        "read_file", "read_unit", "list_units", "file_stat", "file_exists",
        "list_files", "survey_dir", "tree", "grep",
    ]),
    ("**Unit**", [
        "replace_unit", "insert_block", "remove_unit", "create_unit", "copy_unit",
    ]),
    ("**Запись (escape hatch)**", [
        "replace_in_file", "replace_range", "replace_between", "insert_at_anchor",
    ]),
    ("**Файлы**", [
        "create_file", "overwrite_file", "delete_file", "move_file", "copy_file",
    ]),
    ("**Индекс**", [
        "get_index", "get_status", "rebuild_index", "rebuild_code_index",
        "rebuild_csharp_index", "rebuild_lua_code_index",
    ]),
    ("**Граф**", [
        "find_symbol", "find_usages", "symbol_graph",
    ]),
    ("**Прочее**", [
        "run_python", "verify_syntax", "get_scope", "exclude", "include",
        "set_scope", "clear_scope", "grep_replace",
    ]),
]

# Notes appended after a signature (markdown, RU).
NOTES: dict[str, str] = {
    "grep": " — `paths` обязателен",
    "insert_block": " — `position` = `start`\\|`end`; якоря взаимоисключающие, "
                    "`address` = контейнер, якорь = точка внутри",
    "get_index": " — `kind` обязателен (в сигнатуре; без него `missing_arg`); "
                 "по умолчанию overview, `sections=true` — полный список секций",
    "run_python": " — ровно один из `path`/`module`/`code`",
    "rebuild_csharp_index": " — те же аргументы",
}

# Rendered verbatim (signature text only) instead of a generated one.
OVERRIDE: dict[str, str] = {
    "rebuild_csharp_index": "rebuild_csharp_index(...)",
}

# Conditionally enabled groups: name -> (shorthand line, note)
CONDITIONAL: list[tuple[str, str]] = [
    ("MCP (Roblox): `grep_mcp(pattern, directory?, ...)` · `grep_replace_mcp(...)` "
     "· `grep_lua(...)`", "схемы в `REF_TOOLS.md`"),
    ("XML: `xml_read`, `xml_find`, `xml_map`, `xml_insert`, `xml_replace`, "
     "`xml_modify`, `xml_append`, `xml_delete`, `xml_copy`, `xml_move`",
     "`XML_START.md` / `REF_TOOLS.md`"),
]


def _sig(tool_name: str) -> str:
    if tool_name in OVERRIDE:
        return OVERRIDE[tool_name]
    cls = TOOL_MAP.get(tool_name)
    if cls is None:
        return f"{tool_name}(?? missing in TOOL_MAP)"
    fn = getattr(cls, "execute", None)
    if fn is None:
        return f"{tool_name}(?? no execute)"
    params: list[str] = []
    for p in inspect.signature(fn).parameters.values():
        if p.name in SKIP:
            continue
        if p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
            continue
        params.append(p.name + ("?" if p.default is not inspect.Parameter.empty else ""))
    if tool_name == "run_python":
        # path|module|code are mutually exclusive; show as one slot.
        excl = {"path", "module", "code"}
        rest = [x for x in params if x.rstrip("?") not in excl]
        params = ["path\\|module\\|code"] + rest
    return f"{tool_name}({', '.join(params)})"


def render_block() -> str:
    lines: list[str] = []
    for title, names in SPEC:
        lines.append(title)
        for n in names:
            line = f"- `{_sig(n)}`"
            if n in NOTES:
                line += NOTES[n]
            lines.append(line)
        lines.append("")
    lines.append("> **Аргументы:** один путь — `path`, много — `paths`. "
                 "Неверный аргумент — явная ошибка `unknown_arg` со списком валидных.")
    lines.append("")
    lines.append("**Условно включённые**")
    for line, note in CONDITIONAL:
        lines.append(f"- {line} — {note}")
    return "\n".join(lines)


def splice(text: str, block: str) -> str:
    i = text.find(BEGIN)
    j = text.find(END)
    if i < 0 or j < 0 or j < i:
        raise SystemExit(f"markers not found in {DOC} (need {BEGIN} / {END})")
    head = text[: i + len(BEGIN)]
    tail = text[j:]
    return head + "\n" + block.rstrip("\n") + "\n" + tail


def main(argv: list[str]) -> int:
    check = "--check" in argv
    try:
        cur = DOC.read_text(encoding="utf-8")
    except OSError as e:
        print(f"cannot read {DOC}: {e}")
        return 2
    new = splice(cur, render_block())
    if new == cur:
        print(f"{DOC.name}: up to date")
        return 0
    if check:
        print(f"{DOC.name}: STALE — toolset block does not match TOOL_MAP")
        print("run: run_python(path='toolkit/code/manual/gen_toolset_doc.py')")
        return 1
    DOC.write_text(new, encoding="utf-8")
    print(f"{DOC.name}: rewritten from TOOL_MAP")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
