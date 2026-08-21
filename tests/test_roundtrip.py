import json
import os
from pathlib import Path

import pytest

from hindsight.normalize import TABLES, OpenfdaDimension, split
from hindsight.roundtrip import (
    BrokenTables,
    Tables,
    UnknownReport,
    reconstruct,
)
from hindsight.schema import SCHEMA_DIR, infer
from hindsight.stream import iter_reports
from hindsight.write import PARQUET_DIR, partition_dir, write_partition


FIXTURE = Path(__file__).parent / "fixtures" / "sample_100.json"


RAW_DIR = Path("data/raw")


def artifacts_of(partition_id: str) -> tuple[Path, Path, Path]:
    stem = partition_id.replace("/", "-")

    return (
        RAW_DIR / f"{stem}.zip",
        PARQUET_DIR / partition_dir(partition_id),
        SCHEMA_DIR / f"{stem}.json",
    )


def requested_partitions() -> list[str]:
    return [p.strip() for p in os.environ.get("PARTITION", "").split(",") if p.strip()]


def ingested_partitions() -> list[str]:
    return sorted(
        json.loads(path.read_text())["partition"]
        for path in PARQUET_DIR.rglob("metrics.json")
    )


def partitions_under_test() -> list[str]:
    return requested_partitions() or ingested_partitions()


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def explicit_nulls(value: object, path: str = "report") -> list[str]:
    found: list[str] = []

    if isinstance(value, dict):
        for name, child in value.items():
            found += (
                [f"{path}.{name}"]
                if child is None
                else explicit_nulls(child, f"{path}.{name}")
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found += (
                [f"{path}[{index}]"]
                if item is None
                else explicit_nulls(item, f"{path}[{index}]")
            )

    return found


def differences(source: object, rebuilt: object, path: str = "") -> list[str]:
    if isinstance(source, dict) and isinstance(rebuilt, dict):
        found = []

        for name in sorted(source.keys() | rebuilt.keys()):
            where = f"{path}.{name}" if path else name

            if name not in source:
                found.append(f"{where}: only in rebuilt ({canonical(rebuilt[name])[:120]})")
            elif name not in rebuilt:
                found.append(f"{where}: only in source ({canonical(source[name])[:120]})")
            else:
                found += differences(source[name], rebuilt[name], where)

        return found

    if isinstance(source, list) and isinstance(rebuilt, list):
        if len(source) != len(rebuilt):
            return [f"{path}: {len(source)} entries in source, {len(rebuilt)} rebuilt"]

        return [
            d
            for index, (a, b) in enumerate(zip(source, rebuilt))
            for d in differences(a, b, f"{path}[{index}]")
        ]

    if canonical(source) != canonical(rebuilt):
        return [
            f"{path}: source {canonical(source)[:120]} != rebuilt "
            f"{canonical(rebuilt)[:120]}"
        ]

    return []


def tables_in_memory(reports: list[dict]) -> Tables:
    dimension = OpenfdaDimension()
    rows: dict[str, list[dict]] = {table: [] for table in TABLES}

    for ordinal, report in enumerate(reports, start=1):
        for table, produced in split(report, dimension, ordinal).by_table().items():
            rows[table] += produced

    return Tables.from_rows(rows)


def assert_round_trips(reports: list[dict], tables: Tables) -> int:
    for ordinal, source in enumerate(reports, start=1):
        found = differences(source, reconstruct(tables, ordinal))

        assert not found, "safetyreportid {} ({} {}): {} field(s) differ\n  {}".format(
            source["safetyreportid"],
            "ordinal",
            ordinal,
            len(found),
            "\n  ".join(found[:20]),
        )

    return len(reports)


@pytest.fixture(scope="module")
def sample() -> list[dict]:
    return json.loads(FIXTURE.read_text())


def test_the_source_carries_no_explicit_nulls(sample):
    found = [path for report in sample for path in explicit_nulls(report)]

    assert not found, f"{len(found)} explicit nulls, first: {found[:5]}"


def test_the_fixture_covers_the_shapes_it_was_chosen_for(sample):
    def drugs(report):
        return (report.get("patient") or {}).get("drug") or []

    covered = {

        "a drug with openfda: {}": sum(
            any(d.get("openfda") == {} for d in drugs(r)) for r in sample
        ),
        "a drug with no openfda": sum(
            any("openfda" not in d for d in drugs(r)) for r in sample
        ),

        "reportduplicate as an object": sum(
            isinstance(r.get("reportduplicate"), dict) for r in sample
        ),
        "reportduplicate as an array": sum(
            isinstance(r.get("reportduplicate"), list) for r in sample
        ),

        "5+ drugs": sum(len(drugs(r)) >= 5 for r in sample),

        "patient.summary present": sum(
            "summary" in (r.get("patient") or {}) for r in sample
        ),
        "no companynumb": sum("companynumb" not in r for r in sample),
    }

    missing = [name for name, count in covered.items() if count == 0]

    assert not missing, f"the fixture no longer covers: {missing} (have {covered})"
    assert len(sample) == 100


def test_the_fixture_needs_no_network_and_no_partition():
    assert FIXTURE.exists()
    assert FIXTURE.stat().st_size < 8 * 1024 * 1024


def test_every_fixture_report_rebuilds_identically(sample):
    assert assert_round_trips(sample, tables_in_memory(sample)) == 100


def test_drug_order_survives(sample):
    tables = tables_in_memory(sample)
    checked = 0

    for ordinal, source in enumerate(sample, start=1):
        drugs = (source.get("patient") or {}).get("drug") or []

        if len(drugs) < 2:
            continue

        checked += 1
        rebuilt = reconstruct(tables, ordinal)

        assert [canonical(d) for d in rebuilt["patient"]["drug"]] == [
            canonical(d) for d in drugs
        ]

    assert checked > 0, "the fixture has no multi-drug report left to check order on"


def test_an_empty_openfda_comes_back_as_an_empty_object(sample):
    tables = tables_in_memory(sample)
    seen = 0

    for ordinal, source in enumerate(sample, start=1):
        for position, drug in enumerate((source.get("patient") or {}).get("drug") or []):
            if drug.get("openfda") != {}:
                continue

            seen += 1
            rebuilt = reconstruct(tables, ordinal)

            assert rebuilt["patient"]["drug"][position]["openfda"] == {}

    assert seen > 0, "the fixture no longer contains the L-005 case"


def test_the_two_duplicate_shapes_come_back_as_they_arrived(sample):
    tables = tables_in_memory(sample)
    objects = arrays = 0

    for ordinal, source in enumerate(sample, start=1):
        original = source.get("reportduplicate")

        if original is None:
            continue

        rebuilt = reconstruct(tables, ordinal)["reportduplicate"]

        assert type(rebuilt) is type(original)
        assert canonical(rebuilt) == canonical(original)

        objects += isinstance(original, dict)
        arrays += isinstance(original, list)

    assert objects and arrays, f"fixture covers {objects} objects, {arrays} arrays"


def test_the_fixture_rebuilds_from_parquet(sample, tmp_path):
    write_partition(sample, infer(sample), tmp_path)

    assert assert_round_trips(sample, Tables.load(tmp_path)) == 100


def test_collapsing_empty_openfda_into_absent_is_caught(sample):
    ordinal, source = next(
        (position, report)
        for position, report in enumerate(sample, start=1)
        if any(
            d.get("openfda") == {}
            for d in (report.get("patient") or {}).get("drug") or []
        )
    )
    tables = tables_in_memory([source])

    empty = [
        key
        for key, block in tables.openfda.items()
        if not {
            name: value
            for name, value in block.items()
            if name != "openfda_key" and value is not None
        }
    ]

    assert empty, (
        "the fixture's `openfda: {}` never reached dim_openfda. If "
        "`OpenfdaDimension.add` is testing the block for truthiness instead of "
        "`is not None`, that IS the L-005 bug and this is the test saying so."
    )
    empty_key = empty[0]

    for row in tables.drugs[ordinal]:
        if row.get("openfda_key") == empty_key:
            row["openfda_key"] = None

    del tables.openfda[empty_key]

    found = differences(source, reconstruct(tables, ordinal))

    assert found, "the falsy-openfda bug went undetected — this test is the reason"
    assert any("openfda" in difference for difference in found), found[:5]


def test_an_unknown_ordinal_says_so(sample):
    with pytest.raises(UnknownReport, match="999"):
        reconstruct(tables_in_memory(sample), 999)


def test_a_gap_in_seq_is_not_quietly_shortened(sample):
    source = next(
        r for r in sample if len((r.get("patient") or {}).get("drug") or []) >= 3
    )
    tables = tables_in_memory([source])
    tables.drugs[1].pop(1)

    with pytest.raises(BrokenTables, match="seq"):
        reconstruct(tables, 1)


def test_a_duplicate_that_is_both_shapes_at_once_raises(sample):
    source = next(r for r in sample if isinstance(r.get("reportduplicate"), list))
    tables = tables_in_memory([source])
    tables.duplicates[1][0]["seq"] = None

    with pytest.raises(BrokenTables, match="null"):
        reconstruct(tables, 1)


def test_a_drug_pointing_at_a_missing_block_raises(sample):
    source = next(
        r
        for r in sample
        if any("openfda" in d for d in (r.get("patient") or {}).get("drug") or [])
    )
    tables = tables_in_memory([source])
    tables.openfda.clear()

    with pytest.raises(BrokenTables, match="openfda_key"):
        reconstruct(tables, 1)


@pytest.mark.slow
@pytest.mark.parametrize("partition_id", partitions_under_test())
def test_the_whole_partition_rebuilds_from_parquet(partition_id):
    archive, parquet, schema_path = artifacts_of(partition_id)

    missing = [
        path
        for path in (archive, parquet / "report.parquet", schema_path)
        if not path.exists()
    ]
    assert not missing, (
        f"{partition_id}: falta {', '.join(str(path) for path in missing)}. "
        f"Rode `make ingest PARTITION={partition_id}` antes."
    )

    declared = json.loads(schema_path.read_text())["source"]["records"]

    tables = Tables.load(parquet)
    compared = mismatched = 0
    first_failure = ""

    for ordinal, source in enumerate(iter_reports(archive), start=1):
        compared += 1
        assert not explicit_nulls(source), (
            f"{partition_id}: o relato {source['safetyreportid']} carrega um null "
            f"explicito — o sentido da comparacao do round trip muda aqui (L-008)"
        )

        found = differences(source, reconstruct(tables, ordinal))

        if found:
            mismatched += 1
            first_failure = first_failure or (
                f"safetyreportid {source['safetyreportid']}: {found[:10]}"
            )

    print(f"\n{partition_id}: {compared - mismatched:,}/{compared:,} byte-identical")

    assert mismatched == 0, (
        f"{partition_id}: {mismatched:,} de {compared:,} diferem. "
        f"Primeiro: {first_failure}"
    )
    assert compared == declared, (
        f"{partition_id}: li {compared:,} relatos do zip, "
        f"e o manifesto fixado declara {declared:,}"
    )


def tables_with_reports(*identifiers: str) -> Tables:
    rows = {table: [] for table in TABLES}
    rows["report"] = [
        {"safetyreportid": identifier, "ordinal": position}
        for position, identifier in enumerate(identifiers, start=1)
    ]

    return Tables.from_rows(rows)


def test_two_reports_under_one_safetyreportid_are_two_reports():
    tables = tables_with_reports("1", "1")

    assert tables.ordinals == [1, 2]
    assert reconstruct(tables, 1) == {"safetyreportid": "1"}
    assert reconstruct(tables, 2) == {"safetyreportid": "1"}


def test_three_rows_under_one_id_are_still_three_reports():
    assert tables_with_reports("1", "1", "1").ordinals == [1, 2, 3]


def test_distinct_report_ids_still_load():
    assert tables_with_reports("1", "2").ordinals == [1, 2]


def test_a_repeated_ordinal_is_the_writer_breaking_its_contract():
    rows = {table: [] for table in TABLES}
    rows["report"] = [
        {"safetyreportid": "1", "ordinal": 7},
        {"safetyreportid": "2", "ordinal": 7},
    ]

    with pytest.raises(BrokenTables, match="ordinal"):
        Tables.from_rows(rows)
