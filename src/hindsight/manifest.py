"""openFDA's bulk-export manifest, resolved into pinned partitions.

Ids are derived from the download URL, since the manifest carries none:

    .../drug/event/2025q1/drug-event-0001-of-0028.json.zip -> 2025q1/0001-of-0028

The bucket is not always a quarter — `all_other/` holds undatable reports — and
the `-of-NNNN` suffix is not stable across exports (L-006).

Nothing here writes to disk. Pinning happens in fetch.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import httpx


DOWNLOAD_MANIFEST_URL = "https://api.fda.gov/download.json"
REQUEST_TIMEOUT_SECONDS = 30.0

_SECTION_PATH = ("results", "drug", "event")

_PARTITION_URL = re.compile(
    r"/drug/event/(?P<bucket>[^/]+)/drug-event-(?P<part>\d+-of-\d+)\.json\.zip$"
)


# --- errors -----------------------------------------------------------------


class ManifestError(Exception):
    """Base for every failure in this module."""


class PartitionNotFound(ManifestError):
    """No partition in the export matched the requested id."""


class UnexpectedManifestShape(ManifestError):
    """openFDA moved something. Raised instead of a bare KeyError, so the
    message can name what changed."""


# --- model ------------------------------------------------------------------


@dataclass(frozen=True)
class Partition:
    """One bulk-export file, ready to fetch.

    `size_mb` is the manifest's own figure — a string with two decimals, and
    despite the name it is MiB: T5 measured 162,319,793 bytes against a stated
    154.80. Advisory only. The real byte count comes from the download.
    """

    id: str
    url: str
    export_date: date
    size_mb: float
    records: int

    @property
    def stem(self) -> str:
        """The id as one path component: `2025q1/0001-of-0028` -> `2025q1-0001-of-0028`.

        The pin and the schema file are named for the same partition, so they
        are named by the same rule and sort next to each other on disk.
        """
        return self.id.replace("/", "-")


@dataclass(frozen=True)
class Export:
    """Every partition from a single manifest fetch, sharing one date.

    Resolving partitions in separate calls lets them straddle two exports.
    This makes one export per run structural (L-006).
    """

    export_date: date
    partitions: dict[str, Partition]

    def partition(self, partition_id: str) -> Partition:
        found = self.partitions.get(partition_id)

        if found is None:
            raise PartitionNotFound(
                f"No partition {partition_id!r} in openFDA's export of "
                f"{self.export_date}. {self._bucket_contents(partition_id)}"
            )

        return found

    def _bucket_contents(self, partition_id: str) -> str:
        """What the bucket does hold. A stale suffix is likelier than a typo."""
        bucket = partition_id.split("/")[0]
        siblings = sorted(pid for pid in self.partitions if pid.startswith(f"{bucket}/"))

        if not siblings:
            return f"No bucket {bucket!r} in this export either."

        first, last = siblings[0].split("/")[1], siblings[-1].split("/")[1]

        return (
            f"{bucket!r} has {len(siblings)} partitions ({first} .. {last}). "
            f"openFDA re-chunks buckets between exports, so a suffix that "
            f"worked before may be stale."
        )


# --- parsing ----------------------------------------------------------------


def _at(node: object, *path: str) -> object:
    """Walk down `path`, or raise naming the trail.

    Not a .get chain: that returns {} on a renamed key and pushes the failure
    into the caller, far from what actually broke.
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


def _parse_date(raw: object) -> date:
    """A date, not a string: "2026-8-9" sorts above "2026-08-10"."""
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
    if not isinstance(entry, dict) or "file" not in entry:
        raise UnexpectedManifestShape(f"partition entry has no 'file' key: {entry!r}")

    url = entry["file"]
    match = _PARTITION_URL.search(url) if isinstance(url, str) else None

    if match is None:
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
    if not isinstance(entries, list):
        raise UnexpectedManifestShape(
            f"partitions should be a list, got {type(entries).__name__}."
        )

    parsed = (_parse_partition(entry, export_date) for entry in entries)

    return {partition.id: partition for partition in parsed}


# --- api --------------------------------------------------------------------


def _fetch_manifest() -> dict:
    response = httpx.get(DOWNLOAD_MANIFEST_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    return response.json()


def load_export() -> Export:
    """Every drug/event partition openFDA publishes, in one request.

    Prefer this to `resolve` in a loop: the manifest is ~590 KB and lists
    1,767 partitions.

    Raises:
        UnexpectedManifestShape: the manifest moved. Never a partial Export.
        httpx.HTTPError: the manifest could not be fetched.
    """
    manifest = _fetch_manifest()

    export_date = _parse_date(_at(manifest, *_SECTION_PATH, "export_date"))
    entries = _at(manifest, *_SECTION_PATH, "partitions")

    return Export(
        export_date=export_date,
        partitions=_parse_partitions(entries, export_date),
    )


def resolve(partition_id: str) -> Partition:
    """One partition, e.g. "2025q1/0001-of-0028". Re-fetches the manifest.

    Raises:
        PartitionNotFound: no match. The message lists what the bucket holds.
    """
    return load_export().partition(partition_id)
