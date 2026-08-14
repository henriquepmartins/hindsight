"""Which pairs were manufactured by the shape of a report rather than observed.

A report naming one drug and one event asserts one pair. A report naming 90
drugs and 10 events asserts 900, and every one of them arrives with the same
weight as the first. Nine such reports put `a = 9` on pairs no clinician ever
saw — which is the whole of L-010, and the reason the top of M0's PRR table is
nail fungus on a buprenorphine patch.

This module owns one judgement: **how many drugs is too many.** It does not
detect duplicates. Deciding that two reports describe one case is M2's job and
needs entity resolution this milestone does not have. What can be measured here
is narrower and still enough to disqualify the ranking — a pair whose evidence
comes entirely from reports listing dozens of drugs is a pair whose count is
about the document, not about the drug.

**The threshold is a quantile of the partition, not a constant.** Reports above
the 99th percentile of distinct drugs named. A number written into the source
would be a number measured on one partition of one export and then applied to a
corpus spanning 2004–2025, which is the mistake L-006 is about. A quantile
travels; 100 does not.

The consequence, stated where it is easy to check rather than left for a reader
to work out: this flags **every** pair supported by long medication lists, and
some of those are real. A patient on 90 drugs who has an adverse reaction is a
real patient. The flag says the evidence cannot distinguish the two cases, not
that the pair is false.
"""

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


# Measured on 2025q1/0001-of-0028: the median report names 2 distinct drugs and
# the 99th percentile names 27, against a widest of 121. The nine reports of
# L-010 name 66 to 96 — well clear of the cut, so nothing sits on the line
# arguing about which side it belongs on. 125 of 12,000 reports are at or above
# it, which is 1.04% rather than 1% because the counts are integers and ties do
# not split.
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
-- `one` and `other`, not `left` and `right`: those are DuckDB functions and
-- the parser rejects them as aliases.
SELECT
    one.report,
    other.report,
    -- Jaccard: shared products over the union of both lists. Written out
    -- rather than reached for by name, because DuckDB has no jaccard() and a
    -- silent fallback to something else would be worse than the four lines.
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
    """How wide the partition's reports are: the cut, the middle, the widest.

    Returned together because the cut means nothing alone. A 99th percentile of
    27 against a median of 2 says the distribution has a tail worth naming; the
    same 27 against a median of 24 would say the opposite.
    """
    if not 0 < quantile < 1:
        raise PrrError(f"quantile is {quantile}; it has to sit strictly inside 0 and 1.")

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
    """The reports at or above `cut` distinct drugs, widest first."""
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
    """Pairwise Jaccard between the drug lists of `reports`.

    This is the evidence that separates "one patient reported nine times" from
    "nine patients who happen to be on long medication lists". It is not a
    deduplication rule and does not become one — a high overlap is a reason to
    go and read the reports, which is what T13 did.
    """
    if len(reports) < 2:
        raise PrrError("Overlap needs two reports to compare.")

    directory = _directory(partition, root)
    connection = duckdb.connect()

    try:
        rows = connection.execute(
            _query(_OVERLAP, directory), {"reports": reports}
        ).fetchall()
    finally:
        connection.close()

    return [(left, right, score) for left, right, score in rows]
