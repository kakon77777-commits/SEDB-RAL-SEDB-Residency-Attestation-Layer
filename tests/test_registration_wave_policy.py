from __future__ import annotations

import copy
from pathlib import Path

import pytest
from test_production_operations_layout import (
    install_extension,
    write_fixture_activation_receipt,
)
from test_registration_wave_authority import (
    PRINCIPAL_REF,
    approval_artifact,
    approval_intent,
    principal_host,
    raw_principal_item,
    time_evidence,
)
from test_registration_wave_plan import candidates, checkpoint, policy
from test_registry_root import ready_storage

import sedb_ral.registration_wave_policy as policy_module
from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.registration_wave_authority import (
    PrincipalHostObservation,
    RawPrincipalItemSnapshot,
    VerifiedApplicationApproval,
    verify_application_approval,
)
from sedb_ral.registration_wave_context import (
    SYNTHETIC_MARKER_NAME,
    SyntheticWaveExecutionContext,
    WaveEffectJournal,
    WaveExecutionMode,
)
from sedb_ral.registration_wave_models import (
    WavePolicyActivationAuthority,
    WaveTerminalEvent,
)
from sedb_ral.registration_wave_plan import build_wave_plan
from sedb_ral.registration_wave_policy import (
    InjectedWavePolicyCrash,
    VerifiedWavePolicyTerminalAuthority,
    activate_wave_policy,
    activation_receipt_path,
    plan_wave_policy_activation,
    registration_wave_status,
    require_wave_execution,
    terminate_wave_policy,
    verify_wave_policy_activation_authority,
    verify_wave_policy_terminal_authority,
)
from sedb_ral.registry_root import (
    prepare_registry_candidate,
    publish_registry_candidate,
    registry_root_status,
    verify_registry_candidate,
)


def digest(label: str) -> str:
    return sha256_ref({"fixture": label})


@pytest.fixture
def published_storage(tmp_path):
    storage, root_plan, authority, parent_acl, candidate_acl = ready_storage(tmp_path)
    prepare_registry_candidate(
        root_plan, authority, parent_acl, candidate_acl, storage=storage
    )
    verification = verify_registry_candidate(
        root_plan, authority, parent_acl, candidate_acl, storage=storage
    )
    publish_registry_candidate(root_plan, verification, storage=storage)
    return storage


def policy_time(now: int = 200):
    return type(time_evidence())(
        now_ref="time:policy-now",
        now_epoch_ns=now,
        valid_from_ref="ctcl:instant:policy-start",
        valid_from_epoch_ns=100,
        expires_at_ref="ctcl:instant:policy-end",
        expires_at_epoch_ns=300,
        source_ref="clock:synthetic-policy",
        source_digest=digest("policy-clock"),
    )


def install_active_dormant(storage):
    extension_plan, index = install_extension(storage)
    unreceipted = registry_root_status(storage=storage)
    write_fixture_activation_receipt(
        storage,
        extension_plan,
        index,
        unreceipted["registry_generation_digest"],
    )
    assert registry_root_status(storage=storage)["extensions_status"] == "active_dormant"
    return extension_plan, index


def wave_context(tmp_path: Path, storage, journal=None):
    marker = {
        "schema": "sedb-ral.synthetic-wave-fixture-marker/0.1",
        "fixture_marker_ref": "fixture:wave-policy",
        "not_claimed": ["production_root", "real_applicant", "private_access"],
    }
    (tmp_path / SYNTHETIC_MARKER_NAME).write_bytes(canonical_bytes(marker))
    return SyntheticWaveExecutionContext.sealed(
        mode=WaveExecutionMode.SYNTHETIC_TEST,
        fixture_root=tmp_path,
        target_root=storage.final,
        fixture_marker_ref=str(marker["fixture_marker_ref"]),
        fixture_marker_digest=sha256_ref(marker),
        forbidden_roots=(),
        journal=journal or WaveEffectJournal(),
    )


def verified_approvals(tmp_path, selected_candidates) -> tuple[VerifiedApplicationApproval, ...]:
    observed = []
    for index, candidate in enumerate(selected_candidates, start=1):
        application = candidate.prepared.application
        intent = approval_intent(application)
        raw = raw_principal_item(
            intent,
            item_ref=f"user-item:approval-{index}",
            turn_id=f"turn:approval-{index}",
        )
        host = principal_host(raw)
        artifact_value = approval_artifact(application, raw, host).to_dict()
        artifact_value["approval_id"] = f"approval:slot-{index}"
        artifact = type(approval_artifact(application, raw, host)).sealed(artifact_value)
        observed.append(
            verify_application_approval(
                artifact,
                application,
                raw,
                host,
                expected_principal_ref=PRINCIPAL_REF,
                time=time_evidence(),
            )
        )
    return tuple(observed)


def activation_intent(selected_plan, request):
    return {
        "schema": "sedb-ral.registration-wave-policy-activation-intent/0.1",
        "principal_ref": PRINCIPAL_REF,
        "request_ref": request.request_id,
        "request_digest": request.digest,
        "policy_ref": selected_plan.policy_ref,
        "policy_digest": selected_plan.policy_digest,
        "target_ref": "registrar-operations:synthetic",
        "operation": "registration.wave-policy.activate",
    }


def activation_authority_artifact(
    selected_plan,
    request,
    raw: RawPrincipalItemSnapshot,
    host: PrincipalHostObservation,
):
    return WavePolicyActivationAuthority.sealed(
        {
            "schema": "sedb-ral.registration-wave-policy-activation-authority/0.1",
            "authority_id": "authority:wave-policy-activation",
            "principal_ref": PRINCIPAL_REF,
            "operation": "registration.wave-policy.activate",
            "request_ref": request.request_id,
            "request_digest": request.digest,
            "policy_ref": selected_plan.policy_ref,
            "policy_digest": selected_plan.policy_digest,
            "target_ref": "registrar-operations:synthetic",
            "valid_from_ref": "time:start",
            "expires_at_ref": "time:end",
            "status": "active",
            "revoked_by_ref": None,
            "source_user_item_ref": raw.source_item_ref,
            "source_user_item_digest": raw.evidence_digest,
            "host_observation_ref": host.observation_ref,
            "host_observation_digest": host.digest,
            "not_claimed": ["resident_registration", "private_access"],
        }
    )


def acl_observation():
    material = {
        "schema": "sedb-ral.wave-policy-acl-observation/0.1",
        "observation_ref": "acl-observation:wave-policy",
        "protected": True,
        "forbidden_writer_count": 0,
        "observed_at_ref": "ctcl:instant:acl",
    }
    return {**material, "observation_digest": sha256_ref(material)}


def activation_bundle(tmp_path, storage):
    selected_candidates = candidates(tmp_path / "candidates")
    selected_policy = policy(selected_candidates)
    status = registry_root_status(storage=storage)
    selected_plan = build_wave_plan(
        selected_candidates,
        selected_policy,
        {
            "verified": True,
            "registry_control_digest": status["control_digest"],
            "registry_generation_digest": status["registry_generation_digest"],
            "ledger_head": None,
            "ledger_event_count": 0,
            "application_count": 0,
            "resident_count": 0,
            "address_count": 0,
        },
        checkpoint(),
    )
    approvals = verified_approvals(tmp_path / "approvals", selected_candidates)
    request = plan_wave_policy_activation(
        selected_plan,
        approvals,
        selected_policy,
        checkpoint(),
        registry_root_status(storage=storage),
    )
    intent = activation_intent(selected_plan, request)
    raw = raw_principal_item(
        intent,
        item_ref="user-item:policy-activation",
        turn_id="turn:policy-activation",
    )
    host = principal_host(raw)
    authority = verify_wave_policy_activation_authority(
        activation_authority_artifact(selected_plan, request, raw, host),
        request,
        selected_plan,
        raw,
        host,
        expected_principal_ref=PRINCIPAL_REF,
        time=time_evidence(),
    )
    return selected_plan, selected_policy, approvals, request, authority


def test_wave_policy_appends_record_and_receipt_without_rewriting_dormant(
    tmp_path, published_storage
):
    install_active_dormant(published_storage)
    selected_plan, selected_policy, approvals, request, authority = activation_bundle(
        tmp_path, published_storage
    )
    dormant_path = (
        published_storage.final
        / "extensions/registrar-operations/v1/policies/policy-production-dormant-v1.json"
    )
    dormant_before = dormant_path.read_bytes()
    journal = WaveEffectJournal()
    context = wave_context(tmp_path, published_storage, journal)

    activated = activate_wave_policy(
        context,
        published_storage,
        request,
        approvals,
        authority,
        acl_observation(),
        policy=selected_policy,
        plan=selected_plan,
        time=policy_time(),
    )

    assert activated.record.sequence == 1
    assert activated.receipt.active_policy_digest == activated.record.digest
    assert registration_wave_status(context, published_storage, policy_time())[
        "activation_receipt_status"
    ] == "verified"
    assert activation_receipt_path(published_storage, 1).is_file()
    assert journal.synthetic_receipt_writes == 1
    assert journal.refs("synthetic_receipt_writes") == (activated.receipt_ref,)
    assert dormant_path.read_bytes() == dormant_before


def test_policy_requires_three_verified_approvals_before_io(
    tmp_path, published_storage
):
    install_active_dormant(published_storage)
    selected_plan, selected_policy, approvals, request, authority = activation_bundle(
        tmp_path, published_storage
    )
    journal = WaveEffectJournal()
    context = wave_context(tmp_path, published_storage, journal)

    with pytest.raises(RALValidationError, match="wave_exact_three_approvals_required"):
        activate_wave_policy(
            context,
            published_storage,
            request,
            approvals[:2],
            authority,
            acl_observation(),
            policy=selected_policy,
            plan=selected_plan,
            time=policy_time(),
        )

    assert journal.nonzero_dimensions() == ()


def test_plain_self_sealed_activation_authority_is_not_capability(
    tmp_path, published_storage
):
    install_active_dormant(published_storage)
    selected_plan, selected_policy, approvals, request, authority = activation_bundle(
        tmp_path, published_storage
    )
    context = wave_context(tmp_path, published_storage)

    with pytest.raises(
        RALValidationError, match="verified_wave_policy_authority_required"
    ):
        activate_wave_policy(
            context,
            published_storage,
            request,
            approvals,
            authority.authority,
            acl_observation(),
            policy=selected_policy,
            plan=selected_plan,
            time=policy_time(),
        )


def test_crash_after_record_is_unreceipted_and_exact_retry_only_adds_receipt(
    tmp_path, published_storage, monkeypatch
):
    install_active_dormant(published_storage)
    selected_plan, selected_policy, approvals, request, authority = activation_bundle(
        tmp_path, published_storage
    )
    context = wave_context(tmp_path, published_storage)

    def crash():
        raise InjectedWavePolicyCrash("after_active_record_before_receipt")

    monkeypatch.setattr(policy_module, "_after_active_record_published", crash)
    with pytest.raises(InjectedWavePolicyCrash):
        activate_wave_policy(
            context,
            published_storage,
            request,
            approvals,
            authority,
            acl_observation(),
            policy=selected_policy,
            plan=selected_plan,
            time=policy_time(),
        )
    status = registration_wave_status(context, published_storage, policy_time())
    assert status["wave_status"] == "active_unreceipted"
    with pytest.raises(RALValidationError, match="wave_policy_unreceipted"):
        require_wave_execution(status)

    monkeypatch.setattr(policy_module, "_after_active_record_published", lambda: None)
    before = tuple((published_storage.final / "extensions/registrar-operations/v1/active-policy").glob("*.json"))
    activated = activate_wave_policy(
        context,
        published_storage,
        request,
        approvals,
        authority,
        acl_observation(),
        policy=selected_policy,
        plan=selected_plan,
        time=policy_time(),
    )
    after = tuple((published_storage.final / "extensions/registrar-operations/v1/active-policy").glob("*.json"))
    assert before == after
    assert activated.receipt.active_policy_digest == activated.record.digest


def test_tampered_activation_receipt_fails_status(tmp_path, published_storage):
    install_active_dormant(published_storage)
    selected_plan, selected_policy, approvals, request, authority = activation_bundle(
        tmp_path, published_storage
    )
    context = wave_context(tmp_path, published_storage)
    activate_wave_policy(
        context,
        published_storage,
        request,
        approvals,
        authority,
        acl_observation(),
        policy=selected_policy,
        plan=selected_plan,
        time=policy_time(),
    )
    path = activation_receipt_path(published_storage, 1)
    value = copy.deepcopy(activated_receipt_value(path))
    value["active_policy_digest"] = digest("other")
    value["receipt_digest"] = sha256_ref({k: v for k, v in value.items() if k != "receipt_digest"})
    path.write_bytes(canonical_bytes(value))

    with pytest.raises(RALValidationError, match="wave_policy_activation_receipt_mismatch"):
        registration_wave_status(context, published_storage, policy_time())


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("authority_digest", digest("other-authority")),
        ("request_digest", digest("other-request")),
        (
            "application_approval_digests",
            [digest("other-1"), digest("other-2"), digest("other-3")],
        ),
        ("acl_observation_digest", digest("other-acl")),
        ("checkpoint_digest", digest("other-checkpoint")),
        ("pre_status_digest", digest("other-pre-status")),
    ),
)
def test_resealed_receipt_cannot_substitute_bound_evidence(
    tmp_path, published_storage, field, value
):
    install_active_dormant(published_storage)
    selected_plan, selected_policy, approvals, request, authority = activation_bundle(
        tmp_path, published_storage
    )
    context = wave_context(tmp_path, published_storage)
    activate_wave_policy(
        context,
        published_storage,
        request,
        approvals,
        authority,
        acl_observation(),
        policy=selected_policy,
        plan=selected_plan,
        time=policy_time(),
    )
    path = activation_receipt_path(published_storage, 1)
    receipt = activated_receipt_value(path)
    receipt[field] = value
    receipt["receipt_digest"] = sha256_ref(
        {key: item for key, item in receipt.items() if key != "receipt_digest"}
    )
    path.write_bytes(canonical_bytes(receipt))

    with pytest.raises(RALValidationError, match="wave_policy_activation_receipt_mismatch"):
        registration_wave_status(context, published_storage, policy_time())


def activated_receipt_value(path: Path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def test_expired_time_status_refuses_execution(tmp_path, published_storage):
    install_active_dormant(published_storage)
    selected_plan, selected_policy, approvals, request, authority = activation_bundle(
        tmp_path, published_storage
    )
    context = wave_context(tmp_path, published_storage)
    activate_wave_policy(
        context,
        published_storage,
        request,
        approvals,
        authority,
        acl_observation(),
        policy=selected_policy,
        plan=selected_plan,
        time=policy_time(),
    )

    status = registration_wave_status(
        context, published_storage, policy_time(now=400)
    )
    assert status["wave_status"] == "expired"
    with pytest.raises(RALValidationError, match="wave_policy_inactive"):
        require_wave_execution(status)


def test_verified_terminal_authority_appends_stopped_record_and_event(
    tmp_path, published_storage
):
    install_active_dormant(published_storage)
    selected_plan, selected_policy, approvals, request, authority = activation_bundle(
        tmp_path, published_storage
    )
    context = wave_context(tmp_path, published_storage)
    activated = activate_wave_policy(
        context,
        published_storage,
        request,
        approvals,
        authority,
        acl_observation(),
        policy=selected_policy,
        plan=selected_plan,
        time=policy_time(),
    )
    authority_material = {
        "schema": "sedb-ral.registration-wave-terminal-authority/0.1",
        "authority_ref": "authority:wave-policy-terminal",
        "principal_ref": PRINCIPAL_REF,
        "operation": "registration.wave-policy.terminate",
        "wave_plan_digest": selected_plan.digest,
        "policy_digest": selected_policy.digest,
        "valid_from_ref": "time:start",
        "expires_at_ref": "time:end",
        "status": "active",
        "source_user_item_ref": "user-item:terminal",
        "source_user_item_digest": "pending",
        "host_observation_ref": "pending",
        "host_observation_digest": "pending",
    }
    terminal_intent = {
        "schema": "sedb-ral.registration-wave-terminal-intent/0.1",
        "principal_ref": PRINCIPAL_REF,
        "operation": "registration.wave-policy.terminate",
        "wave_plan_digest": selected_plan.digest,
        "policy_digest": selected_policy.digest,
    }
    raw = raw_principal_item(
        terminal_intent,
        item_ref="user-item:terminal",
        turn_id="turn:terminal",
    )
    host = principal_host(raw)
    authority_material.update(
        {
            "source_user_item_digest": raw.evidence_digest,
            "host_observation_ref": host.observation_ref,
            "host_observation_digest": host.digest,
        }
    )
    authority_material["authority_digest"] = sha256_ref(authority_material)
    terminal_authority = verify_wave_policy_terminal_authority(
        authority_material,
        selected_plan,
        selected_policy,
        raw,
        host,
        expected_principal_ref=PRINCIPAL_REF,
        time=time_evidence(),
    )
    terminal_event = WaveTerminalEvent.sealed(
        {
            "schema": "sedb-ral.registration-wave-terminal-event/0.1",
            "event_id": "wave-terminal:2",
            "wave_plan_ref": f"registration-wave-plan:{selected_plan.wave_id}",
            "wave_plan_digest": selected_plan.digest,
            "policy_ref": selected_policy.policy_id,
            "policy_digest": selected_policy.digest,
            "previous_record_ref": activated.record_ref,
            "previous_record_digest": activated.record.digest,
            "terminal_status": "stopped",
            "reason_code": "operator_stop",
            "created_time_ref": "time:terminal",
            "authority_ref": terminal_authority.authority_ref,
            "authority_digest": terminal_authority.authority_digest,
            "not_claimed": ["rollback", "deletion"],
        }
    )

    assert isinstance(terminal_authority, VerifiedWavePolicyTerminalAuthority)
    stopped = terminate_wave_policy(
        context,
        published_storage,
        terminal_event,
        terminal_authority,
        time=policy_time(),
    )
    status = registration_wave_status(context, published_storage, policy_time())

    assert stopped.sequence == 2
    assert status["wave_status"] == "stopped"
    with pytest.raises(RALValidationError, match="wave_policy_inactive"):
        require_wave_execution(status)
