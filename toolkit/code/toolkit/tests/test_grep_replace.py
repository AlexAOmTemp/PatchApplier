"""Tests for `grep_replace` (FS) — symmetry with `grep`, dry_run, apply."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import FilesystemBackend  # noqa: E402
from toolkit.tools.read import GrepTool  # noqa: E402
from toolkit.tools.grep_replace import GrepReplaceTool  # noqa: E402


PASS = "[OK]  "
FAIL = "[FAIL]"


class T:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def expect(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"{PASS} {label}")
            self.passed += 1
        else:
            print(f"{FAIL} {label}" + (f" -- {detail}" if detail else ""))
            self.failed += 1


SEED = "foo foo\nbar baz\nfoo2\nFOO\n"


def main() -> int:
    t = T()
    grep = GrepTool()
    repl = GrepReplaceTool()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.txt").write_text(SEED, encoding="utf-8")
        be = FilesystemBackend(root)
        be.open()

        # --- symmetry: grep finds something, replace plans same matches
        print("== symmetry ==")
        r1 = grep.execute(be, None, pattern="foo", regex=False,
                          ignore_case=True, paths=["a.txt"])
        t.expect("grep finds matches",
                 r1.status == "ok" and "Совпадений не найдено" not in r1.message,
                 r1.message[:120])

        r2 = repl.execute(be, None, pattern="foo", regex=False,
                          ignore_case=True, paths=["a.txt"],
                          replacement="BAR", dry_run=True)
        t.expect("dry_run ok", r2.status == "ok", r2.message[:120])
        t.expect("dry_run header says dry_run", "[dry_run]" in r2.message, r2.message)
        t.expect("dry_run did not write",
                 (root / "a.txt").read_text(encoding="utf-8") == SEED)

        # --- apply
        print()
        print("== apply ==")
        r3 = repl.execute(be, None, pattern="foo", regex=False,
                          ignore_case=True, paths=["a.txt"],
                          replacement="BAR", dry_run=False)
        t.expect("apply ok", r3.status == "ok", r3.message[:120])
        t.expect("apply header says APPLIED", "[APPLIED]" in r3.message, r3.message)
        after = (root / "a.txt").read_text(encoding="utf-8")
        t.expect("foo gone (any case)", "foo" not in after.lower())
        t.expect("foo2 also replaced (no word_boundary)", "bar2" in after.lower())

        # --- word_boundary excludes foo2
        print()
        print("== word_boundary ==")
        (root / "a.txt").write_text(SEED, encoding="utf-8")
        r4 = repl.execute(be, None, pattern="foo", regex=False,
                          ignore_case=True, word_boundary=True,
                          paths=["a.txt"], replacement="BAR", dry_run=False)
        t.expect("wb apply ok", r4.status == "ok", r4.message[:120])
        after4 = (root / "a.txt").read_text(encoding="utf-8")
        t.expect("wb: foo2 untouched", "foo2" in after4)
        t.expect("wb: standalone foo replaced", "BAR" in after4)

        # --- symmetry after apply
        print()
        print("== symmetry after apply ==")
        r5 = grep.execute(be, None, pattern="foo", regex=False,
                          ignore_case=True, word_boundary=True, paths=["a.txt"])
        t.expect("grep after replace finds nothing",
                 "Совпадений не найдено" in r5.message, r5.message[:120])

        # --- bad_regex
        print()
        print("== bad_regex ==")
        r6 = repl.execute(be, None, pattern="(unclosed", paths=["a.txt"],
                          replacement="x")
        t.expect("bad regex -> error", r6.status == "error")
        t.expect("error_code == bad_regex", r6.error_code == "bad_regex",
                 str(r6.error_code))

        # --- too_many_replacements
        print()
        print("== too_many_replacements ==")
        (root / "a.txt").write_text(SEED, encoding="utf-8")
        r7 = repl.execute(be, None, pattern="o", regex=False,
                          paths=["a.txt"], replacement="0",
                          max_replacements=1, dry_run=False)
        t.expect("overflow -> error", r7.status == "error")
        t.expect("error_code == too_many_replacements",
                 r7.error_code == "too_many_replacements", str(r7.error_code))
        t.expect("file untouched on overflow",
                 (root / "a.txt").read_text(encoding="utf-8") == SEED)

        # --- bad_input: pattern + mappings
        print()
        print("== bad_input ==")
        r8 = repl.execute(be, None, pattern="x", mappings=[{"from": "a", "to": "b"}],
                          paths=["a.txt"], dry_run=True)
        t.expect("both pattern+mappings -> error", r8.status == "error")
        t.expect("error_code == bad_input", r8.error_code == "bad_input",
                 str(r8.error_code))

        # --- mappings require fixed_strings
        print()
        print("== mappings + fixed_strings ==")
        r9 = repl.execute(be, None, mappings=[{"from": "foo", "to": "BAR"}],
                          paths=["a.txt"], dry_run=True)
        t.expect("mappings w/o fixed_strings -> error", r9.status == "error")
        t.expect("error_code == patterns_in_mappings_not_supported",
                 r9.error_code == "patterns_in_mappings_not_supported",
                 str(r9.error_code))

        r10 = repl.execute(be, None, mappings=[{"from": "foo", "to": "BAR"}],
                           fixed_strings=True, paths=["a.txt"], dry_run=False)
        t.expect("mappings w/ fixed_strings ok", r10.status == "ok",
                 r10.message[:120])
        after10 = (root / "a.txt").read_text(encoding="utf-8")
        t.expect("mapping applied to foo", "BAR" in after10)
        t.expect("mapping matched inside foo2 (no word_boundary)",
                 "BAR2" in after10)
        t.expect("mapping left FOO alone (case-sensitive)", "FOO" in after10)

        # --- wrong_domain
        print()
        print("== wrong_domain ==")
        r11 = repl.execute(be, None, pattern="x", directory="ReplicatedStorage.Foo",
                           replacement="y")
        t.expect("mcp path -> wrong_domain", r11.status == "error")
        t.expect("error_code == wrong_domain", r11.error_code == "wrong_domain",
                 str(r11.error_code))

        be.close()

    print()
    if t.failed:
        print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok, {t.failed} failed ===")
        return 1
    print(f"=== \u0418\u0422\u041e\u0413: {t.passed} ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
