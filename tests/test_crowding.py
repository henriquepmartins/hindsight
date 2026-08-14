from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from hindsight.analysis.crowding import breadth, overlap, wide_reports
from hindsight.analysis.prr import PrrError


def corpus(root: Path, reports: dict[str, list[str]]) -> Path:
    directory = root / "year=2025" / "quarter=1" / "part=0001-of-0001"
    directory.mkdir(parents=True, exist_ok=True)

    pq.write_table(
        pa.table({"safetyreportid": list(reports)}), directory / "report.parquet"
    )
    pq.write_table(
        pa.table(
            {
                "safetyreportid": [r for r, ds in reports.items() for _ in ds],
                "medicinalproduct": [d for _, ds in reports.items() for d in ds],
            }
        ),
        directory / "report_drug.parquet",
    )

    return directory


def test_breadth_reports_the_middle_and_the_tail(tmp_path):
    corpus(tmp_path, {"1": ["A"], "2": ["A", "B"], "3": list("ABCDE")})

    measured = breadth(root=tmp_path)

    assert measured["median"] == 2
    assert measured["widest"] == 5
    assert measured["reports"] == 3


def test_a_drug_named_twice_in_one_report_is_one_drug(tmp_path):
    corpus(tmp_path, {"1": ["A", "A", "A", "A"], "2": ["A", "B"]})

    assert breadth(root=tmp_path)["widest"] == 2


def test_the_cut_sits_at_the_quantile_asked_for(tmp_path):
    corpus(tmp_path, {str(n): list("ABCDEFGHIJ")[:n] for n in range(1, 11)})

    assert breadth(quantile=0.5, root=tmp_path)["cut"] == 5.5
    assert breadth(quantile=0.9, root=tmp_path)["cut"] == 9.1


@pytest.mark.parametrize("quantile", [0, 1, -0.5, 2])
def test_a_quantile_outside_the_interval_is_refused(tmp_path, quantile):
    corpus(tmp_path, {"1": ["A"]})

    with pytest.raises(PrrError, match="strictly inside"):
        breadth(quantile=quantile, root=tmp_path)


def test_wide_reports_are_inclusive_of_the_cut_and_widest_first(tmp_path):
    corpus(tmp_path, {"narrow": ["A"], "exactly": ["A", "B"], "wide": list("ABCD")})

    assert wide_reports(cut=2, root=tmp_path) == [("wide", 4), ("exactly", 2)]


def test_nothing_reaches_an_impossible_cut(tmp_path):
    corpus(tmp_path, {"1": ["A", "B"]})

    assert wide_reports(cut=99, root=tmp_path) == []


def test_jaccard_is_the_shared_over_the_union(tmp_path):
    corpus(tmp_path, {"1": list("ABC"), "2": list("BCD")})

    assert overlap(["1", "2"], root=tmp_path) == [("1", "2", 0.5)]


def test_identical_lists_score_one_and_disjoint_ones_score_zero(tmp_path):
    corpus(tmp_path, {"1": list("AB"), "2": list("AB"), "3": list("XY")})

    scores = {(a, b): score for a, b, score in overlap(["1", "2", "3"], root=tmp_path)}

    assert scores[("1", "2")] == 1.0
    assert scores[("1", "3")] == 0.0


def test_each_unordered_pair_appears_once(tmp_path):
    corpus(tmp_path, {"1": ["A"], "2": ["A"], "3": ["A"]})

    assert len(overlap(["1", "2", "3"], root=tmp_path)) == 3


def test_repetition_does_not_inflate_the_overlap(tmp_path):
    corpus(tmp_path, {"1": ["A", "A", "A", "B"], "2": ["A", "B"]})

    assert overlap(["1", "2"], root=tmp_path) == [("1", "2", 1.0)]


def test_one_report_has_nothing_to_be_compared_against(tmp_path):
    corpus(tmp_path, {"1": ["A"]})

    with pytest.raises(PrrError, match="two reports"):
        overlap(["1"], root=tmp_path)
