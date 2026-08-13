"""One nested report becomes rows in four flat tables.

`split()` is the move the whole project rests on. A FAERS report is a document
— a patient, an array of drugs, an array of reactions, each drug carrying an
`openfda` enrichment block — and disproportionality statistics need columns.
The shape of the four tables is in design.md; two properties of the translation
are load-bearing enough to live here:

**Every field travels.** Nothing in this module names a source field it wants.
Building a column list by inspecting one record is what dropped `companynumb`
from 89.6% of reports in the spike (L-005), and it is the failure that cannot
be seen from the output — the Parquet is valid, the counts match, the field is
just gone. So the rows are built by iterating the record, and a source field
that would land on a column this module defines raises instead of overwriting
it.

**`seq` is the array position.** JSON arrays are ordered and SQL tables are
not. Without the original index, T10 can rebuild a report's drugs but not the
order they were reported in, and the round-trip proof fails.

The `openfda` blocks are 92.7% of the corpus's JSON bytes, and they repeat —
the same enrichment is stamped onto every drug row that mentions the product
(L-001). `OpenfdaDimension` stores one copy per distinct block, which is most
of what turns 111 GB into something a laptop can hold. A block's identity is
its own content rather than a key someone picked, which is the move Git makes
for every object it stores; `sort_keys=True` is load-bearing, because without
it two identical blocks written in a different key order hash differently and
the dimension silently doubles.

Absent and empty are different facts. No `openfda` on a drug means nobody
looked; `openfda: {}` means someone looked and found nothing. Collapsing them
with a falsy test produced 492 round-trip mismatches in the spike (L-005), and
2025q1/0001-of-0028 carries 507 empty blocks that would go the same way. The
distinction lives in `key()`, so no caller has to remember it.
"""

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

# The two `patient` arrays that become tables of their own. Not a keep-list:
# every other patient field travels into the report row untouched, whatever it
# is called. These two are named because they are the table boundary — which is
# also why they are derived from the same constants the loops read, rather than
# written out a second time.
CHILD_ARRAYS = (DRUG, REACTION)


# --- errors -----------------------------------------------------------------


class NormalizeError(Exception):
    """Base for every failure in this module."""


class KeyCollision(NormalizeError):
    """Two different blocks hashed to the same dimension key.

    Astronomically unlikely, and silent if unchecked: every drug row pointing
    at the key would carry another product's enrichment.
    """


class UnexpectedReportShape(NormalizeError):
    """A report is not the shape the four-table model can hold.

    Raised rather than coerced. Every alternative here is silent: a missing
    `safetyreportid` orphans that report's child rows, a string where an array
    belongs enumerates into one row per character, and a source field colliding
    with a column loses whichever value is written first.
    """


# --- hashing ----------------------------------------------------------------


def _digest(block: dict) -> str:
    """sha1 over the block's canonical JSON, full width.

    Not a security hash — it is a content address, hence `usedforsecurity`.
    `key()` truncates it; the untruncated digest is what makes a truncation
    collision detectable.
    """
    canonical = json.dumps(block, sort_keys=True)

    return hashlib.sha1(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()


def key(block: dict | None) -> str | None:
    """The `dim_openfda` key for a block, or None if there was no block.

    None means absent, and only absent. An empty dict is a real block with a
    real key — the module docstring says why that difference is load-bearing.
    """
    return None if block is None else _digest(block)[:KEY_LENGTH]


# --- api --------------------------------------------------------------------


class OpenfdaDimension:
    """Every distinct block, emitted on first sight.

    Holds digests, never blocks. The 2,251 distinct blocks in
    2025q1/0001-of-0028 cost ~400 KB as digests against ~30 MB as blocks, and
    the ratio only widens with the corpus. The spike held the blocks; that is
    the version that does not survive 1,767 partitions.
    """

    def __init__(self) -> None:
        # key -> the full digest it was truncated from. Storing the whole
        # digest is what turns a collision into an exception instead of a
        # silently merged row, and at 2,251 entries it costs ~90 KB.
        self._digests: dict[str, str] = {}

    def __len__(self) -> int:
        """Distinct blocks seen so far. T9's metrics.json reports this."""
        return len(self._digests)

    def add(self, block: dict | None) -> tuple[str | None, dict | None]:
        """Return the block's key, plus the block itself only on first sight.

        `(None, None)` for an absent block, so the caller writes no branch of
        its own. That is what keeps the L-005 trap structurally impossible
        rather than a rule someone has to remember at every call site.

        Raises:
            KeyCollision: a different block already claims this key.
        """
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
                f"Two different openfda blocks both truncate to {block_key!r} "
                f"({digest} vs {known}). Widen KEY_LENGTH before ingesting "
                f"further — dim_openfda would merge them."
            )

        return block_key, None


# --- splitting --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RowSet:
    """One report's contribution to each of the four tables.

    `openfda` holds only the blocks this report was the first to carry, so
    concatenating every `RowSet` in a partition gives the dimension exactly
    once. It is empty for the great majority of reports.
    """

    report: dict
    drugs: list[dict]
    reactions: list[dict]
    openfda: list[dict]


def _row(columns: dict, fields: dict, table: str) -> dict:
    """One table's row: the columns this module defines, plus the source verbatim.

    The clash check is the reason this exists. `dict | dict` resolves a
    duplicate name by silently keeping the right-hand value, so a drug field
    called `seq` would replace the array position T10 rebuilds the report from.

    A clash is a schema-level event — openFDA adding a field this module already
    writes as a column — so the table and the colliding names are the whole
    diagnosis. Which report tripped it first carries no information, which is
    why no report id is threaded down here to be formatted 117,000 times a
    partition for a message that never prints.
    """
    clash = columns.keys() & fields.keys()

    if clash:
        raise UnexpectedReportShape(
            f"{table}: {sorted(clash)} names both a column this module writes "
            f"and a field in the source. One of the two values would be lost."
        )

    return columns | fields


def _report_id(report: dict) -> str:
    """The join key every child row carries, or raise naming what did arrive."""
    report_id = report.get(REPORT_ID)

    if report_id is None:
        raise UnexpectedReportShape(
            f"A report arrived with no {REPORT_ID!r}. It is the only join key "
            f"back to its drug and reaction rows, so they would be orphaned. "
            f"The report's fields were {sorted(report)}."
        )

    return report_id


def _patient(report: dict, report_id: str) -> dict:
    """The `patient` object, or `{}` if the report has none.

    `report_id` is data, not a formatted prefix — unlike a clash, one malformed
    report among 20.7M is worth naming, and the string is built only if it is.
    """
    patient = report.get(PATIENT)

    if patient is None:
        return {}

    if not isinstance(patient, dict):
        raise UnexpectedReportShape(
            f"report {report_id!r}: {PATIENT!r} should be an object, found "
            f"{type(patient).__name__}."
        )

    return patient


def _entries(patient: dict, field: str, report_id: str) -> Iterator[tuple[int, dict]]:
    """Yield `(position, entry)` for one of the patient arrays, or nothing.

    The type checks are not ceremony. `enumerate` accepts a string and yields
    one character per position, so an array that arrives as a scalar would
    become rows that look entirely valid until the round-trip test runs.
    """
    entries = patient.get(field)

    if entries is None:
        return

    if not isinstance(entries, list):
        raise UnexpectedReportShape(
            f"report {report_id!r}: {field!r} should be an array, found "
            f"{type(entries).__name__}."
        )

    for seq, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise UnexpectedReportShape(
                f"report {report_id!r}: {field!r}[{seq}] should be an object, "
                f"found {type(entry).__name__}."
            )

        yield seq, entry


def split(report: dict, dimension: OpenfdaDimension) -> RowSet:
    """Turn one report into rows for the report, drug, reaction and dim tables.

    `dimension` accumulates across the whole partition — pass the same instance
    to every call, or each block is emitted once per report instead of once.
    Routing the block through it here is what keeps the absent-vs-empty rule
    (L-005) inside this module rather than repeated at every call site.

    Raises:
        UnexpectedReportShape: the report cannot be held by the four tables.
        KeyCollision: two openfda blocks truncated to one dimension key.
    """
    report_id = _report_id(report)
    patient = _patient(report, report_id)

    report_row = _row(
        {name: value for name, value in report.items() if name != PATIENT},
        {
            PATIENT_PREFIX + name: value
            for name, value in patient.items()
            if name not in CHILD_ARRAYS
        },
        "report",
    )

    drugs: list[dict] = []
    blocks: list[dict] = []

    for seq, drug in _entries(patient, DRUG, report_id):
        block_key, block = dimension.add(drug.get(OPENFDA))
        drugs.append(
            _row(
                {REPORT_ID: report_id, SEQ: seq, OPENFDA_KEY: block_key},
                {name: value for name, value in drug.items() if name != OPENFDA},
                "report_drug",
            )
        )

        if block is not None:
            blocks.append(_row({OPENFDA_KEY: block_key}, block, "dim_openfda"))

    reactions = [
        _row({REPORT_ID: report_id, SEQ: seq}, reaction, "report_reaction")
        for seq, reaction in _entries(patient, REACTION, report_id)
    ]

    return RowSet(report=report_row, drugs=drugs, reactions=reactions, openfda=blocks)
