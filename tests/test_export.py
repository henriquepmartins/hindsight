import csv
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from hindsight.analysis.export import COLUMNS, write_csv
from hindsight.analysis.prr import PrrError


def corpus(
    root: Path,
    reports: dict[str, tuple[list[str], list[str]]],
    *,
    metrics: bool = True,
) -> Path:
    directory = root / "year=2025" / "quarter=1" / "part=0001-of-0001"
    directory.mkdir(parents=True, exist_ok=True)

    pq.write_table(
        pa.table({"safetyreportid": list(reports)}), directory / "report.parquet"
    )
    pq.write_table(
        pa.table(
            {
                "safetyreportid": [r for r, (ds, _) in reports.items() for _ in ds],
                "medicinalproduct": [d for _, (ds, _) in reports.items() for d in ds],
            }
        ),
        directory / "report_drug.parquet",
    )
    pq.write_table(
        pa.table(
            {
                "safetyreportid": [r for r, (_, es) in reports.items() for _ in es],
                "reactionmeddrapt": [e for _, (_, es) in reports.items() for e in es],
            }
        ),
        directory / "report_reaction.parquet",
    )

    if metrics:
        (directory / "metrics.json").write_text(
            json.dumps({"partition": "2025q1/0001-of-0001", "export_date": "2026-08-10"})
        )

    return directory


@pytest.fixture
def three_pairs(tmp_path):
    corpus(
        tmp_path / "parquet",
        {str(n): (["ASPIRIN"], ["Headache"]) for n in range(3)},
    )

    return tmp_path


def written(root: Path, **kwargs):
    path = root / "out.csv"
    result = write_csv(path, root=root / "parquet", **kwargs)

    with path.open(newline="") as handle:
        rows = list(csv.DictReader(line for line in handle if not line.startswith("#")))

    return result, rows, path.read_text()


def test_the_header_carries_what_produced_the_rows(three_pairs):
    _, _, text = written(three_pairs)
    header = [line for line in text.splitlines() if line.startswith("#")]

    assert any("2025q1/0001-of-0001" in line for line in header)
    assert any("2026-08-10" in line for line in header)
    assert any("min_count: 3" in line for line in header)
    assert any("crowding_cut" in line for line in header)


def test_a_partition_with_no_metrics_refuses_rather_than_guessing(tmp_path):
    corpus(tmp_path / "parquet", {"1": (["A"], ["X"])}, metrics=False)

    with pytest.raises(PrrError, match="export date"):
        write_csv(tmp_path / "out.csv", root=tmp_path / "parquet")


def test_every_pair_is_written_not_only_the_top(tmp_path):
    drugs = [f"D{n}" for n in range(5)]
    events = [f"E{n}" for n in range(5)]
    corpus(tmp_path / "parquet", {str(n): (drugs, events) for n in range(6)})

    result, rows, _ = written(tmp_path)

    assert result.pairs == len(rows) == 25


def test_the_columns_are_the_contract(three_pairs):
    _, rows, _ = written(three_pairs)

    assert list(rows[0]) == COLUMNS


def test_the_counts_survive_the_round_trip_as_numbers(three_pairs):
    _, rows, _ = written(three_pairs)
    cells = [int(rows[0][name]) for name in "abcd"]

    assert cells[0] == 3
    assert sum(cells) == 3


def test_a_backslash_in_a_product_name_survives(tmp_path):
    corpus(
        tmp_path / "parquet",
        {str(n): ([r"A\B"], ["Headache"]) for n in range(3)},
    )

    _, rows, _ = written(tmp_path)

    assert rows[0]["drug"] == r"A\B"


def test_a_comma_in_an_event_name_survives(tmp_path):
    corpus(
        tmp_path / "parquet",
        {str(n): (["ASPIRIN"], ["Sleep disorder, insomnia type"]) for n in range(3)},
    )

    _, rows, _ = written(tmp_path)

    assert rows[0]["event"] == "Sleep disorder, insomnia type"


def test_crowded_marks_pairs_whose_reports_name_many_drugs(tmp_path):
    reports = {str(n): (["ASPIRIN"], ["Headache"]) for n in range(3)}
    reports["wide"] = ([f"D{n}" for n in range(40)], ["Rash"])
    corpus(tmp_path / "parquet", reports)

    _, rows, _ = written(tmp_path, min_count=1)
    verdict = {f"{row['drug']}|{row['event']}": row["crowded"] for row in rows}

    assert verdict["ASPIRIN|Headache"] == "0"
    assert verdict["D0|Rash"] == "1"


def test_the_cut_moves_with_the_quantile(tmp_path):
    reports = {str(n): ([f"D{n}"], ["X"]) for n in range(9)}
    reports["wide"] = (list("ABCDEFGHIJ"), ["X"])
    corpus(tmp_path / "parquet", reports)

    loose, _, _ = written(tmp_path, min_count=1, quantile=0.5)
    tight, _, _ = written(tmp_path, min_count=1, quantile=0.99)

    assert loose.cut < tight.cut


def test_the_file_is_read_back_before_it_is_called_written(three_pairs):
    result, rows, _ = written(three_pairs)

    assert result.pairs == len(rows)
