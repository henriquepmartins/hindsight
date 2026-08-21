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


def test_a_quarter_becomes_a_hive_path():
    assert partition_dir("2025q1/0001-of-0028") == Path(
        "year=2025", "quarter=1", "part=0001-of-0028"
    )


def test_two_partitions_of_one_quarter_do_not_share_a_directory():
    assert partition_dir("2025q1/0001-of-0028") != partition_dir("2025q1/0002-of-0028")


def test_the_bucket_that_is_not_a_quarter_keeps_its_name():
    assert partition_dir("all_other/0001-of-0004") == Path(
        "bucket=all_other", "part=0001-of-0004"
    )


def test_the_file_appears_only_after_a_clean_exit(tmp_path):
    path = tmp_path / "report.parquet"

    with ParquetSink(path, SCHEMA, "report") as sink:
        sink.write(rows(3))
        sink.flush()

        assert not path.exists()

    assert path.exists()


def test_a_failed_write_leaves_nothing_behind(tmp_path):
    path = tmp_path / "report.parquet"

    with pytest.raises(RuntimeError):
        with ParquetSink(path, SCHEMA, "report") as sink:
            sink.write(rows(3))

            raise RuntimeError("interrupted")

    assert list(tmp_path.iterdir()) == []


def test_each_flush_is_one_row_group(tmp_path):
    path = tmp_path / "report.parquet"

    with ParquetSink(path, SCHEMA, "report") as sink:
        for batch in range(3):
            sink.write(rows(2, start=batch * 2))
            sink.flush()

    assert pq.ParquetFile(path).num_row_groups == 3


def test_flushing_an_empty_buffer_writes_no_row_group(tmp_path):
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
    path = tmp_path / "report.parquet"

    with ParquetSink(path, SCHEMA, "report") as sink:
        sink.write(rows(2))

    metadata = pq.ParquetFile(path).metadata.row_group(0).column(0)

    assert metadata.compression == "ZSTD"
    assert COMPRESSION_LEVEL == 9


def test_every_table_gets_a_file_even_with_nothing_to_put_in_it(tmp_path):
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
    monkeypatch.setattr(write_module, "REPORTS_PER_ROW_GROUP", 2)
    reports = [report(safetyreportid=str(n)) for n in range(5)]

    written = write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert pq.ParquetFile(written.directory / "report.parquet").num_row_groups == 3


def test_a_partial_last_batch_is_not_left_in_the_buffer(tmp_path, monkeypatch):
    monkeypatch.setattr(write_module, "REPORTS_PER_ROW_GROUP", 2)
    reports = [report(safetyreportid=str(n)) for n in range(5)]

    written = write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert written.rows["report"] == 5


def test_the_dimension_is_rebuilt_so_pass_two_writes_the_blocks(tmp_path):
    reports = [report(patient={"drug": [{"openfda": {"unii": ["X"]}}]})]

    written = write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert written.rows["dim_openfda"] == 1
    assert written.distinct_openfda == 1


def test_a_row_the_frozen_schema_has_no_column_for_stops_the_write(tmp_path):
    schemas = infer(iter([report()]))
    later = [report(fieldinventedin2031="x")]

    with pytest.raises(UnknownField, match="fieldinventedin2031"):
        write_partition(iter(later), schemas, tmp_path / "out")

    assert not list((tmp_path / "out").glob("*.parquet"))


def written_report_ids(directory: Path) -> list[str]:
    table = pq.read_table(directory / "report.parquet")

    return table.column("safetyreportid").to_pylist()


def test_distinct_ids_all_reach_the_file(tmp_path):
    reports = [report(safetyreportid=str(n)) for n in range(3)]
    write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert written_report_ids(tmp_path / "out") == ["0", "1", "2"]


def test_a_repeated_safetyreportid_keeps_both_rows_in_the_file(tmp_path):
    reports = [report(safetyreportid="1"), report(safetyreportid="1")]
    written = write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert written.rows["report"] == 2
    assert written_report_ids(tmp_path / "out") == ["1", "1"]


def test_the_writer_never_drops_a_repeated_id(tmp_path):
    reports = [report(safetyreportid="1") for _ in range(3)]
    write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert written_report_ids(tmp_path / "out") == ["1", "1", "1"]


def written_ordinals(directory: Path) -> list[int]:
    table = pq.read_table(directory / "report.parquet")

    return table.column("ordinal").to_pylist()


def test_the_ordinal_is_the_position_in_the_partition(tmp_path):
    reports = [report(safetyreportid=str(n)) for n in range(3)]
    write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert written_ordinals(tmp_path / "out") == [1, 2, 3]


def test_a_repeated_safetyreportid_still_gets_distinct_ordinals(tmp_path):
    reports = [report(safetyreportid="1"), report(safetyreportid="1")]
    write_partition(iter(reports), infer(iter(reports)), tmp_path / "out")

    assert written_ordinals(tmp_path / "out") == [1, 2]
