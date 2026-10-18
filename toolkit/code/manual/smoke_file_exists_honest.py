"""Проверяем, что file_exists честно различает 4 случая.

Как это видит пользователь через патч:
  patcher._filter_paths вызывает filter_check на каждый path_arg
  ДО запуска tool. Если filter_check != None -> пользователь получает
  ошибку фильтра, tool не зовётся. Если None -> tool отвечает true/false.

Тестируем оба уровня (filter_check + tool).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"
PI = STATE / ".patchignore"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.tools.read import FileExistsTool
from toolkit.formats import Format

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)

orig_pi = PI.read_text(encoding="utf-8")

wb = MultiRootFsBackend(ws, STATE)
wb.open()
try:
    def user_view(path):
        """Что пользователь увидит после патча."""
        err = wb.filter_check(path, "read")
        if err is not None:
            return ("filter", err[0], err[1])
        r = FileExistsTool().execute(backend=wb, fmt=Format.load("default"),
                                     file_path=path)
        return ("tool", r.status, r.message)

    print("=== 1. exists, valid root ===")
    print(f"  {user_view('RimWorld/PatchApplier/DEV/NOTES.md')}")

    print("\n=== 2. not exists, valid root ===")
    print(f"  {user_view('RimWorld/PatchApplier/NOPE.txt')}")

    print("\n=== 3. bad root ===")
    print(f"  {user_view('NoSuchRoot/x.txt')}")

    print("\n=== 4. hidden (.git under .patchignore .*) ===")
    # add `.git` rule
    PI.write_text(orig_pi + "\n.git\n", encoding="utf-8")
    wb.reload_patterns()
    print(f"  {user_view('RimWorld/PatchApplier/.git/HEAD')}")
    print(f"  {user_view('PatchAppliers/PatchApplier/.git/HEAD')}")
finally:
    PI.write_text(orig_pi, encoding="utf-8")
    wb.close()
