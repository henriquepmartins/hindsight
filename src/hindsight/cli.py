"""`hindsight <command>` — the entry point the Makefile calls.

Three commands. `fetch` pins one partition; `ingest` takes it the rest of the
way to Parquet, and is where the two passes are wired together in the order
design.md draws them: infer the schema from every record, freeze it to a file,
then write against the file. `analyze` reads the result back and ranks
drug–event pairs by PRR.

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
from hindsight.analysis.export import write_csv
from hindsight.analysis.prr import (
    DEFAULT_LIMIT,
    DEFAULT_MIN_COUNT,
    SIGNAL_CHI2,
    SIGNAL_MIN_COUNT,
    SIGNAL_PRR,
    Pair,
    PrrError,
    top_pairs,
)
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


def _pairs(pairs: list[Pair], *, min_count: int) -> None:
    """The ranking, with the 2×2 beside every ratio and the caveats under it.

    The caveats are printed rather than left to the reader because they are the
    difference between a result and a claim: these are raw `medicinalproduct`
    strings over one partition of undeduplicated spontaneous reports.
    """
    if not pairs:
        print(f"No drug-event pair reaches {min_count} co-reports.")

        return

    print(
        f"{'drug':<30} {'event':<26} {'a':>5} {'b':>6} {'c':>5} {'d':>7} "
        f"{'PRR':>9} {'chi2':>9}  signal"
    )

    for pair in pairs:
        ratio = "undefined" if pair.prr is None else f"{pair.prr:,.1f}"
        chi2 = "" if pair.chi2 is None else f"{pair.chi2:,.1f}"
        print(
            f"{pair.drug[:30]:<30} {pair.event[:26]:<26} {pair.a:>5,} {pair.b:>6,} "
            f"{pair.c:>5,} {pair.d:>7,} {ratio:>9} {chi2:>9}  "
            f"{'yes' if pair.signal else '-'}"
        )

    print(
        f"\n{pairs[0].reports:,} reports · min {min_count} co-reports · "
        f"signal = Evans (PRR>={SIGNAL_PRR:.0f}, chi2>={SIGNAL_CHI2:.0f}, "
        f"a>={SIGNAL_MIN_COUNT}) · raw medicinalproduct strings, no entity "
        f"resolution and no deduplication (M2) · disproportionate reporting is "
        f"not causation"
    )


def _analyze(
    partition_id: str | None,
    *,
    limit: int,
    min_count: int,
    signals_only: bool,
    to_csv: bool,
) -> None:
    if to_csv:
        written = write_csv(min_count=min_count, partition=partition_id)

        print(
            f"{written.path}  {written.pairs:,} pairs · {written.crowded:,} crowded "
            f"(>= {written.cut:g} distinct drugs) · {written.partition}"
        )

        return

    _pairs(
        top_pairs(
            limit=limit,
            min_count=min_count,
            signals_only=signals_only,
            partition=partition_id,
        ),
        min_count=min_count,
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

    analyze = commands.add_parser("analyze", help="Rank drug-event pairs by PRR")
    analyze.add_argument(
        "partition_id",
        nargs="?",
        help="Defaults to the only ingested partition; required once there are two",
    )
    analyze.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    analyze.add_argument(
        "--min-count",
        type=int,
        default=DEFAULT_MIN_COUNT,
        help=f"Minimum co-reports per pair (default {DEFAULT_MIN_COUNT})",
    )
    analyze.add_argument(
        "--signals-only",
        action="store_true",
        help="Keep only pairs meeting Evans. It narrows the table; it does not "
        "clean it — the top of this partition clears the criterion and is "
        "still duplicates",
    )
    analyze.add_argument(
        "--csv",
        action="store_true",
        dest="to_csv",
        help="Write every pair to reports/data/prr_top.csv — the file the "
        "published page reads, since data/parquet/ is gitignored",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        if args.command == "fetch":
            print(ensure_local(resolve(args.partition_id)))
        elif args.command == "analyze":
            _analyze(
                args.partition_id,
                limit=args.limit,
                min_count=args.min_count,
                signals_only=args.signals_only,
                to_csv=args.to_csv,
            )
        else:
            _ingest(args.partition_id, reinfer=args.reinfer)
    except (
        ManifestError,
        FetchError,
        StreamError,
        NormalizeError,
        SchemaError,
        IngestError,
        PrrError,
    ) as exc:
        print(exc, file=sys.stderr)

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
