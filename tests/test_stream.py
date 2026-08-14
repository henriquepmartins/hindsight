import json
import zipfile

import ijson
import pytest

from hindsight.stream import UnexpectedArchiveShape, iter_reports


MEMBER = "drug-event-0001-of-0028.json"

REPORTS = [
    {"safetyreportid": "1", "patient": {"drug": [{"medicinalproduct": "ASPIRIN"}]}},
    {"safetyreportid": "2", "openfda": {}},
    {"safetyreportid": "3", "patient": {"reaction": [{"reactionmeddrapt": "Nausea"}]}},
]


def build(path, members, compression=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, "w", compression) as archive:
        for name, body in members.items():
            archive.writestr(name, body)

    return path


def body(reports):
    return json.dumps({"meta": {"last_updated": "2026-08-10"}, "results": reports})


@pytest.fixture
def partition(tmp_path):
    return build(tmp_path / "2025q1-0001-of-0028.zip", {MEMBER: body(REPORTS)})


def test_every_report_comes_out_intact_and_in_order(partition):
    assert list(iter_reports(partition)) == REPORTS


def test_an_empty_openfda_block_stays_distinct_from_an_absent_one(partition):
    absent, present, _ = list(iter_reports(partition))

    assert present["openfda"] == {}
    assert "openfda" not in absent


def test_numbers_arrive_as_plain_json_types(tmp_path):
    numeric = [{"safetyreportid": "1", "count": 3, "rate": 1.5}]
    archive = build(tmp_path / "numeric.zip", {MEMBER: body(numeric)})

    report = next(iter_reports(archive))

    assert type(report["count"]) is int
    assert type(report["rate"]) is float


def test_a_path_string_works_as_well_as_a_path(partition):
    assert len(list(iter_reports(str(partition)))) == len(REPORTS)


def test_nothing_is_extracted_to_disk(partition):
    before = sorted(p.name for p in partition.parent.iterdir())

    list(iter_reports(partition))

    assert sorted(p.name for p in partition.parent.iterdir()) == before


def test_the_first_report_arrives_before_the_rest_is_parsed(tmp_path):
    truncated = '{"results": [{"safetyreportid": "1"}, {"safetyreportid": "2'
    archive = build(tmp_path / "truncated.zip", {MEMBER: truncated})

    reports = iter_reports(archive)

    assert next(reports) == {"safetyreportid": "1"}

    with pytest.raises(ijson.JSONError):
        list(reports)


def test_an_archive_with_no_json_member_raises_naming_its_contents(tmp_path):
    archive = build(tmp_path / "wrong.zip", {"README.txt": "no json here"})

    with pytest.raises(UnexpectedArchiveShape, match=r"found 0.*README\.txt"):
        list(iter_reports(archive))


def test_two_json_members_raise_rather_than_picking_one(tmp_path):
    archive = build(tmp_path / "two.zip", {MEMBER: body(REPORTS), "extra.json": "{}"})

    with pytest.raises(UnexpectedArchiveShape, match="found 2"):
        list(iter_reports(archive))


def test_a_non_json_sibling_is_ignored(tmp_path):
    archive = build(
        tmp_path / "sibling.zip", {MEMBER: body(REPORTS), "README.txt": "ignore me"}
    )

    assert len(list(iter_reports(archive))) == len(REPORTS)


def test_reports_moved_out_of_results_raise_rather_than_yielding_nothing(tmp_path):
    moved = json.dumps({"meta": {}, "reports": REPORTS})
    archive = build(tmp_path / "moved.zip", {MEMBER: moved})

    with pytest.raises(UnexpectedArchiveShape, match="nothing came out"):
        next(iter_reports(archive))


def test_an_empty_results_array_raises(tmp_path):
    archive = build(tmp_path / "empty.zip", {MEMBER: body([])})

    with pytest.raises(UnexpectedArchiveShape, match="nothing came out"):
        next(iter_reports(archive))


def test_malformed_json_raises(tmp_path):
    archive = build(tmp_path / "malformed.zip", {MEMBER: "{not json at all}"})

    with pytest.raises(ijson.JSONError):
        next(iter_reports(archive))


def test_a_rotted_archive_is_caught_by_its_crc(tmp_path):
    archive = build(
        tmp_path / "rotted.zip", {MEMBER: body(REPORTS)}, zipfile.ZIP_STORED
    )
    archive.write_bytes(archive.read_bytes().replace(b"Nausea", b"Nausez"))

    with pytest.raises(zipfile.BadZipFile, match="Bad CRC-32"):
        list(iter_reports(archive))
