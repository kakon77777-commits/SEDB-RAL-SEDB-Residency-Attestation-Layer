import json
import shutil
from pathlib import Path

from scripts.build_manifest import verify_phase1a_checkpoint
from sedb_ral.phase1a import validate_phase1a

ROOT = Path(__file__).parents[1]


def copy_gate_inputs(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(
        ROOT / "src/sedb_ral/schemas",
        target / "src/sedb_ral/schemas",
    )
    shutil.copytree(ROOT / "fixtures", target / "fixtures")
    return target


def test_phase1a_checkpoint_reads_the_immutable_git_tree():
    assert verify_phase1a_checkpoint(ROOT) == ()
    checkpoint = json.loads(
        (ROOT / "PHASE1A_CHECKPOINT.json").read_text(encoding="utf-8")
    )
    assert checkpoint["checkpoint_commit"] == (
        "99efef01858993274de2c66bd53073f4a794946e"
    )


def test_phase1a_gate_allows_later_schema_files(tmp_path):
    target = copy_gate_inputs(tmp_path)
    (target / "src/sedb_ral/schemas/application.schema.json").write_text(
        """{
          "$schema":"https://json-schema.org/draft/2020-12/schema",
          "$id":"https://evemisslab.com/schemas/sedb-ral/application.schema.json",
          "type":"object"
        }""",
        encoding="utf-8",
    )
    assert validate_phase1a(target).passed is True


def test_phase1a_gate_still_rejects_a_missing_required_schema(tmp_path):
    target = copy_gate_inputs(tmp_path)
    (target / "src/sedb_ral/schemas/ledger-event.schema.json").unlink()
    report = validate_phase1a(target)
    assert report.passed is False
    assert "schema_set_mismatch" in report.error_codes
