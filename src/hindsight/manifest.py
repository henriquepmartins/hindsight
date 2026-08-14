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


class ManifestError(Exception):
    pass


class PartitionNotFound(ManifestError):
    pass


class UnexpectedManifestShape(ManifestError):
    pass


@dataclass(frozen=True)
class Partition:
    id: str
    url: str
    export_date: date
    size_mb: float
    records: int

    @property
    def stem(self) -> str:
        return self.id.replace("/", "-")


@dataclass(frozen=True)
class Export:
    export_date: date
    partitions: dict[str, Partition]

    def partition(self, partition_id: str) -> Partition:
        found = self.partitions.get(partition_id)

        if found is None:
            raise PartitionNotFound(
                f"Nenhuma partição {partition_id!r} no export do openFDA de "
                f"{self.export_date}. {self._bucket_contents(partition_id)}"
            )

        return found

    def _bucket_contents(self, partition_id: str) -> str:
        bucket = partition_id.split("/")[0]
        siblings = sorted(pid for pid in self.partitions if pid.startswith(f"{bucket}/"))

        if not siblings:
            return f"Também não existe o bucket {bucket!r} neste export."

        first, last = siblings[0].split("/")[1], siblings[-1].split("/")[1]

        return (
            f"{bucket!r} tem {len(siblings)} partições ({first} .. {last}). "
            f"o openFDA reparticiona buckets entre exports, entao um sufixo que "
            f"funcionou antes pode estar velho."
        )


def _at(node: object, *path: str) -> object:
    for depth, key in enumerate(path):
        if not isinstance(node, dict) or key not in node:
            trail = " -> ".join(path[:depth]) or "(raiz)"

            raise UnexpectedManifestShape(
                f"{DOWNLOAD_MANIFEST_URL} não tem {key!r} sob {trail}; "
                f"o openFDA mudou o layout do manifesto."
            )

        node = node[key]

    return node


def _parse_date(raw: object) -> date:
    if not isinstance(raw, str):
        raise UnexpectedManifestShape(
            f"export_date deveria ser string, veio {type(raw).__name__}: {raw!r}"
        )

    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise UnexpectedManifestShape(
            f"export_date {raw!r} não esta em YYYY-MM-DD."
        ) from exc


def _parse_partition(entry: object, export_date: date) -> Partition:
    if not isinstance(entry, dict) or "file" not in entry:
        raise UnexpectedManifestShape(f"entrada de partição sem a chave 'file': {entry!r}")

    url = entry["file"]
    match = _PARTITION_URL.search(url) if isinstance(url, str) else None

    if match is None:
        raise UnexpectedManifestShape(
            f"Não da para derivar um id de partição de {url!r}; "
            f"o openFDA mudou o layout da URL de download."
        )

    partition_id = f"{match['bucket']}/{match['part']}"

    try:
        size_mb = float(entry["size_mb"])
        records = int(entry["records"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UnexpectedManifestShape(
            f"A partição {partition_id!r} tem tamanho ou contagem ilegível: "
            f"{entry!r}"
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
            f"partitions deveria ser uma lista, veio {type(entries).__name__}."
        )

    parsed = (_parse_partition(entry, export_date) for entry in entries)

    return {partition.id: partition for partition in parsed}


def _fetch_manifest() -> dict:
    response = httpx.get(DOWNLOAD_MANIFEST_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    return response.json()


def load_export() -> Export:
    manifest = _fetch_manifest()

    export_date = _parse_date(_at(manifest, *_SECTION_PATH, "export_date"))
    entries = _at(manifest, *_SECTION_PATH, "partitions")

    return Export(
        export_date=export_date,
        partitions=_parse_partitions(entries, export_date),
    )


def resolve(partition_id: str) -> Partition:
    return load_export().partition(partition_id)
