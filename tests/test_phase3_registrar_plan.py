import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_phase3_registration_admission import (
    VERIFIED,
    authority_for,
    empty_projection,
    prepared_registration,
)

from sedb_ral.errors import RALValidationError
from sedb_ral.ledger import read_verified_events, verify_ledger
from sedb_ral.projection import project_events
from sedb_ral.registrar import build_admission_plan, commit_admission_plan
from sedb_ral.registration_admission import evaluate_prepared_registration

ROOT = Path(__file__).parents[1]
CTCL = json.loads(
    (ROOT / "fixtures/ctcl/registered-anchor.json").read_text(
        encoding="utf-8"
    )
)


def accepted_inputs():
    prepared = prepared_registration()
    authority = authority_for(prepared)
    decision = evaluate_prepared_registration(
        prepared,
        [authority],
        verified_attestation_refs=VERIFIED,
        projection=empty_projection(),
    )
    return prepared, authority, decision


def build_plan(tmp_path, *, canonical=None, expected_head=None):
    prepared, authority, decision = accepted_inputs()
    canonical = canonical or tmp_path / "canonical"
    plan = build_admission_plan(
        canonical,
        prepared,
        decision,
        authority,
        CTCL,
        expected_head=expected_head,
        verified_attestation_refs=VERIFIED,
        staging_parent=tmp_path / "staging",
    )
    return canonical, prepared, authority, decision, plan


def test_P3_016_staging_builds_candidate_without_canonical_write(tmp_path):
    canonical, prepared, _, _, plan = build_plan(tmp_path)

    assert plan.candidate_event_ids[-1].startswith(
        "evt_resident_registered_"
    )
    assert plan.candidate_head.startswith("sha256:sedb-ral-chain-v1:")
    assert plan.source_head is None
    assert plan.prepared_digest == prepared.digest
    assert plan.application_digest == prepared.application_digest
    assert plan.to_dict()["plan_digest"] == plan.digest
    assert not canonical.exists()
    assert not list((tmp_path / "staging").iterdir())


def test_staged_plan_commits_exact_candidate_and_projection(tmp_path):
    canonical, prepared, authority, decision, plan = build_plan(tmp_path)

    receipt = commit_admission_plan(
        canonical,
        plan,
        prepared,
        decision,
        authority,
        CTCL,
        verified_attestation_refs=VERIFIED,
    )

    assert receipt.committed is True
    assert receipt.idempotent is False
    assert receipt.source_head is None
    assert receipt.final_head == plan.candidate_head
    assert receipt.event_ids == plan.candidate_event_ids
    assert receipt.projection_digest == plan.projection_digest
    verification = verify_ledger(
        canonical, expected_final_chain_digest=receipt.final_head
    )
    assert verification.valid is True
    events = read_verified_events(canonical, receipt.final_head)
    projection = project_events(events)
    assert projection.unapplied_event_ids == ()
    assert prepared.application["claimed_resident_id"] in projection.residents


def test_P3_017_wrong_expected_head_refuses_before_staging(tmp_path):
    canonical, prepared, authority, decision, plan = build_plan(tmp_path)
    receipt = commit_admission_plan(
        canonical,
        plan,
        prepared,
        decision,
        authority,
        CTCL,
        verified_attestation_refs=VERIFIED,
    )
    event_bytes = {
        path.relative_to(canonical).as_posix(): path.read_bytes()
        for path in canonical.rglob("*.json")
    }

    with pytest.raises(RALValidationError, match="external_anchor_mismatch"):
        build_admission_plan(
            canonical,
            prepared,
            decision,
            authority,
            CTCL,
            expected_head="sha256:sedb-ral-chain-v1:" + "0" * 64,
            verified_attestation_refs=VERIFIED,
            staging_parent=tmp_path / "wrong-head-stage",
        )

    assert receipt.final_head == plan.candidate_head
    assert event_bytes == {
        path.relative_to(canonical).as_posix(): path.read_bytes()
        for path in canonical.rglob("*.json")
    }
    assert not (tmp_path / "wrong-head-stage").exists()


@pytest.mark.parametrize(
    "mutation",
    ["prepared", "decision", "authority", "ctcl"],
)
def test_build_revalidates_each_input_before_canonical_write(
    tmp_path, mutation
):
    prepared, authority, decision = accepted_inputs()
    ctcl = copy.deepcopy(CTCL)
    if mutation == "prepared":
        prepared.application["display_label"] = "Tampered"
    elif mutation == "decision":
        decision = replace(decision, reason_codes=("tampered",))
    elif mutation == "authority":
        authority["subject_ref"] = "sha256:wrong"
    else:
        ctcl["ctcl_call_kind"] = "reading"
    canonical = tmp_path / "canonical"

    with pytest.raises(RALValidationError):
        build_admission_plan(
            canonical,
            prepared,
            decision,
            authority,
            ctcl,
            expected_head=None,
            verified_attestation_refs=VERIFIED,
            staging_parent=tmp_path / "staging",
        )

    assert not canonical.exists()


def test_commit_rejects_mutated_plan_before_canonical_write(tmp_path):
    canonical, prepared, authority, decision, plan = build_plan(tmp_path)
    changed = replace(
        plan,
        candidate_event_ids=tuple(reversed(plan.candidate_event_ids)),
    )

    with pytest.raises(
        RALValidationError, match="registrar_plan_digest_mismatch"
    ):
        commit_admission_plan(
            canonical,
            changed,
            prepared,
            decision,
            authority,
            CTCL,
            verified_attestation_refs=VERIFIED,
        )

    assert not canonical.exists()


def test_commit_rejects_input_changed_after_staging(tmp_path):
    canonical, prepared, authority, decision, plan = build_plan(tmp_path)
    changed_authority = copy.deepcopy(authority)
    changed_authority["issued_time_ref"] = "ctcl:instant:changed"

    with pytest.raises(RALValidationError, match="registrar_input_stale"):
        commit_admission_plan(
            canonical,
            plan,
            prepared,
            decision,
            changed_authority,
            CTCL,
            verified_attestation_refs=VERIFIED,
        )

    assert not canonical.exists()
