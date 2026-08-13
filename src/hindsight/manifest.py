"""Resolve openFDA's bulk-export manifest into pinned, downloadable partitions.

openFDA publishes a manifest of every bulk-export file at DOWNLOAD_MANIFEST_URL.
This module turns it into an `Export`: one date and every drug/event partition,
carrying everything `fetch.ensure_local` needs to download and pin one.

The manifest gives no partition id of its own — entries are identified only by
their download URL. The id used throughout this project is derived from that URL:

    https://download.open.fda.gov/drug/event/2025q1/drug-event-0001-of-0028.json.zip
                                             ^^^^^^             ^^^^^^^^^^^^^
                                             bucket             part
    -> "2025q1/0001-of-0028"

Note that `bucket` is not always a quarter: openFDA also publishes an
`all_other/` bucket for reports it could not date. Any pattern tight enough to
require YYYYqN will silently drop those four partitions.

Note also that the `-of-NNNN` suffix is **not stable across exports**. openFDA
re-chunks a bucket when it revises the data, so an id that resolved last month
may be absent today. That is a property of the source, not a bug here — it is
why `fetch` pins a SHA-256 and why a stale id must fail loudly rather than
resolve to something approximate.

`load_export` is the primary entry point. `resolve` is the one-partition
convenience on top of it; prefer `load_export` whenever more than one partition
is wanted, because the manifest is ~590 KB and two separate calls can straddle
two different exports (L-006).

Nothing here writes to disk. Pinning happens in fetch.py (T5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import httpx

DOWNLOAD_MANIFEST_URL = "https://api.fda.gov/download.json"
REQUEST_TIMEOUT_SECONDS = 30.0

# The path this module walks down to reach the drug/event section.
_SECTION_PATH = ("results", "drug", "event")

_PARTITION_URL = re.compile(
    r"/drug/event/(?P<bucket>[^/]+)/drug-event-(?P<part>\d+-of-\d+)\.json\.zip$"
)


class ManifestError(Exception):
    """Base for every failure in this module."""


class PartitionNotFound(ManifestError):
    """No partition in the export matched the requested id."""


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
            last partition of a bucket is a remainder and can be far smaller.
    """

    id: str
    url: str
    export_date: date
    size_mb: float
    records: int


@dataclass(frozen=True)
class Export:
    """One openFDA bulk export of the drug/event corpus.

    Every partition here came from a single manifest fetch, so they share one
    `export_date` by construction rather than by discipline. That is the point:
    partitions resolved by separate calls can silently belong to two different
    exports, and openFDA re-chunks buckets between them (L-006).
    """

    export_date: date
    partitions: dict[str, Partition]

    def partition(self, partition_id: str) -> Partition:
        """Look up one partition, or raise saying what the bucket does hold.

        openFDA re-chunks buckets between exports, so the common cause of a miss
        is a stale `-of-NNNN` suffix rather than a typo. Listing the siblings
        turns a dead end into an obvious fix.
        """
        found = self.partitions.get(partition_id)
        if found is not None:
            return found

        bucket = partition_id.split("/")[0]
        siblings = sorted(pid for pid in self.partitions if pid.startswith(f"{bucket}/"))
        if not siblings:
            detail = f"No bucket {bucket!r} in this export either."
        else:
            detail = (
                f"{bucket!r} has {len(siblings)} partitions "
                f"({siblings[0].split('/')[1]} .. {siblings[-1].split('/')[1]}). "
                f"openFDA re-chunks buckets between exports, so a suffix that "
                f"worked before may be stale."
            )
        raise PartitionNotFound(
            f"No partition {partition_id!r} in openFDA's export of "
            f"{self.export_date}. {detail}"
        )


def _fetch_manifest() -> dict:
    """GET the download manifest and parse it.

    Times out rather than hanging — M1 runs this unattended on a schedule.
    """
    response = httpx.get(DOWNLOAD_MANIFEST_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _at(node: object, *path: str) -> object:
    """Walk down `path`, raising with the full trail if a key is missing.

    Deliberately not `manifest.get("results", {}).get("drug", {})`: a .get chain
    returns {} on a renamed key and pushes the failure into the caller, where
    the traceback no longer points at the thing that broke.
    """
    for depth, key in enumerate(path):
        if not isinstance(node, dict) or key not in node:
            trail = " -> ".join(path[:depth]) or "(top level)"
            raise UnexpectedManifestShape(
                f"{DOWNLOAD_MANIFEST_URL} has no {key!r} under {trail}; "
                f"openFDA changed the manifest layout."
            )
        node = node[key]
    return node


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


def _parse_partition(entry: object, export_date: date) -> Partition:
    """Turn one manifest entry into a Partition, deriving its id from the URL."""
    if not isinstance(entry, dict) or "file" not in entry:
        raise UnexpectedManifestShape(f"partition entry has no 'file' key: {entry!r}")

    url = entry["file"]
    match = _PARTITION_URL.search(url) if isinstance(url, str) else None
    if match is None:
        # Every URL matched when this was written. One that doesn't means
        # openFDA changed its layout, which is drift worth stopping for.
        raise UnexpectedManifestShape(
            f"Cannot derive a partition id from {url!r}; "
            f"openFDA changed its download URL layout."
        )
    partition_id = f"{match['bucket']}/{match['part']}"

    try:
        size_mb = float(entry["size_mb"])
        records = int(entry["records"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UnexpectedManifestShape(
            f"Partition {partition_id!r} has an unreadable size or record "
            f"count: {entry!r}"
        ) from exc

    return Partition(
        id=partition_id,
        url=url,
        export_date=export_date,
        size_mb=size_mb,
        records=records,
    )


def _parse_partitions(entries: object, export_date: date) -> dict[str, Partition]:
    """Build {derived id: Partition} for every entry in the manifest."""
    if not isinstance(entries, list):
        raise UnexpectedManifestShape(
            f"partitions should be a list, got {type(entries).__name__}."
        )
    parsed = (_parse_partition(entry, export_date) for entry in entries)
    return {partition.id: partition for partition in parsed}


def load_export() -> Export:
    """Fetch openFDA's manifest and resolve every drug/event partition in it.

    One HTTP request covers the whole corpus. Prefer this to calling `resolve`
    in a loop: the manifest is ~590 KB and lists 1,767 partitions, so per-id
    fetching is ~1 GB of redundant transfer — and it lets partitions from two
    different exports end up in one run (L-006).

    Returns:
        An Export with openFDA's reported export date and every partition it
        published, keyed by derived id.

    Raises:
        UnexpectedManifestShape: The manifest did not contain the keys this
            function needs, or an entry could not be parsed. Never returns a
            partially-populated Export.
        httpx.HTTPError: The manifest could not be fetched. Left to propagate —
            it is already specific about what failed.
    """
    manifest = _fetch_manifest()
    export_date = _parse_export_date(_at(manifest, *_SECTION_PATH, "export_date"))
    return Export(
        export_date=export_date,
        partitions=_parse_partitions(
            _at(manifest, *_SECTION_PATH, "partitions"), export_date
        ),
    )


def resolve(partition_id: str) -> Partition:
    """Look up one partition in openFDA's current export.

    A convenience over `load_export` for the single-partition case. Resolving
    several partitions this way re-fetches the manifest each time — call
    `load_export` once instead.

    Args:
        partition_id: The partition to resolve, e.g. "2025q1/0001-of-0028".

    Returns:
        A Partition with a real URL, the export date openFDA reports for the
        drug/event corpus, and the manifest's size and record count.

    Raises:
        PartitionNotFound: No partition matched `partition_id`. The message
            includes the id asked for and what the bucket actually contains.
        UnexpectedManifestShape: See `load_export`.
        httpx.HTTPError: See `load_export`.
    """
    return load_export().partition(partition_id)
