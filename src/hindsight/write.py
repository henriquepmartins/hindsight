"""Pass 2: rows against the frozen schema, one row group at a time.

Nothing here decides anything about types. The schema arrives already inferred
from every record (schema.py) and this module's only jobs are to keep memory
flat and to make sure what lands on disk is what came out of `split`.

Flat memory is the point of a row group. `write_table` hands Arrow a batch,
Arrow encodes and compresses it into the file, and the buffer is dropped — so
peak memory is one batch, not one partition. At 2,000 reports per group that is
~2,000 report rows and ~12,000 drug rows in flight, and the ceiling does not
move whether the partition holds 12,000 reports or 300,000.

ZSTD-9 is what turns 807 MB of JSON into single-digit megabytes (L-003), and
almost all of that comes from dictionary encoding rather than the codec: only
4,721 distinct MedDRA terms across the reactions, dates that repeat inside a
quarter, and an `openfda` block that collapses 60,862 inline copies into 2,251
dimension rows.

**A partition is written or it is not.** Each file is built under a `.part`
name and renamed into place only after its writer closes cleanly, the same rule
fetch.py applies to downloads and for the same reason: rename is atomic, a
half-written Parquet file is not, and a later run has no way to tell a truncated
file from a complete one.
"""

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

# Reports per row group. design.md leaves this open for T18 to measure; it is a
# memory knob, not a correctness one.
REPORTS_PER_ROW_GROUP = 2000

_QUARTER_BUCKET = re.compile(r"(?P<year>\d{4})q(?P<quarter>[1-4])$")

log = logging.getLogger(__name__)


# --- where a partition lands -------------------------------------------------


def partition_dir(partition_id: str) -> Path:
    """The Hive-style directory for one partition's tables.

        2025q1/0001-of-0028 -> year=2025/quarter=1/part=0001-of-0028

    The `part=` level is not decoration. Every partition writes files named
    `report.parquet`, so without it the 28 partitions of 2025q1 would overwrite
    each other one by one and leave a corpus that looks complete. That costs
    nothing in M0, where there is one partition, and it is the difference
    between a corpus and a bug at M1's 1,767.

    Not every bucket is a quarter: `all_other/` holds the reports openFDA could
    not date (L-006), and it keeps its own name rather than being forced into a
    year that does not exist.
    """
    bucket, _, part = partition_id.partition("/")
    quarter = _QUARTER_BUCKET.match(bucket)

    if quarter is None:
        return Path(f"bucket={bucket}", f"part={part}")

    return Path(
        f"year={quarter['year']}", f"quarter={quarter['quarter']}", f"part={part}"
    )


# --- one table ---------------------------------------------------------------


class ParquetSink:
    """One Parquet file, written in row groups against a fixed schema.

    A context manager, because the file only becomes real on a clean exit. On
    the way out of an exception the `.part` file is removed: an ingest that died
    halfway leaves nothing behind for the next run to mistake for a finished
    one.
    """

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
        """Buffer rows. They reach the file at the next `flush`."""
        self._buffer.extend(rows)

    def flush(self) -> None:
        """Encode the buffer as one row group and drop it.

        Raises:
            UnknownField: a buffered row has a field the schema lacks.
        """
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


# --- one partition -----------------------------------------------------------


@dataclass(frozen=True)
class Written:
    """What a pass 2 produced, measured as it went."""

    directory: Path
    rows: dict[str, int]
    bytes: int
    distinct_openfda: int


def write_partition(
    reports: Iterable[dict], schemas: Schemas, directory: Path
) -> Written:
    """Split every report and write every table into `directory`.

    The dimension is rebuilt here rather than carried over from pass 1, so each
    block is emitted on its own first sight in this pass. Sharing one across
    both passes would leave pass 2 believing every block had already been
    written and produce an empty `dim_openfda` — with, again, valid Parquet
    files on the other side.

    Raises:
        UnknownField: a row carries a field the frozen schema has no column for.
        UnexpectedReportShape, KeyCollision: raised by `split`.
    """
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
            for table, rows in split(report, dimension).by_table().items():
                sinks[table].write(rows)

            if seen % REPORTS_PER_ROW_GROUP == 0:
                for sink in sinks.values():
                    sink.flush()

                log.info("wrote %s reports", f"{seen:,}")

        # Flushed here rather than left to the context manager, so the row
        # counts below are final before the files are renamed into place.
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
