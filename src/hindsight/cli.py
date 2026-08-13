"""`hindsight <command>` — the entry point the Makefile calls.

Two commands. `fetch` pins one partition; `ingest` takes it the rest of the way
to Parquet, and is where the two passes are wired together in the order
design.md draws them: infer the schema from every record, freeze it to a file,
then write against the file.

The wiring is the only thing here. Every rule this pipeline is held to lives in
the module that owns it, so a reader who wants to know what happens to a field
does not have to start in the CLI.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from hindsight import metrics, schema
from hindsight.fetch import FetchError, ensure_local
from hindsight.manifest import ManifestError, Partition, resolve
from hindsight.normalize import NormalizeError, REPORT_TABLE
from hindsight.schema import SCHEMA_DIR, SchemaError, Schemas
from hindsight.stream import StreamError, iter_reports, json_bytes
from hindsight.write import PARQUET_DIR, partition_dir, write_partition


log = logging.getLogger(__name__)


class IngestError(Exception):
    """The partition on disk is not the partition the manifest describes."""


def _schemas(partition: Partition, archive: Path, *, reinfer: bool) -> Schemas:
    """The frozen schema for this partition, inferred only if it is not on disk.

    Pass 1 is skipped on a re-run because the file *is* the schema — re-deriving
    it every time would make the committed artifact decorative, and a schema
    that is recomputed silently is no longer something a reviewer approved.
    Anything the data has and the file does not now raises in pass 2, which is
    the drift check M1 grows out of.
    """
    path = SCHEMA_DIR / f"{partition.stem}.json"

    if path.exists() and not reinfer:
        log.info("schema %s (committed)", path)

        return schema.load(path)

    log.info("pass 1: inferring the schema from every record")
    inferred = schema.infer(iter_reports(archive))
    schema.save(
        path,
        inferred,
        source={
            "partition": partition.id,
            "export_date": partition.export_date.isoformat(),
            "records": partition.records,
        },
    )
    log.info("schema %s (inferred)", path)

    return inferred


def _report(summary: dict) -> None:
    """The numbers a reviewer wants without opening the JSON."""
    rows = summary["rows"]
    coverage = summary["coverage"]

    print(f"partition          {summary['partition']} (export {summary['export_date']})")

    for table, count in rows.items():
        print(f"{table:<18} {count:>10,}")

    print(f"distinct openfda   {summary['distinct_openfda']:>10,}")
    print(
        f"parquet            {summary['bytes']['parquet'] / 1e6:>10.2f} MB"
        f"   {summary['compression']['vs_json']}x vs json"
        f"   {summary['compression']['vs_zip']}x vs zip"
    )

    for column, rate in coverage.items():
        share = "absent from this partition" if rate is None else f"{rate:.1%}"
        print(f"{column:<18} {share:>10}")


def _ingest(partition_id: str, *, reinfer: bool) -> None:
    """Fetch, infer, write, measure.

    Raises:
        IngestError: the written report count disagrees with the manifest.
    """
    partition = resolve(partition_id)
    archive = ensure_local(partition)
    schemas = _schemas(partition, archive, reinfer=reinfer)

    log.info("pass 2: writing parquet against the frozen schema")
    written = write_partition(
        iter_reports(archive), schemas, PARQUET_DIR / partition_dir(partition.id)
    )

    summary = metrics.snapshot(
        partition=partition,
        written=written,
        schemas=schemas,
        zip_bytes=archive.stat().st_size,
        json_bytes=json_bytes(archive),
    )
    log.info("metrics %s", metrics.save(written.directory, summary))

    _report(summary)

    # The manifest's own count, not a constant: the last partition of a quarter
    # is a remainder — 2025q1/0028-of-0028 holds 3,230, not 12,000.
    if summary["rows"][REPORT_TABLE] != partition.records:
        raise IngestError(
            f"{written.directory} holds {summary['rows'][REPORT_TABLE]:,} report "
            f"rows and openFDA's manifest says {partition.records:,}. Reports "
            f"went missing between the zip and the Parquet."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hindsight")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="Download and pin one partition")
    fetch.add_argument("partition_id", help='e.g. "2025q1/0001-of-0028"')

    ingest = commands.add_parser("ingest", help="Normalize one partition to Parquet")
    ingest.add_argument("partition_id", help='e.g. "2025q1/0001-of-0028"')
    ingest.add_argument(
        "--reinfer",
        action="store_true",
        help="Re-run pass 1 and overwrite the committed schema for this partition",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        if args.command == "fetch":
            print(ensure_local(resolve(args.partition_id)))
        else:
            _ingest(args.partition_id, reinfer=args.reinfer)
    except (
        ManifestError,
        FetchError,
        StreamError,
        NormalizeError,
        SchemaError,
        IngestError,
    ) as exc:
        print(exc, file=sys.stderr)

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
