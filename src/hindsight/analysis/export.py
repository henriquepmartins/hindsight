from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from hindsight.analysis import crowding
from hindsight.analysis.prr import (
    COMMENT,
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


PROVENANCE = ("partition", "export_date", "min_count")


def provenance(path: Path = DEFAULT_CSV) -> dict[str, str]:
    if not path.is_file():
        raise PrrError(
            f"{path} não é um arquivo, resolvido a partir de {Path.cwd()}."
        )

    found = {}

    with path.open(newline="", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith(COMMENT):
                break

            name, separator, value = line[len(COMMENT) :].partition(":")

            if separator and name.strip() in PROVENANCE and value.strip():
                found[name.strip()] = value.strip()

    missing = set(PROVENANCE) - set(found)

    if missing:
        raise PrrError(
            f"{path} não nomeia {sorted(missing)} no cabeçalho, ou os nomeia "
            f"sem valor. Sem isso a "
            f"página publicada não da para amarrar a partição que a produziu, e "
            f"uma divergência entre as duas fica ilegivel."
        )

    return found


def _ingested_provenance(directory: Path) -> tuple[str, str]:
    path = directory / "metrics.json"

    if not path.exists():
        raise PrrError(
            f"{path} não existe, entao a data de export por tras destas linhas e "
            f"desconhecida. Rode a ingestao desta partição de novo."
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
    partition_id, export_date = _ingested_provenance(directory)

    cut = crowding.breadth(quantile=quantile, partition=partition, root=root)["cut"]
    pairs = top_pairs(limit=None, min_count=min_count, partition=partition, root=root)

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        handle.write(
            f"# hindsight — pares medicamento-evento sobre uma partição do FAERS\n"
            f"# partition: {partition_id}\n"
            f"# export_date: {export_date}\n"
            f"# min_count: {min_count}\n"
            f"# corte_lotacao: {cut:g} medicamentos distintos "
            f"(o quantil {quantile:g} desta partição)\n"
            f"# pandas.read_csv(path, comment='#'). Contagens são de relatórios distintos.\n"
        )

        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(COLUMNS)
        writer.writerows(_row(pair, cut) for pair in pairs)

    _verify(path, expected=len(pairs))
    provenance(path)

    return Written(
        path=path,
        pairs=len(pairs),
        crowded=sum(1 for pair in pairs if _crowded(pair, cut)),
        cut=cut,
        partition=partition_id,
    )


def _verify(path: Path, *, expected: int) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.reader(handle) if not row[0].startswith("#")]

    header, body = rows[0], rows[1:]
    widths = {len(row) for row in body}

    if header != COLUMNS or len(body) != expected or widths not in ({len(COLUMNS)}, set()):
        raise PrrError(
            f"{path} foi escrito mas não volta na leitura: {len(body)} linhas "
            f"(esperado {expected}), larguras {sorted(widths)}, cabeçalho {header}."
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
