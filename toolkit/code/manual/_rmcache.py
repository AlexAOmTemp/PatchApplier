import shutil
from pathlib import Path
root = Path(__file__).resolve().parents[1]
removed = []
for p in root.rglob("__pycache__"):
    if p.is_dir():
        try:
            shutil.rmtree(p)
            removed.append(str(p.relative_to(root)))
        except Exception as e:
            print(f"skip {p}: {e}")
print(f"removed {len(removed)} __pycache__ dirs")
for r in removed:
    print(" ", r)
