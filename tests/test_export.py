"""The CSV is the only thing the published page reads, so its shape is a
contract and not an implementation detail.

Two properties matter more than the rest. The file has to carry the provenance
of the numbers in it, because nothing else can stop the page and the pipeline
from drifting apart. And it has to contain **every** pair rather than the CLI's
top 20, because a scatter plot drawn from its own summit is a dot.
"""

import json
from pathlib import Path

import pandas
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
    """One partition from `{report_id: (drugs, events)}`, with its metrics."""
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
    """Three reports sharing one drug and one event, so one pair reaches a = 3."""
    corpus(
        tmp_path / "parquet",
        {str(n): (["ASPIRIN"], ["Headache"]) for n in range(3)},
    )

    return tmp_path


def written(root: Path, **kwargs):
    path = root / "out.csv"
    result = write_csv(path, root=root / "parquet", **kwargs)

    return result, pandas.read_csv(path, comment="#"), path.read_text()


# --- provenance --------------------------------------------------------------


def test_the_header_carries_what_produced_the_rows(three_pairs):
    _, _, text = written(three_pairs)
    header = [line for line in text.splitlines() if line.startswith("#")]

    assert any("2025q1/0001-of-0001" in line for line in header)
    assert any("2026-08-10" in line for line in header)
    assert any("min_count: 3" in line for line in header)
    assert any("crowding_cut" in line for line in header)


def test_a_partition_with_no_metrics_refuses_rather_than_guessing(tmp_path):
    """The export date is the half that makes a partition id mean anything
    (L-006), and only the ingest knows it."""
    corpus(tmp_path / "parquet", {"1": (["A"], ["X"])}, metrics=False)

    with pytest.raises(PrrError, match="export date"):
        write_csv(tmp_path / "out.csv", root=tmp_path / "parquet")


# --- what lands in the file --------------------------------------------------


def test_every_pair_is_written_not_only_the_top(tmp_path):
    """Six reports naming five drugs and five events make 25 pairs. The CLI
    would show 20 of them; the file has to hold all 25."""
    drugs = [f"D{n}" for n in range(5)]
    events = [f"E{n}" for n in range(5)]
    corpus(tmp_path / "parquet", {str(n): (drugs, events) for n in range(6)})

    result, frame, _ = written(tmp_path)

    assert result.pairs == len(frame) == 25


def test_the_columns_are_the_contract(three_pairs):
    _, frame, _ = written(three_pairs)

    assert list(frame.columns) == COLUMNS


def test_the_counts_survive_the_round_trip_as_numbers(three_pairs):
    """QUOTE_ALL quotes the integers too. They have to come back as integers."""
    _, frame, _ = written(three_pairs)

    assert frame.a.dtype.kind == "i"
    assert frame.loc[0, "a"] == 3
    assert frame.loc[0, "a"] + frame.loc[0, "b"] + frame.loc[0, "c"] + frame.loc[0, "d"] == 3


def test_a_backslash_in_a_product_name_survives(tmp_path):
    """`DESOGESTREL\\ETHINYL ESTRADIOL` is a real row, and a backslash is what
    a dialect sniffer guesses wrong about."""
    corpus(
        tmp_path / "parquet",
        {str(n): ([r"A\B"], ["Headache"]) for n in range(3)},
    )

    _, frame, _ = written(tmp_path)

    assert frame.loc[0, "drug"] == r"A\B"


def test_a_comma_in_an_event_name_survives(tmp_path):
    corpus(
        tmp_path / "parquet",
        {str(n): (["ASPIRIN"], ["Sleep disorder, insomnia type"]) for n in range(3)},
    )

    _, frame, _ = written(tmp_path)

    assert frame.loc[0, "event"] == "Sleep disorder, insomnia type"


# --- the crowding verdict ----------------------------------------------------


def test_crowded_marks_pairs_whose_reports_name_many_drugs(tmp_path):
    """One report names 40 drugs, the rest name one. The wide report's pairs are
    the crowded ones and the narrow report's are not."""
    reports = {str(n): (["ASPIRIN"], ["Headache"]) for n in range(3)}
    reports["wide"] = ([f"D{n}" for n in range(40)], ["Rash"])
    corpus(tmp_path / "parquet", reports)

    _, frame, _ = written(tmp_path, min_count=1)
    verdict = dict(zip(frame.drug + "|" + frame.event, frame.crowded))

    assert verdict["ASPIRIN|Headache"] == 0
    assert verdict["D0|Rash"] == 1


def test_the_cut_moves_with_the_quantile(tmp_path):
    reports = {str(n): ([f"D{n}"], ["X"]) for n in range(9)}
    reports["wide"] = (list("ABCDEFGHIJ"), ["X"])
    corpus(tmp_path / "parquet", reports)

    loose, _, _ = written(tmp_path, min_count=1, quantile=0.5)
    tight, _, _ = written(tmp_path, min_count=1, quantile=0.99)

    assert loose.cut < tight.cut


def test_the_file_is_read_back_before_it_is_called_written(three_pairs):
    """The write verifies itself, so a malformed file fails here and not in a
    render workflow on a machine with no partition to regenerate from."""
    result, frame, _ = written(three_pairs)

    assert result.pairs == len(frame)
