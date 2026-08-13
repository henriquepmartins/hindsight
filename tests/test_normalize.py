"""Content-addressed openfda blocks, and one report becoming four tables' rows.

Three properties carry the weight here. The openfda key must depend on a
block's content and nothing else — not key order, not insertion order, not the
run — because `dim_openfda` doubles quietly if it doesn't. An empty block must
stay distinguishable from an absent one, which is the bug (L-005) that these
tests exist to keep dead. And `split` must carry every field it is handed:
these tests are written so that any keep-list, any dropped field, and any
silently overwritten column turns one of them red.
"""

import pytest

from hindsight import normalize as n
from hindsight.normalize import (
    KeyCollision,
    OpenfdaDimension,
    UnexpectedReportShape,
    key,
    split,
)


ASPIRIN = {"brand_name": ["ASPIRIN"], "unii": ["R16CO5Y76E"]}
IBUPROFEN = {"brand_name": ["ADVIL"], "unii": ["WK2XYI10QM"]}


@pytest.fixture
def dimension():
    return OpenfdaDimension()


def report(**overrides) -> dict:
    """A minimal well-formed report. Overrides are the point of each test."""
    return {"safetyreportid": "1", "receiptdate": "20250101"} | overrides


# --- the key is the content -------------------------------------------------


def test_key_ignores_the_order_the_block_was_written_in():
    assert key({"a": ["1"], "b": ["2"]}) == key({"b": ["2"], "a": ["1"]})


def test_key_ignores_key_order_at_every_depth():
    """`sort_keys=True` recurses. If it didn't, nested reordering would split
    one product into two dimension rows."""
    deep = {"outer": {"a": ["1"], "b": ["2"]}, "unii": ["X"]}
    shuffled = {"unii": ["X"], "outer": {"b": ["2"], "a": ["1"]}}

    assert key(deep) == key(shuffled)


def test_key_is_pinned_not_merely_stable():
    """A literal, so that changing the separators, the sort, or the encoding
    fails here rather than silently re-keying every dimension row ever written."""
    assert key(ASPIRIN) == "59556fc197ca0cfa"
    assert key({}) == "bf21a9e8fbc5a384"


def test_key_is_the_documented_width():
    assert len(key(ASPIRIN)) == n.KEY_LENGTH


def test_different_blocks_get_different_keys():
    assert key(ASPIRIN) != key(IBUPROFEN)


# --- absent is not empty ----------------------------------------------------


def test_an_empty_block_is_a_real_block_with_a_real_key():
    assert key({}) is not None


def test_an_absent_block_has_no_key():
    assert key(None) is None


def test_the_falsy_test_is_the_bug_this_rule_exists_for():
    """`if block` instead of `if block is not None` collapses `openfda: {}` into
    absent — 492 mismatches in the spike, and 507 blocks in this partition that
    would follow. Shown side by side rather than committed and waited on."""
    empty = {}

    assert key(empty) is not None
    assert (key(empty) if empty else None) is None


# --- first-sight emission ---------------------------------------------------


def test_a_block_is_emitted_the_first_time_and_not_again(dimension):
    first_key, first_row = dimension.add(ASPIRIN)
    second_key, second_row = dimension.add(ASPIRIN)

    assert first_row is ASPIRIN
    assert second_row is None
    assert first_key == second_key == key(ASPIRIN)


def test_a_reordered_block_is_the_same_block(dimension):
    dimension.add({"a": ["1"], "b": ["2"]})
    _, row = dimension.add({"b": ["2"], "a": ["1"]})

    assert row is None
    assert len(dimension) == 1


def test_every_distinct_block_is_emitted(dimension):
    emitted = [dimension.add(b)[1] for b in (ASPIRIN, IBUPROFEN, ASPIRIN, {})]

    assert emitted == [ASPIRIN, IBUPROFEN, None, {}]
    assert len(dimension) == 3


def test_an_absent_block_costs_the_caller_no_branch(dimension):
    """(None, None) is what lets T9's write loop stay a straight line, which is
    where the L-005 test would otherwise have to be repeated by hand."""
    assert dimension.add(None) == (None, None)
    assert len(dimension) == 0


# --- what the dimension is allowed to remember ------------------------------


def test_the_dimension_holds_digests_not_blocks(dimension):
    """The whole memory argument, pinned. The spike kept the blocks and that is
    the version that does not survive 1,767 partitions."""
    for block in (ASPIRIN, IBUPROFEN, {}):
        dimension.add(block)

    assert set(vars(dimension)) == {"_digests"}
    assert all(isinstance(value, str) for value in dimension._digests.values())


def test_a_truncation_collision_raises_rather_than_merging(monkeypatch, dimension):
    """Two blocks, one key. Forced, because a real sha1 truncation collision is
    not something a test can produce — but a silent merge would hand every drug
    row at that key another product's enrichment."""
    monkeypatch.setattr(
        n, "_digest", lambda block: "f" * n.KEY_LENGTH + ("1" if block else "2") * 24
    )

    dimension.add(ASPIRIN)

    with pytest.raises(KeyCollision, match="truncate to 'ffffffffffffffff'"):
        dimension.add({})


def test_the_same_block_under_a_shared_key_is_not_a_collision(monkeypatch, dimension):
    monkeypatch.setattr(n, "_digest", lambda block: "f" * 40)

    dimension.add(ASPIRIN)

    assert dimension.add(IBUPROFEN)[1] is None


# --- split: the report row --------------------------------------------------


def test_every_top_level_field_travels_except_patient(dimension):
    source = report(occurcountry="US", patient={"patientsex": "1"})

    rows = split(source, dimension)

    assert rows.report == {
        "safetyreportid": "1",
        "receiptdate": "20250101",
        "occurcountry": "US",
        "pt_patientsex": "1",
    }


def test_a_field_nobody_has_seen_before_still_travels(dimension):
    """The L-005 rule as a test: no keep-list can exist if an invented field
    arrives intact. `companynumb` was dropped from 89.6% of reports exactly
    because the column list came from inspecting one record."""
    source = report(fieldinventedin2031="x", patient={"pt_era_field": "y"})

    rows = split(source, dimension)

    assert rows.report["fieldinventedin2031"] == "x"
    assert rows.report["pt_pt_era_field"] == "y"


def test_a_nested_patient_object_stays_an_object(dimension):
    """`pt_summary` is an Arrow struct, not a flattened pair of columns and not
    a JSON string (design.md). Reconstruction is then a straight assignment."""
    source = report(patient={"summary": {"narrativeincludeclinical": "text"}})

    rows = split(source, dimension)

    assert rows.report["pt_summary"] == {"narrativeincludeclinical": "text"}


def test_the_patient_arrays_never_land_in_the_report_row(dimension):
    source = report(patient={"drug": [{"medicinalproduct": "ASPIRIN"}], "reaction": [{}]})

    rows = split(source, dimension)

    assert "pt_drug" not in rows.report
    assert "pt_reaction" not in rows.report


def test_a_report_without_a_patient_still_produces_its_row(dimension):
    rows = split(report(), dimension)

    assert rows.report == {"safetyreportid": "1", "receiptdate": "20250101"}
    assert rows.drugs == []
    assert rows.reactions == []


def test_a_prefixed_patient_field_may_not_overwrite_a_real_top_level_one(dimension):
    """No such collision exists in the 2026-08-10 export — checked, all 27
    top-level names, none start with `pt_`. If openFDA ever adds one, the
    report row would silently carry one value where the source had two."""
    source = report(pt_patientsex="top level", patient={"patientsex": "1"})

    with pytest.raises(UnexpectedReportShape, match="pt_patientsex"):
        split(source, dimension)


# --- split: drug rows -------------------------------------------------------


def test_one_row_per_drug_keyed_and_ordered(dimension):
    source = report(
        patient={"drug": [{"medicinalproduct": "ASPIRIN"}, {"medicinalproduct": "ADVIL"}]}
    )

    rows = split(source, dimension)

    assert rows.drugs == [
        {"safetyreportid": "1", "seq": 0, "openfda_key": None, "medicinalproduct": "ASPIRIN"},
        {"safetyreportid": "1", "seq": 1, "openfda_key": None, "medicinalproduct": "ADVIL"},
    ]


def test_seq_is_the_source_position_not_a_counter_over_kept_rows(dimension):
    """`seq` is what makes the round trip order-preserving. A count of emitted
    rows would drift the moment anything is ever skipped."""
    source = report(patient={"drug": [{}, {}, {}]})

    rows = split(source, dimension)

    assert [drug["seq"] for drug in rows.drugs] == [0, 1, 2]


def test_the_openfda_block_leaves_the_drug_row_and_becomes_a_key(dimension):
    source = report(patient={"drug": [{"medicinalproduct": "ASPIRIN", "openfda": ASPIRIN}]})

    rows = split(source, dimension)

    assert "openfda" not in rows.drugs[0]
    assert rows.drugs[0]["openfda_key"] == key(ASPIRIN)


def test_an_absent_block_keys_to_none_and_an_empty_one_does_not(dimension):
    """The L-005 distinction, at the call site that matters: 507 drug rows in
    this partition carry `openfda: {}` and 11,128 carry nothing at all."""
    source = report(patient={"drug": [{}, {"openfda": {}}]})

    rows = split(source, dimension)

    assert rows.drugs[0]["openfda_key"] is None
    assert rows.drugs[1]["openfda_key"] == key({})


def test_a_block_reaches_the_dimension_once_however_many_drugs_cite_it(dimension):
    source = report(
        patient={"drug": [{"openfda": ASPIRIN}, {"openfda": ASPIRIN}, {"openfda": IBUPROFEN}]}
    )

    rows = split(source, dimension)

    assert rows.openfda == [
        {"openfda_key": key(ASPIRIN)} | ASPIRIN,
        {"openfda_key": key(IBUPROFEN)} | IBUPROFEN,
    ]


def test_a_block_already_seen_in_an_earlier_report_is_not_emitted_again(dimension):
    """The dedup is corpus-wide, not per-report — 27× on this partition alone,
    and the ratio only widens across 1,767 of them."""
    split(report(patient={"drug": [{"openfda": ASPIRIN}]}), dimension)

    rows = split(report(safetyreportid="2", patient={"drug": [{"openfda": ASPIRIN}]}), dimension)

    assert rows.openfda == []
    assert rows.drugs[0]["openfda_key"] == key(ASPIRIN)


def test_a_report_with_no_drugs_is_not_a_skipped_report(dimension):
    source = report(patient={"patientsex": "1", "reaction": [{"reactionmeddrapt": "Nausea"}]})

    rows = split(source, dimension)

    assert rows.report["pt_patientsex"] == "1"
    assert rows.drugs == []
    assert len(rows.reactions) == 1


# --- split: reaction rows ---------------------------------------------------


def test_one_row_per_reaction_keyed_and_ordered(dimension):
    source = report(
        patient={"reaction": [{"reactionmeddrapt": "Nausea"}, {"reactionmeddrapt": "Rash"}]}
    )

    rows = split(source, dimension)

    assert rows.reactions == [
        {"safetyreportid": "1", "seq": 0, "reactionmeddrapt": "Nausea"},
        {"safetyreportid": "1", "seq": 1, "reactionmeddrapt": "Rash"},
    ]


# --- split: duplicate rows, and the shape the source used -------------------


def test_one_duplicate_arrives_as_a_bare_object_and_keeps_a_null_seq(dimension):
    """openFDA writes one occurrence as an object and two or more as an array —
    1,857 against 1,096 in this partition, and never an array of one. The null
    `seq` is the only record of which shape the source used, and T10 needs it to
    put an object back as an object."""
    source = report(reportduplicate={"duplicatenumb": "D1", "duplicatesource": "X"})

    rows = split(source, dimension)

    assert rows.duplicates == [
        {
            "safetyreportid": "1",
            "seq": None,
            "duplicatenumb": "D1",
            "duplicatesource": "X",
        }
    ]


def test_several_duplicates_arrive_as_an_array_and_keep_their_positions(dimension):
    source = report(reportduplicate=[{"duplicatenumb": "D1"}, {"duplicatenumb": "D2"}])

    rows = split(source, dimension)

    assert [(row["seq"], row["duplicatenumb"]) for row in rows.duplicates] == [
        (0, "D1"),
        (1, "D2"),
    ]


def test_an_array_of_one_stays_distinguishable_from_a_bare_object(dimension):
    """No such array exists in the 2026-08-10 export. The corpus runs from 2004
    and one export has been looked at, so the distinction is kept rather than
    derived from the row count."""
    boxed = split(report(reportduplicate=[{"duplicatenumb": "D1"}]), dimension)
    bare = split(report(reportduplicate={"duplicatenumb": "D1"}), dimension)

    assert boxed.duplicates[0]["seq"] == 0
    assert bare.duplicates[0]["seq"] is None


def test_the_duplicate_block_never_lands_in_the_report_row(dimension):
    """It is a repeated child, so leaving it in the report row would put a
    struct in one report and an array in the next — which is exactly the
    conflict that has no Arrow column."""
    source = report(reportduplicate={"duplicatenumb": "D1"})

    rows = split(source, dimension)

    assert "reportduplicate" not in rows.report


def test_a_report_with_no_duplicates_produces_no_duplicate_rows(dimension):
    """9,047 of 12,000 reports. Absent is absent — no row, not a null row."""
    assert split(report(), dimension).duplicates == []


def test_a_duplicate_entry_that_is_not_an_object_raises(dimension):
    with pytest.raises(UnexpectedReportShape, match=r"'reportduplicate'\[0\]"):
        split(report(reportduplicate=["D1"]), dimension)


def test_a_duplicate_that_is_neither_object_nor_array_raises(dimension):
    with pytest.raises(UnexpectedReportShape, match="'reportduplicate' should be an array"):
        split(report(reportduplicate="D1"), dimension)


# --- split: what a malformed report costs -----------------------------------


def test_a_report_without_an_id_raises_rather_than_orphaning_its_rows(dimension):
    """Every report in the export has one — checked, 12,000 of 12,000, all
    distinct. A None join key would strand that report's drug and reaction rows
    where only the round-trip test, milestones later, would notice."""
    with pytest.raises(UnexpectedReportShape, match="safetyreportid"):
        split({"receiptdate": "20250101"}, dimension)


def test_a_patient_that_is_not_an_object_raises(dimension):
    with pytest.raises(UnexpectedReportShape, match="'patient' should be an object"):
        split(report(patient="unexpected"), dimension)


def test_a_drug_array_that_is_not_an_array_raises_rather_than_being_iterated(dimension):
    """A string here would enumerate into one row per character, and every one
    of them would look like a valid drug row downstream. The message has to name
    the array, not its first element — `drug[0] should be an object` sends
    whoever reads the log at partition 900 looking at the wrong thing."""
    with pytest.raises(UnexpectedReportShape, match="'drug' should be an array, found str"):
        split(report(patient={"drug": "ASPIRIN"}), dimension)


def test_a_drug_entry_that_is_not_an_object_raises(dimension):
    with pytest.raises(UnexpectedReportShape, match=r"'drug'\[0\] should be an object"):
        split(report(patient={"drug": ["ASPIRIN"]}), dimension)


def test_a_source_field_may_not_overwrite_a_column_the_table_defines(dimension):
    """`seq` is this table's own. A drug field of the same name would replace
    the position the round trip is rebuilt from."""
    source = report(patient={"drug": [{"seq": "9"}]})

    with pytest.raises(UnexpectedReportShape, match="seq"):
        split(source, dimension)
