"""Print a structure render for eyeball inspection.

Usage:
  python show_structure_demo.py [kind] [limit] [path] [sort]
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
ROOT = HERE.parents[2]
STATE = ROOT / ".patch_applier"

from toolkit.config.loader import load_workspace
from toolkit.backends.multi_root_fs import MultiRootFsBackend
from toolkit.tools.index import GetIndexTool, install_index_paths
from toolkit.formats import Format

args = sys.argv[1:]
kind = args[0] if len(args) > 0 else "code"
limit = int(args[1]) if len(args) > 1 and args[1] else 500
path = args[2] if len(args) > 2 and args[2] else None
sort = args[3] if len(args) > 3 and args[3] else "path"

cfg = {"project_dir": str(ROOT), "state_dir": ".patch_applier"}
ws = load_workspace(cfg)
install_index_paths(cfg)
wb = MultiRootFsBackend(ws, STATE)
wb.open()
try:
    kw = dict(backend=wb, fmt=Format.load("default"), kind=kind, limit=limit, sort=sort)
    if path:
        kw["path"] = path
    r = GetIndexTool().execute(**kw)
    print(r.message)
finally:
    wb.close()
