"""Unit tests for openFDA manifest parsing. No network: every case feeds a dict.

The T4 verify block covers the happy path against the live endpoint, which CI
cannot run. What is left uncovered is the part that matters — a stale partition
id and a manifest whose shape moved. M1's unattended crawler depends on both
failing loudly, with a message that says which one happened.
"""

from datetime import date

import pytest

from hindsight import manifest as m

# --- builders -------------------------------------------------------------


def an_entry(
    bucket: str = "2025q1",
    part: str = "0001-of-0028",
    size_mb: str = "154.80",
    records: int = 12000,
) -> dict:
    """One manifest entry, shaped exactly as openFDA publishes it."""
    return {
        "display_name": f"{bucket} ({part})",
        "file": (
            f"https://download.open.fda.gov/drug/event/"
            f"{bucket}/drug-event-{part}.json.zip"
        ),
        "size_mb": size_mb,
        "records": records,
    }


def a_manifest(entries: list | None = None, export_date: str = "2026-08-10") -> dict:
    """A download.json with the nesting openFDA actually uses."""
    return {
        "results": {
            "drug": {
                "event": {
                    "export_date": export_date,
                    "partitions": [an_entry()] if entries is None else entries,
                    "total_records": 20_692_690,
                }
            }
        }
    }


@pytest.fixture
def load(monkeypatch):
    """Run load_export against a hand-built manifest instead of the network."""

    def _load(doc: dict) -> m.Export:
        monkeypatch.setattr(m, "_fetch_manifest", lambda: doc)
        return m.load_export()

    return _load


# --- parsing --------------------------------------------------------------


def test_load_export_parses_every_partition(load):
    export = load(
        a_manifest([an_entry(part="0001-of-0028"), an_entry(part="0028-of-0028")])
    )

    assert set(export.partitions) == {"2025q1/0001-of-0028", "2025q1/0028-of-0028"}
    first = export.partitions["2025q1/0001-of-0028"]
    assert first.id == "2025q1/0001-of-0028"
    assert first.url.endswith("2025q1/drug-event-0001-of-0028.json.zip")
    assert first.size_mb == 154.80
    assert first.records == 12000


def test_export_date_is_a_date_not_a_string(load):
    """M1 orders exports to detect change; "2026-8-9" > "2026-08-10" as strings."""
    export = load(a_manifest(export_date="2026-08-10"))

    assert export.export_date == date(2026, 8, 10)
    assert export.export_date > date(2026, 8, 9)


def test_every_partition_shares_the_export_date(load):
    """The reason Export exists: one fetch, one date, no straddling (L-006)."""
    export = load(
        a_manifest([an_entry(part="0001-of-0028"), an_entry(bucket="2024q4")])
    )

    assert {p.export_date for p in export.partitions.values()} == {date(2026, 8, 10)}


def test_non_quarter_bucket_resolves(load):
    """openFDA publishes all_other/ for undatable reports. A YYYYqN pattern
    would silently drop those four partitions (L-006)."""
    export = load(a_manifest([an_entry(bucket="all_other", part="0001-of-0004")]))

    assert export.partition("all_other/0001-of-0004").id == "all_other/0001-of-0004"


def test_remainder_partition_keeps_its_own_record_count(load):
    """Not every partition holds 12,000 — the last of a bucket is a remainder."""
    export = load(a_manifest([an_entry(part="0028-of-0028", records=3230)]))

    assert export.partition("2025q1/0028-of-0028").records == 3230


def test_resolve_delegates_to_the_export(monkeypatch):
    monkeypatch.setattr(m, "_fetch_manifest", lambda: a_manifest())

    assert m.resolve("2025q1/0001-of-0028").records == 12000


# --- a partition that is not there ----------------------------------------


def test_stale_suffix_reports_what_the_bucket_actually_holds(load):
    """The L-006 failure: the id was valid last export, and the bucket was
    re-chunked. The message has to make that diagnosable without a second run."""
    export = load(
        a_manifest(
            [
                an_entry(part="0001-of-0028"),
                an_entry(part="0002-of-0028"),
                an_entry(part="0028-of-0028"),
            ]
        )
    )

    with pytest.raises(m.PartitionNotFound) as caught:
        export.partition("2025q1/0001-of-0034")

    message = str(caught.value)
    assert "'2025q1/0001-of-0034'" in message
    assert "2026-08-10" in message
    assert "'2025q1' has 3 partitions" in message
    assert "0001-of-0028 .. 0028-of-0028" in message


def test_unknown_bucket_says_the_bucket_is_missing(load):
    export = load(a_manifest())

    with pytest.raises(m.PartitionNotFound, match="No bucket '1999q1'"):
        export.partition("1999q1/0001-of-0001")


# --- a manifest that moved ------------------------------------------------


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        pytest.param({}, r"no 'results' under \(top level\)", id="empty"),
        pytest.param(
            {"results": {"medication": {}}},
            "no 'drug' under results",
            id="renamed-drug",
        ),
        pytest.param(
            {"results": {"drug": {"event": []}}},
            "no 'export_date' under results -> drug -> event",
            id="section-is-a-list",
        ),
        pytest.param(
            {"results": {"drug": {"event": {"partitions": []}}}},
            "no 'export_date' under results -> drug -> event",
            id="no-export-date",
        ),
        pytest.param(
            {"results": {"drug": {"event": {"export_date": "2026-08-10"}}}},
            "no 'partitions' under results -> drug -> event",
            id="no-partitions",
        ),
    ],
)
def test_a_moved_key_names_the_path_it_was_expected_at(load, doc, expected):
    with pytest.raises(m.UnexpectedManifestShape, match=expected):
        load(doc)


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        pytest.param(
            a_manifest(export_date=20260810),
            "export_date should be a string, got int",
            id="date-not-a-string",
        ),
        pytest.param(
            a_manifest(export_date="2026/08/10"),
            "is not YYYY-MM-DD",
            id="date-wrong-format",
        ),
        pytest.param(
            {
                "results": {
                    "drug": {
                        "event": {"export_date": "2026-08-10", "partitions": {}}
                    }
                }
            },
            "partitions should be a list, got dict",
            id="partitions-not-a-list",
        ),
        pytest.param(
            a_manifest([{"size_mb": "1.00", "records": 1}]),
            "has no 'file' key",
            id="entry-without-a-url",
        ),
        pytest.param(
            a_manifest([{"file": "https://download.open.fda.gov/drug/event/README"}]),
            "Cannot derive a partition id",
            id="url-layout-changed",
        ),
        pytest.param(
            a_manifest([an_entry(size_mb="about 150 MB")]),
            "unreadable size or record count",
            id="unparseable-size",
        ),
        pytest.param(
            a_manifest([an_entry(records=None)]),
            "unreadable size or record count",
            id="unparseable-record-count",
        ),
    ],
)
def test_an_unreadable_manifest_raises_rather_than_returning_none(load, doc, expected):
    with pytest.raises(m.UnexpectedManifestShape, match=expected):
        load(doc)


def test_a_single_bad_entry_fails_the_whole_export(load):
    """Deliberate: a partially-populated Export would let a later stage read a
    silently short partition list as complete. Failing here is the whole point
    of AD-011 — drift is structural, not something a caller can forget to check.
    """
    with pytest.raises(m.UnexpectedManifestShape):
        load(a_manifest([an_entry(), {"file": "https://example.com/nope.zip"}]))
