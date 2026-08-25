import json
import re
from pathlib import Path

from test_phase3_registrar_plan import CTCL, VERIFIED
from test_phase3_registration_admission import authority_for, empty_projection
from test_phase3_registration_prepare import (
    IDS,
    valid_claim,
    valid_host_observation,
)

from sedb_ral.canonical import canonical_bytes
from sedb_ral.cli import main
from sedb_ral.registrar import build_admission_plan
from sedb_ral.registration import prepare_registration
from sedb_ral.registration_admission import evaluate_prepared_registration


def write_json(path: Path, value: object) -> Path:
    path.write_bytes(canonical_bytes(value))
    return path


def cli_inputs(tmp_path):
    claim_value = valid_claim()
    host_value = valid_host_observation()
    ids_value = {
        "prepared_id": IDS.prepared_id,
        "application_id": IDS.application_id,
        "resident_id": IDS.resident_id,
        "instance_id": IDS.instance_id,
        "continuity_line_id": IDS.continuity_line_id,
        "address_ids": list(IDS.address_ids),
        "claim_ids": list(IDS.claim_ids),
    }
    return (
        write_json(tmp_path / "claim.json", claim_value),
        write_json(tmp_path / "host.json", host_value),
        write_json(tmp_path / "ids.json", ids_value),
        claim_value,
        host_value,
    )


def registrar_inputs(tmp_path):
    prepared = prepare_registration(
        valid_claim(), valid_host_observation(), IDS
    )
    authority = authority_for(prepared)
    decision = evaluate_prepared_registration(
        prepared,
        [authority],
        verified_attestation_refs=VERIFIED,
        projection=empty_projection(),
    )
    paths = {
        "prepared": write_json(
            tmp_path / "prepared.json", prepared.to_dict()
        ),
        "decision": write_json(
            tmp_path / "decision.json", decision.to_dict()
        ),
        "authority": write_json(tmp_path / "authority.json", authority),
        "ctcl": write_json(tmp_path / "ctcl.json", CTCL),
        "refs": write_json(tmp_path / "refs.json", sorted(VERIFIED)),
    }
    return prepared, authority, decision, paths


def test_P3_022_prepare_cli_matches_direct_core_bytes(tmp_path, capfd):
    claim, host, ids, claim_value, host_value = cli_inputs(tmp_path)

    code = main(
        [
            "application",
            "prepare",
            str(claim),
            str(host),
            "--ids",
            str(ids),
        ]
    )

    assert code == 0
    emitted = json.loads(capfd.readouterr().out)
    assert canonical_bytes(emitted) == canonical_bytes(
        prepare_registration(claim_value, host_value, IDS).to_dict()
    )


def test_prepare_cli_generated_ids_are_opaque_and_stable_in_one_output(
    tmp_path, capfd
):
    claim, host, _, _, _ = cli_inputs(tmp_path)

    assert main(["application", "prepare", str(claim), str(host)]) == 0
    value = json.loads(capfd.readouterr().out)

    application = value["application"]
    identifiers = [
        value["prepared_id"],
        application["application_id"],
        application["claimed_resident_id"],
        application["instance_claims"][0]["instance_id"],
        value["continuity_line_id"],
        *(item["address_id"] for item in application["addresses"]),
        *(item["claim_id"] for item in application["claims"]),
    ]
    assert len(identifiers) == len(set(identifiers))
    assert all("syntheticresident" not in re.sub(r"\W", "", item).lower() for item in identifiers)


def test_prepare_output_never_overwrites_existing_file(tmp_path, capfd):
    claim, host, ids, _, _ = cli_inputs(tmp_path)
    output = tmp_path / "prepared.json"
    output.write_bytes(b"keep")

    code = main(
        [
            "application",
            "prepare",
            str(claim),
            str(host),
            "--ids",
            str(ids),
            "--output",
            str(output),
        ]
    )

    assert code == 2
    assert output.read_bytes() == b"keep"
    payload = json.loads(capfd.readouterr().out)
    assert payload["reason_codes"] == ["output_exists"]
    assert str(output) not in json.dumps(payload)


def test_prepare_malformed_json_is_typed_without_path_or_stack(tmp_path, capfd):
    claim = tmp_path / "malformed.json"
    claim.write_text("{", encoding="utf-8")
    host = write_json(tmp_path / "host.json", valid_host_observation())

    assert main(["application", "prepare", str(claim), str(host)]) == 1
    output = capfd.readouterr().out
    payload = json.loads(output)
    assert payload["reason_codes"] == ["input_invalid_json"]
    assert str(claim) not in output
    assert "Traceback" not in output


def test_application_digest_and_human_explain_are_explicit(tmp_path, capfd):
    prepared, _, _, paths = registrar_inputs(tmp_path)

    assert main(["application", "digest", str(paths["prepared"])]) == 0
    digest = json.loads(capfd.readouterr().out)
    assert digest["application_digest"] == prepared.application_digest

    assert main(["application", "explain", str(paths["prepared"])]) == 0
    human = json.loads(capfd.readouterr().out)
    assert human["canonical_approval_artifact"] is False
    assert human["human_view"] is True
    assert human["prepared_digest"] == prepared.digest
    assert "private_access" in human["not_claimed"]


def test_registrar_plan_cli_matches_direct_core_bytes(tmp_path, capfd):
    prepared, authority, decision, paths = registrar_inputs(tmp_path)
    canonical = tmp_path / "canonical"
    expected = build_admission_plan(
        canonical,
        prepared,
        decision,
        authority,
        CTCL,
        expected_head=None,
        verified_attestation_refs=VERIFIED,
        staging_parent=tmp_path / "direct-stage",
    )

    code = main(
        [
            "registrar",
            "plan",
            str(paths["prepared"]),
            str(paths["decision"]),
            str(paths["authority"]),
            "--ctcl-receipt",
            str(paths["ctcl"]),
            "--verified-attestation-refs",
            str(paths["refs"]),
            "--ledger-root",
            str(canonical),
            "--expected-head",
            "GENESIS",
            "--staging-parent",
            str(tmp_path / "cli-stage"),
        ]
    )

    assert code == 0
    emitted = json.loads(capfd.readouterr().out)
    assert canonical_bytes(emitted) == canonical_bytes(expected.to_dict())
    assert not canonical.exists()


def test_registrar_admit_requires_expected_head_and_exact_files(capfd):
    assert main(["registrar", "admit"]) == 2
    payload = json.loads(capfd.readouterr().out)
    assert payload["reason_codes"] == ["cli_usage_error"]


def test_registrar_plan_missing_authority_or_unverified_attestation_refuses(
    tmp_path, capfd
):
    _, _, _, paths = registrar_inputs(tmp_path)
    empty_refs = write_json(tmp_path / "empty-refs.json", [])
    args = [
        "registrar",
        "plan",
        str(paths["prepared"]),
        str(paths["decision"]),
        str(paths["authority"]),
        "--ctcl-receipt",
        str(paths["ctcl"]),
        "--verified-attestation-refs",
        str(empty_refs),
        "--ledger-root",
        str(tmp_path / "canonical"),
        "--expected-head",
        "GENESIS",
        "--staging-parent",
        str(tmp_path / "stage"),
    ]

    assert main(args) == 2
    payload = json.loads(capfd.readouterr().out)
    assert payload["reason_codes"] == ["registration_decision_stale"]
    assert not (tmp_path / "canonical").exists()


def test_registrar_admit_and_status_use_exact_plan_and_head(tmp_path, capfd):
    prepared, _, _, paths = registrar_inputs(tmp_path)
    canonical = tmp_path / "canonical"
    common = [
        str(paths["prepared"]),
        str(paths["decision"]),
        str(paths["authority"]),
        "--ctcl-receipt",
        str(paths["ctcl"]),
        "--verified-attestation-refs",
        str(paths["refs"]),
        "--ledger-root",
        str(canonical),
        "--expected-head",
        "GENESIS",
    ]
    assert (
        main(
            [
                "registrar",
                "plan",
                *common,
                "--staging-parent",
                str(tmp_path / "stage"),
            ]
        )
        == 0
    )
    plan_value = json.loads(capfd.readouterr().out)
    plan_path = write_json(tmp_path / "plan.json", plan_value)

    assert main(["registrar", "admit", str(plan_path), *common]) == 0
    receipt = json.loads(capfd.readouterr().out)
    assert receipt["committed"] is True
    assert receipt["idempotent"] is False
    assert receipt["prepared_digest"] == prepared.digest

    assert (
        main(
            [
                "registrar",
                "status",
                prepared.application_digest,
                "--ledger-root",
                str(canonical),
                "--expected-head",
                receipt["final_head"],
            ]
        )
        == 0
    )
    status = json.loads(capfd.readouterr().out)
    assert status["registration_status"] == "complete"
    assert status["checkpoint_verified"] is True
    assert status["final_head"] == receipt["final_head"]


def test_registrar_wrong_head_is_typed_and_does_not_create_staging(
    tmp_path, capfd
):
    _, _, _, paths = registrar_inputs(tmp_path)
    stage = tmp_path / "stage"

    code = main(
        [
            "registrar",
            "plan",
            str(paths["prepared"]),
            str(paths["decision"]),
            str(paths["authority"]),
            "--ctcl-receipt",
            str(paths["ctcl"]),
            "--verified-attestation-refs",
            str(paths["refs"]),
            "--ledger-root",
            str(tmp_path / "canonical"),
            "--expected-head",
            "sha256:sedb-ral-chain-v1:" + "0" * 64,
            "--staging-parent",
            str(stage),
        ]
    )

    assert code == 2
    payload = json.loads(capfd.readouterr().out)
    assert payload["reason_codes"] == ["external_anchor_mismatch"]
    assert not stage.exists()
