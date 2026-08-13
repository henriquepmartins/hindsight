"""One nested report becomes rows in five flat tables.

`split()` is the move the whole project rests on. A FAERS report is a document
— a patient, an array of drugs, an array of reactions, each drug carrying an
`openfda` enrichment block — and disproportionality statistics need columns.
The shape of the tables is in design.md; two properties of the translation
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

A third repeated child hides in plain sight. `reportduplicate` arrives as a
bare object when the report has one duplicate and as an array when it has two
or more — the corpus is an XML-to-JSON conversion, and a repeated element that
occurred once has no array to be in. It gets the same treatment as `drug` and
`reaction`, a table with a `seq`, and the bare-object case is recorded as a
null `seq`: no array, so no position in one.

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
DUPLICATE = "reportduplicate"

# The tables, named once. Every later module — the schema file, the Parquet file
# names, the metrics — reads them from here, so a table cannot be renamed in one
# place and left behind in another.
REPORT_TABLE = "report"
DRUG_TABLE = "report_drug"
REACTION_TABLE = "report_reaction"
DUPLICATE_TABLE = "report_duplicate"
OPENFDA_TABLE = "dim_openfda"

TABLES = (REPORT_TABLE, DRUG_TABLE, REACTION_TABLE, DUPLICATE_TABLE, OPENFDA_TABLE)

# The columns each table gets from this module rather than from a report — the
# join keys and positions `_row` writes. Their types are known before a record
# is read, which is what schema.py needs to keep `seq` an integer in a partition
# where every row of it is null. `report` has none: its `safetyreportid` is the
# source's own field, travelling like any other.
#
# A column missing from here is inferred like source data, which is the harmless
# direction for this to drift in.
PIPELINE_COLUMNS = {
    REPORT_TABLE: (),
    DRUG_TABLE: (REPORT_ID, SEQ, OPENFDA_KEY),
    REACTION_TABLE: (REPORT_ID, SEQ),
    DUPLICATE_TABLE: (REPORT_ID, SEQ),
    OPENFDA_TABLE: (OPENFDA_KEY,),
}

# The two `patient` arrays that become tables of their own. Not a keep-list:
# every other patient field travels into the report row untouched, whatever it
# is called. These two are named because they are the table boundary — which is
# also why they are derived from the same constants the loops read, rather than
# written out a second time.
CHILD_ARRAYS = (DRUG, REACTION)

# The top-level fields that do not travel into the report row: `patient` because
# it is unwrapped into `pt_` columns and two tables, `reportduplicate` because it
# is a repeated child of its own (see `_duplicates`).
UNWRAPPED = (PATIENT, DUPLICATE)


# --- errors -----------------------------------------------------------------


class NormalizeError(Exception):
    """Base for every failure in this module."""


class KeyCollision(NormalizeError):
    """Two different blocks hashed to the same dimension key.

    Astronomically unlikely, and silent if unchecked: every drug row pointing
    at the key would carry another product's enrichment.
    """


class UnexpectedReportShape(NormalizeError):
    """A report is not the shape the table model can hold.

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
    """One report's contribution to each of the five tables.

    `openfda` holds only the blocks this report was the first to carry, so
    concatenating every `RowSet` in a partition gives the dimension exactly
    once. It is empty for the great majority of reports.
    """

    report: dict
    drugs: list[dict]
    reactions: list[dict]
    duplicates: list[dict]
    openfda: list[dict]

    def by_table(self) -> dict[str, list[dict]]:
        """The same rows, keyed by the table each one belongs to.

        The report row is wrapped in a list so that both passes over a partition
        — inferring the schema and writing the Parquet — are one loop over five
        identical cases instead of one loop and a special case.
        """
        return {
            REPORT_TABLE: [self.report],
            DRUG_TABLE: self.drugs,
            REACTION_TABLE: self.reactions,
            DUPLICATE_TABLE: self.duplicates,
            OPENFDA_TABLE: self.openfda,
        }


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


def _entries(container: dict, field: str, report_id: str) -> Iterator[tuple[int, dict]]:
    """Yield `(position, entry)` for one of the repeated children, or nothing.

    The type checks are not ceremony. `enumerate` accepts a string and yields
    one character per position, so an array that arrives as a scalar would
    become rows that look entirely valid until the round-trip test runs.
    """
    entries = container.get(field)

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


def _duplicates(report: dict, report_id: str) -> Iterator[tuple[int | None, dict]]:
    """Yield `(position, entry)` for `reportduplicate`, in either shape it comes.

    openFDA serializes one occurrence as a bare object and two or more as an
    array. Measured over 2025q1/0001-of-0028: 1,857 objects, 1,096 arrays, and
    **not one array of length 1** — the fingerprint of an XML-to-JSON conversion,
    where a repeated element that happens to occur once has no array to be in.

    So the position is `None` for the bare object, and that null is the whole
    record of which shape the source used: T10 puts an object back as an object
    rather than as a list of one. Deriving the shape from the row count instead
    — one row means object — reproduces this partition exactly and rests on a
    rule nobody guarantees, in a corpus spanning 2004 to 2025 of which exactly
    one export has been looked at.

    `duplicatenumb` is the field M2's deduplication joins on, which is the other
    reason this is a table rather than a column: a repeated child in a column is
    something every later query has to unnest first.
    """
    entries = report.get(DUPLICATE)

    if isinstance(entries, dict):
        yield None, entries

        return

    yield from _entries(report, DUPLICATE, report_id)


def split(report: dict, dimension: OpenfdaDimension) -> RowSet:
    """Turn one report into rows for the report, drug, reaction and dim tables.

    `dimension` accumulates across the whole partition — pass the same instance
    to every call, or each block is emitted once per report instead of once.
    Routing the block through it here is what keeps the absent-vs-empty rule
    (L-005) inside this module rather than repeated at every call site.

    Raises:
        UnexpectedReportShape: the report cannot be held by the tables.
        KeyCollision: two openfda blocks truncated to one dimension key.
    """
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
