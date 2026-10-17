"""Read `metrics.json` and print a usage summary.

Run:  python manual/metrics_report.py
      python manual/metrics_report.py --reset   # delete the counters file

Output groups actions into three buckets — unit model, text escape hatch,
old symbol model — and prints their share. The signal for the DECISIONS
§2.1 experiment: if the escape hatch's share stays low (<15%), the unit
model wins; if it climbs (>40%), the model failed.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve()
# .../toolkit/code/manual/metrics_report.py -> .../toolkit/code
_CODE_ROOT = _HERE.parents[1]
if str(_CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CODE_ROOT))

from toolkit.config.loader import toolkit_runtime_state_dir  # noqa: E402


UNIT_MODEL = {
    "list_units", "read_unit",
    "replace_unit", "replace_block", "delete_block", "insert_block",
}

TEXT_ESCAPE = {
    "replace_in_file", "replace_range", "replace_between", "insert_at_anchor",
}

OLD_SYMBOL = {
    "list_symbols", "list_symbols_lua",
    "read_symbol", "read_symbol_lua",
    "replace_symbol", "replace_symbol_body", "replace_symbol_signature",
    "replace_statement",
    "replace_section", "set_summary", "verify_section",
    "insert_symbol", "delete_symbol", "move_symbol",
    "replace_function", "replace_function_body", "replace_function_lua",
}


def _fmt_ts(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def main(argv: list[str]) -> int:
    p = toolkit_runtime_state_dir() / "metrics.json"
    if "--reset" in argv:
        if p.is_file():
            p.unlink()
            print(f"removed {p}")
        else:
            print(f"nothing to remove ({p} not found)")
        return 0

    if not p.is_file():
        print(f"no metrics yet ({p})")
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    counts: dict = data.get("counts") or {}
    errors: dict = data.get("errors") or {}

    total = sum(sum(b.values()) for b in counts.values())
    if total == 0:
        print("metrics file exists but counters are empty")
        return 0

    print("=== metrics ===")
    if "since" in data:
        print(f"since:   {_fmt_ts(data['since'])}")
    if "updated" in data:
        print(f"updated: {_fmt_ts(data['updated'])}")
    print(f"total actions: {total}")
    print()

    # --- Top actions ---
    rows: list[tuple[str, int, dict]] = []
    for a, bucket in counts.items():
        n = sum(bucket.values())
        rows.append((a, n, bucket))
    rows.sort(key=lambda r: -r[1])

    print("top actions (share, errors):")
    for a, n, bucket in rows:
        pct = n * 100.0 / total
        err = bucket.get("error", 0) + bucket.get("blocked", 0)
        err_pct = err * 100.0 / n if n else 0.0
        print(f"  {a:<24} {n:>5}  ({pct:5.1f}%)   err/block: {err_pct:4.1f}%")
    print()

    # --- Buckets ---
    def bucket_sum(names: set[str]) -> int:
        return sum(sum(counts.get(a, {}).values()) for a in names)

    unit_n = bucket_sum(UNIT_MODEL)
    escape_n = bucket_sum(TEXT_ESCAPE)
    old_n = bucket_sum(OLD_SYMBOL)
    other_n = total - unit_n - escape_n - old_n

    def line(label: str, n: int) -> str:
        return f"  {label:<28} {n:>5}  ({n * 100.0 / total:5.1f}%)"

    print("buckets:")
    print(line("unit model", unit_n))
    print(line("text escape hatch", escape_n))
    print(line("old symbol model", old_n))
    print(line("other (indexes, exec, ...)", other_n))
    print()

    # --- Errors breakdown (only for actions that had any) ---
    if errors:
        print("errors by action:")
        for a in sorted(errors):
            e = errors[a]
            if not e:
                continue
            items = ", ".join(f"{k} ({v})" for k, v in
                              sorted(e.items(), key=lambda kv: -kv[1]))
            print(f"  {a}: {items}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
