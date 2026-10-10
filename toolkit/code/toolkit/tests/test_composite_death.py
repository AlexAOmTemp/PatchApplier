"""Composite: a sub-backend that dies *after* open must be reported dead.

Previously `backend_state` / `backend_state_all` returned the cached value
without a live check: after a successful `open()` the cache said `ready`
forever, even if the process had died. The GUI lamp and status snapshot
therefore kept reporting `ready` for a dead bridge.

Expected:
  - `backend_state(name)` downgrades a stale `ready` to `failed: not alive`
  - `backend_state_all()` does the same
  - `is_alive()` reflects the live state
  - the cache itself is *not* mutated (only the returned value is checked)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from toolkit.backends.composite import CompositeBackend  # noqa: E402


class SwitchableBackend:
    """Sub-backend whose `is_alive` toggles on demand."""

    def __init__(self):
        self._alive = False

    def open(self):
        self._alive = True

    def close(self):
        self._alive = False

    def is_alive(self):
        return self._alive

    def kill(self):
        self._alive = False


class BombBackend:
    """Sub-backend whose `is_alive` raises."""

    def open(self):
        pass

    def close(self):
        pass

    def is_alive(self):
        raise RuntimeError("boom")


PASSED = 0
FAILED = 0


def check(label, ok):
    global PASSED, FAILED
    if ok:
        print(f"  PASS  {label}")
        PASSED += 1
    else:
        print(f"  FAIL  {label}")
        FAILED += 1


def main():
    print("=== Switching backend: ready -> dead ===")
    a = SwitchableBackend()
    b = SwitchableBackend()
    comp = CompositeBackend([("fs", a), ("mcp", b)])
    comp.open()

    check("after open, fs is ready", comp.backend_state("fs") == "ready")
    check("after open, mcp is ready", comp.backend_state("mcp") == "ready")
    check("is_alive() is True", comp.is_alive() is True)

    b.kill()

    check("mcp reported as failed: not alive",
          comp.backend_state("mcp") == "failed: not alive")
    check("fs still ready", comp.backend_state("fs") == "ready")

    states = comp.backend_state_all()
    check("backend_state_all: fs ready", states.get("fs") == "ready")
    check("backend_state_all: mcp dead",
          states.get("mcp") == "failed: not alive")

    check("is_alive() still True (fs alive)", comp.is_alive() is True)

    a.kill()
    check("is_alive() False when both dead", comp.is_alive() is False)

    # Cache itself is untouched (only the returned value is downgraded).
    check("cache not mutated by live check",
          comp._state.get("mcp") == "ready")

    print("=== Bomb backend: is_alive raises ===")
    bomb = BombBackend()
    comp2 = CompositeBackend([("fs", SwitchableBackend()), ("mcp", bomb)])
    comp2.open()
    check("bomb reported as failed: not alive",
          comp2.backend_state("mcp") == "failed: not alive")
    states2 = comp2.backend_state_all()
    check("bomb in state_all is failed: not alive",
          states2.get("mcp") == "failed: not alive")

    print()
    print(f"=== ok={PASSED}, fail={FAILED} ===")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
