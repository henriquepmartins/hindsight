from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from hindsight import metrics, schema
from hindsight.analysis.export import write_csv
from hindsight.analysis.prr import (
    DEFAULT_LIMIT,
    DEFAULT_MIN_COUNT,
    SIGNAL_CHI2,
    SIGNAL_MIN_COUNT,
    SIGNAL_PRR,
    Pair,
    PrrError,
    top_pairs,
)
from hindsight.fetch import FetchError, ensure_local
from hindsight.manifest import ManifestError, Partition, resolve
from hindsight.normalize import NormalizeError, REPORT_TABLE
from hindsight.schema import SCHEMA_DIR, SchemaError, Schemas
from hindsight.stream import StreamError, iter_reports, json_bytes
from hindsight.write import PARQUET_DIR, partition_dir, write_partition


log = logging.getLogger(__name__)


class IngestError(Exception):
    pass


def _schemas(partition: Partition, archive: Path, *, reinfer: bool) -> Schemas:
    path = SCHEMA_DIR / f"{partition.stem}.json"

    if path.exists() and not reinfer:
        log.info("schema %s (versionado)", path)

        return schema.load(path)

    log.info("passo 1: inferindo o schema a partir de todos os registros")
    inferred = schema.infer(iter_reports(archive))
    schema.save(
        path,
        inferred,
        source={
            "partition": partition.id,
            "export_date": partition.export_date.isoformat(),
            "records": partition.records,
        },
    )
    log.info("schema %s (inferido)", path)

    return inferred


def _report(summary: dict) -> None:
    rows = summary["rows"]
    coverage = summary["coverage"]

    print(f"partição           {summary['partition']} (export {summary['export_date']})")

    for table, count in rows.items():
        print(f"{table:<18} {count:>10,}")

    print(f"openfda distintos  {summary['distinct_openfda']:>10,}")
    print(f"ids repetidos      {summary['repeated_report_ids']:>10,}")
    print(
        f"parquet            {summary['bytes']['parquet'] / 1e6:>10.2f} MB"
        f"   {summary['compression']['vs_json']}x vs json"
        f"   {summary['compression']['vs_zip']}x vs zip"
    )

    for column, rate in coverage.items():
        share = "ausente nesta partição" if rate is None else f"{rate:.1%}"
        print(f"{column:<18} {share:>10}")


def _ingest(partition_id: str, *, reinfer: bool, repin: bool) -> None:
    partition = resolve(partition_id)
    archive = ensure_local(partition, repin=repin)
    schemas = _schemas(partition, archive, reinfer=reinfer or repin)

    log.info("passo 2: escrevendo parquet contra o schema congelado")
    written = write_partition(
        iter_reports(archive), schemas, PARQUET_DIR / partition_dir(partition.id)
    )

    summary = metrics.snapshot(
        partition=partition,
        written=written,
        schemas=schemas,
        zip_bytes=archive.stat().st_size,
        json_bytes=json_bytes(archive),
    )
    log.info("metrics %s", metrics.save(written.directory, summary))

    _report(summary)

    if summary["rows"][REPORT_TABLE] != partition.records:
        raise IngestError(
            f"{written.directory} tem {summary['rows'][REPORT_TABLE]:,} linhas de "
            f"relatório e o manifesto do openFDA diz {partition.records:,}. "
            f"Relatorios sumiram entre o zip e o Parquet."
        )


def _pairs(pairs: list[Pair], *, min_count: int) -> None:
    if not pairs:
        print(f"Nenhum par medicamento-evento chega a {min_count} co-relatos.")

        return

    print(
        f"{'medicamento':<30} {'evento':<26} {'a':>5} {'b':>6} {'c':>5} {'d':>7} "
        f"{'PRR':>9} {'chi2':>9}  sinal"
    )

    for pair in pairs:
        ratio = "indefinido" if pair.prr is None else f"{pair.prr:,.1f}"
        chi2 = "" if pair.chi2 is None else f"{pair.chi2:,.1f}"
        print(
            f"{pair.drug[:30]:<30} {pair.event[:26]:<26} {pair.a:>5,} {pair.b:>6,} "
            f"{pair.c:>5,} {pair.d:>7,} {ratio:>9} {chi2:>9}  "
            f"{'sim' if pair.signal else '-'}"
        )

    print(
        f"\n{pairs[0].reports:,} relatórios · min {min_count} co-relatos · "
        f"sinal = Evans (PRR>={SIGNAL_PRR:.0f}, chi2>={SIGNAL_CHI2:.0f}, "
        f"a>={SIGNAL_MIN_COUNT}) · strings cruas de medicinalproduct, sem "
        f"resolução de entidades e sem deduplicação (M2) · reporte "
        f"desproporcional não é causalidade"
    )


def _analyze(
    partition_id: str | None,
    *,
    limit: int,
    min_count: int,
    signals_only: bool,
    to_csv: bool,
) -> None:
    if to_csv:
        written = write_csv(min_count=min_count, partition=partition_id)

        print(
            f"{written.path}  {written.pairs:,} pares · {written.crowded:,} lotados "
            f"(>= {written.cut:g} medicamentos distintos) · {written.partition}"
        )

        return

    _pairs(
        top_pairs(
            limit=limit,
            min_count=min_count,
            signals_only=signals_only,
            partition=partition_id,
        ),
        min_count=min_count,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hindsight")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="Baixa e fixa uma partição")
    fetch.add_argument("partition_id", help='e.g. "2025q1/0001-of-0028"')
    fetch.add_argument(
        "--repin",
        action="store_true",
        help="Move a partição para o export corrente do openFDA e grava um pin "
        "novo. Todo número medido contra o export antigo passa a precisar de "
        "nova medição",
    )

    ingest = commands.add_parser("ingest", help="Normaliza uma partição para Parquet")
    ingest.add_argument("partition_id", help='e.g. "2025q1/0001-of-0028"')
    ingest.add_argument(
        "--reinfer",
        action="store_true",
        help="Refaz o passo 1 e sobrescreve o schema versionado desta partição",
    )
    ingest.add_argument(
        "--repin",
        action="store_true",
        help="Move a partição para o export corrente do openFDA antes de "
        "ingerir. Implica --reinfer, porque o schema congelado descreve os "
        "bytes antigos",
    )

    analyze = commands.add_parser("analyze", help="Ordena pares medicamento-evento por PRR")
    analyze.add_argument(
        "partition_id",
        nargs="?",
        help="Assume a única partição ingerida; obrigatório quando houver duas",
    )
    analyze.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    analyze.add_argument(
        "--min-count",
        type=int,
        default=DEFAULT_MIN_COUNT,
        help=f"Minimo de co-relatos por par (padrão {DEFAULT_MIN_COUNT})",
    )
    analyze.add_argument(
        "--signals-only",
        action="store_true",
        help="Mantem só os pares que atendem Evans. Estreita a tabela; não a "
        "limpa — o topo desta partição passa no critério e continua sendo "
        "duplicata",
    )
    analyze.add_argument(
        "--csv",
        action="store_true",
        dest="to_csv",
        help="Escreve todos os pares em reports/data/prr_top.csv — o arquivo que "
        "a pagina publicada le, já que data/parquet/ esta no gitignore",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        if args.command == "fetch":
            print(ensure_local(resolve(args.partition_id), repin=args.repin))
        elif args.command == "analyze":
            _analyze(
                args.partition_id,
                limit=args.limit,
                min_count=args.min_count,
                signals_only=args.signals_only,
                to_csv=args.to_csv,
            )
        else:
            _ingest(args.partition_id, reinfer=args.reinfer, repin=args.repin)
    except (
        ManifestError,
        FetchError,
        StreamError,
        NormalizeError,
        SchemaError,
        IngestError,
        PrrError,
    ) as exc:
        print(exc, file=sys.stderr)

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
