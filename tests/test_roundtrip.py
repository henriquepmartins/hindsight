"""The proof that "lossless" is a test result and not an adjective.

This file is the highest-value artifact in M0. It found two real bugs before any
pipeline existed (L-005), and the compression number the project publishes —
175× — is a statement about how much data was thrown away until this passes.

**The comparison is deliberately one-sided.** The spike normalized *both*
documents before comparing them: Parquet has no absent column, so a report with
no `companynumb` reads back as `{"companynumb": None}`, and stripping nulls from
each side made the two agree. That works, and it is also the shape of a test
that cannot fail — any normalization applied to both sides of an equality can
only ever make it pass (L-008).

So the source is never touched here. `reconstruct` strips nulls on the way out,
which is legitimate only while the source carries no explicit null of its own,
and that condition is a *test* rather than a comment — the first one below. If a
2005-era partition ever carries an explicit null, that test goes red and says so,
instead of the round trip quietly starting to compare two documents after
deleting the difference between them.

**The fixture is chosen, not sampled.** 100 random reports cover the common case
100 times and the cases that broke this project zero times. The shapes it was
picked for are asserted below, so the fixture cannot silently stop covering them
when it is regenerated against a future export.
"""

import json
from pathlib import Path

import pytest

from hindsight.normalize import TABLES, OpenfdaDimension, split
from hindsight.roundtrip import (
    BrokenTables,
    Tables,
    UnknownReport,
    reconstruct,
)
from hindsight.schema import infer
from hindsight.stream import iter_reports
from hindsight.write import write_partition


FIXTURE = Path(__file__).parent / "fixtures" / "sample_100.json"

# The full partition, for the slow test. Absent on a clean clone and in CI,
# which is the whole reason the fixture exists.
PARTITION_ZIP = Path("data/raw/2025q1-0001-of-0028.zip")
PARTITION_PARQUET = Path("data/parquet/year=2025/quarter=1/part=0001-of-0028")


# --- helpers ------------------------------------------------------------------


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def explicit_nulls(value: object, path: str = "report") -> list[str]:
    """Every place a document carries an explicit JSON null.

    The precondition the whole comparison rests on, expressed as data so a
    failure can name where rather than just that.
    """
    found: list[str] = []

    if isinstance(value, dict):
        for name, child in value.items():
            found += (
                [f"{path}.{name}"]
                if child is None
                else explicit_nulls(child, f"{path}.{name}")
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found += (
                [f"{path}[{index}]"]
                if item is None
                else explicit_nulls(item, f"{path}[{index}]")
            )

    return found


def differences(source: object, rebuilt: object, path: str = "") -> list[str]:
    """Where two documents disagree, deepest name first.

    `assert a == b` on two 46 KB nested dicts prints both of them and leaves you
    to find the character that moved. The criterion for this task is that a
    failure names the field, so the diff is computed rather than dumped.
    """
    if isinstance(source, dict) and isinstance(rebuilt, dict):
        found = []

        for name in sorted(source.keys() | rebuilt.keys()):
            where = f"{path}.{name}" if path else name

            if name not in source:
                found.append(f"{where}: only in rebuilt ({canonical(rebuilt[name])[:120]})")
            elif name not in rebuilt:
                found.append(f"{where}: only in source ({canonical(source[name])[:120]})")
            else:
                found += differences(source[name], rebuilt[name], where)

        return found

    if isinstance(source, list) and isinstance(rebuilt, list):
        if len(source) != len(rebuilt):
            return [f"{path}: {len(source)} entries in source, {len(rebuilt)} rebuilt"]

        return [
            d
            for index, (a, b) in enumerate(zip(source, rebuilt))
            for d in differences(a, b, f"{path}[{index}]")
        ]

    if canonical(source) != canonical(rebuilt):
        return [
            f"{path}: source {canonical(source)[:120]} != rebuilt "
            f"{canonical(rebuilt)[:120]}"
        ]

    return []


def tables_in_memory(reports: list[dict]) -> Tables:
    """Split the reports and index the rows, without going through Parquet."""
    dimension = OpenfdaDimension()
    rows: dict[str, list[dict]] = {table: [] for table in TABLES}

    for report in reports:
        for table, produced in split(report, dimension).by_table().items():
            rows[table] += produced

    return Tables.from_rows(rows)


def assert_round_trips(reports: list[dict], tables: Tables) -> int:
    """Every report rebuilds identically, or fail naming which and where."""
    for source in reports:
        report_id = source["safetyreportid"]
        found = differences(source, reconstruct(tables, report_id))

        assert not found, "safetyreportid {}: {} field(s) differ\n  {}".format(
            report_id, len(found), "\n  ".join(found[:20])
        )

    return len(reports)


@pytest.fixture(scope="module")
def sample() -> list[dict]:
    return json.loads(FIXTURE.read_text())


# --- the precondition the comparison rests on (L-008) -------------------------


def test_the_source_carries_no_explicit_nulls(sample):
    """`reconstruct` strips nulls, and that is an inverse of Parquet's nullable
    columns only while the source never writes a null of its own. If it does,
    the strip erases a real value and the round trip passes by deleting the
    difference — the test built to catch data loss becoming the thing that hides
    it. Measured across the whole partition: zero. Asserted here so a future
    export cannot change it quietly."""
    found = [path for report in sample for path in explicit_nulls(report)]

    assert not found, f"{len(found)} explicit nulls, first: {found[:5]}"


# --- the fixture is chosen, not sampled ---------------------------------------


def test_the_fixture_covers_the_shapes_it_was_chosen_for(sample):
    """A fixture regenerated against a future export could pass every round-trip
    assertion while covering none of the cases that ever broke this project. The
    counts are the recipe, executable instead of described."""

    def drugs(report):
        return (report.get("patient") or {}).get("drug") or []

    covered = {
        # the two facts L-005 cost 492 mismatches over
        "a drug with openfda: {}": sum(
            any(d.get("openfda") == {} for d in drugs(r)) for r in sample
        ),
        "a drug with no openfda": sum(
            any("openfda" not in d for d in drugs(r)) for r in sample
        ),
        # AD-013's two serializations
        "reportduplicate as an object": sum(
            isinstance(r.get("reportduplicate"), dict) for r in sample
        ),
        "reportduplicate as an array": sum(
            isinstance(r.get("reportduplicate"), list) for r in sample
        ),
        # order is only falsifiable above one
        "5+ drugs": sum(len(drugs(r)) >= 5 for r in sample),
        # the fields the keep-list dropped
        "patient.summary present": sum(
            "summary" in (r.get("patient") or {}) for r in sample
        ),
        "no companynumb": sum("companynumb" not in r for r in sample),
    }

    missing = [name for name, count in covered.items() if count == 0]

    assert not missing, f"the fixture no longer covers: {missing} (have {covered})"
    assert len(sample) == 100


def test_the_fixture_needs_no_network_and_no_partition():
    """CI runs on push. A 155 MB download per push is what this file exists to
    avoid, so the fast path must not reach for the partition at all."""
    assert FIXTURE.exists()
    assert FIXTURE.stat().st_size < 8 * 1024 * 1024


# --- the round trip, in memory ------------------------------------------------


def test_every_fixture_report_rebuilds_identically(sample):
    assert assert_round_trips(sample, tables_in_memory(sample)) == 100


def test_drug_order_survives(sample):
    """`seq` is the only thing standing between an ordered JSON array and an
    unordered SQL table. Checked on the reports that have enough drugs for the
    question to mean anything."""
    tables = tables_in_memory(sample)
    checked = 0

    for source in sample:
        drugs = (source.get("patient") or {}).get("drug") or []

        if len(drugs) < 2:
            continue

        checked += 1
        rebuilt = reconstruct(tables, source["safetyreportid"])

        assert [canonical(d) for d in rebuilt["patient"]["drug"]] == [
            canonical(d) for d in drugs
        ]

    assert checked > 0, "the fixture has no multi-drug report left to check order on"


def test_an_empty_openfda_comes_back_as_an_empty_object(sample):
    """`openfda: {}` means someone looked and found no enrichment; an absent
    `openfda` means nobody looked. The rebuilt drug must say which."""
    tables = tables_in_memory(sample)
    seen = 0

    for source in sample:
        for position, drug in enumerate((source.get("patient") or {}).get("drug") or []):
            if drug.get("openfda") != {}:
                continue

            seen += 1
            rebuilt = reconstruct(tables, source["safetyreportid"])

            assert rebuilt["patient"]["drug"][position]["openfda"] == {}

    assert seen > 0, "the fixture no longer contains the L-005 case"


def test_the_two_duplicate_shapes_come_back_as_they_arrived(sample):
    """AD-013: a null `seq` is a bare object, `seq` 0..N is an array. Promoting
    the object to a one-element list would pass a looser test and make
    "byte-identical" mean "identical after a normalization we did not
    mention"."""
    tables = tables_in_memory(sample)
    objects = arrays = 0

    for source in sample:
        original = source.get("reportduplicate")

        if original is None:
            continue

        rebuilt = reconstruct(tables, source["safetyreportid"])["reportduplicate"]

        assert type(rebuilt) is type(original)
        assert canonical(rebuilt) == canonical(original)

        objects += isinstance(original, dict)
        arrays += isinstance(original, list)

    assert objects and arrays, f"fixture covers {objects} objects, {arrays} arrays"


# --- the round trip, through the real artifact --------------------------------


def test_the_fixture_rebuilds_from_parquet(sample, tmp_path):
    """In-memory rows prove `reconstruct` inverts `split`. Only the files prove
    nothing was lost between them — a schema missing a column drops it silently
    and writes valid Parquet with matching row counts, which is exactly the
    L-005 failure with better paperwork."""
    write_partition(sample, infer(sample), tmp_path)

    assert assert_round_trips(sample, Tables.load(tmp_path)) == 100


# --- the bug this test exists for ---------------------------------------------


def test_collapsing_empty_openfda_into_absent_is_caught(sample):
    """`k = key(o) if o else None` — the one-character class of bug that produced
    492 mismatches in the spike. An empty dict is falsy, so `openfda: {}` gets
    treated as absent.

    The bug is simulated in the tables rather than reintroduced in
    `normalize.py`, so the property is permanent instead of a manual step
    someone has to remember to repeat. The task also asks for the manual break;
    that is the Verify block, and this is what keeps it from being a one-off."""
    source = next(
        r
        for r in sample
        if any(d.get("openfda") == {} for d in (r.get("patient") or {}).get("drug") or [])
    )
    tables = tables_in_memory([source])

    empty = [
        key
        for key, block in tables.openfda.items()
        if not {
            name: value
            for name, value in block.items()
            if name != "openfda_key" and value is not None
        }
    ]

    # Not `next(...)`: with the bug live no empty block ever reaches the
    # dimension, and a bare StopIteration would report the symptom as a crash
    # in the test rather than as the bug it is looking for.
    assert empty, (
        "the fixture's `openfda: {}` never reached dim_openfda. If "
        "`OpenfdaDimension.add` is testing the block for truthiness instead of "
        "`is not None`, that IS the L-005 bug and this is the test saying so."
    )
    empty_key = empty[0]

    # what `if o` would have produced: the key never assigned, the block never emitted
    for row in tables.drugs[source["safetyreportid"]]:
        if row.get("openfda_key") == empty_key:
            row["openfda_key"] = None

    del tables.openfda[empty_key]

    found = differences(source, reconstruct(tables, source["safetyreportid"]))

    assert found, "the falsy-openfda bug went undetected — this test is the reason"
    assert any("openfda" in difference for difference in found), found[:5]


# --- what the tables refuse ----------------------------------------------------


def test_an_unknown_report_id_says_so(sample):
    with pytest.raises(UnknownReport, match="nope"):
        reconstruct(tables_in_memory(sample), "nope")


def test_a_gap_in_seq_is_not_quietly_shortened(sample):
    """`sorted` returns four entries for an array that had five and looks
    entirely correct doing it."""
    source = next(
        r for r in sample if len((r.get("patient") or {}).get("drug") or []) >= 3
    )
    tables = tables_in_memory([source])
    report_id = source["safetyreportid"]
    tables.drugs[report_id].pop(1)

    with pytest.raises(BrokenTables, match="seq"):
        reconstruct(tables, report_id)


def test_a_duplicate_that_is_both_shapes_at_once_raises(sample):
    """A report has one `reportduplicate` field and the source wrote it one way.
    Rows saying both is corruption, not ambiguity, and guessing which to believe
    is how AD-013's contract quietly stops meaning anything."""
    source = next(
        r for r in sample if isinstance(r.get("reportduplicate"), list)
    )
    tables = tables_in_memory([source])
    report_id = source["safetyreportid"]
    tables.duplicates[report_id][0]["seq"] = None

    with pytest.raises(BrokenTables, match="null"):
        reconstruct(tables, report_id)


def test_a_drug_pointing_at_a_missing_block_raises(sample):
    """The enrichment is gone, not merely unjoined. Returning the drug without
    it would be silent data loss with a passing test."""
    source = next(
        r
        for r in sample
        if any("openfda" in d for d in (r.get("patient") or {}).get("drug") or [])
    )
    tables = tables_in_memory([source])
    tables.openfda.clear()

    with pytest.raises(BrokenTables, match="openfda_key"):
        reconstruct(tables, source["safetyreportid"])


# --- the whole partition ------------------------------------------------------


@pytest.mark.slow
def test_the_whole_partition_rebuilds_from_parquet():
    """12,000 reports against the Parquet the pipeline actually wrote.

    Local only — it needs the 155 MB partition and the ingest to have run. The
    fixture above is what CI gets, and the two must not drift: this is the test
    that says the fixture's 100 reports were representative of the 12,000 rather
    than merely convenient.
    """
    if not (PARTITION_ZIP.exists() and (PARTITION_PARQUET / "report.parquet").exists()):
        pytest.skip(f"needs {PARTITION_ZIP} and a completed ingest into {PARTITION_PARQUET}")

    tables = Tables.load(PARTITION_PARQUET)
    compared = mismatched = 0
    first_failure = ""

    for source in iter_reports(PARTITION_ZIP):
        compared += 1
        assert not explicit_nulls(source), (
            f"report {source['safetyreportid']} carries an explicit null — the "
            f"round-trip comparison's meaning changes here (L-008)"
        )

        found = differences(source, reconstruct(tables, source["safetyreportid"]))

        if found:
            mismatched += 1
            first_failure = first_failure or (
                f"safetyreportid {source['safetyreportid']}: {found[:10]}"
            )

    print(f"\n{compared - mismatched:,}/{compared:,} byte-identical")

    assert mismatched == 0, f"{mismatched:,} of {compared:,} differ. First: {first_failure}"
    assert compared == 12000
