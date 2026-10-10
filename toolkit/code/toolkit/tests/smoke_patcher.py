"""Smoke test for Session + Patcher + Tools end-to-end (with Policy)."""
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOLKIT_ROOT = HERE.parent
PROJECT_ROOT = TOOLKIT_ROOT.parent

sys.path.insert(0, str(PROJECT_ROOT))

from toolkit.backends import FilesystemBackend
from toolkit.core import Policy, Session
from toolkit.tools import TOOL_MAP


FIXTURE = "tests/fixtures/simple.md"


PATCHES = [
    {"action": "file_exists", "arguments": {"file_path": FIXTURE}},
    {"action": "file_exists", "arguments": {"file_path": "tests/fixtures/nope.md"}},
    {"action": "read_file", "arguments": {"file_path": FIXTURE, "max_bytes": 60}},
    {"action": "read_file", "arguments": {"file_path": "tests/fixtures/nope.md"}},
    {"action": "no_such_action", "arguments": {}},
    {"action": "file_exists"},
]


def main():
    print(f"Toolkit root: {TOOLKIT_ROOT}")
    print(f"Tools registered: {sorted(TOOL_MAP.keys())}")
    print()

    backend = FilesystemBackend(TOOLKIT_ROOT)
    policy = Policy.uniform(mode="white", paths=["tests"])

    with Session(backend, fmt=None, tools=TOOL_MAP, policy=policy) as s:
        print("== Running 6 patches ==")
        results = s.apply_patches(PATCHES)

    print()
    print("== Expected summary ==")
    print("ok=3, errors=1, skipped=2, blocked=0")

    actual = {
        "ok": sum(1 for r in results if r.status == "ok"),
        "error": sum(1 for r in results if r.status == "error"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "blocked": sum(1 for r in results if r.status == "blocked"),
    }
    expected = {"ok": 3, "error": 1, "skipped": 2, "blocked": 0}

    print()
    print(f"actual: {actual}")
    if actual != expected:
        print(f"[FAIL] mismatch: expected {expected}")
        return 1

    marker = s.patcher.result_marker(results)
    print(f"marker: {marker}")
    if not marker.startswith("##RESULT:"):
        print("[FAIL] marker prefix wrong")
        return 1

    # Parse marker and verify legacy-compatible keys
    import json
    payload = json.loads(marker[len("##RESULT:"):])
    for key in ("ok", "errors", "skipped", "failed", "blocked"):
        if key not in payload:
            print(f"[FAIL] marker missing key: {key}")
            return 1
    if payload["failed"] != [4]:
        print(f"[FAIL] failed ids wrong: {payload['failed']}")
        return 1
    if payload["blocked"] != []:
        print(f"[FAIL] blocked ids should be empty: {payload['blocked']}")
        return 1
    print("[OK] marker compatible with legacy GUI")

    # Blocked path
    print()
    print("== Blocked-path check ==")
    backend2 = FilesystemBackend(TOOLKIT_ROOT)
    policy2 = Policy.uniform(mode="white", paths=["core"])
    with Session(backend2, fmt=None, tools=TOOL_MAP, policy=policy2) as s2:
        results2 = s2.apply_patches([
            {"action": "read_file", "arguments": {"file_path": FIXTURE}},
        ])
    if results2[0].status != "blocked":
        print(f"[FAIL] expected blocked, got {results2[0].status}")
        return 1
    print("[OK] blocked as expected")

    marker2 = s2.patcher.result_marker(results2)
    payload2 = json.loads(marker2[len("##RESULT:"):])
    if payload2["blocked"] != [1]:
        print(f"[FAIL] blocked ids wrong: {payload2['blocked']}")
        return 1
    print("[OK] blocked marker ids correct")

    print()
    print("=== \u0418\u0422\u041e\u0413: ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
