"""The inverse of `split`, which is how "lossless" stops being an adjective.

`normalize.split` claims that a nested FAERS report survives being torn into
five flat tables. That claim is checkable rather than assertable: if the claim
is true then `reconstruct(split(report)) == report`, and the equality either
holds for all 12,000 reports of a partition or it does not.

It is worth being precise about why this module carries the weight it does. The
pipeline's headline number — 807 MB of JSON becoming 4.62 MB of Parquet, 175×
— is a compression ratio, and a compression ratio without a round trip is a
statement about how much data you threw away. The first version of this
transformation *was* lossy, and it looked fine: valid output, matching row
counts, a better ratio than the correct version (L-005). Nothing downstream
could see the hole. This is the only thing that can.

**Reconstruction is mechanical, and that is by design.** Every choice `split`
made was made so that undoing it requires no lookup table and no knowledge of
FAERS:

- `pt_` prefix -> the key goes back inside `patient`, everything else stays top
  level. The prefix exists for this line and nothing else.
- `seq` -> the position in the original array. SQL tables are unordered; without
  the index a report's drugs come back in whatever order Parquet felt like.
- `openfda_key` -> look the block up in the dimension. `None` means the source
  had no `openfda` at all, and a key pointing at `{}` means it had an empty one.
  Those are different facts and collapsing them cost 492 mismatches once.
- `seq IS NULL` on a duplicate -> the source carried a bare object rather than
  an array (AD-013). One null column is the entire record of a shape openFDA
  serializes two ways.

**The one normalization, and why it is not cheating.** Parquet has no concept of
an absent column: a report with no `companynumb` is stored with `companynumb`
null, and reading it back gives `{"companynumb": None}` where the source had no
such key. So the comparison strips nulls from both sides.

That is legitimate only under a condition, and the condition is measurable
rather than assumed: **the source must never carry an explicit JSON null.** If
it did, stripping would erase a real value and turn a genuine mismatch into a
pass — the failure mode where the test that exists to catch data loss is the
thing hiding it. Measured over 2025q1/0001-of-0028: zero explicit nulls in
19,648,458 scalars. The check runs in T11 against every partition the round trip
is claimed on, because it is a property of an export and not of the format.

**A known hole, recorded rather than papered over.** An empty array in the
source (`"drug": []`) produces zero child rows, which is indistinguishable from
an absent `drug` field, and this module rebuilds the absent version. Nothing in
the 2026-08-10 export triggers it — L-007 checked every array in the partition
and none is empty — so it is a hole with no known instance rather than a bug
with no fix. It is on STATE.md's todo list and it is M1's to close, before the
crawler reaches partitions nobody has read.
"""

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


# --- errors -----------------------------------------------------------------


class RoundTripError(Exception):
    """Base for every failure in this module."""


class UnknownReport(RoundTripError):
    """No report row carries the requested id."""


class BrokenTables(RoundTripError):
    """The tables cannot produce the report they claim to hold.

    Every case here means the corpus is already wrong — a drug row pointing at a
    dimension key nobody wrote, a gap in the `seq` of an array, a duplicate that
    is somehow an object and an array at once. Raised loudly, because the
    alternative is a reconstruction that silently differs from a source nobody
    still has.
    """


# --- the one normalization ---------------------------------------------------


def _without_nulls(value: object) -> object:
    """Drop every null-valued key, at every depth.

    This is the inverse of what Parquet does on the way in, not a convenience:
    an absent field and a null column are the same fact in the source, and only
    because the source never writes an explicit null (module docstring).

    It recurses into structs, which is what makes `primarysource` come back with
    the two keys the report had rather than the union of every key any report
    had. List *items* are recursed into but never dropped — a null inside an
    array is a position, and positions are what `seq` exists to preserve.
    """
    if isinstance(value, dict):
        return {
            name: _without_nulls(child)
            for name, child in value.items()
            if child is not None
        }

    if isinstance(value, list):
        return [_without_nulls(item) for item in value]

    return value


# --- the tables ---------------------------------------------------------------


@dataclass(frozen=True)
class Tables:
    """One partition's five tables, indexed for reconstruction.

    Child rows are grouped by `safetyreportid` on load rather than scanned per
    report. Rebuilding 12,000 reports out of 71,990 drug rows is 12,000 linear
    scans if the grouping is not done once — quadratic on the number the corpus
    grows in.
    """

    reports: dict[str, dict]
    drugs: dict[str, list[dict]]
    reactions: dict[str, list[dict]]
    duplicates: dict[str, list[dict]]
    openfda: dict[str, dict]

    @property
    def report_ids(self) -> list[str]:
        """Every report the tables can rebuild, for T11 to iterate."""
        return list(self.reports)

    @classmethod
    def from_rows(cls, rows: dict[str, list[dict]]) -> "Tables":
        """Index rows already in memory, keyed by table name.

        The Parquet reader and a caller holding `RowSet.by_table()` output land
        here together, so the indexing rules are written once and `load` is only
        about reading files.
        """
        return cls(
            reports={row[REPORT_ID]: row for row in rows[REPORT_TABLE]},
            drugs=_by_report(rows[DRUG_TABLE]),
            reactions=_by_report(rows[REACTION_TABLE]),
            duplicates=_by_report(rows[DUPLICATE_TABLE]),
            openfda={row[OPENFDA_KEY]: row for row in rows[OPENFDA_TABLE]},
        )

    @classmethod
    def load(cls, directory: Path) -> "Tables":
        """Read all five Parquet files of one partition.

        Reading the artifact rather than reusing the rows `split` produced is
        the point of the exercise. Rows held in memory prove that `reconstruct`
        inverts `split`; the files prove that nothing was lost between them —
        which is where a schema that drops a column silently would hide.
        """
        return cls.from_rows(
            {
                table: pq.read_table(directory / f"{table}.parquet").to_pylist()
                for table in TABLES
            }
        )


def _by_report(rows: list[dict]) -> dict[str, list[dict]]:
    """Group child rows by the report they belong to."""
    grouped: dict[str, list[dict]] = defaultdict(list)

    for row in rows:
        grouped[row[REPORT_ID]].append(row)

    return grouped


# --- rebuilding one report ----------------------------------------------------


def _entry(row: dict, *columns: str) -> dict:
    """A stored row as the source object it came from: named columns dropped.

    Which columns to drop is the caller's, because it is not uniform: a drug row
    keeps its `openfda_key` a moment longer than the others, since `_drugs`
    needs the value before it can throw the column away.
    """
    return _without_nulls(
        {name: value for name, value in row.items() if name not in columns}
    )


def _ordered(rows: list[dict], table: str, report_id: str) -> list[dict]:
    """Child rows back in their original array order.

    A gap or a repeat in `seq` means rows were lost or duplicated between the
    split and here, and the reconstruction would be quietly short. Checked
    rather than tolerated: `sorted` would happily return four entries for an
    array that had five.
    """
    positions = sorted(row[SEQ] for row in rows)

    if positions != list(range(len(rows))):
        raise BrokenTables(
            f"report {report_id!r}: {table} has {SEQ} {positions}, which is not "
            f"0..{len(rows) - 1}. The original array order cannot be restored "
            f"from rows that are missing or duplicated."
        )

    return [
        _entry(row, REPORT_ID, SEQ) for row in sorted(rows, key=lambda row: row[SEQ])
    ]


def _drugs(tables: "Tables", report_id: str) -> list[dict]:
    """The drug array, with each `openfda` block rejoined from the dimension."""
    drugs = _ordered(tables.drugs.get(report_id, []), DRUG_TABLE, report_id)

    for drug in drugs:
        # Absent after `_without_nulls` means the column was null, and a null
        # `openfda_key` means the source drug had no `openfda` at all. A block
        # that was present but empty has a real key pointing at an empty row,
        # which is the distinction L-005 was built on.
        block_key = drug.pop(OPENFDA_KEY, None)

        if block_key is None:
            continue

        block = tables.openfda.get(block_key)

        if block is None:
            raise BrokenTables(
                f"report {report_id!r}: a drug row points at openfda_key "
                f"{block_key!r}, which {OPENFDA_TABLE} has no row for. The "
                f"block's contents are gone, not merely unjoined."
            )

        drug[OPENFDA] = _entry(block, OPENFDA_KEY)

    return drugs


def _duplicates(tables: "Tables", report_id: str) -> dict | list[dict] | None:
    """`reportduplicate` in the shape the source used, or None if it had none.

    A null `seq` is the bare-object marker (AD-013), and it is the whole reason
    this is not just another `_ordered` call. The two shapes cannot be mixed —
    a report has one `reportduplicate` field and the source wrote it one way —
    so a table holding both for one report is corrupt rather than ambiguous.
    """
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
        f"a bare object, so it can only ever appear alone — this report is "
        f"recorded as having been both an object and an array."
    )


def reconstruct(tables: Tables, report_id: str) -> dict:
    """Rebuild one report's original nested JSON from the five tables.

    Raises:
        UnknownReport: no report row carries this id.
        BrokenTables: the rows cannot produce the report they claim to.
    """
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

    # Empty means the source field was absent — zero child rows is what an
    # absent array produces. It is also what an *empty* array would produce, a
    # collision nothing in this export can trigger (module docstring).
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
