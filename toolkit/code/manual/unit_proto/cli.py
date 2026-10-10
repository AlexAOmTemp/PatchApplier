"""CLI for the unit-model prototype.

Usage:
    python cli.py PATH --list
    python cli.py PATH --dump
    python cli.py PATH '{"qualname": "Foo.bar"}' [--part head,body] [--block "1-3"]

PATH — путь к файлу относительно текущей директории.
Адрес — JSON на входе; выводится текст, если найдено, или ошибка.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the package importable when run as a bare script.
# Layout: code/toolkit/... and code/manual/unit_proto/... are siblings,
# so `code` goes on sys.path; then `toolkit.*` and `manual.unit_proto.*`
# both resolve.
_HERE = Path(__file__).resolve()
_CODE_ROOT = _HERE.parents[2]  # .../toolkit/code
if str(_CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CODE_ROOT))

from manual.unit_proto import reader  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("path", help="path to the file to read")
    p.add_argument("address", nargs="?", help="JSON address (optional)")
    p.add_argument("--list", action="store_true", help="list all units")
    p.add_argument("--dump", action="store_true", help="dump the full tree")
    p.add_argument("--part", help="comma-separated parts: head,annotation,body")
    p.add_argument("--block", help="block selector: N or 'A-B' or 'A,B,C'")
    args = p.parse_args(argv)

    src = Path(args.path).read_text(encoding="utf-8")
    try:
        if args.list:
            print(reader.list_units(src, args.path))
            return 0
        if args.dump:
            print(reader.dump_tree(src, args.path))
            return 0
        if not args.address:
            print("error: address required unless --list / --dump", file=sys.stderr)
            return 2
        addr = json.loads(args.address)
        part = args.part.split(",") if args.part else None
        block = args.block if args.block else None
        print(reader.read_unit(src, args.path, addr, part=part, block=block))
        return 0
    except KeyError as e:
        print(f"error: {e.args[0]}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
