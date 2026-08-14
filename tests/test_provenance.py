import json
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


def test_the_published_partition_has_a_committed_pin(published):
    path = PIN_DIR / f"{stem(published['partition'])}.json"

    assert path.exists(), (
        f"{path} não existe. A página publicada cita uma partição sem pin "
        f"versionado, entao ninguém consegue refazer o download que a produziu."
    )


def test_the_published_export_date_matches_the_pin(published):
    pin = json.loads((PIN_DIR / f"{stem(published['partition'])}.json").read_text())

    assert pin["export_date"] == published["export_date"], (
        f"a página diz export {published['export_date']} e o pin diz "
        f"{pin['export_date']}. Uma das duas foi regerada sem a outra."
    )


def test_the_published_partition_has_a_committed_schema(published):
    path = SCHEMA_DIR / f"{stem(published['partition'])}.json"

    assert path.exists(), f"{path} não existe."

    source = json.loads(path.read_text())["source"]

    assert source["partition"] == published["partition"]
    assert source["export_date"] == published["export_date"]


def test_a_header_without_the_partition_is_refused(tmp_path):
    path = tmp_path / "prr_top.csv"
    path.write_text('# hindsight\n"drug","event"\n"A","B"\n')

    with pytest.raises(PrrError, match="partition"):
        provenance(path)


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(PrrError):
        provenance(tmp_path / "ausente.csv")
