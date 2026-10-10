"""Smoke: import the whole toolkit graph to catch stale symbols."""
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

fails = []

def try_import(label, fn):
    try:
        fn()
        print(f"[OK]   {label}")
    except Exception as e:
        print(f"[FAIL] {label} -- {type(e).__name__}: {e}")
        fails.append(label)


try_import("toolkit.core", lambda: __import__("toolkit.core", fromlist=["*"]))
try_import("toolkit.core.models", lambda: __import__("toolkit.core.models", fromlist=["*"]))
try_import("toolkit.core.patcher", lambda: __import__("toolkit.core.patcher", fromlist=["*"]))
try_import("toolkit.core.session", lambda: __import__("toolkit.core.session", fromlist=["*"]))
try_import("toolkit.config", lambda: __import__("toolkit.config", fromlist=["*"]))
try_import("toolkit.config.workspace", lambda: __import__("toolkit.config.workspace", fromlist=["*"]))
try_import("toolkit.backends", lambda: __import__("toolkit.backends", fromlist=["*"]))
try_import("toolkit.backends.filesystem", lambda: __import__("toolkit.backends.filesystem", fromlist=["*"]))
try_import("toolkit.backends.workspace", lambda: __import__("toolkit.backends.workspace", fromlist=["*"]))
try_import("toolkit.backends.composite", lambda: __import__("toolkit.backends.composite", fromlist=["*"]))
try_import("toolkit.backends.mcp", lambda: __import__("toolkit.backends.mcp", fromlist=["*"]))
try_import("toolkit.indexers", lambda: __import__("toolkit.indexers", fromlist=["*"]))
try_import("toolkit.indexers.doc", lambda: __import__("toolkit.indexers.doc", fromlist=["*"]))
try_import("toolkit.indexers.code", lambda: __import__("toolkit.indexers.code", fromlist=["*"]))
try_import("toolkit.tools", lambda: __import__("toolkit.tools", fromlist=["*"]))
try_import("toolkit.tools.index", lambda: __import__("toolkit.tools.index", fromlist=["*"]))
try_import("toolkit.tools.status", lambda: __import__("toolkit.tools.status", fromlist=["*"]))
try_import("toolkit.runner.projects", lambda: __import__("toolkit.runner.projects", fromlist=["*"]))

print()
if fails:
    print(f"=== {len(fails)} import failures ===")
    sys.exit(1)
print("=== all imports OK ===")
