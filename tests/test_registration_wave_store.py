from __future__ import annotations

import copy
from pathlib import Path

import pytest
from test_registration_wave_authority import verified_approval
from test_registration_wave_contracts import (
    valid_recovery_receipt,
    valid_slot_receipt,
    valid_slot_request,
    valid_synthetic_recovery_result,
    valid_synthetic_result,
)
from test_registration_wave_intake import (
    CountingIdsFactory,
    claim,
    context,
    host,
    ids,
    item,
    raw_item,
)

from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.registration_wave_context import (
    SYNTHETIC_MARKER_NAME,
    SyntheticWaveExecutionContext,
    WaveEffectJournal,
    WaveExecutionMode,
)
from sedb_ral.registration_wave_intake import prepare_wave_candidate
from sedb_ral.registration_wave_models import (
    SyntheticWaveSlotExecutionResult,
    SyntheticWaveSlotRecoveryResult,
    WaveSlotReceipt,
    WaveSlotRecoveryReceipt,
    WaveSlotRequest,
)
from sedb_ral.registration_wave_store import RegistrationWaveStore


def digest(label: str) -> str:
    return sha256_ref({"fixture": label})


def store_context(tmp_path: Path):
    return context(tmp_path)


def verified_candidate(tmp_path):
    return prepare_wave_candidate(
        store_context(tmp_path),
        claim(),
        item(),
        host(),
        raw_item(),
        CountingIdsFactory(ids()),
    )


def test_synthetic_store_creates_only_closed_layout_and_manifest(tmp_path):
    selected_context = store_context(tmp_path)
    store = RegistrationWaveStore(
        selected_context, selected_context.target_root, digest("wave")
    )

    report = store.verify()

    assert report["verified"] is True
    assert report["mode"] == "synthetic_test"
    assert report["record_count"] == 0
    assert store.read_manifest()["expected_wave_digest"] == digest("wave")


def test_real_staging_mode_refuses_temp_root(tmp_path):
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    marker = {
        "schema": "sedb-ral.synthetic-wave-fixture-marker/0.1",
        "fixture_marker_ref": "fixture:real-staging",
        "not_claimed": ["production_root", "real_applicant", "private_access"],
    }
    (fixture_root / SYNTHETIC_MARKER_NAME).write_bytes(canonical_bytes(marker))
    target = tmp_path / "candidate"
    selected_context = SyntheticWaveExecutionContext.sealed(
        mode=WaveExecutionMode.REAL_STAGING_CANDIDATE,
        fixture_root=fixture_root,
        target_root=target,
        fixture_marker_ref=str(marker["fixture_marker_ref"]),
        fixture_marker_digest=sha256_ref(marker),
        forbidden_roots=(),
        journal=WaveEffectJournal(),
    )

    with pytest.raises(RALValidationError, match="wave_staging_root_refused"):
        RegistrationWaveStore(selected_context, target, digest("wave"))


def test_same_id_same_bytes_is_duplicate_changed_bytes_quarantine(tmp_path):
    selected_context = store_context(tmp_path)
    store = RegistrationWaveStore(
        selected_context, selected_context.target_root, digest("wave")
    )
    first = claim()

    created = store.put_claim("slot:1", first)
    duplicate = store.put_claim("slot:1", copy.deepcopy(first))
    changed = copy.deepcopy(first)
    changed["role_description_claim"] = "Changed role"

    assert created.kind == "created"
    assert duplicate.kind == "duplicate"
    with pytest.raises(RALValidationError, match="wave_staging_digest_conflict"):
        store.put_claim("slot:1", changed)
    assert len(tuple((store.root / "quarantine").glob("*.json"))) == 1
    assert store.put_claim("slot:1", first).kind == "duplicate"


def test_candidate_requires_verified_capability_and_manifest_stays_sanitized(tmp_path):
    selected_context = store_context(tmp_path)
    store = RegistrationWaveStore(
        selected_context, selected_context.target_root, digest("wave")
    )
    candidate = verified_candidate(tmp_path / "candidate")

    with pytest.raises(RALValidationError, match="verified_candidate_required"):
        store.put_candidate("slot:1", candidate.candidate)
    store.put_candidate("slot:1", candidate)

    manifest_bytes = (store.root / "STORE-MANIFEST.json").read_bytes()
    assert candidate.canonical_locator.encode("utf-8") not in manifest_bytes
    assert candidate.verified_item.host.native_turn_id.encode("utf-8") not in manifest_bytes
    assert store.verify()["record_count"] == 1


def test_synthetic_result_paths_reject_production_receipt_types(tmp_path):
    selected_context = store_context(tmp_path)
    store = RegistrationWaveStore(
        selected_context, selected_context.target_root, digest("wave")
    )

    with pytest.raises(RALValidationError, match="synthetic_result_type_required"):
        store.put_slot_result(
            "slot:1", WaveSlotReceipt.from_dict(valid_slot_receipt())
        )
    with pytest.raises(RALValidationError, match="synthetic_result_type_required"):
        store.put_recovery_result(
            "slot:1", WaveSlotRecoveryReceipt.from_dict(valid_recovery_receipt())
        )

    assert (
        store.put_slot_result(
            "slot:1",
            SyntheticWaveSlotExecutionResult.from_dict(valid_synthetic_result()),
        ).kind
        == "created"
    )
    assert (
        store.put_recovery_result(
            "slot:1",
            SyntheticWaveSlotRecoveryResult.from_dict(
                valid_synthetic_recovery_result()
            ),
        ).kind
        == "created"
    )


def test_request_and_verified_approval_are_create_only(tmp_path):
    selected_context = store_context(tmp_path)
    store = RegistrationWaveStore(
        selected_context, selected_context.target_root, digest("wave")
    )
    request = WaveSlotRequest.from_dict(valid_slot_request())
    approval, _, _ = verified_approval(tmp_path / "approval")

    assert store.put_slot_request("slot:1", request).kind == "created"
    assert store.put_approval("slot:1", approval).kind == "created"
    assert store.put_slot_request("slot:1", request).kind == "duplicate"
    assert store.put_approval("slot:1", approval).kind == "duplicate"


def test_record_tamper_turns_verify_red(tmp_path):
    selected_context = store_context(tmp_path)
    store = RegistrationWaveStore(
        selected_context, selected_context.target_root, digest("wave")
    )
    result = store.put_claim("slot:1", claim())
    path = store.root / result.relative_ref
    path.write_bytes(canonical_bytes({"tampered": True}))

    with pytest.raises(RALValidationError, match="wave_store_record_invalid"):
        store.verify()


def test_identifier_text_cannot_escape_store_paths(tmp_path):
    selected_context = store_context(tmp_path)
    store = RegistrationWaveStore(
        selected_context, selected_context.target_root, digest("wave")
    )

    result = store.put_claim("../../outside", claim())

    assert (store.root / result.relative_ref).is_file()
    assert (store.root / result.relative_ref).resolve().is_relative_to(
        store.root.resolve()
    )


def test_unexpected_file_turns_exact_layout_red(tmp_path):
    selected_context = store_context(tmp_path)
    store = RegistrationWaveStore(
        selected_context, selected_context.target_root, digest("wave")
    )
    (store.root / "unexpected.bin").write_bytes(b"unexpected")

    with pytest.raises(RALValidationError, match="wave_store_layout_invalid"):
        store.verify()


def test_quarantine_digest_is_verified(tmp_path):
    selected_context = store_context(tmp_path)
    store = RegistrationWaveStore(
        selected_context, selected_context.target_root, digest("wave")
    )
    store.put_claim("slot:1", claim())
    changed = claim()
    changed["role_description_claim"] = "Changed role"
    with pytest.raises(RALValidationError, match="wave_staging_digest_conflict"):
        store.put_claim("slot:1", changed)
    quarantine = next((store.root / "quarantine").glob("*.json"))
    quarantine.write_bytes(canonical_bytes({"tampered": True}))

    with pytest.raises(RALValidationError, match="wave_store_quarantine_invalid"):
        store.verify()
