"""Regenerate toolset blocks in the starter docs from TOOL_MAP.

Usage:
  run_python(path="toolkit/code/manual/gen_toolset_doc.py")            # rewrite
  run_python(path="toolkit/code/manual/gen_toolset_doc.py",
             args=["--check"])                                        # verify only

Three docs, each owns a disjoint subset of TOOL_MAP:

* LLM_START.ru.md   — base tools (everything not in the two groups below)
* XML_START.md      — ``toolkit.tools.xml``
* MCPBridgeRules.md — ``toolkit.tools.grep_mcp``, ``.grep_replace_mcp``

The XML/MCP docs are appended to the starter text only when the user
enables them in the GUI (``include_xml`` / ``include_roblox``); the base
doc never mentions those tools. A tool's group is its class module, so
adding a tool to ``tools/xml.py`` puts it in XML_START automatically.

Coverage is enforced: every TOOL_MAP entry must be assigned to exactly
one doc, else ``--check`` (and the rewrite) fails. Signatures come from
``inspect.signature``. Each block lives between ``<!-- tools:auto:begin -->``
and ``<!-- tools:auto:end -->``; text outside the markers is untouched.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # toolkit/code

from toolkit.tools import TOOL_MAP  # noqa: E402

DOCS_DIR = HERE.parents[1] / "docs"
BEGIN = "<!-- tools:auto:begin -->"
END = "<!-- tools:auto:end -->"

SKIP = {"self", "backend", "fmt"}

# tool module -> doc it belongs to. Everything else lands in the base doc.
XML_MODULE = "toolkit.tools.xml"
MCP_MODULES = {"toolkit.tools.grep_mcp", "toolkit.tools.grep_replace_mcp"}

# Render order inside a section; tools not listed go after, alphabetically.
ORDER: dict[str, list[str]] = {
    "base": [
        "read_file", "read_unit", "list_units", "file_stat", "file_exists",
        "list_files", "survey_dir", "tree", "grep",
        "replace_unit", "insert_block", "remove_unit", "create_unit", "copy_unit",
        "replace_in_file", "replace_range", "replace_between", "insert_at_anchor",
        "create_file", "overwrite_file", "delete_file", "move_file", "copy_file",
        "get_index", "get_status", "rebuild_index", "rebuild_code_index",
        "rebuild_csharp_index", "rebuild_lua_code_index",
        "find_symbol", "find_usages", "symbol_graph",
        "run_python", "verify_syntax", "get_scope", "exclude", "include",
        "set_scope", "clear_scope", "grep_replace",
    ],
    "xml": [
        "xml_read", "xml_find", "xml_map", "xml_insert", "xml_replace",
        "xml_modify", "xml_append", "xml_delete", "xml_copy", "xml_move",
    ],
    "mcp": ["grep_mcp", "grep_lua", "grep_replace_mcp"],
}

NOTES: dict[str, str] = {
    "grep": " — `paths` обязателен",
    "insert_block": " — `position` = `start`\\|`end`; якоря взаимоисключающие, "
                    "`address` = контейнер, якорь = точка внутри",
    "get_index": " — `kind` обязателен (в сигнатуре; без него `missing_arg`); "
                 "по умолчанию overview, `sections=true` — полный список секций",
    "run_python": " — ровно один из `path`/`module`/`code`",
    "rebuild_csharp_index": " — те же аргументы",
    "grep_lua": " — legacy-алиас `grep_mcp`",
}

OVERRIDE: dict[str, str] = {
    "rebuild_csharp_index": "rebuild_csharp_index(...)",
    "grep_lua": "grep_lua(...)",
}


def _group(tool_name: str) -> str:
    mod = getattr(TOOL_MAP[tool_name], "__module__", "")
    if mod == XML_MODULE:
        return "xml"
    if mod in MCP_MODULES:
        return "mcp"
    return "base"


def _sig(tool_name: str) -> str:
    if tool_name in OVERRIDE:
        return OVERRIDE[tool_name]
    cls = TOOL_MAP[tool_name]
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
        excl = {"path", "module", "code"}
        rest = [x for x in params if x.rstrip("?") not in excl]
        params = ["path\\|module\\|code"] + rest
    return f"{tool_name}({', '.join(params)})"


def _ordered(group: str, names: list[str]) -> list[str]:
    pref = ORDER.get(group, [])
    rank = {n: i for i, n in enumerate(pref)}
    return sorted(names, key=lambda n: (rank.get(n, len(pref)), n))


def _coverage() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {"base": [], "xml": [], "mcp": []}
    for name in TOOL_MAP:
        groups[_group(name)].append(name)
    for g in groups:
        groups[g] = _ordered(g, groups[g])
    return groups


def _render_group(group: str) -> str:
    names = _coverage()[group]
    lines = [f"- `{_sig(n)}`" + NOTES.get(n, "") for n in names]
    return "\n".join(lines)


def _render_base() -> str:
    # Base doc keeps its curated section headings; each section lists the
    # tools assigned to it by the ORDER table, in that order. Sections are
    # fixed; a tool missing from ORDER still renders in the trailing block.
    groups = _coverage()
    base = groups["base"]
    sections: list[tuple[str, list[str]]] = [
        ("**Чтение**", ["read_file", "read_unit", "list_units", "file_stat",
                        "file_exists", "list_files", "survey_dir", "tree", "grep"]),
        ("**Unit**", ["replace_unit", "insert_block", "remove_unit",
                      "create_unit", "copy_unit"]),
        ("**Запись (escape hatch)**", ["replace_in_file", "replace_range",
                                       "replace_between", "insert_at_anchor"]),
        ("**Файлы**", ["create_file", "overwrite_file", "delete_file",
                       "move_file", "copy_file"]),
        ("**Индекс**", ["get_index", "get_status", "rebuild_index",
                        "rebuild_code_index", "rebuild_csharp_index",
                        "rebuild_lua_code_index"]),
        ("**Граф**", ["find_symbol", "find_usages", "symbol_graph"]),
        ("**Прочее**", ["run_python", "verify_syntax", "get_scope", "exclude",
                        "include", "set_scope", "clear_scope", "grep_replace"]),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for title, names in sections:
        present = [n for n in names if n in base]
        seen.update(present)
        out.append(title)
        for n in present:
            out.append(f"- `{_sig(n)}`" + NOTES.get(n, ""))
        out.append("")
    left = [n for n in base if n not in seen]
    if left:
        out.append("**Прочее (продолжение)**")
        for n in left:
            out.append(f"- `{_sig(n)}`" + NOTES.get(n, ""))
        out.append("")
    out.append("> **Аргументы:** один путь — `path`, много — `paths`. "
               "Неверный аргумент — явная ошибка `unknown_arg` со списком валидных.")
    return "\n".join(out)


def render(group: str) -> str:
    return _render_base() if group == "base" else _render_group(group)


TARGETS = {
    "base": DOCS_DIR / "LLM_START.ru.md",
    "xml": DOCS_DIR / "XML_START.md",
    "mcp": DOCS_DIR / "MCPBridgeRules.md",
}


def splice(text: str, block: str, path: Path) -> str:
    i = text.find(BEGIN)
    j = text.find(END)
    if i < 0 or j < 0 or j < i:
        raise SystemExit(f"markers not found in {path} (need {BEGIN} / {END})")
    head = text[: i + len(BEGIN)]
    tail = text[j:]
    return head + "\n" + block.rstrip("\n") + "\n" + tail


def main(argv: list[str]) -> int:
    check = "--check" in argv
    rc = 0
    for group, path in TARGETS.items():
        try:
            cur = path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"cannot read {path}: {e}")
            rc = 2
            continue
        new = splice(cur, render(group), path)
        if new == cur:
            print(f"{path.name}: up to date")
            continue
        if check:
            print(f"{path.name}: STALE — toolset block does not match TOOL_MAP")
            rc = 1
        else:
            path.write_text(new, encoding="utf-8")
            print(f"{path.name}: rewritten from TOOL_MAP")
    if rc == 1:
        print("run: run_python(path='toolkit/code/manual/gen_toolset_doc.py')")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
