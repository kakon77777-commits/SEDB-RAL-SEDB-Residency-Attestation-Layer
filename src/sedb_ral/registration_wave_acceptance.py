from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from . import registration_wave_engine as wave_engine_module
from .canonical import canonical_bytes, loads_strict, sha256_ref
from .errors import RALValidationError
from .production_operations_contracts import (
    default_dormant_policy,
    plan_production_operations_extension,
)
from .production_operations_layout import (
    prepare_production_operations_candidate,
    publish_production_operations_candidate,
    verify_production_operations_candidate,
    write_activation_receipt,
)
from .registrar import commit_admission_plan
from .registration import RegistrationIds, canonical_claim_digest
from .registration_wave_authority import (
    PrincipalHostObservation,
    RawPrincipalItemSnapshot,
    VerifiedApplicationApproval,
    derive_verified_application_authority,
    observe_synthetic_authority_time,
    verify_application_approval,
    verify_authority_time_evidence,
    verify_slot_execution_authorization,
)
from .registration_wave_context import (
    SYNTHETIC_MARKER_NAME,
    SyntheticWaveExecutionContext,
    WaveEffectJournal,
    WaveExecutionMode,
)
from .registration_wave_engine import (
    InjectedWaveSlotCrash,
    plan_wave_slot,
    simulate_wave_slot,
    verify_synthetic_wave_result_prefix,
)
from .registration_wave_intake import RawApplicantItemSnapshot, prepare_wave_candidate
from .registration_wave_models import (
    ApplicantItemEvidence,
    PrincipalApplicationApproval,
    RegistrationWavePolicy,
    SlotExecutionAuthorization,
    WaveSlotRecoveryAuthorization,
    WaveSlotRequest,
)
from .registration_wave_plan import (
    build_slot_request,
    build_wave_plan,
    verify_wave_receipt_prefix,
)
from .registration_wave_policy import (
    _write_new_or_same,
    activate_wave_policy,
    plan_wave_policy_activation,
    registration_wave_status,
    require_wave_execution,
    verify_wave_policy_activation_authority,
)
from .registration_wave_readback import build_wave_readback_bundle
from .registration_wave_recovery import (
    inspect_wave_slot_prefix,
    verify_wave_slot_recovery_authorization,
)
from .registration_wave_store import RegistrationWaveStore
from .registry_root import (
    RegistryStorage,
    prepare_registry_candidate,
    publish_registry_candidate,
    registry_root_status,
    verify_registry_candidate,
)
from .registry_root_contracts import (
    APPROVED_ROOT_SCOPES,
    bind_document_digest,
    bind_registry_acl_fingerprint,
    plan_registry_root,
)

OWNER_PLAN_CASES = frozenset(
    {"W1-019", "W1-020", "W1-021", "W1-022", "W1-047", "W1-048"}
)
CASE_POPULATIONS = {
    f"W1-{index:03d}": description
    for index, description in enumerate(
        (
            "three exact applicant-authored claims",
            "one absent applicant before slot one",
            "applicant opt-out before slot one",
            "task turn or output mismatch",
            "three distinct canonical thread locators",
            "uppercase case-confusable locator",
            "retained prepare replay",
            "changed candidate with old approval",
            "three independently verified approvals",
            "registrar self-approval",
            "missing or unreceipted Wave policy",
            "slot one against H0",
            "slot two still using H0",
            "slot two against H1",
            "slot three against H2",
            "repeated admitted application",
            "injected crash before append",
            "exact durable result retry",
            "LIMEN B6A after slot one",
            "LIMEN B6A after slot two",
            "LIMEN B6A after slot three",
            "cross-resident task resolution",
            "private request after public admission",
            "measured positive and forbidden effects",
            "readback rebuild reproducibility",
            "independent full synthetic wave replay",
            "slot three at H1 without slot two receipt",
            "changed reordered or duplicate Wave plan",
            "missing predecessor receipt",
            "assistant forged or relayed principal approval",
            "approval for a different application",
            "application approval without JIT authority",
            "independent registrar self-approval evidence",
            "missing stale expired or unreceipted policy",
            "create-only policy overwrite attempt",
            "control digest supplied as H0",
            "complete event chain without outer result",
            "partial-prefix recovery authority",
            "expired policy with pending slot",
            "old execution authority on continuation",
            "uppercase braced and Unicode-hyphen locator",
            "exact duplicate canonical locator",
            "claim digest differs from host evidence",
            "unrelated turn or item reference",
            "continue or non-null resident claim",
            "failed third candidate before activation",
            "claim-time observation reused for B6A",
            "fresh B6A observation on rebuilt view",
            "strict mid-chain transaction prefix",
            "controller user message as applicant output",
            "reasoning tool command or file applicant item",
            "completed applicant output unavailable",
            "exact completed assistant agent message",
        ),
        start=1,
    )
}
_THREADS = (
    "10000000-0000-4000-8000-000000000001",
    "20000000-0000-4000-8000-000000000002",
    "30000000-0000-4000-8000-000000000003",
)
_PRINCIPAL_REF = "principal:neo.k:synthetic-acceptance"
_PRINCIPAL_THREAD = "90000000-0000-4000-8000-000000000009"
_FINAL_ROOT = r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"
_PARENT_ROOT = r"D:\AI_RESIDENCE\REGISTRY"
_OWNER_SID = "S-1-5-21-1000-1001-1002-1003"
_ROOT_CANDIDATE = "6f5121df-a649-49f3-a3f8-f1ef7df6f3af"
_EXTENSION_CANDIDATE = "9b0c7d46-b94d-4b39-b59f-42f4d458955c"
_TIME_REF = "time:synthetic-wave-acceptance"


@dataclass(frozen=True)
class RegistrationWaveAcceptanceCase:
    case_id: str
    executed: bool
    passed: bool
    status: str
    evidence_digest: str
    control_evidence: object

    def as_json(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "executed": self.executed,
            "passed": self.passed,
            "status": self.status,
            "evidence_digest": self.evidence_digest,
            "control_evidence": self.control_evidence,
        }


@dataclass(frozen=True)
class RegistrationWaveAcceptanceReport:
    cases: tuple[RegistrationWaveAcceptanceCase, ...]
    effects: WaveEffectJournal
    first_run_digest: str
    second_run_digest: str
    report_digest: str
    production_wave_run: str = "NOT_RUN"
    live_limen_b6a: str = "NOT_RUN"
    production_root_status: str = "NOT_READ"

    @property
    def passed(self) -> bool:
        return (
            self.first_run_digest == self.second_run_digest
            and all(case.passed for case in self.cases)
            and not self.effects.forbidden_nonzero_dimensions()
        )

    def as_json(self) -> dict[str, object]:
        effect_counts = {
            name: getattr(self.effects, name)
            for name in self.effects.__dataclass_fields__
            if not name.startswith("_")
        }
        value = {
            "schema": "sedb-ral.registration-wave-acceptance-report/0.1",
            "status": "pass" if self.passed else "fail",
            "cases": [case.as_json() for case in self.cases],
            "executed_count": sum(case.executed for case in self.cases),
            "owner_plan_not_run_count": sum(not case.executed for case in self.cases),
            "effects": {
                "counts": effect_counts,
                "allowed_refs": {
                    name: list(refs)
                    for name, refs in self.effects.allowed_refs().items()
                },
                "forbidden_nonzero_dimensions": list(
                    self.effects.forbidden_nonzero_dimensions()
                ),
            },
            "first_run_digest": self.first_run_digest,
            "second_run_digest": self.second_run_digest,
            "production_wave_run": self.production_wave_run,
            "live_limen_b6a": self.live_limen_b6a,
            "production_root_status": self.production_root_status,
            "not_claimed": [
                "production_admission",
                "live_limen_resolution",
                "private_access",
                "network_effect",
            ],
        }
        return {**value, "report_digest": self.report_digest}


@dataclass(frozen=True)
class _PositiveRun:
    digest: str
    effects: WaveEffectJournal
    candidates: tuple[object, ...]
    approvals: tuple[VerifiedApplicationApproval, ...]
    plan: object
    policy: RegistrationWavePolicy
    slot_results: tuple[object, ...]
    readbacks: tuple[object, ...]
    event_count: int
    final_head: str
    context: SyntheticWaveExecutionContext
    store: RegistrationWaveStore
    storage: RegistryStorage
    policy_context: SyntheticWaveExecutionContext
    authorizations: tuple[object, ...]
    planned_slots: tuple[object, ...]
    replay_result_digests: tuple[str, ...]
    readback_repeat_digests: tuple[str, ...]


def _digest(label: str) -> str:
    return sha256_ref({"fixture": label})


def _seal(value: dict[str, object], field: str) -> dict[str, object]:
    material = copy.deepcopy(value)
    material.pop(field, None)
    return {**material, field: sha256_ref(material)}


def _root_plan() -> dict[str, object]:
    return plan_registry_root(
        final_root=_FINAL_ROOT,
        candidate_id=_ROOT_CANDIDATE,
        source_commit="a" * 40,
        source_package_version="0.5.0b1",
        time_ref=_TIME_REF,
        filesystem="NTFS",
        volume_identity="volume:synthetic-wave",
        expected_owner_sid=_OWNER_SID,
    )


def _root_authority(plan: dict[str, object]) -> dict[str, object]:
    return bind_document_digest(
        {
            "schema": "sedb-ral.registry-root-authority/0.1",
            "authority_id": "authority:4e928ea1-0827-40d1-b6bf-47dc9cba1708",
            "operation_plan_digest": plan["plan_digest"],
            "exact_root": _FINAL_ROOT,
            "scopes": list(APPROVED_ROOT_SCOPES),
            "status": "active",
            "issued_time_ref": _TIME_REF,
            "authorization_basis": "direct_user_instruction",
            "expires_after_plan_completion": True,
            "not_claimed": [
                "resident_identity",
                "resident_registration",
                "private_access",
                "delete_authority",
            ],
        },
        "authority_digest",
    )


def _acl(root: str) -> dict[str, object]:
    return bind_registry_acl_fingerprint(
        {
            "schema": "sedb-ral.registry-acl-observation/0.1",
            "observed_root": root,
            "owner_sid": _OWNER_SID,
            "filesystem": "NTFS",
            "volume_identity": "volume:synthetic-wave",
            "inheritance_protected": True,
            "reparse_point": False,
            "required_full_control_sids": [
                _OWNER_SID,
                "S-1-5-18",
                "S-1-5-32-544",
            ],
            "forbidden_write_sids": [],
            "sddl_sha256": "0" * 64,
            "observed_time_ref": _TIME_REF,
            "not_claimed": [
                "offsite_backup",
                "private_confidentiality",
                "multi_host_security",
            ],
        }
    )


def _extension_authority(plan_digest: str) -> dict[str, object]:
    return bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-extension-authority/0.1",
            "authority_id": "authority:synthetic-wave-extension",
            "principal_ref": _PRINCIPAL_REF,
            "operation": "registry.operations-extension.activate",
            "target_root": _FINAL_ROOT,
            "operation_plan_digest": plan_digest,
            "scopes": ["registry.operations-extension.activate"],
            "status": "active",
            "issued_time_ref": _TIME_REF,
            "expires_time_ref": "time:synthetic-wave-end",
            "authorship_attestation_ref": "attestation:synthetic-wave",
            "not_claimed": [
                "resident_approval",
                "ledger_append",
                "private_access",
                "rollback_authority",
            ],
        },
        "authority_digest",
    )


def _install_storage(root: Path) -> RegistryStorage:
    storage = RegistryStorage.synthetic(root)
    plan = _root_plan()
    authority = _root_authority(plan)
    storage.parent.mkdir(parents=True)
    storage.candidate(plan).mkdir()
    parent_acl = _acl(_PARENT_ROOT)
    candidate_acl = _acl(str(plan["candidate_root"]))
    prepare_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    verified = verify_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    publish_registry_candidate(plan, verified, storage=storage)

    status = registry_root_status(storage=storage)
    policy = default_dormant_policy()
    candidate_root = (
        rf"D:\AI_RESIDENCE\REGISTRY\.SEDB-RAL.operations-{_EXTENSION_CANDIDATE}"
    )
    extension_acl = _acl(candidate_root)
    extension_plan = plan_production_operations_extension(
        registry_status=status,
        candidate_id=_EXTENSION_CANDIDATE,
        operations_generation=f"operations-generation:{_EXTENSION_CANDIDATE}",
        policy_digest=str(policy["policy_digest"]),
        source_commit="b" * 40,
        source_package_version="0.5.0b1",
        filesystem="NTFS",
        volume_identity=str(extension_acl["volume_identity"]),
        expected_owner_sid=str(extension_acl["owner_sid"]),
        acl_fingerprint=str(extension_acl["acl_fingerprint"]),
        pre_checkpoint_digest=_digest("pre-checkpoint"),
        time_ref=_TIME_REF,
    )
    candidate = storage.parent / str(extension_plan["candidate_name"])
    candidate.mkdir()
    prepared = prepare_production_operations_candidate(
        extension_plan,
        _extension_authority(str(extension_plan["plan_digest"])),
        extension_acl,
        policy,
        storage=storage,
    )
    extension_verified = verify_production_operations_candidate(
        extension_plan, prepared, storage=storage
    )
    publish_production_operations_candidate(
        extension_plan, extension_verified, storage=storage
    )
    index_path = storage.final / "extensions/index/00000000000000000000.json"
    index = loads_strict(index_path.read_text(encoding="utf-8"))
    if not isinstance(index, dict):
        raise TypeError("extension index is not an object")
    write_activation_receipt(
        root=storage.final,
        plan=extension_plan,
        index=index,
        observed_time_ref=_TIME_REF,
    )
    return storage


def _claim(index: int, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema": "sedb-ral.self-application-claim/0.1",
        "applicant_claim_only": True,
        "desired_display_label": f"Synthetic Wave Seat {index}",
        "existing_resident_claim": None,
        "continuity_claim": "new",
        "desired_addresses": [
            {
                "namespace": "codex_thread",
                "identifier_kind": "codex_thread",
                "locator": _THREADS[index - 1],
            }
        ],
        "role_description_claim": f"Synthetic Wave role {index}",
        "dissent_or_limits": ["public registration only"],
        "opt_in": True,
        "relay_is_authorship": False,
        "not_claimed": [
            "verified_identity",
            "registrar_authority",
            "private_access",
        ],
    }
    value.update(changes)
    return value


def _raw_applicant(
    index: int, claim_value: dict[str, object] | None = None, **changes: object
) -> RawApplicantItemSnapshot:
    selected = _claim(index) if claim_value is None else claim_value
    fields: dict[str, object] = {
        "provider": "openai",
        "adapter_kind": "codex_app_task_tool",
        "native_thread_id": _THREADS[index - 1],
        "native_turn_id": f"turn:wave-seat-{index}",
        "source_item_role": "assistant",
        "source_item_kind": "agentMessage",
        "source_item_status": "completed",
        "source_item_parent_thread_id": _THREADS[index - 1],
        "source_item_parent_turn_id": f"turn:wave-seat-{index}",
        "applicant_item_ref": f"item:wave-seat-{index}",
        "content_bytes": canonical_bytes(selected),
    }
    fields.update(changes)
    return RawApplicantItemSnapshot(**fields)


def _item(
    index: int,
    claim_value: dict[str, object] | None = None,
    raw_value: RawApplicantItemSnapshot | None = None,
    **changes: object,
) -> dict[str, object]:
    selected = _claim(index) if claim_value is None else claim_value
    raw = _raw_applicant(index, selected) if raw_value is None else raw_value
    value: dict[str, object] = {
        "schema": "sedb-ral.registration-applicant-item-evidence/0.1",
        "item_evidence_id": f"item-evidence:wave-seat-{index}",
        "provider": raw.provider,
        "adapter_kind": raw.adapter_kind,
        "native_thread_id": raw.native_thread_id,
        "native_turn_id": raw.native_turn_id,
        "source_item_role": raw.source_item_role,
        "source_item_kind": raw.source_item_kind,
        "source_item_status": raw.source_item_status,
        "source_item_parent_thread_id": raw.source_item_parent_thread_id,
        "source_item_parent_turn_id": raw.source_item_parent_turn_id,
        "applicant_item_ref": raw.applicant_item_ref,
        "canonical_claim_digest": canonical_claim_digest(selected),
        "raw_item_evidence_digest": raw.evidence_digest,
        "capture_status": "host_observed",
        "observed_origin": "host:codex-app",
        "observed_at_ref": f"ctcl:instant:wave-seat-{index}",
        "unavailable_fields": [
            {
                "field": "native_session_id",
                "reason": "structurally_unavailable_from_codex_app_task_tool",
            }
        ],
        "not_claimed": ["verified_identity", "registrar_authority"],
    }
    value.update(changes)
    return _seal(value, "item_evidence_digest")


def _host(
    index: int,
    claim_value: dict[str, object] | None = None,
    item_value: dict[str, object] | None = None,
    **changes: object,
) -> dict[str, object]:
    selected = _claim(index) if claim_value is None else claim_value
    evidence = _item(index, selected) if item_value is None else item_value
    value: dict[str, object] = {
        "schema": "sedb-ral.registration-host-observation/0.2",
        "observation_id": f"observation:wave-seat-{index}",
        "provider": "openai",
        "adapter_kind": "codex_app_task_tool",
        "identifier_kind": "codex_thread",
        "native_thread_id": _THREADS[index - 1],
        "native_session_id": None,
        "native_turn_id": f"turn:wave-seat-{index}",
        "unavailable_fields": evidence["unavailable_fields"],
        "observed_origin": "host:codex-app",
        "observed_at_ref": f"ctcl:instant:wave-seat-{index}",
        "applicant_item_ref": f"item:wave-seat-{index}",
        "applicant_item_evidence_ref": f"item-evidence:wave-seat-{index}",
        "applicant_item_evidence_digest": evidence["item_evidence_digest"],
        "canonical_claim_digest": canonical_claim_digest(selected),
        "not_claimed": ["pre_turn_output_enforcement", "verified_identity"],
    }
    value.update(changes)
    return _seal(value, "observation_digest")


def _ids(index: int) -> RegistrationIds:
    return RegistrationIds(
        prepared_id=f"prepared:{index:08x}",
        application_id=f"application:{index + 10:08x}",
        resident_id=f"resident:{index + 20:08x}",
        instance_id=f"instance:{index + 30:08x}",
        continuity_line_id=f"line:{index + 40:08x}",
        address_ids=(f"address:{index + 50:08x}",),
        claim_ids=(
            f"claim:{index + 60:08x}",
            f"claim:{index + 70:08x}",
            f"claim:{index + 80:08x}",
        ),
    )


def _marker_context(
    root: Path,
    name: str,
    target: Path,
    journal: WaveEffectJournal | None = None,
) -> SyntheticWaveExecutionContext:
    fixture = root / name
    fixture.mkdir(parents=True, exist_ok=True)
    marker = {
        "schema": "sedb-ral.synthetic-wave-fixture-marker/0.1",
        "fixture_marker_ref": f"fixture:{name}",
        "not_claimed": ["production_root", "real_applicant", "private_access"],
    }
    (fixture / SYNTHETIC_MARKER_NAME).write_bytes(canonical_bytes(marker))
    return SyntheticWaveExecutionContext.sealed(
        mode=WaveExecutionMode.SYNTHETIC_TEST,
        fixture_root=fixture,
        target_root=target,
        fixture_marker_ref=str(marker["fixture_marker_ref"]),
        fixture_marker_digest=sha256_ref(marker),
        forbidden_roots=(),
        journal=journal or WaveEffectJournal(),
    )


def _candidate(
    root: Path,
    index: int,
    *,
    journal: WaveEffectJournal | None = None,
    **claim_changes: object,
):
    claim_value = _claim(index, **claim_changes)
    raw = _raw_applicant(index, claim_value)
    item_value = _item(index, claim_value, raw)
    host_value = _host(index, claim_value, item_value)
    context = _marker_context(
        root,
        f"candidate-{index}",
        root / f"candidate-{index}" / "target",
        journal,
    )
    return prepare_wave_candidate(
        context,
        claim_value,
        item_value,
        host_value,
        raw,
        lambda: _ids(index),
    )


def _wave_policy(candidates: tuple[object, ...]) -> RegistrationWavePolicy:
    return RegistrationWavePolicy.sealed(
        {
            "schema": "sedb-ral.registration-wave-policy/0.1",
            "policy_id": "policy:wave-1",
            "wave_id": "wave:synthetic:1",
            "ordered_application_digests": [
                value.application_digest for value in candidates
            ],
            "ordered_locators": list(_THREADS),
            "allowed_actions": ["prepare", "readback", "admit_one"],
            "max_slots": 3,
            "batch_append": False,
            "capabilities": {
                "correction": False,
                "merge": False,
                "private_access": False,
                "network_send": False,
                "provider_call": False,
                "fabric_emit": False,
                "mcp_call": False,
                "cloud": False,
                "deletion": False,
            },
            "valid_from_ref": "ctcl:instant:policy-start",
            "expires_at_ref": "ctcl:instant:policy-end",
            "not_claimed": ["batch_authority", "private_access"],
        }
    )


def _checkpoint() -> dict[str, object]:
    return {
        "checkpoint_ref": "checkpoint:wave-1",
        "checkpoint_digest": _digest("wave-checkpoint"),
        "ledger_head": None,
    }


def _time(now: int = 200, expires_at: int = 300):
    return verify_authority_time_evidence(
        observe_synthetic_authority_time(
            now_ref="time:now",
            now_epoch_ns=now,
            valid_from_ref="time:start",
            valid_from_epoch_ns=100,
            expires_at_ref="time:end",
            expires_at_epoch_ns=expires_at,
        )
    )


def _policy_time(now: int = 200, expires_at: int = 300):
    return verify_authority_time_evidence(
        observe_synthetic_authority_time(
            now_ref="time:policy-now",
            now_epoch_ns=now,
            valid_from_ref="ctcl:instant:policy-start",
            valid_from_epoch_ns=100,
            expires_at_ref="ctcl:instant:policy-end",
            expires_at_epoch_ns=expires_at,
        )
    )


def _raw_principal(
    intent: dict[str, object], *, item_ref: str, turn_id: str, role: str = "user"
) -> RawPrincipalItemSnapshot:
    return RawPrincipalItemSnapshot(
        provider="openai",
        adapter_kind="codex_app_task_tool",
        native_thread_id=_PRINCIPAL_THREAD,
        native_turn_id=turn_id,
        source_item_role=role,
        source_item_kind="userMessage",
        source_item_status="completed",
        source_item_parent_thread_id=_PRINCIPAL_THREAD,
        source_item_parent_turn_id=turn_id,
        source_item_ref=item_ref,
        content_bytes=canonical_bytes(intent),
    )


def _principal_host(raw: RawPrincipalItemSnapshot) -> PrincipalHostObservation:
    return PrincipalHostObservation.sealed(
        provider=raw.provider,
        adapter_kind=raw.adapter_kind,
        native_thread_id=raw.native_thread_id,
        native_turn_id=raw.native_turn_id,
        source_item_role=raw.source_item_role,
        source_item_kind=raw.source_item_kind,
        source_item_status=raw.source_item_status,
        source_item_ref=raw.source_item_ref,
        observed_origin="host:codex-app",
        observed_at_ref=f"ctcl:instant:{raw.native_turn_id}",
    )


def _approval(candidate: object, index: int) -> VerifiedApplicationApproval:
    application = candidate.prepared.application
    intent = {
        "schema": "sedb-ral.principal-application-approval-intent/0.1",
        "principal_ref": _PRINCIPAL_REF,
        "application_ref": application["application_id"],
        "application_digest": sha256_ref(application),
        "approved_scopes": ["registration.application.approve"],
    }
    raw = _raw_principal(
        intent,
        item_ref=f"user-item:approval-{index}",
        turn_id=f"turn:approval-{index}",
    )
    host = _principal_host(raw)
    artifact = PrincipalApplicationApproval.sealed(
        {
            "schema": "sedb-ral.principal-application-approval/0.1",
            "approval_id": f"approval:slot-{index}",
            "principal_ref": _PRINCIPAL_REF,
            "application_ref": application["application_id"],
            "application_digest": sha256_ref(application),
            "source_user_item_ref": raw.source_item_ref,
            "source_user_item_digest": raw.evidence_digest,
            "host_observation_ref": host.observation_ref,
            "host_observation_digest": host.digest,
            "approved_scopes": ["registration.application.approve"],
            "valid_from_ref": "time:start",
            "expires_at_ref": "time:end",
            "status": "active",
            "revoked_by_ref": None,
            "not_claimed": ["slot_execution", "registrar_authority"],
        }
    )
    return verify_application_approval(
        artifact,
        application,
        raw,
        host,
        expected_principal_ref=_PRINCIPAL_REF,
        time=_time(),
    )


def _approval_with_role(
    candidate: object, role: str, *, observed_origin: str = "host:codex-app"
):
    application = candidate.prepared.application
    intent = {
        "schema": "sedb-ral.principal-application-approval-intent/0.1",
        "principal_ref": _PRINCIPAL_REF,
        "application_ref": application["application_id"],
        "application_digest": sha256_ref(application),
        "approved_scopes": ["registration.application.approve"],
    }
    raw = _raw_principal(
        intent,
        item_ref="user-item:role-control",
        turn_id="turn:role-control",
        role=role,
    )
    host = _principal_host(raw)
    if observed_origin != host.observed_origin:
        host = PrincipalHostObservation.sealed(
            provider=host.provider,
            adapter_kind=host.adapter_kind,
            native_thread_id=host.native_thread_id,
            native_turn_id=host.native_turn_id,
            source_item_role=host.source_item_role,
            source_item_kind=host.source_item_kind,
            source_item_status=host.source_item_status,
            source_item_ref=host.source_item_ref,
            observed_origin=observed_origin,
            observed_at_ref=host.observed_at_ref,
        )
    artifact = PrincipalApplicationApproval.sealed(
        {
            "schema": "sedb-ral.principal-application-approval/0.1",
            "approval_id": "approval:role-control",
            "principal_ref": _PRINCIPAL_REF,
            "application_ref": application["application_id"],
            "application_digest": sha256_ref(application),
            "source_user_item_ref": raw.source_item_ref,
            "source_user_item_digest": raw.evidence_digest,
            "host_observation_ref": host.observation_ref,
            "host_observation_digest": host.digest,
            "approved_scopes": ["registration.application.approve"],
            "valid_from_ref": "time:start",
            "expires_at_ref": "time:end",
            "status": "active",
            "revoked_by_ref": None,
            "not_claimed": ["slot_execution", "registrar_authority"],
        }
    )
    return verify_application_approval(
        artifact,
        application,
        raw,
        host,
        expected_principal_ref=_PRINCIPAL_REF,
        time=_time(),
    )


def _activate_wave(
    root: Path,
    storage: RegistryStorage,
    plan: object,
    policy: RegistrationWavePolicy,
    approvals: tuple[VerifiedApplicationApproval, ...],
    journal: WaveEffectJournal | None = None,
) -> tuple[SyntheticWaveExecutionContext, object]:
    request = plan_wave_policy_activation(
        plan,
        approvals,
        policy,
        _checkpoint(),
        registry_root_status(storage=storage),
    )
    intent = {
        "schema": "sedb-ral.registration-wave-policy-activation-intent/0.1",
        "principal_ref": _PRINCIPAL_REF,
        "request_ref": request.request_id,
        "request_digest": request.digest,
        "policy_ref": plan.policy_ref,
        "policy_digest": plan.policy_digest,
        "target_ref": "registrar-operations:synthetic",
        "operation": "registration.wave-policy.activate",
    }
    raw = _raw_principal(
        intent,
        item_ref="user-item:policy-activation",
        turn_id="turn:policy-activation",
    )
    host = _principal_host(raw)
    from .registration_wave_models import WavePolicyActivationAuthority

    artifact = WavePolicyActivationAuthority.sealed(
        {
            "schema": "sedb-ral.registration-wave-policy-activation-authority/0.1",
            "authority_id": "authority:wave-policy-activation",
            "principal_ref": _PRINCIPAL_REF,
            "operation": "registration.wave-policy.activate",
            "request_ref": request.request_id,
            "request_digest": request.digest,
            "policy_ref": plan.policy_ref,
            "policy_digest": plan.policy_digest,
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
    authority = verify_wave_policy_activation_authority(
        artifact,
        request,
        plan,
        raw,
        host,
        expected_principal_ref=_PRINCIPAL_REF,
        time=_time(),
    )
    acl_material = {
        "schema": "sedb-ral.wave-policy-acl-observation/0.1",
        "observation_ref": "acl-observation:wave-policy",
        "protected": True,
        "forbidden_writer_count": 0,
        "observed_at_ref": "ctcl:instant:acl",
    }
    acl = {**acl_material, "observation_digest": sha256_ref(acl_material)}
    context = _marker_context(root, "wave-policy", storage.final, journal)
    result = activate_wave_policy(
        context,
        storage,
        request,
        approvals,
        authority,
        acl,
        policy=policy,
        plan=plan,
        time=_policy_time(),
    )
    return context, result


def _slot_request(plan: object, index: int, prefix: object) -> WaveSlotRequest:
    slot = plan.ordered_slots[index - 1]
    predecessor = None if not prefix.results else prefix.results[-1]
    return WaveSlotRequest.sealed(
        {
            "schema": "sedb-ral.registration-wave-slot-request/0.1",
            "request_id": f"slot-request:synthetic:{index}",
            "wave_plan_ref": f"registration-wave-plan:{plan.wave_id}",
            "wave_plan_digest": plan.digest,
            "slot_id": slot["slot_id"],
            "slot_index": index,
            "candidate_ref": slot["candidate_ref"],
            "candidate_digest": slot["candidate_digest"],
            "application_ref": slot["application_ref"],
            "application_digest": slot["application_digest"],
            "predecessor_receipt_ref": (
                None if predecessor is None else predecessor.result_id
            ),
            "predecessor_receipt_digest": (
                None if predecessor is None else predecessor.digest
            ),
            "expected_ledger_state": {
                "expected_ledger_head": prefix.final_head,
                "cli_token": "GENESIS" if prefix.final_head is None else prefix.final_head,
                "ledger_event_count": prefix.ledger_event_count,
            },
            "policy_ref": plan.policy_ref,
            "policy_digest": plan.policy_digest,
            "checkpoint_ref": plan.checkpoint_ref,
            "checkpoint_digest": plan.checkpoint_digest,
            "registry_generation_digest": plan.registry_generation_digest,
            "registry_control_digest": plan.registry_control_digest,
            "not_claimed": ["batch_execution", "rank", "authority"],
        }
    )


def _execution_authorization(
    plan: object,
    policy: RegistrationWavePolicy,
    request: WaveSlotRequest,
    approval: VerifiedApplicationApproval,
):
    intent = {
        "schema": "sedb-ral.registration-slot-execution-intent/0.1",
        "principal_ref": _PRINCIPAL_REF,
        "wave_plan_ref": f"registration-wave-plan:{plan.wave_id}",
        "wave_plan_digest": plan.digest,
        "slot_id": request.slot_id,
        "slot_index": request.slot_index,
        "operation_request_ref": request.request_id,
        "operation_request_digest": request.digest,
        "application_approval_ref": approval.approval.approval_id,
        "application_approval_digest": approval.approval.digest,
        "policy_ref": plan.policy_ref,
        "policy_digest": plan.policy_digest,
        "checkpoint_ref": plan.checkpoint_ref,
        "checkpoint_digest": plan.checkpoint_digest,
        "expected_ledger_head": request.expected_ledger_state[
            "expected_ledger_head"
        ],
        "registry_control_digest": plan.registry_control_digest,
    }
    raw = _raw_principal(
        intent,
        item_ref=f"user-item:slot-{request.slot_index}",
        turn_id=f"turn:slot-{request.slot_index}",
    )
    host = _principal_host(raw)
    artifact = SlotExecutionAuthorization.sealed(
        {
            "schema": "sedb-ral.registration-slot-execution-authorization/0.1",
            "execution_authorization_id": (
                f"execution-authorization:slot-{request.slot_index}"
            ),
            "principal_ref": _PRINCIPAL_REF,
            "wave_plan_ref": request.wave_plan_ref,
            "wave_plan_digest": plan.digest,
            "slot_id": request.slot_id,
            "slot_index": request.slot_index,
            "operation_request_ref": request.request_id,
            "operation_request_digest": request.digest,
            "application_approval_ref": approval.approval.approval_id,
            "application_approval_digest": approval.approval.digest,
            "policy_ref": plan.policy_ref,
            "policy_digest": plan.policy_digest,
            "checkpoint_ref": plan.checkpoint_ref,
            "checkpoint_digest": plan.checkpoint_digest,
            "expected_ledger_head": request.expected_ledger_state[
                "expected_ledger_head"
            ],
            "registry_control_digest": plan.registry_control_digest,
            "valid_from_ref": "time:start",
            "expires_at_ref": "time:end",
            "status": "active",
            "revoked_by_ref": None,
            "source_user_item_ref": raw.source_item_ref,
            "source_user_item_digest": raw.evidence_digest,
            "host_observation_ref": host.observation_ref,
            "host_observation_digest": host.digest,
            "not_claimed": ["batch_execution", "private_access"],
        }
    )
    current_status = {
        "wave_status": "active",
        "policy_ref": plan.policy_ref,
        "policy_digest": plan.policy_digest,
        "checkpoint_ref": plan.checkpoint_ref,
        "checkpoint_digest": plan.checkpoint_digest,
        "registry_generation_digest": plan.registry_generation_digest,
        "registry_control_digest": plan.registry_control_digest,
        "current_ledger_head": request.expected_ledger_state[
            "expected_ledger_head"
        ],
    }
    return verify_slot_execution_authorization(
        artifact,
        plan,
        request,
        approval,
        policy,
        _checkpoint(),
        current_status,
        raw,
        host,
        expected_principal_ref=_PRINCIPAL_REF,
        time=_time(),
    )


def _ctcl() -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "ctcl_instant_id": "ctcl:instant:5a76bd1b-2db2-463b-b2ad-0b1307102710",
        "ctcl_call_kind": "registered_anchor",
        "reference": {
            "timescale": "utc",
            "value": "2026-08-23T08:09:39.165Z",
        },
        "encodings": {
            "unix_s": "1787472579.165",
            "unix_ms": "1787472579165",
            "unix_us": "1787472579165000",
            "unix_ns": "1787472579165000000",
            "rfc3339": "2026-08-23T08:09:39.165Z",
        },
        "source": {
            "class": "wall_clock",
            "protocol": None,
            "provider": None,
            "sync_status": "unreported",
        },
        "quality": {
            "precision": None,
            "estimated_uncertainty_ns": None,
            "synchronized": None,
            "note": "ctcl_register_instant did not report clock quality fields",
        },
        "signature": {
            "alg": "Ed25519",
            "key_id": "ctcl-ed25519-1",
            "signed_fields": "instant_id|unix_ns|timescale",
            "value": "FuzXlb1Fs4tRbf85PuVABWeZBTHNMKRaLaQRBvRu7+u6NG96OfZWuk+jYeX8mMu0Hr8uV9pLGTIcmHM0S9c0AQ==",
            "verify_endpoint": "/v1/pubkey",
            "verification_status": "not_performed",
        },
        "retrievability": {
            "expected": True,
            "status": "verified",
            "checked_at_ref": None,
            "retrieval_evidence_ref": (
                "evidence/ctcl/2026-08-23-initial-design-commit-intent.json"
            ),
        },
        "service_returned_share_url": (
            "https://commoninstant.org/i/5a76bd1b-2db2-463b-b2ad-0b1307102710"
        ),
    }


def _run_positive(root: Path) -> _PositiveRun:
    effects = WaveEffectJournal()
    storage = _install_storage(root / "wave-policy" / "storage")
    candidates = tuple(
        _candidate(root / "candidates", index, journal=effects)
        for index in (1, 2, 3)
    )
    policy = _wave_policy(candidates)
    status = registry_root_status(storage=storage)
    plan = build_wave_plan(
        candidates,
        policy,
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
        _checkpoint(),
    )
    approvals = tuple(_approval(candidate, index) for index, candidate in enumerate(candidates, 1))
    policy_context, _activation_result = _activate_wave(
        root, storage, plan, policy, approvals, effects
    )

    execution_root = root / "engine" / "execution"
    context = _marker_context(root, "engine", execution_root, effects)
    execution_root.mkdir()
    store_context = _marker_context(
        root, "engine", execution_root / "store", effects
    )
    store = RegistrationWaveStore(store_context, store_context.target_root, plan.digest)
    ledger_root = execution_root / "ledger"
    prefix = verify_synthetic_wave_result_prefix(context, plan, store, ledger_root)
    results = []
    readbacks = []
    authorizations = []
    planned_slots = []
    replay_result_digests = []
    readback_repeat_digests = []
    for index in (1, 2, 3):
        request = _slot_request(plan, index, prefix)
        authorization = _execution_authorization(
            plan, policy, request, approvals[index - 1]
        )
        authorizations.append(authorization)
        application_authority = derive_verified_application_authority(
            candidates[index - 1].application_digest,
            authorization,
            _policy_time(),
        )
        planned = plan_wave_slot(
            context,
            candidate=candidates[index - 1],
            wave_plan=plan,
            slot_request=request,
            execution_authorization=authorization,
            result_prefix=prefix,
            policy_context=policy_context,
            policy_storage=storage,
            policy_time=_policy_time(),
            application_authority=application_authority,
            ctcl_receipt=_ctcl(),
            ledger_root=ledger_root,
            staging_parent=execution_root / f"staging-{index}",
        )
        planned_slots.append(planned)
        result = simulate_wave_slot(context, planned, store, time=_policy_time())
        results.append(result)
        replayed = simulate_wave_slot(
            context, planned, store, time=_policy_time()
        )
        replay_result_digests.append(replayed.digest)
        capability = store.get_verified_slot_result(f"slot:{index}")
        if capability is None:
            raise RALValidationError(
                "verified_synthetic_result_required", "result was not durable"
            )
        prefix = verify_synthetic_wave_result_prefix(context, plan, store, ledger_root)
        capabilities = tuple(
            store.get_verified_slot_result(f"slot:{slot_index}")
            for slot_index in range(1, index + 1)
        )
        readback = build_wave_readback_bundle(
            context, ledger_root, result.post_head, plan, capabilities
        )
        repeated_readback = build_wave_readback_bundle(
            context, ledger_root, result.post_head, plan, capabilities
        )
        readbacks.append(readback)
        readback_repeat_digests.append(repeated_readback.digest)

    outcome = {
        "plan_digest": plan.digest,
        "policy_digest": policy.digest,
        "candidate_digests": [candidate.digest for candidate in candidates],
        "approval_digests": [approval.approval.digest for approval in approvals],
        "result_digests": [result.digest for result in results],
        "readback_digests": [bundle.digest for bundle in readbacks],
        "final_head": results[-1].post_head,
        "event_count": prefix.ledger_event_count,
        "effect_refs": {
            name: list(refs) for name, refs in effects.allowed_refs().items()
        },
    }
    return _PositiveRun(
        digest=sha256_ref(outcome),
        effects=effects,
        candidates=candidates,
        approvals=approvals,
        plan=plan,
        policy=policy,
        slot_results=tuple(results),
        readbacks=tuple(readbacks),
        event_count=prefix.ledger_event_count,
        final_head=str(results[-1].post_head),
        context=context,
        store=store,
        storage=storage,
        policy_context=policy_context,
        authorizations=tuple(authorizations),
        planned_slots=tuple(planned_slots),
        replay_result_digests=tuple(replay_result_digests),
        readback_repeat_digests=tuple(readback_repeat_digests),
    )


def _expect_error(code: str, function: Callable[[], object]) -> bool:
    try:
        function()
    except RALValidationError as error:
        return error.code == code or code in error.code
    return False


def _case(
    case_id: str,
    passed: bool,
    evidence: object,
    *,
    executed: bool = True,
    status: str = "PASS",
) -> RegistrationWaveAcceptanceCase:
    canonical_evidence = _json_value(evidence)
    return RegistrationWaveAcceptanceCase(
        case_id=case_id,
        executed=executed,
        passed=passed,
        status=status,
        evidence_digest=sha256_ref(
            {
                "case_id": case_id,
                "status": status,
                "evidence": canonical_evidence,
            }
        ),
        control_evidence=canonical_evidence,
    )


def _json_value(value: object) -> object:
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _fails(function: Callable[[], object]) -> tuple[bool, str]:
    try:
        function()
    except RALValidationError as error:
        return True, error.code
    return False, "accepted"


def _prepare_custom(
    root: Path,
    *,
    index: int = 1,
    claim_value: dict[str, object] | None = None,
    raw_changes: dict[str, object] | None = None,
    item_changes: dict[str, object] | None = None,
    host_changes: dict[str, object] | None = None,
):
    selected_claim = _claim(index) if claim_value is None else claim_value
    raw = _raw_applicant(index, selected_claim, **(raw_changes or {}))
    item_value = _item(
        index, selected_claim, raw, **(item_changes or {})
    )
    host_value = _host(
        index, selected_claim, item_value, **(host_changes or {})
    )
    context = _marker_context(root, "custom", root / "custom" / "target")
    return prepare_wave_candidate(
        context,
        selected_claim,
        item_value,
        host_value,
        raw,
        lambda: _ids(index),
    )


def _verify_recovery_control(planned: object, inspection: object) -> object:
    intent = {
        "schema": "sedb-ral.registration-wave-slot-recovery-intent/0.1",
        "principal_ref": _PRINCIPAL_REF,
        "wave_plan_digest": planned.wave_plan.digest,
        "slot_id": planned.slot_request.slot_id,
        "slot_request_digest": planned.slot_request.digest,
        "original_execution_authorization_digest": planned.execution_authorization.authorization.digest,
        "application_approval_digest": planned.execution_authorization.approval.approval.digest,
        "verified_prefix_digest": inspection.prefix_digest,
        "pre_head": planned.slot_request.expected_ledger_state[
            "expected_ledger_head"
        ],
        "post_head": inspection.current_head,
        "checkpoint_digest": planned.wave_plan.checkpoint_digest,
        "current_readback_digest": inspection.prefix_digest,
    }
    raw = _raw_principal(
        intent, item_ref="user-item:recovery-control", turn_id="turn:recovery-control"
    )
    host = _principal_host(raw)
    artifact = WaveSlotRecoveryAuthorization.sealed(
        {
            "schema": "sedb-ral.registration-wave-slot-recovery-authorization/0.1",
            "recovery_authorization_id": "recovery-authorization:control",
            "principal_ref": _PRINCIPAL_REF,
            "wave_plan_ref": f"registration-wave-plan:{planned.wave_plan.wave_id}",
            "wave_plan_digest": planned.wave_plan.digest,
            "slot_id": planned.slot_request.slot_id,
            "slot_request_ref": planned.slot_request.request_id,
            "slot_request_digest": planned.slot_request.digest,
            "original_execution_authorization_ref": planned.execution_authorization.authorization.execution_authorization_id,
            "original_execution_authorization_digest": planned.execution_authorization.authorization.digest,
            "application_approval_ref": planned.execution_authorization.approval.approval.approval_id,
            "application_approval_digest": planned.execution_authorization.approval.approval.digest,
            "verified_prefix_digest": inspection.prefix_digest,
            "pre_head": planned.slot_request.expected_ledger_state[
                "expected_ledger_head"
            ],
            "post_head": inspection.current_head,
            "checkpoint_ref": planned.wave_plan.checkpoint_ref,
            "checkpoint_digest": planned.wave_plan.checkpoint_digest,
            "current_readback_digest": inspection.prefix_digest,
            "valid_from_ref": "time:start",
            "expires_at_ref": "time:end",
            "status": "active",
            "revoked_by_ref": None,
            "source_user_item_ref": raw.source_item_ref,
            "source_user_item_digest": raw.evidence_digest,
            "host_observation_ref": host.observation_ref,
            "host_observation_digest": host.digest,
            "not_claimed": ["new_admission", "partial_prefix_acceptance"],
        }
    )
    return verify_wave_slot_recovery_authorization(
        artifact,
        inspection,
        planned,
        raw,
        host,
        expected_principal_ref=_PRINCIPAL_REF,
        time=_time(),
    )


def _slot_scenario(root: Path, first: _PositiveRun, name: str):
    target = root / name / "execution"
    context = _marker_context(root, name, target)
    target.mkdir()
    store_context = _marker_context(root, name, target / "store")
    store = RegistrationWaveStore(
        store_context, store_context.target_root, first.plan.digest
    )
    prefix = verify_synthetic_wave_result_prefix(
        context, first.plan, store, target / "ledger"
    )
    request = _slot_request(first.plan, 1, prefix)
    authorization = _execution_authorization(
        first.plan, first.policy, request, first.approvals[0]
    )
    planned = plan_wave_slot(
        context,
        candidate=first.candidates[0],
        wave_plan=first.plan,
        slot_request=request,
        execution_authorization=authorization,
        result_prefix=prefix,
        policy_context=first.policy_context,
        policy_storage=first.storage,
        policy_time=_policy_time(),
        application_authority=derive_verified_application_authority(
            first.candidates[0].application_digest,
            authorization,
            _policy_time(),
        ),
        ctcl_receipt=_ctcl(),
        ledger_root=target / "ledger",
        staging_parent=target / "staging",
    )
    return context, store, planned


def _transaction_controls(root: Path, first: _PositiveRun) -> dict[str, object]:
    before_context, before_store, before_plan = _slot_scenario(
        root, first, "before-append"
    )
    with patch.object(
        wave_engine_module,
        "_before_slot_append",
        side_effect=InjectedWaveSlotCrash("injected before append"),
    ):
        before_fault = None
        try:
            simulate_wave_slot(
                before_context, before_plan, before_store, time=_policy_time()
            )
        except InjectedWaveSlotCrash:
            before_fault = "InjectedWaveSlotCrash"
        else:
            raise AssertionError("before-append fault did not execute")
    before = inspect_wave_slot_prefix(before_context, before_plan, before_store)

    complete_context, complete_store, complete_plan = _slot_scenario(
        root, first, "complete-prefix"
    )
    commit_admission_plan(
        complete_plan.ledger_root,
        complete_plan.registrar_plan,
        complete_plan.candidate.prepared,
        complete_plan.decision,
        complete_plan.application_authority.authority,
        complete_plan.ctcl_receipt,
        verified_attestation_refs=complete_plan.application_authority.attestation_refs,
    )
    complete = inspect_wave_slot_prefix(
        complete_context, complete_plan, complete_store
    )

    partial_context, partial_store, partial_plan = _slot_scenario(
        root, first, "partial-prefix"
    )
    commit_admission_plan(
        partial_plan.ledger_root,
        partial_plan.registrar_plan,
        partial_plan.candidate.prepared,
        partial_plan.decision,
        partial_plan.application_authority.authority,
        partial_plan.ctcl_receipt,
        verified_attestation_refs=partial_plan.application_authority.attestation_refs,
    )
    event_paths = sorted((partial_plan.ledger_root / "events").rglob("*.json"))
    anchor_paths = sorted((partial_plan.ledger_root / "anchors").glob("*.json"))
    for path in event_paths[2:]:
        path.unlink()
    for path in anchor_paths[2:]:
        path.unlink()
    partial = inspect_wave_slot_prefix(partial_context, partial_plan, partial_store)
    partial_refused, partial_reason = _fails(
        lambda: _verify_recovery_control(partial_plan, partial)
    )
    return {
        "before": before.status,
        "before_count": before.event_count,
        "before_fault": before_fault,
        "complete": complete.status,
        "complete_count": complete.event_count,
        "partial": partial.status,
        "partial_count": partial.event_count,
        "partial_recovery_refused": partial_refused,
        "partial_recovery_reason": partial_reason,
    }


def _rebind_policy(
    policy: RegistrationWavePolicy, **changes: object
) -> RegistrationWavePolicy:
    value = policy.to_dict()
    value.update(changes)
    return RegistrationWavePolicy.sealed(value)


def _case_outcomes(
    root: Path, first: _PositiveRun, second: _PositiveRun
) -> dict[str, tuple[bool, object]]:
    plan = first.plan
    outcomes: dict[str, tuple[bool, object]] = {}

    candidate_digests = [value.digest for value in first.candidates]
    locators = [value.canonical_locator for value in first.candidates]
    approval_digests = [value.approval.digest for value in first.approvals]
    result_digests = [value.digest for value in first.slot_results]
    heads = [value.post_head for value in first.slot_results]
    transactions = _transaction_controls(root / "transactions", first)
    empty_prefix = verify_wave_receipt_prefix(plan, ())
    positive_slot_one_request = build_slot_request(
        plan,
        1,
        empty_prefix,
        {
            "expected_ledger_head": None,
            "cli_token": "GENESIS",
            "ledger_event_count": 0,
        },
    )

    outcomes["W1-001"] = (
        len(set(candidate_digests)) == 3,
        candidate_digests,
    )
    failed, code = _fails(
        lambda: build_wave_plan(
            first.candidates[:2], first.policy, _empty_registry_view(plan), _checkpoint()
        )
    )
    outcomes["W1-002"] = (failed, code)
    failed, code = _fails(
        lambda: _candidate(root / "w1-003", 1, opt_in=False)
    )
    outcomes["W1-003"] = (failed, code)
    failed, code = _fails(
        lambda: _prepare_custom(
            root / "w1-004",
            raw_changes={"native_turn_id": "turn:mismatch"},
        )
    )
    outcomes["W1-004"] = (failed, code)
    outcomes["W1-005"] = (len(set(locators)) == 3, locators)
    uppercase_claim = _claim(1)
    uppercase_claim["desired_addresses"][0]["locator"] = (
        "ABCDEFAB-CDEF-4ABC-8ABC-ABCDEFABCDEF"
    )
    failed, code = _fails(
        lambda: _prepare_custom(
            root / "w1-006", claim_value=uppercase_claim
        )
    )
    outcomes["W1-006"] = (failed, code)
    replay = _candidate(root / "w1-007-a", 1)
    replay_two = _candidate(root / "w1-007-b", 1)
    outcomes["W1-007"] = (
        replay.to_dict() == replay_two.to_dict(),
        replay.digest,
    )
    changed = _candidate(
        root / "w1-008", 1, desired_display_label="Changed synthetic seat"
    )
    old_approval_refused, old_approval_reason = _fails(
        lambda: verify_application_approval(
            first.approvals[0].approval,
            changed.prepared.application,
            first.approvals[0].raw_item,
            first.approvals[0].host,
            expected_principal_ref=_PRINCIPAL_REF,
            time=_time(),
        )
    )
    outcomes["W1-008"] = (
        changed.digest != first.candidates[0].digest and old_approval_refused,
        {
            "mutation": "desired_display_label",
            "old_candidate_digest": first.candidates[0].digest,
            "new_candidate_digest": changed.digest,
            "old_approval_reason": old_approval_reason,
            "adjacent_positive": first.approvals[0].verification_digest,
        },
    )
    outcomes["W1-009"] = (
        len(set(approval_digests)) == 3
        and all(value.approval.status == "active" for value in first.approvals),
        approval_digests,
    )
    failed, code = _fails(
        lambda: verify_application_approval(
            first.approvals[0].approval,
            first.candidates[0].prepared.application,
            first.approvals[0].raw_item,
            first.approvals[0].host,
            expected_principal_ref="principal:registrar-self",
            time=_time(),
        )
    )
    outcomes["W1-010"] = (failed, code)
    missing_refused, missing_reason = _fails(
        lambda: require_wave_execution({"wave_status": "absent"})
    )
    unreceipted_refused, unreceipted_reason = _fails(
        lambda: require_wave_execution({"wave_status": "active_unreceipted"})
    )
    outcomes["W1-011"] = (
        missing_refused and unreceipted_refused,
        {
            "mutations": ["missing_policy", "unreceipted_policy"],
            "negative_reasons": [missing_reason, unreceipted_reason],
            "adjacent_positive": first.policy.digest,
        },
    )
    outcomes["W1-012"] = (
        first.slot_results[0].pre_head is None
        and len(first.slot_results[0].appended_events) == 4,
        first.slot_results[0].to_dict(),
    )
    stale_h0_refused, stale_h0_reason = _fails(
        lambda: build_slot_request(
            plan,
            2,
            empty_prefix,
            {
                "expected_ledger_head": None,
                "cli_token": "GENESIS",
                "ledger_event_count": 0,
            },
        )
    )
    outcomes["W1-013"] = (
        stale_h0_refused
        and positive_slot_one_request.slot_index == 1
        and first.slot_results[1].pre_head == first.slot_results[0].post_head,
        {
            "mutation": "slot_2_reuses_H0",
            "negative_reason": stale_h0_reason,
            "adjacent_positive_request": positive_slot_one_request.digest,
        },
    )
    outcomes["W1-014"] = (
        first.slot_results[1].pre_head == heads[0],
        first.slot_results[1].to_dict(),
    )
    outcomes["W1-015"] = (
        first.slot_results[2].pre_head == heads[1],
        first.slot_results[2].to_dict(),
    )
    outcomes["W1-016"] = (
        len(set(result_digests)) == 3
        and list(first.replay_result_digests) == result_digests
        and first.event_count == 12,
        {
            "mutation": "repeat_each_admitted_slot",
            "initial_results": result_digests,
            "replayed_results": list(first.replay_result_digests),
            "event_count_after_replay": first.event_count,
        },
    )
    outcomes["W1-017"] = (
        transactions["before"] == "absent"
        and transactions["before_count"] == 0
        and transactions["before_fault"] == "InjectedWaveSlotCrash",
        transactions,
    )
    outcomes["W1-018"] = (
        list(first.replay_result_digests) == result_digests,
        {
            "mutation": "exact_durable_result_retry",
            "initial": result_digests,
            "retry": list(first.replay_result_digests),
        },
    )
    private_journal = WaveEffectJournal()
    private_context = _marker_context(
        root / "w1-023",
        "private-attempt",
        root / "w1-023" / "private-attempt" / "target",
        private_journal,
    )
    private_context.record_effect("private_reads", "injected:private-request")
    outcomes["W1-023"] = (
        first.policy.capabilities["private_access"] is False
        and private_journal.forbidden_nonzero_dimensions() == ("private_reads",),
        {
            "mutation": "private_read_request_after_public_admission",
            "negative_observed": list(
                private_journal.forbidden_nonzero_dimensions()
            ),
            "adjacent_positive": first.readbacks[-1].digest,
        },
    )
    outcomes["W1-024"] = (
        first.event_count == 12
        and [getattr(first.effects, name) for name in (
            "production_reads",
            "production_writes",
            "private_reads",
            "private_writes",
            "network_calls",
            "provider_calls",
            "fabric_calls",
            "mcp_calls",
            "external_cli_calls",
        )] == [0] * 9,
        first.effects.nonzero_dimensions(),
    )
    outcomes["W1-025"] = (
        first.readbacks[-1].ledger_head == first.final_head
        and first.readbacks[-1].admitted_slot_indexes == [1, 2, 3]
        and [value.digest for value in first.readbacks]
        == list(first.readback_repeat_digests),
        {
            "mutation": "rebuild_each_exact_head_readback",
            "first": [value.digest for value in first.readbacks],
            "rebuilt": list(first.readback_repeat_digests),
        },
    )
    outcomes["W1-026"] = (
        first.digest == second.digest,
        [first.digest, second.digest],
    )
    slot_three_without_two_refused, slot_three_without_two_reason = _fails(
        lambda: build_slot_request(
            plan,
            3,
            empty_prefix,
            {
                "expected_ledger_head": heads[0],
                "cli_token": heads[0],
                "ledger_event_count": 4,
            },
        )
    )
    outcomes["W1-027"] = (
        slot_three_without_two_refused
        and [value.slot_index for value in first.slot_results] == [1, 2, 3],
        {
            "mutation": "slot_3_at_H1_without_slot_2_receipt",
            "negative_reason": slot_three_without_two_reason,
            "adjacent_positive": result_digests[2],
        },
    )
    reversed_policy = _rebind_policy(
        first.policy,
        ordered_application_digests=list(
            reversed(first.policy.ordered_application_digests)
        ),
    )
    failed, code = _fails(
        lambda: build_wave_plan(
            first.candidates,
            reversed_policy,
            _empty_registry_view(plan),
            _checkpoint(),
        )
    )
    outcomes["W1-028"] = (failed, code)
    missing_predecessor_refused, missing_predecessor_reason = _fails(
        lambda: build_slot_request(
            plan,
            2,
            empty_prefix,
            {
                "expected_ledger_head": heads[0],
                "cli_token": heads[0],
                "ledger_event_count": 4,
            },
        )
    )
    outcomes["W1-029"] = (
        missing_predecessor_refused
        and first.slot_results[1].pre_head == heads[0],
        {
            "mutation": "slot_2_missing_predecessor_receipt",
            "negative_reason": missing_predecessor_reason,
            "adjacent_positive": result_digests[1],
        },
    )
    assistant_refused, assistant_reason = _fails(
        lambda: _approval_with_role(first.candidates[0], "assistant")
    )
    forged_refused, forged_reason = _fails(
        lambda: verify_application_approval(
            first.approvals[0].approval,
            first.candidates[0].prepared.application,
            first.approvals[0].raw_item,
            first.approvals[0].host,
            expected_principal_ref="principal:forged",
            time=_time(),
        )
    )
    relayed_refused, relayed_reason = _fails(
        lambda: _approval_with_role(
            first.candidates[0], "user", observed_origin="relay:controller"
        )
    )
    outcomes["W1-030"] = (
        assistant_refused and forged_refused and relayed_refused,
        {
            "mutations": ["assistant_role", "forged_principal", "relay_origin"],
            "negative_reasons": [
                assistant_reason,
                forged_reason,
                relayed_reason,
            ],
            "adjacent_positive": first.approvals[0].verification_digest,
        },
    )
    failed, code = _fails(
        lambda: verify_application_approval(
            first.approvals[0].approval,
            first.candidates[1].prepared.application,
            first.approvals[0].raw_item,
            first.approvals[0].host,
            expected_principal_ref=_PRINCIPAL_REF,
            time=_time(),
        )
    )
    outcomes["W1-031"] = (failed, code)
    failed, code = _fails(
        lambda: plan_wave_slot(
            first.context,
            candidate=first.candidates[0],
            wave_plan=plan,
            slot_request=None,
            execution_authorization=None,
            result_prefix=None,
            policy_context=first.policy_context,
            policy_storage=first.storage,
            policy_time=_policy_time(),
            application_authority=None,
            ctcl_receipt=_ctcl(),
            ledger_root=first.context.target_root / "ledger",
            staging_parent=first.context.target_root / "no-jit",
        )
    )
    outcomes["W1-032"] = (failed, code)
    self_approval_refused, self_approval_reason = _fails(
        lambda: verify_application_approval(
            first.approvals[0].approval,
            first.candidates[0].prepared.application,
            first.approvals[0].raw_item,
            first.approvals[0].host,
            expected_principal_ref="principal:registrar-self:independent-control",
            time=_time(),
        )
    )
    outcomes["W1-033"] = (
        self_approval_refused,
        {
            "mutation": "registrar_self_approval_principal",
            "negative_reason": self_approval_reason,
            "adjacent_positive": first.approvals[0].verification_digest,
        },
    )
    policy_status_controls = {}
    for status_name in ("absent", "active_unreceipted", "expired", "stopped"):
        refused, reason = _fails(
            lambda selected=status_name: require_wave_execution(
                {"wave_status": selected}
            )
        )
        policy_status_controls[status_name] = {
            "refused": refused,
            "reason": reason,
        }
    active_status = registration_wave_status(
        first.policy_context, first.storage, _policy_time()
    )
    active_positive = True
    try:
        require_wave_execution(active_status)
    except RALValidationError:
        active_positive = False
    outcomes["W1-034"] = (
        active_positive
        and all(value["refused"] for value in policy_status_controls.values()),
        {
            "mutations": policy_status_controls,
            "adjacent_positive_status": active_status["wave_status"],
        },
    )
    policy_paths = tuple(
        (
            first.storage.final
            / "extensions/registrar-operations/v1/policies"
        ).glob("wave1-policy-*.json")
    )
    receipt_path = (
        first.storage.final
        / "evidence/registration-wave-policy-activation-00000000000000000001.json"
    )
    policy_value = (
        loads_strict(policy_paths[0].read_text(encoding="utf-8"))
        if len(policy_paths) == 1
        else {}
    )
    same_policy_duplicate = (
        False
        if len(policy_paths) != 1
        else _write_new_or_same(policy_paths[0], policy_value)
    )
    changed_policy_value = dict(policy_value)
    changed_policy_value["not_claimed"] = ["changed-overwrite-attempt"]
    overwrite_refused, overwrite_reason = _fails(
        lambda: _write_new_or_same(policy_paths[0], changed_policy_value)
    ) if len(policy_paths) == 1 else (False, "policy_missing")
    outcomes["W1-035"] = (
        len(policy_paths) == 1
        and receipt_path.is_file()
        and same_policy_duplicate is False
        and overwrite_refused,
        {
            "mutation": "changed_existing_wave_policy_bytes",
            "negative_reason": overwrite_reason,
            "adjacent_positive_duplicate": same_policy_duplicate,
            "policy_digest": None
            if not policy_value
            else sha256_ref(policy_value),
        },
    )
    failed, code = _fails(
        lambda: build_slot_request(
            plan,
            1,
            empty_prefix,
            {
                "expected_ledger_head": plan.registry_control_digest,
                "cli_token": plan.registry_control_digest,
                "ledger_event_count": 0,
            },
        )
    )
    outcomes["W1-036"] = (failed, code)
    outcomes["W1-037"] = (
        transactions["complete"] == "recovery_required"
        and transactions["complete_count"] == 4,
        transactions,
    )
    outcomes["W1-038"] = (
        transactions["partial_recovery_refused"] is True,
        {
            "mutation": "recovery_authority_against_partial_prefix",
            "negative_reason": transactions["partial_recovery_reason"],
            "adjacent_positive": transactions["complete"],
        },
    )
    expired_context, expired_store, expired_plan = _slot_scenario(
        root / "w1-039", first, "expired-pending"
    )
    expired_refused, expired_reason = _fails(
        lambda: simulate_wave_slot(
            expired_context,
            expired_plan,
            expired_store,
            time=_policy_time(now=400, expires_at=300),
        )
    )
    expired_inspection = inspect_wave_slot_prefix(
        expired_context, expired_plan, expired_store
    )
    outcomes["W1-039"] = (
        expired_refused
        and expired_inspection.status == "absent"
        and expired_inspection.event_count == 0,
        {
            "mutation": "expired_policy_with_pending_slot",
            "negative_reason": expired_reason,
            "post_state": expired_inspection.status,
            "adjacent_positive": result_digests[0],
        },
    )
    continuation_context, continuation_store, continuation_plan_one = _slot_scenario(
        root / "w1-040", first, "old-authority"
    )
    simulate_wave_slot(
        continuation_context,
        continuation_plan_one,
        continuation_store,
        time=_policy_time(),
    )
    continuation_prefix = verify_synthetic_wave_result_prefix(
        continuation_context,
        first.plan,
        continuation_store,
        continuation_plan_one.ledger_root,
    )
    continuation_request = _slot_request(first.plan, 2, continuation_prefix)
    old_authority_refused, old_authority_reason = _fails(
        lambda: plan_wave_slot(
            continuation_context,
            candidate=first.candidates[1],
            wave_plan=first.plan,
            slot_request=continuation_request,
            execution_authorization=continuation_plan_one.execution_authorization,
            result_prefix=continuation_prefix,
            policy_context=first.policy_context,
            policy_storage=first.storage,
            policy_time=_policy_time(),
            application_authority=continuation_plan_one.application_authority,
            ctcl_receipt=_ctcl(),
            ledger_root=continuation_plan_one.ledger_root,
            staging_parent=continuation_context.target_root / "stale-authority",
        )
    )
    outcomes["W1-040"] = (
        old_authority_refused and continuation_prefix.ledger_event_count == 4,
        {
            "mutation": "slot_2_reuses_slot_1_execution_authority",
            "negative_reason": old_authority_reason,
            "adjacent_positive": result_digests[1],
        },
    )
    braced_claim = _claim(1)
    braced_claim["desired_addresses"][0]["locator"] = "{" + _THREADS[0] + "}"
    braced_refused, braced_reason = _fails(
        lambda: _prepare_custom(
            root / "w1-041-braced", claim_value=braced_claim
        )
    )
    unicode_claim = _claim(1)
    unicode_claim["desired_addresses"][0]["locator"] = _THREADS[0].replace(
        "-", "‐"
    )
    unicode_refused, unicode_reason = _fails(
        lambda: _prepare_custom(
            root / "w1-041-unicode", claim_value=unicode_claim
        )
    )
    outcomes["W1-041"] = (
        outcomes["W1-006"][0] and braced_refused and unicode_refused,
        {
            "mutations": ["uppercase", "braced", "unicode_hyphen"],
            "negative_reasons": [
                outcomes["W1-006"][1],
                braced_reason,
                unicode_reason,
            ],
            "adjacent_positive": first.candidates[0].verification_digest,
        },
    )
    duplicate_claim = _claim(3)
    duplicate_claim["desired_addresses"][0]["locator"] = _THREADS[0]
    duplicate_candidate = _prepare_custom(
        root / "w1-042",
        index=3,
        claim_value=duplicate_claim,
        raw_changes={
            "native_thread_id": _THREADS[0],
            "source_item_parent_thread_id": _THREADS[0],
        },
        host_changes={"native_thread_id": _THREADS[0]},
    )
    duplicate_candidates = (
        first.candidates[0],
        first.candidates[1],
        duplicate_candidate,
    )
    failed, code = _fails(
        lambda: RegistrationWavePolicy.sealed(
            {
                **first.policy.to_dict(),
                "ordered_application_digests": [
                    value.application_digest for value in duplicate_candidates
                ],
                "ordered_locators": [
                    value.canonical_locator for value in duplicate_candidates
                ],
            }
        )
    )
    outcomes["W1-042"] = (failed, code)
    failed, code = _fails(
        lambda: _prepare_custom(
            root / "w1-043",
            host_changes={"canonical_claim_digest": _digest("other-claim")},
        )
    )
    outcomes["W1-043"] = (failed, code)
    failed, code = _fails(
        lambda: _prepare_custom(
            root / "w1-044",
            raw_changes={"applicant_item_ref": "item:unrelated"},
        )
    )
    outcomes["W1-044"] = (failed, code)
    failed, code = _fails(
        lambda: _candidate(root / "w1-045", 1, continuity_claim="continue")
    )
    outcomes["W1-045"] = (failed, code)
    failed_candidate_refused, failed_candidate_reason = _fails(
        lambda: _candidate(root / "w1-046-failed", 3, opt_in=False)
    )
    two_candidate_policy_refused, two_candidate_reason = _fails(
        lambda: build_wave_plan(
            first.candidates[:2],
            first.policy,
            _empty_registry_view(plan),
            _checkpoint(),
        )
    )
    outcomes["W1-046"] = (
        failed_candidate_refused
        and two_candidate_policy_refused
        and not (root / "w1-046-failed" / "candidate-3" / "target").exists(),
        {
            "mutation": "third_candidate_opt_out_before_policy_activation",
            "negative_reasons": [
                failed_candidate_reason,
                two_candidate_reason,
            ],
            "adjacent_positive": first.plan.digest,
        },
    )
    outcomes["W1-049"] = (
        transactions["partial"] == "registrar_partial_transaction"
        and transactions["partial_count"] == 2,
        transactions,
    )
    failed, code = _fails(
        lambda: _prepare_custom(
            root / "w1-050",
            raw_changes={
                "source_item_role": "user",
                "source_item_kind": "userMessage",
            },
        )
    )
    outcomes["W1-050"] = (failed, code)
    failed, code = _fails(
        lambda: _prepare_custom(
            root / "w1-051",
            raw_changes={"source_item_kind": "toolCall"},
        )
    )
    outcomes["W1-051"] = (failed, code)
    failed, code = _fails(
        lambda: prepare_wave_candidate(
            _marker_context(
                root / "w1-052",
                "missing-item",
                root / "w1-052" / "missing-item" / "target",
            ),
            _claim(1),
            None,
            _host(1),
            _raw_applicant(1),
            lambda: _ids(1),
        )
    )
    outcomes["W1-052"] = (failed, code)
    parsed_item = ApplicantItemEvidence.from_dict(_item(1))
    outcomes["W1-053"] = (
        parsed_item.source_item_role == "assistant"
        and parsed_item.source_item_kind == "agentMessage"
        and parsed_item.source_item_status == "completed",
        parsed_item.digest,
    )
    return outcomes


def _empty_registry_view(plan: object) -> dict[str, object]:
    return {
        "verified": True,
        "registry_control_digest": plan.registry_control_digest,
        "registry_generation_digest": plan.registry_generation_digest,
        "ledger_head": None,
        "ledger_event_count": 0,
        "application_count": 0,
        "resident_count": 0,
        "address_count": 0,
    }


def _effect_injection_controls(root: Path) -> dict[str, bool]:
    dimensions = (
        "production_reads",
        "production_writes",
        "private_reads",
        "private_writes",
        "network_calls",
        "provider_calls",
        "fabric_calls",
        "mcp_calls",
        "external_cli_calls",
    )
    result: dict[str, bool] = {}
    for dimension in dimensions:
        journal = WaveEffectJournal()
        context = _marker_context(
            root,
            f"effect-{dimension}",
            root / f"effect-{dimension}" / "target",
            journal,
        )
        context.record_effect(dimension, f"injected:{dimension}")
        result[dimension] = journal.forbidden_nonzero_dimensions() == (dimension,)
    return result


def validate_registration_wave(root: Path) -> RegistrationWaveAcceptanceReport:
    selected_root = Path(root).resolve(strict=False)
    selected_root.mkdir(parents=True, exist_ok=True)
    first = _run_positive(selected_root / "run-a")
    second = _run_positive(selected_root / "run-b")
    return _build_acceptance_report(selected_root, first, second)


def _build_acceptance_report(
    selected_root: Path, first: _PositiveRun, second: _PositiveRun
) -> RegistrationWaveAcceptanceReport:
    outcomes = _case_outcomes(selected_root / "cases", first, second)
    controls = _effect_injection_controls(selected_root / "effect-controls")
    passed, evidence = outcomes["W1-024"]
    outcomes["W1-024"] = (
        passed and all(controls.values()),
        {"positive": evidence, "injected_controls": controls},
    )

    cases: list[RegistrationWaveAcceptanceCase] = []
    for index in range(1, 54):
        case_id = f"W1-{index:03d}"
        if case_id in OWNER_PLAN_CASES:
            cases.append(
                _case(
                    case_id,
                    True,
                    {
                        "owner": "LIMEN",
                        "production_wave_run": "NOT_RUN",
                        "live_limen_b6a": "NOT_RUN",
                    },
                    executed=False,
                    status="NOT_RUN_OWNER_PLAN_REQUIRED",
                )
            )
            continue
        passed, evidence = outcomes.get(
            case_id, (False, "acceptance_case_not_executed")
        )
        cases.append(
            _case(
                case_id,
                passed,
                {
                    "population": CASE_POPULATIONS[case_id],
                    "negative_and_adjacent_positive": evidence,
                    "adjacent_positive_run_digest": first.digest,
                },
            )
        )

    material = {
        "case_digests": [case.evidence_digest for case in cases],
        "first_run_digest": first.digest,
        "second_run_digest": second.digest,
        "effect_refs": {
            name: list(refs) for name, refs in first.effects.allowed_refs().items()
        },
        "production_wave_run": "NOT_RUN",
        "live_limen_b6a": "NOT_RUN",
        "production_root_status": "NOT_READ",
    }
    return RegistrationWaveAcceptanceReport(
        cases=tuple(cases),
        effects=first.effects,
        first_run_digest=first.digest,
        second_run_digest=second.digest,
        report_digest=sha256_ref(material),
    )


def write_registration_wave_report(
    report: RegistrationWaveAcceptanceReport, output: Path
) -> None:
    payload = canonical_bytes(report.as_json())
    try:
        with Path(output).open("xb") as stream:
            stream.write(payload)
    except FileExistsError as error:
        raise RALValidationError("output_exists", "report output already exists") from error
