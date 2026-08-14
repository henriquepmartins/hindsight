import json
import re
from pathlib import Path

import pytest

from hindsight.analysis.export import PROVENANCE, provenance
from hindsight.analysis.prr import PrrError


ROOT = Path(__file__).parent.parent

PUBLISHED_CSV = ROOT / "reports" / "data" / "prr_top.csv"
PIN_DIR = ROOT / "data" / "manifest"
SCHEMA_DIR = ROOT / "schema"


def stem(partition_id: str) -> str:
    return partition_id.replace("/", "-")


@pytest.fixture(scope="module")
def published() -> dict[str, str]:
    return provenance(PUBLISHED_CSV)


def test_the_published_csv_names_the_partition_behind_it(published):
    assert set(published) == set(PROVENANCE)
    assert re.fullmatch(r"\d{4}q[1-4]/\d{4}-of-\d{4}", published["partition"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", published["export_date"])
    assert published["min_count"].isdigit() and int(published["min_count"]) >= 1


def test_the_published_partition_has_a_committed_pin(published):
    path = PIN_DIR / f"{stem(published['partition'])}.json"

    assert path.exists(), (
        f"{path} não existe. A página publicada cita uma partição sem pin "
        f"versionado, entao ninguém consegue refazer o download que a produziu."
    )


def test_the_published_export_date_matches_the_pin(published):
    pin = json.loads((PIN_DIR / f"{stem(published['partition'])}.json").read_text(encoding="utf-8"))

    assert pin["export_date"] == published["export_date"], (
        f"a página diz export {published['export_date']} e o pin diz "
        f"{pin['export_date']}. Uma das duas foi regerada sem a outra."
    )


def test_the_published_partition_has_a_committed_schema(published):
    path = SCHEMA_DIR / f"{stem(published['partition'])}.json"

    assert path.exists(), f"{path} não existe."

    source = json.loads(path.read_text(encoding="utf-8"))["source"]

    assert source["partition"] == published["partition"]
    assert source["export_date"] == published["export_date"]


def header(**named: str) -> str:
    lines = "".join(f"# {name}: {value}\n" for name, value in named.items())

    return f"# hindsight\n{lines}" + '"drug","event"\n"A","B"\n'


def test_a_header_missing_only_the_partition_is_refused(tmp_path):
    path = tmp_path / "prr_top.csv"
    path.write_text(header(export_date="2026-08-10", min_count="3"), encoding="utf-8")

    with pytest.raises(PrrError, match="partition"):
        provenance(path)


def test_a_header_with_no_provenance_at_all_names_all_three(tmp_path):
    path = tmp_path / "prr_top.csv"
    path.write_text(header(), encoding="utf-8")

    with pytest.raises(PrrError, match="export_date.*min_count.*partition"):
        provenance(path)


def test_a_key_present_with_an_empty_value_is_not_a_value(tmp_path):
    path = tmp_path / "prr_top.csv"
    path.write_text(
        header(partition="", export_date="2026-08-10", min_count="3"),
        encoding="utf-8",
    )

    with pytest.raises(PrrError, match="partition"):
        provenance(path)


def test_a_value_containing_the_comment_marker_survives(tmp_path):
    path = tmp_path / "prr_top.csv"
    path.write_text(
        header(partition="2025q1/0001-of-0028 # recortada", export_date="2026-08-10",
               min_count="3"),
        encoding="utf-8",
    )

    assert provenance(path)["partition"] == "2025q1/0001-of-0028 # recortada"


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(PrrError):
        provenance(tmp_path / "ausente.csv")


def test_a_directory_is_refused_as_such(tmp_path):
    with pytest.raises(PrrError, match="não é um arquivo"):
        provenance(tmp_path)
