"""Row groups, atomic files, and where a partition lands.

Nothing here checks types — the schema arrives frozen. What is checked is that
the write keeps its three promises: memory stays flat because rows leave in
batches, a file exists only if it is complete, and two partitions of the same
quarter do not land on top of each other. The last one costs nothing in M0 and
is the difference between a corpus and a bug at 1,767 partitions.
"""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from hindsight.normalize import TABLES
from hindsight.schema import UnknownField, infer
from hindsight.write import (
    COMPRESSION_LEVEL,
    ParquetSink,
    partition_dir,
    write_partition,
)
from hindsight import write as write_module


SCHEMA = pa.schema([pa.field("safetyreportid", pa.string()), pa.field("seq", pa.int64())])


def rows(count: int, start: int = 0) -> list[dict]:
    return [{"safetyreportid": str(n), "seq": n} for n in range(start, start + count)]


def report(**overrides) -> dict:
    return {"safetyreportid": "1", "patient": {"drug": [{}], "reaction": [{}]}} | overrides


# --- where a partition lands -------------------------------------------------


def test_a_quarter_becomes_a_hive_path():
    assert partition_dir("2025q1/0001-of-0028") == Path(
        "year=2025", "quarter=1", "part=0001-of-0028"
    )


def test_two_partitions_of_one_quarter_do_not_share_a_directory():
    """Both write a file called `report.parquet`. Without the `part=` level the
    28 partitions of 2025q1 overwrite each other and leave a corpus that looks
    finished."""
    assert partition_dir("2025q1/0001-of-0028") != partition_dir("2025q1/0002-of-0028")


def test_the_bucket_that_is_not_a_quarter_keeps_its_name():
    """`all_other/` holds the reports openFDA could not date — 4 partitions
    (L-006). Forcing them into a year would invent one."""
    assert partition_dir("all_other/0001-of-0004") == Path(
        "bucket=all_other", "part=0001-of-0004"
    )


# --- the file exists only when it is finished --------------------------------


def test_the_file_appears_only_after_a_clean_exit(tmp_path):
    path = tmp_path / "report.parquet"

    with ParquetSink(path, SCHEMA, "report") as sink:
        sink.write(rows(3))
        sink.flush()

        assert not path.exists()

    assert path.exists()


def test_a_failed_write_leaves_nothing_behind(tmp_path):
    """A truncated Parquet file is indistinguishable from a complete one to the
    next run, which is the same reason fetch.py downloads into a `.part`."""
    path = tmp_path / "report.parquet"

    with pytest.raises(RuntimeError):
        with ParquetSink(path, SCHEMA, "report") as sink:
            sink.write(rows(3))

            raise RuntimeError("interrupted")

    assert list(tmp_path.iterdir()) == []


# --- batching ----------------------------------------------------------------


def test_each_flush_is_one_row_group(tmp_path):
    """The memory argument, visible in the file: rows leave in batches, so peak
    memory is one batch whether the partition holds 12,000 reports or 300,000."""
    path = tmp_path / "report.parquet"

    with ParquetSink(path, SCHEMA, "report") as sink:
        for batch in range(3):
            sink.write(rows(2, start=batch * 2))
            sink.flush()

    assert pq.ParquetFile(path).num_row_groups == 3


def test_flushing_an_empty_buffer_writes_no_row_group(tmp_path):
    """Otherwise every partition ends with an empty group, and a table no report
    filled would be a file of nothing but group headers."""
    path = tmp_path / "report.parquet"

    with ParquetSink(path, SCHEMA, "report") as sink:
        sink.flush()
        sink.flush()

    assert pq.ParquetFile(path).num_row_groups == 0


def test_the_rows_written_are_the_rows_read_back(tmp_path):
    path = tmp_path / "report.parquet"

    with ParquetSink(path, SCHEMA, "report") as sink:
        sink.write(rows(5))

    assert pq.read_table(path).to_pylist() == rows(5)


def test_the_codec_is_zstd(tmp_path):
    """ZSTD-9 is the setting L-003's compression claim was measured under. The
    level is not recorded in the file, so it is pinned as a constant here and
    read from one place in the writer."""
    path = tmp_path / "report.parquet"

    with ParquetSink(path, SCHEMA, "report") as sink:
        sink.write(rows(2))

    metadata = pq.ParquetFile(path).metadata.row_group(0).column(0)

    assert metadata.compression == "ZSTD"
    assert COMPRESSION_LEVEL == 9


# --- one partition -----------------------------------------------------------


def test_every_table_gets_a_file_even_with_nothing_to_put_in_it(tmp_path):
    """An absent file and an empty one read very differently at query time: one
    is a missing table, the other is a table with no rows. Only the second is
    true."""
    reports = [report()]
    written = write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert {path.stem for path in written.directory.glob("*.parquet")} == set(TABLES)
    assert written.rows["report_duplicate"] == 0


def test_the_row_counts_are_what_landed_in_the_files(tmp_path):
    reports = [report(safetyreportid=str(n)) for n in range(3)]
    written = write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert written.rows == {
        "report": 3,
        "report_drug": 3,
        "report_reaction": 3,
        "report_duplicate": 0,
        "dim_openfda": 0,
    }


def test_a_partition_leaves_in_batches_rather_than_all_at_the_end(tmp_path, monkeypatch):
    """The flat-memory promise, and the one property whose absence changes
    nothing about the output: buffering the whole partition writes the same
    rows, one row group, and a peak memory that grows with the file. Five
    reports at two per group is 2 + 2 + 1."""
    monkeypatch.setattr(write_module, "REPORTS_PER_ROW_GROUP", 2)
    reports = [report(safetyreportid=str(n)) for n in range(5)]

    written = write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert pq.ParquetFile(written.directory / "report.parquet").num_row_groups == 3


def test_a_partial_last_batch_is_not_left_in_the_buffer(tmp_path, monkeypatch):
    """12,000 is a round multiple of 2,000 and the smallest partition in the
    export holds 324. A final flush that only ran on the boundary would drop the
    remainder of every partition that is not a multiple of the batch size."""
    monkeypatch.setattr(write_module, "REPORTS_PER_ROW_GROUP", 2)
    reports = [report(safetyreportid=str(n)) for n in range(5)]

    written = write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert written.rows["report"] == 5


def test_the_dimension_is_rebuilt_so_pass_two_writes_the_blocks(tmp_path):
    """Sharing pass 1's dimension would leave every block already seen and
    `dim_openfda` empty — with four other valid files beside it."""
    reports = [report(patient={"drug": [{"openfda": {"unii": ["X"]}}]})]

    written = write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert written.rows["dim_openfda"] == 1
    assert written.distinct_openfda == 1


def test_a_row_the_frozen_schema_has_no_column_for_stops_the_write(tmp_path):
    """The drift check, end to end: a schema inferred from one export meeting a
    record from a later one. Arrow's own answer is to drop the field and write
    the file."""
    schemas = infer(iter([report()]))
    later = [report(fieldinventedin2031="x")]

    with pytest.raises(UnknownField, match="fieldinventedin2031"):
        write_partition(iter(later), schemas, tmp_path / "out")

    assert not list((tmp_path / "out").glob("*.parquet"))
