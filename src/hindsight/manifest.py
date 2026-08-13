"""Resolve an openFDA partition id to a pinned, downloadable URL.

openFDA publishes a manifest of every bulk-export file at DOWNLOAD_MANIFEST_URL.
This module turns a human-typed partition id into everything `fetch.ensure_local`
needs to download it and pin it.

The manifest gives no partition id of its own — entries are identified only by
their download URL. The id used throughout this project is derived from that URL:

    https://download.open.fda.gov/drug/event/2025q1/drug-event-0001-of-0028.json.zip
                                             ^^^^^^             ^^^^^^^^^^^^^
                                             quarter            part
    -> "2025q1/0001-of-0028"

Note that `quarter` is not always a quarter: openFDA also publishes an
`all_other/` bucket for reports it could not date. Any pattern tight enough to
require YYYYqN will silently drop those four partitions.

Note also that the `-of-NNNN` suffix is **not stable across exports**. openFDA
re-chunks a quarter when it revises the data, so an id that resolved last month
may be absent today. That is a property of the source, not a bug here — it is
why `fetch` pins a SHA-256 and why a stale id must fail loudly rather than
resolve to something approximate.

Nothing here writes to disk. Pinning happens in fetch.py (T5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import httpx

DOWNLOAD_MANIFEST_URL = "https://api.fda.gov/download.json"
REQUEST_TIMEOUT_SECONDS = 30.0

# The path this module walks down to reach the drug/event partition list.
_SECTION_PATH = ("results", "drug", "event")

_PARTITION_URL = re.compile(
    r"/drug/event/(?P<bucket>[^/]+)/drug-event-(?P<part>\d+-of-\d+)\.json\.zip$"
)


class ManifestError(Exception):
    """Base for every failure in this module."""


class PartitionNotFound(ManifestError):
    """No partition in the manifest matched the requested id."""


class UnexpectedManifestShape(ManifestError):
    """openFDA's download.json is not shaped the way this module expects.

    Raised instead of letting a bare KeyError escape, so the message can say
    *what* changed rather than just naming a missing key. An unattended crawler
    (M1) needs the difference between "openFDA moved a key" and "this partition
    doesn't exist" to be visible from the log line alone.
    """


@dataclass(frozen=True)
class Partition:
    """One openFDA bulk-export file, resolved and ready to fetch.

    Attributes:
        id: Derived id, e.g. "2025q1/0001-of-0028".
        url: Direct download URL for the zipped JSON.
        export_date: The date openFDA exported the drug/event corpus. Shared by
            every partition in a given export, and M1's change signal.
        size_mb: The manifest's own size figure, in megabytes. Approximate and
            advisory — openFDA reports it as a string with two decimals. The
            authoritative byte count is what `fetch` actually downloads.
        records: Reports in this partition. Varies: most are 12,000, but the
            last partition of a quarter is a remainder and can be far smaller.
    """

    id: str
    url: str
    export_date: date
    size_mb: float
    records: int


def _fetch_manifest() -> dict:
    """GET the download manifest and parse it.

    Times out rather than hanging — M1 runs this unattended on a schedule.
    """
    response = httpx.get(DOWNLOAD_MANIFEST_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _drug_event_section(manifest: dict) -> dict:
    """Walk down to the drug/event section, raising if the path isn't there.

    Deliberately not `manifest.get("results", {}).get("drug", {})`: a .get chain
    returns {} on a renamed key and pushes the failure into the caller, where
    the traceback no longer points at the thing that broke.
    """
    section: object = manifest
    for depth, key in enumerate(_SECTION_PATH):
        if not isinstance(section, dict) or key not in section:
            walked = " -> ".join(_SECTION_PATH[:depth]) or "(top level)"
            raise UnexpectedManifestShape(
                f"{DOWNLOAD_MANIFEST_URL} has no {key!r} under {walked}; "
                f"openFDA changed the manifest layout."
            )
        section = section[key]

    if not isinstance(section, dict):
        raise UnexpectedManifestShape(
            f"Expected a mapping at {' -> '.join(_SECTION_PATH)}, "
            f"got {type(section).__name__}."
        )
    for key in ("export_date", "partitions"):
        if key not in section:
            raise UnexpectedManifestShape(
                f"drug/event section has no {key!r}; openFDA changed the manifest."
            )
    return section


def _parse_export_date(raw: object) -> date:
    """Parse openFDA's YYYY-MM-DD export date.

    Kept as a `date` rather than a string so callers can order two exports.
    String comparison would rank "2026-8-9" above "2026-08-10".
    """
    if not isinstance(raw, str):
        raise UnexpectedManifestShape(
            f"export_date should be a string, got {type(raw).__name__}: {raw!r}"
        )
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise UnexpectedManifestShape(
            f"export_date {raw!r} is not YYYY-MM-DD."
        ) from exc


def _index_by_id(entries: object) -> dict[str, dict]:
    """Build {derived id: entry} for every partition in the manifest."""
    if not isinstance(entries, list):
        raise UnexpectedManifestShape(
            f"partitions should be a list, got {type(entries).__name__}."
        )

    indexed: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict) or "file" not in entry:
            raise UnexpectedManifestShape(
                f"partition entry has no 'file' key: {entry!r}"
            )
        match = _PARTITION_URL.search(entry["file"])
        if match is None:
            # Every URL matched when this was written. One that doesn't means
            # openFDA changed its layout, which is drift worth stopping for.
            raise UnexpectedManifestShape(
                f"Cannot derive a partition id from {entry['file']!r}; "
                f"openFDA changed its download URL layout."
            )
        indexed[f"{match['bucket']}/{match['part']}"] = entry
    return indexed


def _not_found(partition_id: str, indexed: dict[str, dict], on: date) -> PartitionNotFound:
    """Build an error that says what *does* exist in that bucket.

    openFDA re-chunks quarters between exports, so the common cause of a miss is
    a stale `-of-NNNN` suffix rather than a typo. Listing the siblings turns a
    dead end into an obvious fix.
    """
    bucket = partition_id.split("/")[0]
    siblings = sorted(pid for pid in indexed if pid.startswith(f"{bucket}/"))
    if not siblings:
        detail = f"No bucket {bucket!r} in this export either."
    else:
        detail = (
            f"{bucket!r} has {len(siblings)} partitions "
            f"({siblings[0].split('/')[1]} .. {siblings[-1].split('/')[1]}). "
            f"openFDA re-chunks quarters between exports, so a suffix that "
            f"worked before may be stale."
        )
    return PartitionNotFound(
        f"No partition {partition_id!r} in openFDA's export of {on}. {detail}"
    )


def resolve(partition_id: str) -> Partition:
    """Look up one partition in openFDA's download manifest.

    Args:
        partition_id: The partition to resolve, e.g. "2025q1/0001-of-0028".

    Returns:
        A Partition with a real URL, the export date openFDA reports for the
        drug/event corpus, and the manifest's size and record count.

    Raises:
        PartitionNotFound: No partition matched `partition_id`. The message
            includes the id asked for and what the bucket actually contains.
        UnexpectedManifestShape: The manifest did not contain the keys this
            function needs. Never returns None in this case.
        httpx.HTTPError: The manifest could not be fetched. Left to propagate —
            it is already specific about what failed.
    """
    section = _drug_event_section(_fetch_manifest())
    export_date = _parse_export_date(section["export_date"])
    indexed = _index_by_id(section["partitions"])

    entry = indexed.get(partition_id)
    if entry is None:
        raise _not_found(partition_id, indexed, export_date)

    try:
        size_mb = float(entry["size_mb"])
        records = int(entry["records"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UnexpectedManifestShape(
            f"Partition {partition_id!r} has an unreadable size or record count: "
            f"{entry!r}"
        ) from exc

    return Partition(
        id=partition_id,
        url=entry["file"],
        export_date=export_date,
        size_mb=size_mb,
        records=records,
    )
