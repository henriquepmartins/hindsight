import json
from datetime import date

import pytest

from hindsight import fetch as f
from hindsight.manifest import Partition


BODY = b"pretend this is 155 MB of zipped JSON" * 4


@pytest.fixture
def partition():
    return Partition(
        id="2025q1/0001-of-0028",
        url="https://download.open.fda.gov/drug/event/2025q1/drug-event-0001-of-0028.json.zip",
        export_date=date(2026, 8, 10),
        size_mb=154.80,
        records=12000,
    )


class _Response:
    def __init__(self, body: bytes, status_code: int):
        self.body = body
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self, size: int):
        for start in range(0, len(self.body), size):
            yield self.body[start : start + size]


class _Server:
    def __init__(self, body: bytes):
        self.body = body
        self.requests: list[dict] = []

    def stream(self, _method, _url, headers=None, **_kwargs):
        headers = headers or {}
        self.requests.append(headers)

        span = headers.get("Range")

        if span:
            start = int(span.removeprefix("bytes=").rstrip("-"))
            return _Response(self.body[start:], 206)

        return _Response(self.body, 200)


@pytest.fixture
def server(monkeypatch):
    running = _Server(BODY)
    monkeypatch.setattr(f.httpx, "stream", running.stream)

    return running


@pytest.fixture
def store(tmp_path):
    def _ensure(partition):
        return f.ensure_local(
            partition,
            raw_dir=tmp_path / "raw",
            pin_dir=tmp_path / "manifest",
        )

    _ensure.raw = tmp_path / "raw"
    _ensure.pins = tmp_path / "manifest"

    return _ensure


def test_first_run_downloads_and_writes_the_pin(server, store, partition):
    archive = store(partition)

    assert archive.read_bytes() == BODY
    assert len(server.requests) == 1

    pin = json.loads((store.pins / "2025q1-0001-of-0028.json").read_text())

    assert pin["id"] == "2025q1/0001-of-0028"
    assert pin["url"] == partition.url
    assert pin["export_date"] == "2026-08-10"
    assert pin["bytes"] == len(BODY)
    assert len(pin["sha256"]) == 64


def test_second_run_transfers_zero_bytes(server, store, partition):
    first = store(partition)
    second = store(partition)

    assert first == second
    assert len(server.requests) == 1


def test_nothing_is_left_behind_on_success(server, store, partition):
    store(partition)

    assert [p.name for p in store.raw.iterdir()] == ["2025q1-0001-of-0028.zip"]


def test_a_leftover_part_file_is_not_treated_as_complete(server, store, partition):
    store.raw.mkdir(parents=True)
    (store.raw / "2025q1-0001-of-0028.zip.part").write_bytes(BODY[:10])

    archive = store(partition)

    assert archive.read_bytes() == BODY
    assert server.requests == [{}]


def test_an_interrupted_run_resumes_against_a_known_pin(server, store, partition):
    store(partition)

    archive = store.raw / "2025q1-0001-of-0028.zip"
    archive.unlink()
    archive.with_name(f"{archive.name}.part").write_bytes(BODY[:10])

    assert store(partition).read_bytes() == BODY
    assert server.requests[-1] == {"Range": "bytes=10-"}


def test_a_server_ignoring_range_restarts_cleanly(monkeypatch, server, store, partition):
    store(partition)

    archive = store.raw / "2025q1-0001-of-0028.zip"
    archive.unlink()
    archive.with_name(f"{archive.name}.part").write_bytes(BODY[:10])

    monkeypatch.setattr(
        f.httpx, "stream", lambda *a, **kw: _Response(BODY, 200)
    )

    assert store(partition).read_bytes() == BODY


def test_a_rotted_local_file_is_deleted_and_raises(server, store, partition):
    archive = store(partition)
    archive.write_bytes(b"corrupted")

    with pytest.raises(f.ChecksumMismatch, match="não bate com seu pin"):
        store(partition)

    assert not archive.exists()


def test_a_partition_rewritten_in_place_is_refused(server, store, partition):
    store(partition)
    (store.raw / "2025q1-0001-of-0028.zip").unlink()

    server.body = BODY + b"openFDA revised this"

    with pytest.raises(f.ChecksumMismatch, match="o openFDA reescreveu a partição no lugar"):
        store(partition)

    assert not (store.raw / "2025q1-0001-of-0028.zip").exists()
    assert not (store.raw / "2025q1-0001-of-0028.zip.part").exists()


def test_a_mismatch_after_resuming_names_both_causes(server, store, partition):
    store(partition)

    archive = store.raw / "2025q1-0001-of-0028.zip"
    archive.unlink()
    archive.with_name(f"{archive.name}.part").write_bytes(b"garbage!!!")

    with pytest.raises(f.ChecksumMismatch, match="não era um prefixo limpo, ou o openFDA reescreveu"):
        store(partition)


def test_an_unreadable_pin_raises_rather_than_re_downloading(server, store, partition):
    store(partition)
    (store.pins / "2025q1-0001-of-0028.json").write_text("{ truncated")

    with pytest.raises(f.FetchError, match="não é um pin legível"):
        store(partition)
