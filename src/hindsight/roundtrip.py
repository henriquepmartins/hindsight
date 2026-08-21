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
    ORDINAL,
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
    reports: dict[int, dict]
    drugs: dict[int, list[dict]]
    reactions: dict[int, list[dict]]
    duplicates: dict[int, list[dict]]
    openfda: dict[str, dict]

    @property
    def ordinals(self) -> list[int]:
        return list(self.reports)

    @classmethod
    def from_rows(cls, rows: dict[str, list[dict]]) -> "Tables":
        return cls(
            reports=_by_ordinal(rows[REPORT_TABLE]),
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


def _by_ordinal(rows: list[dict]) -> dict[int, dict]:
    reports: dict[int, dict] = {}

    for row in rows:
        ordinal = row[ORDINAL]

        if ordinal in reports:
            raise BrokenTables(
                f"{ORDINAL} {ordinal} aparece em mais de uma linha de "
                f"{REPORT_TABLE}. A posição dentro da partição é atribuída uma "
                f"vez, pela passagem 2 — repetida, é o escritor quebrando o "
                f"próprio contrato, e nenhuma linha pode ser descartada em "
                f"silêncio."
            )

        reports[ordinal] = row

    return reports


def _by_report(rows: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = defaultdict(list)

    for row in rows:
        grouped[row[ORDINAL]].append(row)

    return grouped


def _entry(row: dict, *columns: str) -> dict:
    return _without_nulls(
        {name: value for name, value in row.items() if name not in columns}
    )


def _ordered(rows: list[dict], table: str, ordinal: int) -> list[dict]:
    positions = sorted(row[SEQ] for row in rows)

    if positions != list(range(len(rows))):
        raise BrokenTables(
            f"relatório {ordinal}: {table} tem {SEQ} {positions}, que não é "
            f"0..{len(rows) - 1}. A ordem original do array não dá para "
            f"restaurar de linhas faltando ou duplicadas."
        )

    return [
        _entry(row, REPORT_ID, ORDINAL, SEQ)
        for row in sorted(rows, key=lambda row: row[SEQ])
    ]


def _drugs(tables: "Tables", ordinal: int) -> list[dict]:
    drugs = _ordered(tables.drugs.get(ordinal, []), DRUG_TABLE, ordinal)

    for drug in drugs:

        block_key = drug.pop(OPENFDA_KEY, None)

        if block_key is None:
            continue

        block = tables.openfda.get(block_key)

        if block is None:
            raise BrokenTables(
                f"relatório {ordinal}: uma linha de medicamento aponta para "
                f"openfda_key {block_key!r}, sem linha correspondente em "
                f"{OPENFDA_TABLE}. O conteúdo do bloco sumiu, não só o join."
            )

        drug[OPENFDA] = _entry(block, OPENFDA_KEY)

    return drugs


def _duplicates(tables: "Tables", ordinal: int) -> dict | list[dict] | None:
    rows = tables.duplicates.get(ordinal, [])

    if not rows:
        return None

    bare = [row for row in rows if row[SEQ] is None]

    if not bare:
        return _ordered(rows, DUPLICATE_TABLE, ordinal)

    if len(bare) == len(rows) == 1:
        return _entry(rows[0], REPORT_ID, ORDINAL, SEQ)

    raise BrokenTables(
        f"report {ordinal}: {DUPLICATE_TABLE} holds {len(rows)} rows of "
        f"which {len(bare)} have a null {SEQ}. A null means the source carried "
        f"a bare object, so it can only ever appear alone — this report is "
        f"recorded as having been both an object and an array."
    )


def reconstruct(tables: Tables, ordinal: int) -> dict:
    row = tables.reports.get(ordinal)

    if row is None:
        raise UnknownReport(
            f"No report row for {ORDINAL} {ordinal}. The tables hold "
            f"{len(tables.reports):,} reports."
        )

    row = _without_nulls({name: value for name, value in row.items() if name != ORDINAL})

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

    drugs = _drugs(tables, ordinal)
    reactions = _ordered(tables.reactions.get(ordinal, []), REACTION_TABLE, ordinal)

    if drugs:
        patient[DRUG] = drugs

    if reactions:
        patient[REACTION] = reactions

    if patient:
        report[PATIENT] = patient

    duplicates = _duplicates(tables, ordinal)

    if duplicates is not None:
        report[DUPLICATE] = duplicates

    return report
