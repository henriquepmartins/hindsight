from __future__ import annotations

from pathlib import Path

import duckdb

from hindsight.analysis.prr import (
    DRUG_COLUMN,
    REPORT_ID,
    PrrError,
    _directory,
    _parquet,
)
from hindsight.normalize import DRUG_TABLE
from hindsight.write import PARQUET_DIR


DEFAULT_QUANTILE = 0.99


_BREADTH = """
WITH breadth AS (
    SELECT {report_id}, count(DISTINCT {drug}) AS drugs
    FROM read_parquet({drug_file})
    WHERE {drug} IS NOT NULL
    GROUP BY 1
)
SELECT
    quantile_cont(drugs, $quantile) AS cut,
    median(drugs)                   AS middle,
    max(drugs)                      AS widest,
    count(*)                        AS reports
FROM breadth
"""

_WIDE_REPORTS = """
SELECT {report_id}, count(DISTINCT {drug}) AS drugs
FROM read_parquet({drug_file})
WHERE {drug} IS NOT NULL
GROUP BY 1
HAVING count(DISTINCT {drug}) >= $cut
ORDER BY drugs DESC, {report_id}
"""

_OVERLAP = """
WITH lists AS (
    SELECT {report_id} AS report, list(DISTINCT {drug}) AS drugs
    FROM read_parquet({drug_file})
    WHERE {report_id} IN (SELECT unnest($reports)) AND {drug} IS NOT NULL
    GROUP BY 1
)
SELECT
    one.report,
    other.report,
    len(list_intersect(one.drugs, other.drugs))::DOUBLE
        / len(list_distinct(list_concat(one.drugs, other.drugs)))
FROM lists AS one
JOIN lists AS other ON one.report < other.report
ORDER BY 3 DESC
"""


def _query(template: str, directory: Path) -> str:
    return template.format(
        report_id=REPORT_ID,
        drug=DRUG_COLUMN,
        drug_file=_parquet(directory, DRUG_TABLE),
    )


def breadth(
    *,
    quantile: float = DEFAULT_QUANTILE,
    partition: str | None = None,
    root: Path = PARQUET_DIR,
) -> dict[str, float]:
    if not 0 < quantile < 1:
        raise PrrError(f"quantile é {quantile}; precisa ficar estritamente entre 0 e 1.")

    directory = _directory(partition, root)
    connection = duckdb.connect()

    try:
        cut, middle, widest, reports = connection.execute(
            _query(_BREADTH, directory), {"quantile": quantile}
        ).fetchone()
    finally:
        connection.close()

    return {"cut": cut, "median": middle, "widest": widest, "reports": reports}


def wide_reports(
    *,
    cut: float,
    partition: str | None = None,
    root: Path = PARQUET_DIR,
) -> list[tuple[str, int]]:
    directory = _directory(partition, root)
    connection = duckdb.connect()

    try:
        rows = connection.execute(
            _query(_WIDE_REPORTS, directory), {"cut": cut}
        ).fetchall()
    finally:
        connection.close()

    return [(report, drugs) for report, drugs in rows]


def overlap(
    reports: list[str],
    *,
    partition: str | None = None,
    root: Path = PARQUET_DIR,
) -> list[tuple[str, str, float]]:
    if len(reports) < 2:
        raise PrrError("A sobreposição precisa de dois relatórios para comparar.")

    directory = _directory(partition, root)
    connection = duckdb.connect()

    try:
        rows = connection.execute(
            _query(_OVERLAP, directory), {"reports": reports}
        ).fetchall()
    finally:
        connection.close()

    return [(left, right, score) for left, right, score in rows]
