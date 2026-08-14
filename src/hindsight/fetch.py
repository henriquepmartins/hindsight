from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from hindsight.manifest import Partition


RAW_DIR = Path("data/raw")
PIN_DIR = Path("data/manifest")

CHUNK_BYTES = 1 << 20
DOWNLOAD_TIMEOUT_SECONDS = 60.0

log = logging.getLogger(__name__)


class FetchError(Exception):
    pass


class ChecksumMismatch(FetchError):
    pass


@dataclass(frozen=True)
class Pin:
    id: str
    url: str
    export_date: date
    sha256: str
    bytes: int


def _read_pin(path: Path) -> Pin | None:
    if not path.exists():
        return None

    try:
        record = json.loads(path.read_text())

        return Pin(
            id=record["id"],
            url=record["url"],
            export_date=date.fromisoformat(record["export_date"]),
            sha256=record["sha256"],
            bytes=record["bytes"],
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise FetchError(f"{path} is not a readable pin: {exc}") from exc


def _write_pin(path: Path, pin: Pin) -> None:
    record = {
        "id": pin.id,
        "url": pin.url,
        "export_date": pin.export_date.isoformat(),
        "sha256": pin.sha256,
        "bytes": pin.bytes,
    }

    path.write_text(json.dumps(record, indent=2) + "\n")


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0

    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)

    return digest.hexdigest(), size


def _download(url: str, destination: Path, resume: bool) -> bool:
    start = destination.stat().st_size if resume and destination.exists() else 0
    headers = {"Range": f"bytes={start}-"} if start else {}

    with httpx.stream(
        "GET",
        url,
        headers=headers,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as response:
        response.raise_for_status()

        resumed = bool(start) and response.status_code == httpx.codes.PARTIAL_CONTENT

        with destination.open("ab" if resumed else "wb") as out:
            for chunk in response.iter_bytes(CHUNK_BYTES):
                out.write(chunk)

    return resumed


def ensure_local(
    partition: Partition,
    *,
    raw_dir: Path = RAW_DIR,
    pin_dir: Path = PIN_DIR,
) -> Path:
    archive = raw_dir / f"{partition.stem}.zip"
    pin_path = pin_dir / f"{partition.stem}.json"
    pin = _read_pin(pin_path)

    if pin is not None and archive.exists():
        digest, size = _sha256(archive)

        if digest == pin.sha256:
            log.info("cached %s (%s bytes)", partition.id, f"{size:,}")
            return archive

        archive.unlink()

        raise ChecksumMismatch(
            f"{archive} does not match its pin ({digest[:12]} vs "
            f"{pin.sha256[:12]}). Deleted it — re-run to fetch a clean copy."
        )

    raw_dir.mkdir(parents=True, exist_ok=True)
    pin_dir.mkdir(parents=True, exist_ok=True)

    partial = archive.with_name(f"{archive.name}.part")

    log.info("downloading %s (%.1f MB)", partition.id, partition.size_mb)

    resumed = _download(partition.url, partial, resume=pin is not None)

    digest, size = _sha256(partial)

    if pin is not None and digest != pin.sha256:
        partial.unlink()

        cause = (
            "the file it resumed from was not a clean prefix, or openFDA "
            "rewrote the partition"
            if resumed
            else "openFDA rewrote the partition in place"
        )

        raise ChecksumMismatch(
            f"Bytes for {partition.id} disagree with the pin recorded on "
            f"{pin.export_date} ({digest[:12]} vs {pin.sha256[:12]}): {cause}. "
            f"Discarded the download — the next run starts clean."
        )

    partial.replace(archive)
    _write_pin(
        pin_path,
        Pin(
            id=partition.id,
            url=partition.url,
            export_date=partition.export_date,
            sha256=digest,
            bytes=size,
        ),
    )

    log.info("fetched %s (%s bytes) -> %s", partition.id, f"{size:,}", archive)

    return archive
