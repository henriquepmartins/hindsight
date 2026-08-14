from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from hindsight.normalize import DRUG_TABLE, REACTION_TABLE, REPORT_TABLE
from hindsight.write import PARQUET_DIR


EXCLUSIONS = Path("reference/excluded_terms.csv")


COMMENT = "#"
TERM_COLUMN = "term"

DRUG_COLUMN = "medicinalproduct"
EVENT_COLUMN = "reactionmeddrapt"
REPORT_ID = "safetyreportid"


DEFAULT_MIN_COUNT = 3
DEFAULT_LIMIT = 20


SIGNAL_PRR = 2.0
SIGNAL_CHI2 = 4.0
SIGNAL_MIN_COUNT = 3


class PrrError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Pair:
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
        return self.a + self.b + self.c + self.d

    @property
    def signal(self) -> bool:
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
    return f"'{directory / f'{table}.parquet'}'"


def partitions(root: Path | str = PARQUET_DIR) -> list[Path]:
    root = Path(root)

    if not root.exists():
        return []

    return sorted(path.parent for path in root.rglob(f"{REPORT_TABLE}.parquet"))


def _directory(partition: str | None, root: Path | str) -> Path:
    root = Path(root)

    if partition is not None:
        from hindsight.write import partition_dir

        directory = root / partition_dir(partition)

        if not (directory / f"{REPORT_TABLE}.parquet").exists():
            raise PrrError(
                f"{directory} não tem {REPORT_TABLE}.parquet. "
                f"Rode `make ingest PARTITION={partition}` antes."
            )

        return directory

    found = partitions(root)

    if not found:
        raise PrrError(
            f"Nenhuma partição ingerida em {root}. Rode `make ingest` antes."
        )

    if len(found) > 1:
        listed = "\n  ".join(str(path) for path in found)

        raise PrrError(
            f"{len(found)} partições ingeridas, e o PRR e reportado por partição, "
            f"não somado entre epocas. Escolha uma:\n  {listed}"
        )

    return found[0]


def excluded_terms(
    connection: duckdb.DuckDBPyConnection, path: Path | str = EXCLUSIONS
) -> list[str]:
    path = Path(path)

    if not path.exists():
        raise PrrError(
            f"{path} não existe, resolvido a partir de {Path.cwd()}. O arquivo e "
            f"versionado: restaure do git ou passe `exclusions=` — o padrão e "
            f"relativo a raiz do repo e um notebook roda um nivel abaixo."
        )

    query = (
        f"SELECT {TERM_COLUMN} FROM read_csv('{path}', comment='{COMMENT}') "
        f"WHERE {TERM_COLUMN} IS NOT NULL"
    )

    try:
        rows = connection.sql(query).fetchall()
    except duckdb.Error as exc:
        raise PrrError(f"{path} não foi lido como CSV: {exc}") from exc

    if not rows:
        raise PrrError(
            f"{path} não devolveu nenhum termo. O cabeçalho é prosa atras de '{COMMENT}' "
            f"e uma leitura sem comment='{COMMENT}' retorna zero linhas, o que "
            f"desligaria todas as exclusoes em silêncio."
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
    if min_count < 1:
        raise PrrError(f"min_count é {min_count}; um par visto zero vezes não é um par.")

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
