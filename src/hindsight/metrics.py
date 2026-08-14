from __future__ import annotations

import json
from pathlib import Path

import duckdb

from hindsight.manifest import Partition
from hindsight.normalize import (
    DRUG_TABLE,
    OPENFDA_KEY,
    OPENFDA_TABLE,
    REPORT_ID,
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
    return f"'{directory / f'{table}.parquet'}'"


def _rate(matched: int, total: int) -> float | None:
    return round(matched / total, 4) if total else None


def _column_coverage(
    connection: duckdb.DuckDBPyConnection,
    directory: Path,
    table: str,
    column: str,
    schemas: Schemas,
) -> int | None:
    if not schemas.has_column(table, column):
        return None

    query = f"SELECT count({column}) FROM read_parquet({_parquet(directory, table)})"

    return connection.sql(query).fetchone()[0]


def _unii_coverage(
    connection: duckdb.DuckDBPyConnection, directory: Path, schemas: Schemas
) -> int | None:
    if not schemas.has_column(OPENFDA_TABLE, UNII):
        return None

    query = f"""
        SELECT count(*) FILTER (WHERE len(dim.{UNII}) > 0)
        FROM read_parquet({_parquet(directory, DRUG_TABLE)}) AS drug
        LEFT JOIN read_parquet({_parquet(directory, OPENFDA_TABLE)}) AS dim
            USING ({OPENFDA_KEY})
    """

    return connection.sql(query).fetchone()[0]


def _repeated_report_ids(
    connection: duckdb.DuckDBPyConnection, directory: Path
) -> int:
    query = (
        f"SELECT count(*) - count(DISTINCT {REPORT_ID}) "
        f"FROM read_parquet({_parquet(directory, REPORT_TABLE)})"
    )

    return connection.sql(query).fetchone()[0]


def snapshot(
    *,
    partition: Partition,
    written: Written,
    schemas: Schemas,
    zip_bytes: int,
    json_bytes: int,
) -> dict:
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
    repeated = _repeated_report_ids(connection, directory)

    connection.close()

    return {
        "partition": partition.id,
        "export_date": partition.export_date.isoformat(),
        "manifest_records": partition.records,
        "rows": rows,
        "distinct_openfda": written.distinct_openfda,
        "repeated_report_ids": repeated,
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
    path = directory / METRICS_FILE
    path.write_text(json.dumps(metrics, indent=2) + "\n")

    return path
