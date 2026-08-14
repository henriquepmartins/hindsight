from datetime import date

import pytest

from hindsight import manifest as m


def an_entry(
    bucket: str = "2025q1",
    part: str = "0001-of-0028",
    size_mb: str = "154.80",
    records: int = 12000,
) -> dict:
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
    def _load(doc: dict) -> m.Export:
        monkeypatch.setattr(m, "_fetch_manifest", lambda: doc)
        return m.load_export()

    return _load


def test_load_export_parses_every_partition(load):
    export = load(
        a_manifest([an_entry(part="0001-of-0028"), an_entry(part="0028-of-0028")])
    )

    assert set(export.partitions) == {"2025q1/0001-of-0028", "2025q1/0028-of-0028"}

    first = export.partitions["2025q1/0001-of-0028"]

    assert first.url.endswith("2025q1/drug-event-0001-of-0028.json.zip")
    assert first.size_mb == 154.80
    assert first.records == 12000


def test_export_date_is_a_date_not_a_string(load):
    export = load(a_manifest(export_date="2026-08-10"))

    assert export.export_date == date(2026, 8, 10)
    assert export.export_date > date(2026, 8, 9)


def test_every_partition_shares_the_export_date(load):
    export = load(a_manifest([an_entry(), an_entry(bucket="2024q4")]))

    assert {p.export_date for p in export.partitions.values()} == {date(2026, 8, 10)}


def test_non_quarter_bucket_resolves(load):
    export = load(a_manifest([an_entry(bucket="all_other", part="0001-of-0004")]))

    assert export.partition("all_other/0001-of-0004").id == "all_other/0001-of-0004"


def test_remainder_partition_keeps_its_own_record_count(load):
    export = load(a_manifest([an_entry(part="0028-of-0028", records=3230)]))

    assert export.partition("2025q1/0028-of-0028").records == 3230


def test_resolve_delegates_to_the_export(monkeypatch):
    monkeypatch.setattr(m, "_fetch_manifest", lambda: a_manifest())

    assert m.resolve("2025q1/0001-of-0028").records == 12000


def test_stale_suffix_reports_what_the_bucket_actually_holds(load):
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
    assert "'2025q1' tem 3 partições" in message
    assert "0001-of-0028 .. 0028-of-0028" in message


def test_unknown_bucket_says_the_bucket_is_missing(load):
    export = load(a_manifest())

    with pytest.raises(m.PartitionNotFound, match="não existe o bucket '1999q1'"):
        export.partition("1999q1/0001-of-0001")


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        pytest.param({}, r"não tem 'results' sob \(raiz\)", id="empty"),
        pytest.param(
            {"results": {"medication": {}}},
            "não tem 'drug' sob results",
            id="renamed-drug",
        ),
        pytest.param(
            {"results": {"drug": {"event": []}}},
            "não tem 'export_date' sob results -> drug -> event",
            id="section-is-a-list",
        ),
        pytest.param(
            {"results": {"drug": {"event": {"partitions": []}}}},
            "não tem 'export_date' sob results -> drug -> event",
            id="no-export-date",
        ),
        pytest.param(
            {"results": {"drug": {"event": {"export_date": "2026-08-10"}}}},
            "não tem 'partitions' sob results -> drug -> event",
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
            "export_date deveria ser string, veio int",
            id="date-not-a-string",
        ),
        pytest.param(
            a_manifest(export_date="2026/08/10"),
            "não esta em YYYY-MM-DD",
            id="date-wrong-format",
        ),
        pytest.param(
            {
                "results": {
                    "drug": {"event": {"export_date": "2026-08-10", "partitions": {}}}
                }
            },
            "partitions deveria ser uma lista, veio dict",
            id="partitions-not-a-list",
        ),
        pytest.param(
            a_manifest([{"size_mb": "1.00", "records": 1}]),
            "sem a chave 'file'",
            id="entry-without-a-url",
        ),
        pytest.param(
            a_manifest([{"file": "https://download.open.fda.gov/drug/event/README"}]),
            "Não da para derivar um id de partição",
            id="url-layout-changed",
        ),
        pytest.param(
            a_manifest([an_entry(size_mb="about 150 MB")]),
            "tamanho ou contagem ilegível",
            id="unparseable-size",
        ),
        pytest.param(
            a_manifest([an_entry(records=None)]),
            "tamanho ou contagem ilegível",
            id="unparseable-record-count",
        ),
    ],
)
def test_an_unreadable_manifest_raises_rather_than_returning_none(load, doc, expected):
    with pytest.raises(m.UnexpectedManifestShape, match=expected):
        load(doc)


def test_a_single_bad_entry_fails_the_whole_export(load):
    with pytest.raises(m.UnexpectedManifestShape):
        load(a_manifest([an_entry(), {"file": "https://example.com/nope.zip"}]))
