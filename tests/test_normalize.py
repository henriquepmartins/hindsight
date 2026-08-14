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
    return {"safetyreportid": "1", "receiptdate": "20250101"} | overrides


def test_key_ignores_the_order_the_block_was_written_in():
    assert key({"a": ["1"], "b": ["2"]}) == key({"b": ["2"], "a": ["1"]})


def test_key_ignores_key_order_at_every_depth():
    deep = {"outer": {"a": ["1"], "b": ["2"]}, "unii": ["X"]}
    shuffled = {"unii": ["X"], "outer": {"b": ["2"], "a": ["1"]}}

    assert key(deep) == key(shuffled)


def test_key_is_pinned_not_merely_stable():
    assert key(ASPIRIN) == "59556fc197ca0cfa"
    assert key({}) == "bf21a9e8fbc5a384"


def test_key_is_the_documented_width():
    assert len(key(ASPIRIN)) == n.KEY_LENGTH


def test_different_blocks_get_different_keys():
    assert key(ASPIRIN) != key(IBUPROFEN)


def test_an_empty_block_is_a_real_block_with_a_real_key():
    assert key({}) is not None


def test_an_absent_block_has_no_key():
    assert key(None) is None


def test_the_falsy_test_is_the_bug_this_rule_exists_for():
    empty = {}

    assert key(empty) is not None
    assert (key(empty) if empty else None) is None


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
    assert dimension.add(None) == (None, None)
    assert len(dimension) == 0


def test_the_dimension_holds_digests_not_blocks(dimension):
    for block in (ASPIRIN, IBUPROFEN, {}):
        dimension.add(block)

    assert set(vars(dimension)) == {"_digests"}
    assert all(isinstance(value, str) for value in dimension._digests.values())


def test_a_truncation_collision_raises_rather_than_merging(monkeypatch, dimension):
    monkeypatch.setattr(
        n, "_digest", lambda block: "f" * n.KEY_LENGTH + ("1" if block else "2") * 24
    )

    dimension.add(ASPIRIN)

    with pytest.raises(KeyCollision, match="truncam para 'ffffffffffffffff'"):
        dimension.add({})


def test_the_same_block_under_a_shared_key_is_not_a_collision(monkeypatch, dimension):
    monkeypatch.setattr(n, "_digest", lambda block: "f" * 40)

    dimension.add(ASPIRIN)

    assert dimension.add(IBUPROFEN)[1] is None


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
    source = report(fieldinventedin2031="x", patient={"pt_era_field": "y"})

    rows = split(source, dimension)

    assert rows.report["fieldinventedin2031"] == "x"
    assert rows.report["pt_pt_era_field"] == "y"


def test_a_nested_patient_object_stays_an_object(dimension):
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
    source = report(pt_patientsex="top level", patient={"patientsex": "1"})

    with pytest.raises(UnexpectedReportShape, match="pt_patientsex"):
        split(source, dimension)


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
    source = report(patient={"drug": [{}, {}, {}]})

    rows = split(source, dimension)

    assert [drug["seq"] for drug in rows.drugs] == [0, 1, 2]


def test_the_openfda_block_leaves_the_drug_row_and_becomes_a_key(dimension):
    source = report(patient={"drug": [{"medicinalproduct": "ASPIRIN", "openfda": ASPIRIN}]})

    rows = split(source, dimension)

    assert "openfda" not in rows.drugs[0]
    assert rows.drugs[0]["openfda_key"] == key(ASPIRIN)


def test_an_absent_block_keys_to_none_and_an_empty_one_does_not(dimension):
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


def test_one_row_per_reaction_keyed_and_ordered(dimension):
    source = report(
        patient={"reaction": [{"reactionmeddrapt": "Nausea"}, {"reactionmeddrapt": "Rash"}]}
    )

    rows = split(source, dimension)

    assert rows.reactions == [
        {"safetyreportid": "1", "seq": 0, "reactionmeddrapt": "Nausea"},
        {"safetyreportid": "1", "seq": 1, "reactionmeddrapt": "Rash"},
    ]


def test_one_duplicate_arrives_as_a_bare_object_and_keeps_a_null_seq(dimension):
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
    boxed = split(report(reportduplicate=[{"duplicatenumb": "D1"}]), dimension)
    bare = split(report(reportduplicate={"duplicatenumb": "D1"}), dimension)

    assert boxed.duplicates[0]["seq"] == 0
    assert bare.duplicates[0]["seq"] is None


def test_the_duplicate_block_never_lands_in_the_report_row(dimension):
    source = report(reportduplicate={"duplicatenumb": "D1"})

    rows = split(source, dimension)

    assert "reportduplicate" not in rows.report


def test_a_report_with_no_duplicates_produces_no_duplicate_rows(dimension):
    assert split(report(), dimension).duplicates == []


def test_a_duplicate_entry_that_is_not_an_object_raises(dimension):
    with pytest.raises(UnexpectedReportShape, match=r"'reportduplicate'\[0\]"):
        split(report(reportduplicate=["D1"]), dimension)


def test_a_duplicate_that_is_neither_object_nor_array_raises(dimension):
    with pytest.raises(UnexpectedReportShape, match="'reportduplicate' deveria ser um array"):
        split(report(reportduplicate="D1"), dimension)


def test_a_report_without_an_id_raises_rather_than_orphaning_its_rows(dimension):
    with pytest.raises(UnexpectedReportShape, match="safetyreportid"):
        split({"receiptdate": "20250101"}, dimension)


def test_a_patient_that_is_not_an_object_raises(dimension):
    with pytest.raises(UnexpectedReportShape, match="'patient' deveria ser um objeto"):
        split(report(patient="unexpected"), dimension)


def test_a_drug_array_that_is_not_an_array_raises_rather_than_being_iterated(dimension):
    with pytest.raises(UnexpectedReportShape, match="'drug' deveria ser um array, veio str"):
        split(report(patient={"drug": "ASPIRIN"}), dimension)


def test_a_drug_entry_that_is_not_an_object_raises(dimension):
    with pytest.raises(UnexpectedReportShape, match=r"'drug'\[0\] deveria ser um objeto"):
        split(report(patient={"drug": ["ASPIRIN"]}), dimension)


def test_a_source_field_may_not_overwrite_a_column_the_table_defines(dimension):
    source = report(patient={"drug": [{"seq": "9"}]})

    with pytest.raises(UnexpectedReportShape, match="seq"):
        split(source, dimension)
