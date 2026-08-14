from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from hindsight.analysis.prr import (
    DEFAULT_MIN_COUNT,
    Pair,
    PrrError,
    excluded_terms,
    partitions,
    top_pairs,
)
import duckdb


def corpus(root: Path, reports: dict[str, tuple[list[str], list[str]]]) -> Path:
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

    return directory


def exclusions(root: Path, terms: list[str] = ["Off label use"]) -> Path:
    path = root / "excluded_terms.csv"
    rows = "\n".join(f'{term},administration,1,"because"' for term in terms)
    path.write_text(
        "# a header the reader is meant to see\n"
        "# and the parser is not\n"
        "term,category,partition_rows,reason\n" + rows + ("\n" if rows else "")
    )

    return path


@pytest.fixture
def empty_list(tmp_path) -> Path:
    return exclusions(tmp_path, [])


def test_the_cells_partition_the_corpus(tmp_path):
    root = tmp_path / "parquet"
    corpus(
        root,
        {
            "1": (["ASPIRIN"], ["Nausea"]),
            "2": (["ASPIRIN"], ["Headache"]),
            "3": (["WARFARIN"], ["Nausea"]),
            "4": (["WARFARIN"], ["Rash"]),
        },
    )

    for pair in top_pairs(root=root, exclusions=exclusions(tmp_path), min_count=1):
        assert pair.reports == 4


def test_prr_matches_the_arithmetic(tmp_path):
    root = tmp_path / "parquet"
    corpus(
        root,
        {
            "1": (["ASPIRIN"], ["Nausea"]),
            "2": (["ASPIRIN"], ["Nausea"]),
            "3": (["ASPIRIN"], ["Headache"]),
            "4": (["WARFARIN"], ["Nausea"]),
            "5": (["WARFARIN"], ["Rash"]),
            "6": (["WARFARIN"], ["Rash"]),
        },
    )

    pairs = top_pairs(root=root, exclusions=exclusions(tmp_path), min_count=2)
    aspirin = next(p for p in pairs if p.drug == "ASPIRIN" and p.event == "Nausea")

    assert (aspirin.a, aspirin.b, aspirin.c, aspirin.d) == (2, 1, 1, 2)
    assert aspirin.prr == pytest.approx(2.0)


def test_a_drug_named_many_times_in_one_report_counts_once(tmp_path):
    root = tmp_path / "parquet"
    corpus(
        root,
        {
            "1": (["INFLIXIMAB"] * 50, ["Sepsis"] * 4),
            "2": (["ASPIRIN"], ["Nausea"]),
        },
    )

    pairs = top_pairs(root=root, exclusions=exclusions(tmp_path), min_count=1)
    sepsis = next(p for p in pairs if p.event == "Sepsis")

    assert sepsis.a == 1
    assert sepsis.reports == 2


def test_an_event_repeated_in_one_report_counts_once(tmp_path):
    root = tmp_path / "parquet"
    corpus(root, {"1": (["ASPIRIN"], ["Nausea"] * 9), "2": (["ASPIRIN"], ["Rash"])})

    pairs = top_pairs(root=root, exclusions=exclusions(tmp_path), min_count=1)

    assert next(p for p in pairs if p.event == "Nausea").a == 1


def test_excluded_terms_leave_the_output(tmp_path):
    root = tmp_path / "parquet"
    corpus(
        root,
        {
            "1": (["ASPIRIN"], ["Off label use"]),
            "2": (["ASPIRIN"], ["Off label use", "Nausea"]),
        },
    )

    pairs = top_pairs(
        root=root, exclusions=exclusions(tmp_path, ["Off label use"]), min_count=1
    )

    assert [p.event for p in pairs] == ["Nausea"]


def test_an_excluded_event_still_leaves_its_report_in_the_corpus(tmp_path):
    root = tmp_path / "parquet"
    corpus(
        root,
        {
            "1": (["ASPIRIN"], ["Nausea"]),
            "2": (["WARFARIN"], ["Off label use"]),
        },
    )

    pairs = top_pairs(
        root=root, exclusions=exclusions(tmp_path, ["Off label use"]), min_count=1
    )

    assert pairs[0].reports == 2


def test_an_empty_exclusion_list_is_an_error_not_an_empty_filter(tmp_path, empty_list):
    with pytest.raises(PrrError, match="no terms"):
        excluded_terms(duckdb.connect(), empty_list)


def test_reading_the_list_without_the_comment_flag_returns_nothing(tmp_path):
    path = exclusions(tmp_path, ["Off label use"])
    connection = duckdb.connect()

    assert connection.sql(f"SELECT * FROM read_csv('{path}')").fetchall() == []
    assert excluded_terms(connection, path) == ["Off label use"]


def test_a_missing_exclusion_list_says_it_is_committed(tmp_path):
    with pytest.raises(PrrError, match="restore it from git"):
        excluded_terms(duckdb.connect(), tmp_path / "gone.csv")


def test_min_count_filters_on_a(tmp_path):
    root = tmp_path / "parquet"
    corpus(
        root,
        {
            "1": (["ASPIRIN"], ["Nausea"]),
            "2": (["ASPIRIN"], ["Nausea"]),
            "3": (["ASPIRIN"], ["Rash"]),
        },
    )

    path = exclusions(tmp_path)

    assert {p.event for p in top_pairs(root=root, exclusions=path, min_count=1)} == {
        "Nausea",
        "Rash",
    }
    assert {p.event for p in top_pairs(root=root, exclusions=path, min_count=2)} == {
        "Nausea"
    }


def test_the_default_threshold_is_three():
    assert DEFAULT_MIN_COUNT == 3


def test_a_threshold_below_one_is_refused(tmp_path):
    with pytest.raises(PrrError, match="not a pair"):
        top_pairs(min_count=0, root=tmp_path)


def test_an_event_seen_only_with_one_drug_has_no_ratio_but_keeps_its_counts(tmp_path):
    root = tmp_path / "parquet"
    corpus(
        root,
        {
            "1": (["ASPIRIN"], ["Onychomadesis"]),
            "2": (["ASPIRIN"], ["Onychomadesis"]),
            "3": (["WARFARIN"], ["Nausea"]),
            "4": (["WARFARIN"], ["Nausea"]),
        },
    )

    pairs = top_pairs(root=root, exclusions=exclusions(tmp_path), min_count=2)
    undefined = [p for p in pairs if p.prr is None]

    assert {p.event for p in undefined} == {"Onychomadesis", "Nausea"}
    assert all(p.c == 0 and p.a == 2 for p in undefined)
    assert pairs[-1].prr is None


def test_nothing_ingested_says_so(tmp_path):
    with pytest.raises(PrrError, match="make ingest"):
        top_pairs(root=tmp_path / "empty")


def test_two_partitions_refuse_to_pool(tmp_path):
    root = tmp_path / "parquet"
    corpus(root, {"1": (["ASPIRIN"], ["Nausea"])})

    other = root / "year=2005" / "quarter=1" / "part=0001-of-0001"
    other.mkdir(parents=True)
    pq.write_table(pa.table({"safetyreportid": ["9"]}), other / "report.parquet")

    assert len(partitions(root)) == 2

    with pytest.raises(PrrError, match="not pooled across eras"):
        top_pairs(root=root, exclusions=exclusions(tmp_path))


def test_a_named_partition_that_was_never_ingested_says_what_to_run(tmp_path):
    with pytest.raises(PrrError, match="make ingest PARTITION=2005q1/0001-of-0004"):
        top_pairs(partition="2005q1/0001-of-0004", root=tmp_path)


def test_pairs_come_back_prr_descending(tmp_path):
    root = tmp_path / "parquet"
    corpus(
        root,
        {
            "1": (["ASPIRIN"], ["Nausea"]),
            "2": (["ASPIRIN"], ["Nausea"]),
            "3": (["ASPIRIN"], ["Rash"]),
            "4": (["WARFARIN"], ["Nausea"]),
            "5": (["WARFARIN"], ["Rash"]),
            "6": (["WARFARIN"], ["Rash"]),
            "7": (["IBUPROFEN"], ["Nausea"]),
            "8": (["IBUPROFEN"], ["Rash"]),
        },
    )

    ratios = [
        p.prr
        for p in top_pairs(root=root, exclusions=exclusions(tmp_path), min_count=1)
        if p.prr is not None
    ]

    assert ratios == sorted(ratios, reverse=True)


def test_limit_is_honoured(tmp_path):
    root = tmp_path / "parquet"
    corpus(root, {str(n): (["ASPIRIN", "WARFARIN"], ["Nausea", "Rash"]) for n in range(4)})

    assert len(top_pairs(root=root, exclusions=exclusions(tmp_path), min_count=1, limit=2)) == 2


def test_a_pair_carries_its_counts():
    assert Pair(drug="d", event="e", a=1, b=2, c=3, d=4, prr=1.0, chi2=1.0).reports == 10


def pair(**overrides) -> Pair:
    return Pair(
        **{
            "drug": "d",
            "event": "e",
            "a": 5,
            "b": 5,
            "c": 5,
            "d": 985,
            "prr": 10.0,
            "chi2": 30.0,
        }
        | overrides
    )


def test_evans_needs_all_three():
    assert pair().signal

    assert not pair(prr=1.9).signal
    assert not pair(chi2=3.9).signal
    assert not pair(a=2).signal


def test_an_undefined_ratio_is_not_a_signal():
    assert not pair(prr=None, c=0).signal


def test_chi_squared_matches_the_arithmetic(tmp_path):
    root = tmp_path / "parquet"
    corpus(
        root,
        {
            "1": (["ASPIRIN"], ["Nausea"]),
            "2": (["ASPIRIN"], ["Nausea"]),
            "3": (["ASPIRIN"], ["Headache"]),
            "4": (["WARFARIN"], ["Nausea"]),
            "5": (["WARFARIN"], ["Rash"]),
            "6": (["WARFARIN"], ["Rash"]),
        },
    )

    pairs = top_pairs(root=root, exclusions=exclusions(tmp_path), min_count=2)
    aspirin = next(p for p in pairs if p.drug == "ASPIRIN" and p.event == "Nausea")

    assert aspirin.chi2 == pytest.approx(0.0)
    assert not aspirin.signal


def test_yates_never_returns_a_negative_chi_squared(tmp_path):
    root = tmp_path / "parquet"
    corpus(root, {str(n): (["ASPIRIN"], ["Nausea"]) for n in range(4)})

    for found in top_pairs(root=root, exclusions=exclusions(tmp_path), min_count=1):
        assert found.chi2 is None or found.chi2 >= 0


def test_signals_only_narrows_the_table(tmp_path):
    root = tmp_path / "parquet"
    corpus(
        root,
        {
            "1": (["ASPIRIN"], ["Nausea"]),
            "2": (["ASPIRIN"], ["Nausea"]),
            "3": (["ASPIRIN"], ["Nausea"]),
            "4": (["WARFARIN"], ["Nausea"]),
            "5": (["WARFARIN"], ["Rash"]),
            "6": (["WARFARIN"], ["Rash"]),
            "7": (["WARFARIN"], ["Rash"]),
        },
    )

    path = exclusions(tmp_path)
    everything = top_pairs(root=root, exclusions=path, min_count=1)
    flagged = top_pairs(root=root, exclusions=path, min_count=1, signals_only=True)

    assert len(flagged) < len(everything)
    assert all(found.signal for found in flagged)
    assert {(f.drug, f.event) for f in flagged} == {
        (f.drug, f.event) for f in everything if f.signal
    }
