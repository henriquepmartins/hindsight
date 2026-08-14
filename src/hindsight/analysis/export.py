"""The one file the published page is allowed to read.

`data/parquet/` is gitignored, so the workflow that renders the site has no
corpus to query. The page reads this CSV instead, and the CSV is written by the
pipeline rather than by hand.

**That buys a hermetic build and costs a way for the site to be wrong.** Someone
edits the exclusion list, nothing regenerates, the published number stays where
it was, and no test fails — the page and the pipeline disagree and the repo
looks fine. Nothing here can prevent that. What it can do is make the
disagreement legible: the header carries the partition, the export date, the
minimum count and the crowding cut that produced these rows, so a reader
comparing the page against a fresh run has the provenance in front of them
instead of having to reconstruct it.

The header is prose behind `#`, which is the same shape as the exclusion list
and therefore the same trap — a reader without `comment='#'` gets the comments
as data. The exclusion list answered that by raising on an empty read. Here the
failure is loud on its own: the first column would parse as `# hindsight …`
and every downstream number would be a string.
"""

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
    """What the run produced, so the CLI can report it without re-reading."""

    path: Path
    pairs: int
    crowded: int
    cut: float
    partition: str


def _provenance(directory: Path) -> tuple[str, str]:
    """The partition and export date this table was computed from.

    Read from the `metrics.json` the ingest left beside the Parquet, not from
    the directory name and not from the network. The directory name would have
    to be un-mangled back through `partition_dir`, and openFDA re-chunks
    quarters between exports (L-006) — the export date is the half that makes a
    partition id mean anything, and only the ingest knows it.
    """
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
    """Every pair reaching `min_count`, with its 2×2 and its crowding verdict.

    Every pair and not the top 20: the chart is a cloud, and a cloud drawn from
    its own summit is a dot.
    """
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

        # QUOTE_ALL, because FAERS product names carry backslashes —
        # `DESOGESTREL\ETHINYL ESTRADIOL` is a real row — and a backslash is
        # one of the escape characters a CSV dialect sniffer has to guess at.
        # Quoting every field leaves nothing to guess.
        #
        # It does not fix everything, and the part it does not fix is worth
        # knowing before you debug it. **DuckDB 1.5.5 sniffs this file
        # intermittently**: identical bytes at the same path raise on one run
        # and return 28,540 rows on the next, and `strict_mode=false` is the
        # only option that succeeded ten times out of ten. That is the
        # sniffer's sampling, not this file — Python's `csv` reader parses it
        # as 28,541 rows of exactly 11 columns with no stray control
        # characters, and pandas reads it deterministically with the right
        # dtypes. Read this file with pandas. DuckDB's job in this project is
        # the Parquet.
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
    """Read back what was just written and check its shape.

    The same move as the round-trip test, at a much smaller scale: the claim is
    that this file is a well-formed table, and a claim about a file is checkable
    by opening it. Without this the failure surfaces at render time, in a
    workflow, on a machine that has no partition to regenerate from.

    Raises:
        PrrError: the file does not read back as `expected` rows of `COLUMNS`.
    """
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
    """One CSV row.

    PRR and χ² are rounded to three decimals and crowding is not rounded at all.
    The ratios are read; the crowding is compared against `cut`, and rounding a
    value that a threshold is applied to is how a pair ends up on the wrong side
    of a line for a reason nobody can see.
    """
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
