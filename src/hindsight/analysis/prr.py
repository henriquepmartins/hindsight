"""The proportional reporting ratio, over a 2×2 built from distinct reports.

PRR is the disproportionality statistic regulators actually screen with. For one
drug D and one event E it asks whether E makes up a larger share of D's reports
than of everything else's:

    a = reports naming D and E          b = reports naming D, not E
    c = reports naming E, not D         d = reports naming neither

    PRR = (a / (a + b)) / (c / (c + d))

Nothing here is a causal claim. FAERS is spontaneous reporting: what a high PRR
says is that a pair is over-represented *in the reporting*, which can be a real
adverse reaction and can equally be a publicity cycle, a litigation campaign or
a reporting programme run by one manufacturer. M3 adds shrinkage for the small
counts, M4 asks whether any of it would have arrived before the FDA's own
warning. This module computes the ratio, its four counts, and the conventional
screening criterion.

**The screening criterion is Evans**: a pair is flagged when PRR ≥ 2, χ² ≥ 4 and
a ≥ 3 — all three, because any one of them alone passes on noise. χ² is computed
with Yates' continuity correction, which is the conservative choice on the small
cells this data is full of and is what the criterion is usually quoted with.

**The criterion does not rescue this table, and that is worth stating where
someone will read it.** `BUTRANS × Onychomycosis` — nail fungus on a
buprenorphine patch — scores PRR 5,991 and χ² 4,811 and is flagged. It is not
pharmacology. Nine near-duplicate Canadian reports, one 40-year-old patient on
66–96 medications, filed by six different manufacturers, put a = 9 where the
truth is closer to a = 1 (L-010). χ² is large *because* the expected count is
0.015, so both statistics agree enthusiastically about the same bad input. No
threshold fixes a duplicate; deduplication does, and that is M2.

**The cells count distinct reports, not joined rows,** and that is the whole
reason this file is not the two-line join design.md sketches. One report in the
partition lists 2,321 drug entries against 8 reactions — 862 of them the same
`INFLIXIMAB` string, from 212 distinct drug objects (L-009). Joining drug rows
to reaction rows multiplies those out: 882,585 joined rows over the partition
against 405,230 distinct `(report, drug, event)` triples, 2.1% of the total
coming from that one report. Ranked on joined rows, the top of the table is a
ranking of whoever filed the most verbose report. `SELECT DISTINCT` on both
sides is what makes a report count once, however many times it repeats itself.

Two things this deliberately does not do, both because M2 owns them:

- **No entity resolution.** `drug` is the raw `medicinalproduct` string, so
  `INFLIXIMAB` and `REMICADE` are different drugs, and 25 names in the partition
  differ from another name only by capitalisation. Every number is provisional
  until M2.
- **No deduplication.** The same case reported twice counts twice.

The corpus denominator is every report in the partition, including reports
whose only reaction was an excluded artifact. They keep their place in `d`:
they are real reports that happened not to record a codeable event, and
dropping them would quietly shrink the population the ratio is taken against.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from hindsight.normalize import DRUG_TABLE, REACTION_TABLE, REPORT_TABLE
from hindsight.write import PARQUET_DIR


EXCLUSIONS = Path("reference/excluded_terms.csv")

# The list carries a prose header explaining what it excludes and why, so the
# reader has to be told the header is not data. Left off, DuckDB returns zero
# rows and no error — the exclusion list silently stops existing and the top of
# the table fills with `Off label use` again.
COMMENT = "#"
TERM_COLUMN = "term"

DRUG_COLUMN = "medicinalproduct"
EVENT_COLUMN = "reactionmeddrapt"
REPORT_ID = "safetyreportid"

# Below three co-reports, PRR is arithmetic on noise: a pair seen twice, both
# times on a rare drug, outranks everything real in the partition. Three is the
# conventional screening floor and it is a parameter because it is a judgement,
# not a constant — the published page states whichever value produced it.
DEFAULT_MIN_COUNT = 3
DEFAULT_LIMIT = 20

# Evans et al. 2001, the convention PRR screening is quoted against. All three
# together: PRR alone flags every rare pair, χ² alone flags every common one.
SIGNAL_PRR = 2.0
SIGNAL_CHI2 = 4.0
SIGNAL_MIN_COUNT = 3


class PrrError(Exception):
    """The inputs the ratio is taken from are not there, or not usable."""


@dataclass(frozen=True, slots=True)
class Pair:
    """One drug–event pair with the 2×2 it was computed from.

    The counts are not diagnostics. A ratio without them cannot be read: PRR 40
    off a = 3 and PRR 40 off a = 300 are the same number and not remotely the
    same finding, and the first is the one that disappears under M3's shrinkage.

    `crowding` is the median number of distinct drugs named by the reports
    behind `a`. The partition's median report names 2, so a pair whose
    supporting reports each name 90 was not observed 9 times — it was observed
    in 9 documents that assert a pair between every drug and every event they
    list. It is a property of the evidence, not of the drug, and `crowding.py`
    owns what counts as high.
    """

    drug: str
    event: str
    a: int
    b: int
    c: int
    d: int
    prr: float | None
    chi2: float | None
    crowding: float | None = None

    @property
    def reports(self) -> int:
        """The corpus the 2×2 was taken over — the four cells partition it."""
        return self.a + self.b + self.c + self.d

    @property
    def signal(self) -> bool:
        """Evans: PRR ≥ 2 and χ² ≥ 4 and a ≥ 3.

        A pair with no defined ratio — the event occurs nowhere but on this drug
        — is not a signal here. It is not judged as one either; Evans has
        nothing to say about a denominator of zero, and pretending otherwise
        would put the least-evidenced pairs at the top of a flagged list.
        """
        return (
            self.prr is not None
            and self.prr >= SIGNAL_PRR
            and self.chi2 is not None
            and self.chi2 >= SIGNAL_CHI2
            and self.a >= SIGNAL_MIN_COUNT
        )


_QUERY = """
WITH exposure AS (
    SELECT DISTINCT {report_id}, {drug} AS drug
    FROM read_parquet({drug_file})
    WHERE {drug} IS NOT NULL
),
occurrence AS (
    SELECT DISTINCT {report_id}, {event} AS event
    FROM read_parquet({reaction_file})
    WHERE {event} IS NOT NULL
      AND {event} NOT IN (SELECT unnest($excluded))
),
corpus AS (
    SELECT count(DISTINCT {report_id}) AS reports
    FROM read_parquet({report_file})
),
-- How many distinct drugs each report names. `exposure` is already distinct,
-- so this counts products and not repetitions of one. A report listing 90 of
-- them manufactures a pair against every event it carries, which is the
-- mechanism behind L-010 and the reason this column exists.
breadth AS (
    SELECT {report_id}, count(*) AS drugs FROM exposure GROUP BY 1
),
drug_reports AS (
    SELECT drug, count(*) AS with_drug FROM exposure GROUP BY drug
),
event_reports AS (
    SELECT event, count(*) AS with_event FROM occurrence GROUP BY event
),
pair AS (
    SELECT
        exposure.drug,
        occurrence.event,
        count(*)             AS a,
        median(breadth.drugs) AS crowding
    FROM exposure
    JOIN occurrence USING ({report_id})
    JOIN breadth USING ({report_id})
    GROUP BY 1, 2
    HAVING count(*) >= $min_count
),
cell AS (
    SELECT
        pair.drug,
        pair.event,
        pair.a                                          AS a,
        pair.crowding                                   AS crowding,
        drug_reports.with_drug - pair.a                 AS b,
        event_reports.with_event - pair.a               AS c,
        corpus.reports - drug_reports.with_drug
            - event_reports.with_event + pair.a         AS d,
        drug_reports.with_drug                          AS with_drug,
        event_reports.with_event                        AS with_event,
        corpus.reports                                  AS reports
    FROM pair
    JOIN drug_reports USING (drug)
    JOIN event_reports USING (event)
    CROSS JOIN corpus
),
scored AS (
    SELECT
        drug, event, a, b, c, d, crowding,
        CASE
            WHEN c > 0 AND reports - with_drug > 0
            THEN (a::DOUBLE / with_drug) / (c::DOUBLE / (reports - with_drug))
        END AS prr,
        -- Yates' correction: |ad - bc| loses N/2 before it is squared, floored
        -- at zero so an over-corrected cell cannot come back negative.
        CASE
            WHEN with_drug > 0 AND with_event > 0
             AND reports - with_drug > 0 AND reports - with_event > 0
            THEN reports
               * pow(greatest(abs(a::DOUBLE * d - b::DOUBLE * c) - reports / 2.0, 0), 2)
               / (with_drug::DOUBLE * (reports - with_drug)
                  * with_event * (reports - with_event))
        END AS chi2
    FROM cell
)
SELECT drug, event, a, b, c, d, prr, chi2, crowding
FROM scored
WHERE NOT $signals_only
   OR (prr >= $signal_prr AND chi2 >= $signal_chi2 AND a >= $signal_min_count)
ORDER BY prr DESC NULLS LAST, a DESC, drug, event
LIMIT $limit
"""


def _parquet(directory: Path, table: str) -> str:
    """A table's file as a SQL literal.

    Same reasoning as metrics.py: the path is built from a partition id
    `manifest.resolve` already matched against openFDA's own URL pattern, so
    there is nothing here a quote could escape into.
    """
    return f"'{directory / f'{table}.parquet'}'"


def partitions(root: Path | str = PARQUET_DIR) -> list[Path]:
    """Every ingested partition directory under `root`, sorted.

    `root` is coerced rather than required to be a `Path`, because the callers
    that pass a string are notebooks, and a notebook that has to import
    `pathlib` to name a directory is a notebook with a line of ceremony in it.
    """
    root = Path(root)

    if not root.exists():
        return []

    return sorted(path.parent for path in root.rglob(f"{REPORT_TABLE}.parquet"))


def _directory(partition: str | None, root: Path | str) -> Path:
    """The partition to read, named or discovered.

    Discovery rather than a default partition id spelled into the source: an id
    hardcoded here is the stale pin of L-006 waiting to happen, and openFDA
    re-chunks quarters between exports. What is on disk cannot go stale.

    Two partitions on disk is an error rather than a choice, because after T19
    the second one is a 2005-era file and silently averaging two eras into one
    table would answer a question nobody asked.

    Raises:
        PrrError: nothing is ingested, or more than one thing is and the caller
            did not say which.
    """
    root = Path(root)

    if partition is not None:
        from hindsight.write import partition_dir

        directory = root / partition_dir(partition)

        if not (directory / f"{REPORT_TABLE}.parquet").exists():
            raise PrrError(
                f"{directory} holds no {REPORT_TABLE}.parquet. "
                f"Run `make ingest PARTITION={partition}` first."
            )

        return directory

    found = partitions(root)

    if not found:
        raise PrrError(
            f"No ingested partition under {root}. Run `make ingest` first."
        )

    if len(found) > 1:
        listed = "\n  ".join(str(path) for path in found)

        raise PrrError(
            f"{len(found)} partitions are ingested and PRR is reported per "
            f"partition, not pooled across eras. Name one:\n  {listed}"
        )

    return found[0]


def excluded_terms(
    connection: duckdb.DuckDBPyConnection, path: Path | str = EXCLUSIONS
) -> list[str]:
    """The MedDRA reporting artifacts to drop, read from the committed CSV.

    An empty read raises. It is the one failure this file has that is invisible
    downstream: the query still runs, still returns a full table, and the only
    symptom is `Off label use` back at the top of a chart nobody re-reads.

    Raises:
        PrrError: the list is missing, unreadable, or empty.
    """
    path = Path(path)

    if not path.exists():
        raise PrrError(
            f"{path} is missing, resolved from {Path.cwd()}. It is committed, so "
            f"either restore it from git or pass `exclusions=` — the default is "
            f"relative to the repo root and a notebook runs one level down."
        )

    query = (
        f"SELECT {TERM_COLUMN} FROM read_csv('{path}', comment='{COMMENT}') "
        f"WHERE {TERM_COLUMN} IS NOT NULL"
    )

    try:
        rows = connection.sql(query).fetchall()
    except duckdb.Error as exc:
        raise PrrError(f"{path} did not parse as CSV: {exc}") from exc

    if not rows:
        raise PrrError(
            f"{path} yielded no terms. Its header is prose behind '{COMMENT}' "
            f"and a read without comment='{COMMENT}' returns zero rows, which "
            f"would silently disable every exclusion."
        )

    return [term for (term,) in rows]


def top_pairs(
    *,
    limit: int | None = DEFAULT_LIMIT,
    min_count: int = DEFAULT_MIN_COUNT,
    signals_only: bool = False,
    partition: str | None = None,
    root: Path = PARQUET_DIR,
    exclusions: Path = EXCLUSIONS,
) -> list[Pair]:
    """The highest-PRR drug–event pairs, each with the 2×2 behind it.

    `limit=None` returns every pair reaching `min_count` — what the chart needs,
    since a cloud drawn from its own top 20 has no cloud in it.

    Pairs whose PRR is undefined — every report carrying the event also carries
    the drug, so `c` is zero — sort last rather than being dropped. The counts
    still describe them, and an event that occurs nowhere else is not a result
    to hide; it is a result M3's shrinkage exists to judge.

    `signals_only` applies Evans. It narrows the table; it does not clean it,
    because the pairs at the top of this partition clear the criterion
    comfortably and are still duplicates (L-010).

    Raises:
        PrrError: no usable partition, or an empty exclusion list.
    """
    if min_count < 1:
        raise PrrError(f"min_count is {min_count}; a pair seen zero times is not a pair.")

    directory = _directory(partition, root)
    connection = duckdb.connect()

    try:
        query = _QUERY.format(
            report_id=REPORT_ID,
            drug=DRUG_COLUMN,
            event=EVENT_COLUMN,
            drug_file=_parquet(directory, DRUG_TABLE),
            reaction_file=_parquet(directory, REACTION_TABLE),
            report_file=_parquet(directory, REPORT_TABLE),
        )
        parameters = {
            "excluded": excluded_terms(connection, exclusions),
            "min_count": min_count,
            "limit": limit,
            "signals_only": signals_only,
            "signal_prr": SIGNAL_PRR,
            "signal_chi2": SIGNAL_CHI2,
            "signal_min_count": SIGNAL_MIN_COUNT,
        }

        rows = connection.execute(query, parameters).fetchall()
    finally:
        connection.close()

    return [Pair(*row) for row in rows]
