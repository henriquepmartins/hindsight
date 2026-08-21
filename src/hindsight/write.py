from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from hindsight.normalize import TABLES, OpenfdaDimension, split
from hindsight.schema import Schemas, enforce


PARQUET_DIR = Path("data/parquet")

COMPRESSION = "zstd"
COMPRESSION_LEVEL = 9


REPORTS_PER_ROW_GROUP = 2000

_QUARTER_BUCKET = re.compile(r"(?P<year>\d{4})q(?P<quarter>[1-4])$")

log = logging.getLogger(__name__)


def partition_dir(partition_id: str) -> Path:
    bucket, _, part = partition_id.partition("/")
    quarter = _QUARTER_BUCKET.match(bucket)

    if quarter is None:
        return Path(f"bucket={bucket}", f"part={part}")

    return Path(
        f"year={quarter['year']}", f"quarter={quarter['quarter']}", f"part={part}"
    )


class ParquetSink:
    def __init__(self, path: Path, schema: pa.Schema, table: str) -> None:
        self.path = path
        self.table = table
        self.rows = 0

        self._schema = schema
        self._partial = path.with_name(f"{path.name}.part")
        self._buffer: list[dict] = []
        self._writer: pq.ParquetWriter | None = None

    def __enter__(self) -> "ParquetSink":
        self._writer = pq.ParquetWriter(
            self._partial,
            self._schema,
            compression=COMPRESSION,
            compression_level=COMPRESSION_LEVEL,
        )

        return self

    def write(self, rows: list[dict]) -> None:
        self._buffer.extend(rows)

    def flush(self) -> None:
        if not self._buffer or self._writer is None:
            return

        enforce(self._buffer, self._schema, self.table)
        self._writer.write_table(
            pa.Table.from_pylist(self._buffer, schema=self._schema)
        )

        self.rows += len(self._buffer)
        self._buffer.clear()

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            if exc_type is None:
                self.flush()
        finally:
            if self._writer is not None:
                self._writer.close()
                self._writer = None

        if exc_type is None:
            self._partial.replace(self.path)
        else:
            self._partial.unlink(missing_ok=True)

        return False


@dataclass(frozen=True)
class Written:
    directory: Path
    rows: dict[str, int]
    bytes: int
    distinct_openfda: int


def write_partition(
    reports: Iterable[dict], schemas: Schemas, directory: Path
) -> Written:
    directory.mkdir(parents=True, exist_ok=True)
    dimension = OpenfdaDimension()
    seen = 0

    with ExitStack() as stack:
        sinks = {
            table: stack.enter_context(
                ParquetSink(directory / f"{table}.parquet", schemas[table], table)
            )
            for table in TABLES
        }

        for seen, report in enumerate(reports, start=1):
            for table, rows in split(report, dimension, seen).by_table().items():
                sinks[table].write(rows)

            if seen % REPORTS_PER_ROW_GROUP == 0:
                for sink in sinks.values():
                    sink.flush()

                log.info("wrote %s reports", f"{seen:,}")

        for sink in sinks.values():
            sink.flush()

    if seen % REPORTS_PER_ROW_GROUP:
        log.info("wrote %s reports", f"{seen:,}")

    return Written(
        directory=directory,
        rows={table: sink.rows for table, sink in sinks.items()},
        bytes=sum(sink.path.stat().st_size for sink in sinks.values()),
        distinct_openfda=len(dimension),
    )
