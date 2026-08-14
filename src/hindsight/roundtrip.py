from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from hindsight.normalize import (
    DRUG,
    DRUG_TABLE,
    DUPLICATE,
    DUPLICATE_TABLE,
    OPENFDA,
    OPENFDA_KEY,
    OPENFDA_TABLE,
    PATIENT,
    PATIENT_PREFIX,
    REACTION,
    REACTION_TABLE,
    REPORT_ID,
    REPORT_TABLE,
    SEQ,
    TABLES,
)


class RoundTripError(Exception):
    pass


class UnknownReport(RoundTripError):
    pass


class BrokenTables(RoundTripError):
    pass


def _without_nulls(value: object) -> object:
    if isinstance(value, dict):
        return {
            name: _without_nulls(child)
            for name, child in value.items()
            if child is not None
        }

    if isinstance(value, list):
        return [_without_nulls(item) for item in value]

    return value


@dataclass(frozen=True)
class Tables:
    reports: dict[str, dict]
    drugs: dict[str, list[dict]]
    reactions: dict[str, list[dict]]
    duplicates: dict[str, list[dict]]
    openfda: dict[str, dict]
    ambiguous: frozenset[str] = frozenset()

    @property
    def report_ids(self) -> list[str]:
        return list(self.reports)

    @classmethod
    def from_rows(cls, rows: dict[str, list[dict]]) -> "Tables":
        reports, ambiguous = _by_id(rows[REPORT_TABLE])

        return cls(
            reports=reports,
            ambiguous=ambiguous,
            drugs=_by_report(rows[DRUG_TABLE]),
            reactions=_by_report(rows[REACTION_TABLE]),
            duplicates=_by_report(rows[DUPLICATE_TABLE]),
            openfda={row[OPENFDA_KEY]: row for row in rows[OPENFDA_TABLE]},
        )

    @classmethod
    def load(cls, directory: Path) -> "Tables":
        return cls.from_rows(
            {
                table: pq.read_table(directory / f"{table}.parquet").to_pylist()
                for table in TABLES
            }
        )


def _by_id(rows: list[dict]) -> tuple[dict[str, dict], frozenset[str]]:
    reports: dict[str, dict] = {}
    ambiguous: set[str] = set()

    for row in rows:
        report_id = row[REPORT_ID]

        if report_id in reports or report_id in ambiguous:
            reports.pop(report_id, None)
            ambiguous.add(report_id)

            continue

        reports[report_id] = row

    return reports, frozenset(ambiguous)


def _by_report(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)

    for row in rows:
        grouped[row[REPORT_ID]].append(row)

    return grouped


def _entry(row: dict, *columns: str) -> dict:
    return _without_nulls(
        {name: value for name, value in row.items() if name not in columns}
    )


def _ordered(rows: list[dict], table: str, report_id: str) -> list[dict]:
    positions = sorted(row[SEQ] for row in rows)

    if positions != list(range(len(rows))):
        raise BrokenTables(
            f"relatório {report_id!r}: {table} tem {SEQ} {positions}, que não e "
            f"0..{len(rows) - 1}. A ordem original do array não da para "
            f"restaurar de linhas faltando ou duplicadas."
        )

    return [
        _entry(row, REPORT_ID, SEQ) for row in sorted(rows, key=lambda row: row[SEQ])
    ]


def _drugs(tables: "Tables", report_id: str) -> list[dict]:
    drugs = _ordered(tables.drugs.get(report_id, []), DRUG_TABLE, report_id)

    for drug in drugs:

        block_key = drug.pop(OPENFDA_KEY, None)

        if block_key is None:
            continue

        block = tables.openfda.get(block_key)

        if block is None:
            raise BrokenTables(
                f"relatório {report_id!r}: uma linha de medicamento aponta para "
                f"openfda_key {block_key!r}, sem linha correspondente em "
                f"{OPENFDA_TABLE}. O conteudo do bloco sumiu, não só o join."
            )

        drug[OPENFDA] = _entry(block, OPENFDA_KEY)

    return drugs


def _duplicates(tables: "Tables", report_id: str) -> dict | list[dict] | None:
    rows = tables.duplicates.get(report_id, [])

    if not rows:
        return None

    bare = [row for row in rows if row[SEQ] is None]

    if not bare:
        return _ordered(rows, DUPLICATE_TABLE, report_id)

    if len(bare) == len(rows) == 1:
        return _entry(rows[0], REPORT_ID, SEQ)

    raise BrokenTables(
        f"report {report_id!r}: {DUPLICATE_TABLE} holds {len(rows)} rows of "
        f"which {len(bare)} have a null {SEQ}. A null means the source carried "
        f"a bare object, só it can only ever appear alone — this report is "
        f"recorded as having been both an object and an array."
    )


def reconstruct(tables: Tables, report_id: str) -> dict:
    if report_id in tables.ambiguous:
        raise BrokenTables(
            f"{REPORT_ID} {report_id!r} aparece em mais de uma linha de "
            f"{REPORT_TABLE}. As linhas de medicamento e reação das duas "
            f"chegam misturadas numa lista só, entao não da para dizer qual "
            f"array pertence a qual relatório — e uma reconstrução que chuta "
            f"isso passaria no teste sem ser o inverso da escrita. Só este "
            f"relatório é recusado; os outros da partição continuam "
            f"reconstruíveis, e metrics.json conta os ids em "
            f"repeated_report_ids."
        )

    row = tables.reports.get(report_id)

    if row is None:
        raise UnknownReport(
            f"No report row for {report_id!r}. The tables hold "
            f"{len(tables.reports):,} reports."
        )

    row = _without_nulls(row)

    report = {
        name: value
        for name, value in row.items()
        if not name.startswith(PATIENT_PREFIX)
    }
    patient = {
        name[len(PATIENT_PREFIX) :]: value
        for name, value in row.items()
        if name.startswith(PATIENT_PREFIX)
    }

    drugs = _drugs(tables, report_id)
    reactions = _ordered(
        tables.reactions.get(report_id, []), REACTION_TABLE, report_id
    )

    if drugs:
        patient[DRUG] = drugs

    if reactions:
        patient[REACTION] = reactions

    if patient:
        report[PATIENT] = patient

    duplicates = _duplicates(tables, report_id)

    if duplicates is not None:
        report[DUPLICATE] = duplicates

    return report
