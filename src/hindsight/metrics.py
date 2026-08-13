"""What the write actually produced, as a file a later run can compare against.

Three numbers per partition matter enough to be recorded rather than remembered
(L-004), because each one caps a milestone before it is planned:

- `drugstartdate` is present on ~20% of drug rows, so M3's time-to-onset
  analysis can only ever run on a fifth of the data
- UNII is present on ~83%, so the remaining ~17% is M2's entity-resolution
  workload, quantified instead of estimated
- `companynumb` is the field the spike's keep-list dropped from 89.6% of
  reports (L-005), and its coverage is the cheapest standing check that it is
  still travelling

Everything here is measured by reading the Parquet back with DuckDB rather than
by counting in memory during the write. A counter measures the loop; a query
measures the artifact, and the artifact is what the claim is about. It also
means anyone holding the files can re-run these numbers without re-running
the pipeline.

A column absent from the schema reports `null`, not zero and not an error. A
2005-era partition may carry no `unii` at all (spec, P2) — that is a difference
to write down, and it is not the same fact as a column that exists and is empty.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from hindsight.manifest import Partition
from hindsight.normalize import (
    DRUG_TABLE,
    OPENFDA_KEY,
    OPENFDA_TABLE,
    REPORT_TABLE,
    TABLES,
)
from hindsight.schema import Schemas
from hindsight.write import Written


METRICS_FILE = "metrics.json"

COMPANY_NUMBER = "companynumb"
DRUG_START_DATE = "drugstartdate"
UNII = "unii"


def _parquet(directory: Path, table: str) -> str:
    """A table's file as a SQL literal.

    The path is built from a partition id that `manifest.resolve` already
    matched against openFDA's own URL pattern, so there is nothing here a
    quote could escape into.
    """
    return f"'{directory / f'{table}.parquet'}'"


def _rate(matched: int, total: int) -> float | None:
    """A coverage rate, or None when there is nothing to take a rate of."""
    return round(matched / total, 4) if total else None


def _column_coverage(
    connection: duckdb.DuckDBPyConnection,
    directory: Path,
    table: str,
    column: str,
    schemas: Schemas,
) -> int | None:
    """How many rows of `table` have a non-null `column`."""
    if not schemas.has_column(table, column):
        return None

    query = f"SELECT count({column}) FROM read_parquet({_parquet(directory, table)})"

    return connection.sql(query).fetchone()[0]


def _unii_coverage(
    connection: duckdb.DuckDBPyConnection, directory: Path, schemas: Schemas
) -> int | None:
    """How many drug rows resolve to an openfda block carrying a UNII.

    A drug row holds no UNII of its own — it holds a key into `dim_openfda`, so
    this is a join, and the number it produces is the share of drug rows with a
    canonical substance identifier. The rest is what M2 has to resolve by name.

    `len(...) > 0` rather than a null test: a block can carry the field as an
    empty list, and an empty list is not an identifier.
    """
    if not schemas.has_column(OPENFDA_TABLE, UNII):
        return None

    query = f"""
        SELECT count(*) FILTER (WHERE len(dim.{UNII}) > 0)
        FROM read_parquet({_parquet(directory, DRUG_TABLE)}) AS drug
        LEFT JOIN read_parquet({_parquet(directory, OPENFDA_TABLE)}) AS dim
            USING ({OPENFDA_KEY})
    """

    return connection.sql(query).fetchone()[0]


def snapshot(
    *,
    partition: Partition,
    written: Written,
    schemas: Schemas,
    zip_bytes: int,
    json_bytes: int,
) -> dict:
    """Row counts, coverage rates and compression, read back off the disk.

    Row counts come from the files rather than from `written.rows`, which is the
    point: the two agreeing is what says the rows survived encoding, and the
    caller compares the report count against the manifest's own `records`.
    """
    connection = duckdb.connect()
    directory = written.directory

    rows = {
        table: connection.sql(
            f"SELECT count(*) FROM read_parquet({_parquet(directory, table)})"
        ).fetchone()[0]
        for table in TABLES
    }

    with_company = _column_coverage(
        connection, directory, REPORT_TABLE, COMPANY_NUMBER, schemas
    )
    with_start_date = _column_coverage(
        connection, directory, DRUG_TABLE, DRUG_START_DATE, schemas
    )
    with_unii = _unii_coverage(connection, directory, schemas)

    connection.close()

    return {
        "partition": partition.id,
        "export_date": partition.export_date.isoformat(),
        "manifest_records": partition.records,
        "rows": rows,
        "distinct_openfda": written.distinct_openfda,
        "bytes": {
            "source_zip": zip_bytes,
            "source_json": json_bytes,
            "parquet": written.bytes,
        },
        "compression": {
            "vs_json": round(json_bytes / written.bytes, 1) if written.bytes else None,
            "vs_zip": round(zip_bytes / written.bytes, 1) if written.bytes else None,
        },
        "coverage": {
            COMPANY_NUMBER: _rate(with_company, rows[REPORT_TABLE])
            if with_company is not None
            else None,
            DRUG_START_DATE: _rate(with_start_date, rows[DRUG_TABLE])
            if with_start_date is not None
            else None,
            UNII: _rate(with_unii, rows[DRUG_TABLE]) if with_unii is not None else None,
        },
    }


def save(directory: Path, metrics: dict) -> Path:
    """Write `metrics.json` beside the Parquet it describes."""
    path = directory / METRICS_FILE
    path.write_text(json.dumps(metrics, indent=2) + "\n")

    return path
