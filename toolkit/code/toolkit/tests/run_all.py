"""Run all toolkit tests in order. Exit code = 1 on any failure."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


SCRIPTS = [
    ("parser", HERE / "test_parser.py"),
    ("code parser", HERE / "test_code_parser.py"),
    ("indexer", HERE / "test_indexer.py"),
    ("code indexer", HERE / "test_code_indexer.py"),
    ("reverse deps", HERE / "test_reverse_deps.py"),
    ("lua indexer", HERE / "test_lua_indexer.py"),
    ("lua reverse deps", HERE / "test_lua_reverse_deps.py"),
    ("code diff", HERE / "test_code_diff.py"),
    ("write tools", HERE / "test_write.py"),
    ("write matcher", HERE / "test_matching_text.py"),
    ("replace in file", HERE / "test_replace_in_file.py"),
    ("range order", HERE / "test_range_order.py"),
    ("grep replace", HERE / "test_grep_replace.py"),
    ("file ops", HERE / "test_fileops.py"),
    ("find symbol", HERE / "test_find_symbol.py"),
    ("find usages", HERE / "test_find_usages.py"),
    ("mcp backend", HERE / "test_mcp_backend.py"),
    ("composite backend", HERE / "test_composite_backend.py"),
    ("run_python", HERE / "test_run_python.py"),
    ("index version", HERE / "test_index_version.py"),
    ("copy unit", HERE / "test_copy_unit.py"),
    ("lua symbols", HERE / "test_lua_symbols.py"),
    ("native tools", HERE / "test_native_tools.py"),
    ("router", HERE / "test_router.py"),
    ("get_index", HERE / "test_get_index.py"),
    ("get_status", HERE / "test_get_status.py"),
    ("xml address", HERE / "test_xml_address.py"),
    ("xml discriminator", HERE / "test_xml_discriminator.py"),
    ("xml reader", HERE / "test_xml_reader.py"),
    ("xml resolver", HERE / "test_xml_resolver.py"),
    ("xml tool", HERE / "test_xml_tool.py"),
    ("xml find", HERE / "test_xml_find.py"),
    ("xml map", HERE / "test_xml_map.py"),
    ("xml writer", HERE / "test_xml_writer.py"),
    ("xml modify", HERE / "test_xml_modify.py"),
    ("xml append", HERE / "test_xml_append.py"),
    ("xml append tool", HERE / "test_xml_append_tool.py"),
    ("xml delete replace", HERE / "test_xml_delete_replace.py"),
    ("xml copy move", HERE / "test_xml_copy_move.py"),
    ("xml refinements", HERE / "test_xml_refinements.py"),
    ("starter text", HERE / "test_starter_text.py"),
    ("unit cs", HERE / "test_unit_cs.py"),
    ("csharp index", HERE / "test_csharp_index.py"),
]


# NOTE: test_live_studio.py is intentionally NOT in SCRIPTS.
# It requires a running Roblox Studio + bridge and is meant to be run
# manually:
#     python toolkit/code/toolkit/tests/test_live_studio.py


def main():
    failures = 0
    for label, script in SCRIPTS:
        print("=" * 60)
        print(f"[{label}] {script.name}")
        print("=" * 60)
        rc = subprocess.call([sys.executable, str(script)])
        if rc != 0:
            failures += 1
            print(f"[!] {script.name} exited with code {rc}")
        print()
    # Consistency: LLM_START toolset block must match TOOL_MAP.
    print("=" * 60)
    print("[tools doc] LLM_START toolset block vs TOOL_MAP")
    print("=" * 60)
    gen = HERE.parent / "manual" / "gen_toolset_doc.py"
    rc = subprocess.call([sys.executable, str(gen), "--check"])
    if rc != 0:
        failures += 1
        print(f"[!] {gen.name} --check exited with code {rc}")
    print()

    print("=" * 60)
    if failures:
        print(f"=== \u0418\u0422\u041e\u0413: {failures} script(s) failed ===")
        return 1
    print("=== \u0418\u0422\u041e\u0413: all tests passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
