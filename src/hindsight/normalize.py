from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass


KEY_LENGTH = 16

PATIENT = "patient"
PATIENT_PREFIX = "pt_"
OPENFDA = "openfda"
OPENFDA_KEY = "openfda_key"
REPORT_ID = "safetyreportid"
SEQ = "seq"
DRUG = "drug"
REACTION = "reaction"
DUPLICATE = "reportduplicate"


REPORT_TABLE = "report"
DRUG_TABLE = "report_drug"
REACTION_TABLE = "report_reaction"
DUPLICATE_TABLE = "report_duplicate"
OPENFDA_TABLE = "dim_openfda"

TABLES = (REPORT_TABLE, DRUG_TABLE, REACTION_TABLE, DUPLICATE_TABLE, OPENFDA_TABLE)


PIPELINE_COLUMNS = {
    REPORT_TABLE: (),
    DRUG_TABLE: (REPORT_ID, SEQ, OPENFDA_KEY),
    REACTION_TABLE: (REPORT_ID, SEQ),
    DUPLICATE_TABLE: (REPORT_ID, SEQ),
    OPENFDA_TABLE: (OPENFDA_KEY,),
}


CHILD_ARRAYS = (DRUG, REACTION)


UNWRAPPED = (PATIENT, DUPLICATE)


class NormalizeError(Exception):
    pass


class KeyCollision(NormalizeError):
    pass


class UnexpectedReportShape(NormalizeError):
    pass


def _digest(block: dict) -> str:
    canonical = json.dumps(block, sort_keys=True)

    return hashlib.sha1(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()


def key(block: dict | None) -> str | None:
    return None if block is None else _digest(block)[:KEY_LENGTH]


class OpenfdaDimension:
    def __init__(self) -> None:

        self._digests: dict[str, str] = {}

    def __len__(self) -> int:
        return len(self._digests)

    def add(self, block: dict | None) -> tuple[str | None, dict | None]:
        if block is None:
            return None, None

        digest = _digest(block)
        block_key = digest[:KEY_LENGTH]
        known = self._digests.get(block_key)

        if known is None:
            self._digests[block_key] = digest

            return block_key, block

        if known != digest:
            raise KeyCollision(
                f"Dois blocos openfda diferentes truncam para {block_key!r} "
                f"({digest} vs {known}). Aumente KEY_LENGTH antes de seguir "
                f"ingerindo — dim_openfda juntaria os dois."
            )

        return block_key, None


@dataclass(frozen=True, slots=True)
class RowSet:
    report: dict
    drugs: list[dict]
    reactions: list[dict]
    duplicates: list[dict]
    openfda: list[dict]

    def by_table(self) -> dict[str, list[dict]]:
        return {
            REPORT_TABLE: [self.report],
            DRUG_TABLE: self.drugs,
            REACTION_TABLE: self.reactions,
            DUPLICATE_TABLE: self.duplicates,
            OPENFDA_TABLE: self.openfda,
        }


def _row(columns: dict, fields: dict, table: str) -> dict:
    clash = columns.keys() & fields.keys()

    if clash:
        raise UnexpectedReportShape(
            f"{table}: {sorted(clash)} é ao mesmo tempo uma coluna que este módulo "
            f"escreve e um campo da fonte. Um dos dois valores se perderia."
        )

    return columns | fields


def _report_id(report: dict) -> str:
    report_id = report.get(REPORT_ID)

    if report_id is None:
        raise UnexpectedReportShape(
            f"Chegou um relatório sem {REPORT_ID!r}. E a única chave de volta para "
            f"suas linhas de medicamento e reação, que ficariam órfãs. "
            f"Os campos do relatório eram {sorted(report)}."
        )

    return report_id


def _patient(report: dict, report_id: str) -> dict:
    patient = report.get(PATIENT)

    if patient is None:
        return {}

    if not isinstance(patient, dict):
        raise UnexpectedReportShape(
            f"relatório {report_id!r}: {PATIENT!r} deveria ser um objeto, veio "
            f"{type(patient).__name__}."
        )

    return patient


def _entries(container: dict, field: str, report_id: str) -> Iterator[tuple[int, dict]]:
    entries = container.get(field)

    if entries is None:
        return

    if not isinstance(entries, list):
        raise UnexpectedReportShape(
            f"relatório {report_id!r}: {field!r} deveria ser um array, veio "
            f"{type(entries).__name__}."
        )

    for seq, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise UnexpectedReportShape(
                f"relatório {report_id!r}: {field!r}[{seq}] deveria ser um objeto, "
                f"veio {type(entry).__name__}."
            )

        yield seq, entry


def _duplicates(report: dict, report_id: str) -> Iterator[tuple[int | None, dict]]:
    entries = report.get(DUPLICATE)

    if isinstance(entries, dict):
        yield None, entries

        return

    yield from _entries(report, DUPLICATE, report_id)


def split(report: dict, dimension: OpenfdaDimension) -> RowSet:
    report_id = _report_id(report)
    patient = _patient(report, report_id)

    report_row = _row(
        {name: value for name, value in report.items() if name not in UNWRAPPED},
        {
            PATIENT_PREFIX + name: value
            for name, value in patient.items()
            if name not in CHILD_ARRAYS
        },
        REPORT_TABLE,
    )

    drugs: list[dict] = []
    blocks: list[dict] = []

    for seq, drug in _entries(patient, DRUG, report_id):
        block_key, block = dimension.add(drug.get(OPENFDA))
        drugs.append(
            _row(
                {REPORT_ID: report_id, SEQ: seq, OPENFDA_KEY: block_key},
                {name: value for name, value in drug.items() if name != OPENFDA},
                DRUG_TABLE,
            )
        )

        if block is not None:
            blocks.append(_row({OPENFDA_KEY: block_key}, block, OPENFDA_TABLE))

    reactions = [
        _row({REPORT_ID: report_id, SEQ: seq}, reaction, REACTION_TABLE)
        for seq, reaction in _entries(patient, REACTION, report_id)
    ]

    duplicates = [
        _row({REPORT_ID: report_id, SEQ: seq}, entry, DUPLICATE_TABLE)
        for seq, entry in _duplicates(report, report_id)
    ]

    return RowSet(
        report=report_row,
        drugs=drugs,
        reactions=reactions,
        duplicates=duplicates,
        openfda=blocks,
    )
