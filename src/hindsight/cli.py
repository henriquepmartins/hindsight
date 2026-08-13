"""`hindsight <command>` — the entry point the Makefile calls.

One command so far. `ingest` lands in T9.
"""

from __future__ import annotations

import argparse
import logging
import sys

from hindsight.fetch import FetchError, ensure_local
from hindsight.manifest import ManifestError, resolve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hindsight")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="Download and pin one partition")
    fetch.add_argument("partition_id", help='e.g. "2025q1/0001-of-0028"')

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        print(ensure_local(resolve(args.partition_id)))
    except (ManifestError, FetchError) as exc:
        print(exc, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
