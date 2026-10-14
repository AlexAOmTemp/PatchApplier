"""Smoke for SurveyDirTool — counts by extension and first-level subdir.

Run: python toolkit/code/manual/smoke_survey_dir.py
Exits non-zero on any failed check.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from toolkit.backends import FilesystemBackend  # noqa: E402
from toolkit.core import Session  # noqa: E402
from toolkit.formats import Format  # noqa: E402
from toolkit.tools import TOOL_MAP  # noqa: E402


FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK' if ok else 'FAIL'}  {label}" + (f" -- {detail}" if not ok and detail else ""))
    if not ok:
        FAILS.append(label)


def _setup(root: Path) -> None:
    (root / "a.py").write_text("x")
    (root / "b.py").write_text("x")
    (root / "README.md").write_text("x")
    sub = root / "sub"
    sub.mkdir()
    (sub / "c.py").write_text("x")
    (sub / "d.txt").write_text("x")
    (sub / "e.png").write_text("x")
    deep = sub / "deeper"
    deep.mkdir()
    (deep / "f.py").write_text("x")


def _ext_section(msg: str) -> str:
    if "по расширениям" not in msg:
        return ""
    tail = msg.split("по расширениям", 1)[1]
    if "подкаталоги" in tail:
        tail = tail.split("подкаталоги", 1)[0]
    return tail


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _setup(root)
        be = FilesystemBackend(root)
        fmt = Format.load("default")
        with Session(be, fmt=fmt, tools=TOOL_MAP) as s:
            # Full survey. 7 files + .patchignore auto-created by backend.
            r = s.apply_patches([{
                "id": 1, "action": "survey_dir",
                "arguments": {"path": ""},
            }])[0]
            check("ok", r.status == "ok", r.message[:120])
            check("header has total", "файлов" in r.message.splitlines()[0],
                  r.message.splitlines()[0] if r.message else "")
            check("counts .py", ".py" in r.message)
            check("counts .md", ".md" in r.message)
            check("lists subdir", "sub" in r.message)

            # Extension filter
            r = s.apply_patches([{
                "id": 2, "action": "survey_dir",
                "arguments": {"path": "", "ext": ".py"},
            }])[0]
            check("ext filter ok", r.status == "ok")
            ext_sec = _ext_section(r.message)
            check("ext filter shows .py", ".py" in ext_sec, ext_sec)
            check("ext filter hides .md", ".md" not in ext_sec, ext_sec)

            # Scoped to subdir
            r = s.apply_patches([{
                "id": 3, "action": "survey_dir",
                "arguments": {"path": "sub"},
            }])[0]
            check("scoped ok", r.status == "ok")
            check("scoped sees 4 files", "4 файлов" in r.message, r.message.splitlines()[0])

    print()
    if FAILS:
        print(f"{len(FAILS)} failure(s):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
