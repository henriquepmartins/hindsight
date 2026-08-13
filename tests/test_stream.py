"""Streaming reports out of a partition archive, without the partition.

The real one is 155 MB and 12,000 reports. These are three-report zips built in
tmp_path, and what they pin is exactly what the real archive's size makes
expensive to check by hand: that the stream is lazy, that a moved shape fails
loudly instead of yielding nothing, and that what comes out is plain JSON —
the types T7's content hash and T9's schema inference are written against.
"""

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
    """An archive member shaped like openFDA's: meta first, then results."""
    return json.dumps({"meta": {"last_updated": "2026-08-10"}, "results": reports})


@pytest.fixture
def partition(tmp_path):
    return build(tmp_path / "2025q1-0001-of-0028.zip", {MEMBER: body(REPORTS)})


# --- the happy path ---------------------------------------------------------


def test_every_report_comes_out_intact_and_in_order(partition):
    assert list(iter_reports(partition)) == REPORTS


def test_an_empty_openfda_block_stays_distinct_from_an_absent_one(partition):
    """`{}` and absent are different facts, and the difference starts here.
    Collapsing them is what produced 492 round-trip mismatches (L-005)."""
    absent, present, _ = list(iter_reports(partition))

    assert present["openfda"] == {}
    assert "openfda" not in absent


def test_numbers_arrive_as_plain_json_types(tmp_path):
    """ijson yields Decimal by default, which T7's json.dumps cannot hash."""
    numeric = [{"safetyreportid": "1", "count": 3, "rate": 1.5}]
    archive = build(tmp_path / "numeric.zip", {MEMBER: body(numeric)})

    report = next(iter_reports(archive))

    assert type(report["count"]) is int
    assert type(report["rate"]) is float


def test_a_path_string_works_as_well_as_a_path(partition):
    assert len(list(iter_reports(str(partition)))) == len(REPORTS)


# --- bounded memory ---------------------------------------------------------


def test_nothing_is_extracted_to_disk(partition):
    before = sorted(p.name for p in partition.parent.iterdir())

    list(iter_reports(partition))

    assert sorted(p.name for p in partition.parent.iterdir()) == before


def test_the_first_report_arrives_before_the_rest_is_parsed(tmp_path):
    """A generator, not a list wearing a costume. The member is truncated mid
    report 2, so a `next()` that succeeds proves report 1 was yielded without
    the parser having reached the end."""
    truncated = '{"results": [{"safetyreportid": "1"}, {"safetyreportid": "2'
    archive = build(tmp_path / "truncated.zip", {MEMBER: truncated})

    reports = iter_reports(archive)

    assert next(reports) == {"safetyreportid": "1"}

    with pytest.raises(ijson.JSONError):
        list(reports)


# --- an archive that is not what we expect ----------------------------------


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
    """The silent failure this module exists to prevent: openFDA renames the
    array, every partition ingests cleanly, and the corpus is empty."""
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
    """Stored, not deflated, so the flipped byte survives into valid JSON and
    only the CRC can catch it — which it does, on the read that hits EOF."""
    archive = build(
        tmp_path / "rotted.zip", {MEMBER: body(REPORTS)}, zipfile.ZIP_STORED
    )
    archive.write_bytes(archive.read_bytes().replace(b"Nausea", b"Nausez"))

    with pytest.raises(zipfile.BadZipFile, match="Bad CRC-32"):
        list(iter_reports(archive))
