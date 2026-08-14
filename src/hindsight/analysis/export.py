from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from hindsight.analysis import crowding
from hindsight.analysis.prr import (
    DEFAULT_MIN_COUNT,
    Pair,
    PrrError,
    _directory,
    top_pairs,
)
from hindsight.write import PARQUET_DIR


DEFAULT_CSV = Path("reports/data/prr_top.csv")

COLUMNS = ["drug", "event", "a", "b", "c", "d", "prr", "chi2", "signal", "crowding", "crowded"]


@dataclass(frozen=True, slots=True)
class Written:
    path: Path
    pairs: int
    crowded: int
    cut: float
    partition: str


def _provenance(directory: Path) -> tuple[str, str]:
    path = directory / "metrics.json"

    if not path.exists():
        raise PrrError(
            f"{path} is missing, so the export date behind these rows is unknown. "
            f"Re-run the ingest for this partition."
        )

    metrics = json.loads(path.read_text())

    return metrics["partition"], metrics["export_date"]


def write_csv(
    path: Path = DEFAULT_CSV,
    *,
    min_count: int = DEFAULT_MIN_COUNT,
    quantile: float = crowding.DEFAULT_QUANTILE,
    partition: str | None = None,
    root: Path = PARQUET_DIR,
) -> Written:
    directory = _directory(partition, root)
    partition_id, export_date = _provenance(directory)

    cut = crowding.breadth(quantile=quantile, partition=partition, root=root)["cut"]
    pairs = top_pairs(limit=None, min_count=min_count, partition=partition, root=root)

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="") as handle:
        handle.write(
            f"# hindsight — drug-event pairs over one FAERS partition\n"
            f"# partition: {partition_id}\n"
            f"# export_date: {export_date}\n"
            f"# min_count: {min_count}\n"
            f"# crowding_cut: {cut:g} distinct drugs "
            f"(the {quantile:g} quantile of this partition)\n"
            f"# pandas.read_csv(path, comment='#'). Counts are distinct reports.\n"
        )

        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(COLUMNS)
        writer.writerows(_row(pair, cut) for pair in pairs)

    _verify(path, expected=len(pairs))

    return Written(
        path=path,
        pairs=len(pairs),
        crowded=sum(1 for pair in pairs if _crowded(pair, cut)),
        cut=cut,
        partition=partition_id,
    )


def _verify(path: Path, *, expected: int) -> None:
    with path.open(newline="") as handle:
        rows = [row for row in csv.reader(handle) if not row[0].startswith("#")]

    header, body = rows[0], rows[1:]
    widths = {len(row) for row in body}

    if header != COLUMNS or len(body) != expected or widths not in ({len(COLUMNS)}, set()):
        raise PrrError(
            f"{path} was written but does not read back: {len(body)} rows "
            f"(expected {expected}), widths {sorted(widths)}, header {header}."
        )


def _crowded(pair: Pair, cut: float) -> bool:
    return pair.crowding is not None and pair.crowding >= cut


def _row(pair: Pair, cut: float) -> list:
    return [
        pair.drug,
        pair.event,
        pair.a,
        pair.b,
        pair.c,
        pair.d,
        "" if pair.prr is None else round(pair.prr, 3),
        "" if pair.chi2 is None else round(pair.chi2, 3),
        int(pair.signal),
        pair.crowding,
        int(_crowded(pair, cut)),
    ]
