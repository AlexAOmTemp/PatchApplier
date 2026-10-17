"""Symmetry test: run_python(path=...) resolves through MultiRootFsBackend.

Regression for the bug where run_python(script=...) resolved from
project_root, while create_file / read_file / grep used workspace-relative
paths. Now run_python(path=...) uses backend.resolve_physical, so
create_file + run_python on the same workspace-relative path work.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.config import workspace as ws_mod
from toolkit.core import Session
from toolkit.formats import Format
from toolkit.tools import TOOL_MAP
from toolkit.tools.shell import RunPythonTool


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


def _setup(tmp: Path):
    proj = tmp / "proj"
    (proj / "nested").mkdir(parents=True)
    (proj / "nested" / "x.py").write_text("print('SYM_OK')\n", encoding="utf-8")

    project = tmp / "project"
    state = project / ".patch_applier"
    state.mkdir(parents=True)

    w = ws_mod.Workspace(id="test", name="sym")
    ws_mod.add_root(w, str(proj))
    if not ws_mod.save(w, state):
        raise RuntimeError("could not save workspace")

    wb = MultiRootFsBackend(w, state)
    wb.open()
    return wb, project


def _cfg(project: Path) -> None:
    RunPythonTool.set_config(
        {
            "enabled": True,
            "interpreter": None,
            "allow_module_mode": True,
            "child_encoding": "utf-8",
            "default_timeout": 30,
            "max_timeout": 60,
            "max_output_bytes": 200_000,
            "env_passthrough": ["PATH", "SYSTEMROOT", "PYTHONIOENCODING", "PYTHONUTF8"],
            "env_deny_patterns": ["*_TOKEN", "*_KEY", "*_SECRET"],
        },
        project,
    )


def main():
    t = T()
    _orig_cfg = dict(RunPythonTool._config)
    _orig_root = RunPythonTool._project_root

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td).resolve()
        wb, project = _setup(tmp)
        try:
            # project_root deliberately does NOT contain 'proj'. The old
            # buggy path would try <project>/proj/nested/x.py (missing).
            _cfg(project)

            with Session(wb, fmt=Format.load("default"),
                         tools=TOOL_MAP) as s:
                # 1. Symmetry: workspace-relative path resolves through backend.
                print("== run_python(path=workspace-relative) ==")
                r = s.apply_patches([{
                    "action": "run_python",
                    "arguments": {"path": "proj/nested/x.py"},
                }])[0]
                t.expect("ok", r.status == "ok", f"{r.status}: {r.message}")
                t.expect("stdout SYM_OK", "SYM_OK" in r.message, r.message)

                # 2. create_file + run_python: the exact use case that failed.
                print("== create_file + run_python symmetry ==")
                r = s.apply_patches([{
                    "action": "create_file",
                    "arguments": {
                        "file_path": "proj/nested/y.py",
                        "file_content": "print('CREATED_OK')\n",
                    },
                }])[0]
                t.expect("create ok", r.status == "ok", r.message)

                r = s.apply_patches([{
                    "action": "run_python",
                    "arguments": {"path": "proj/nested/y.py"},
                }])[0]
                t.expect("run created ok", r.status == "ok", r.message)
                t.expect("stdout CREATED_OK", "CREATED_OK" in r.message, r.message)

                # 3. Legacy alias: script= still works.
                print("== run_python(script=) legacy alias ==")
                r = s.apply_patches([{
                    "action": "run_python",
                    "arguments": {"script": "proj/nested/x.py"},
                }])[0]
                t.expect("script alias ok", r.status == "ok", r.message)

                # 4. code= inline: tempfile cleaned up.
                print("== run_python(code=) inline ==")
                r = s.apply_patches([{
                    "action": "run_python",
                    "arguments": {"code": "print('INLINE_OK')"},
                }])[0]
                t.expect("code ok", r.status == "ok", r.message)
                t.expect("stdout INLINE_OK", "INLINE_OK" in r.message)

                leftovers = list(project.glob("*.py"))
                t.expect("no temp .py in project dir",
                         not leftovers, str(leftovers))

                # 5. Ambiguous: neither path nor module nor code.
                print("== ambiguous: no args ==")
                r = s.apply_patches([{
                    "action": "run_python",
                    "arguments": {},
                }])[0]
                t.expect("error", r.status == "error")
                t.expect("ambiguous_input",
                         r.error_code == "ambiguous_input", r.error_code)

                # 6. Missing workspace-relative path: clear error.
                print("== run_python(path=missing) ==")
                r = s.apply_patches([{
                    "action": "run_python",
                    "arguments": {"path": "proj/nested/nope.py"},
                }])[0]
                t.expect("error", r.status == "error")
                t.expect("script_not_found",
                         r.error_code == "script_not_found", r.error_code)
        finally:
            wb.close()
            RunPythonTool.set_config(_orig_cfg, _orig_root)

    print()
    print(f"=== {t.passed} ok, {t.failed} failed ===")
    return 0 if t.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
