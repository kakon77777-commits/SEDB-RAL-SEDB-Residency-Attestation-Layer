from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .errors import RALValidationError
from .registration_wave_authority import (
    PrincipalHostObservation,
    RawPrincipalItemSnapshot,
    VerifiedApplicationApproval,
    VerifiedAuthorityTimeEvidence,
    _verify_user_item,
)
from .registration_wave_context import SyntheticWaveExecutionContext
from .registration_wave_models import (
    ActiveWavePolicyRecord,
    PrincipalApplicationApproval,
    RegistrationWavePlan,
    RegistrationWavePolicy,
    WavePolicyActivationAuthority,
    WavePolicyActivationReceipt,
    WavePolicyActivationRequest,
    WaveTerminalEvent,
)
from .registry_root import RegistryStorage, registry_root_status

_POLICY_AUTHORITY_TOKEN = object()
_POLICY_TERMINAL_AUTHORITY_TOKEN = object()


class InjectedWavePolicyCrash(RuntimeError):
    pass


def _after_active_record_published() -> None:
    return None


@dataclass(frozen=True)
class VerifiedWavePolicyActivationAuthority:
    authority: WavePolicyActivationAuthority
    request_digest: str
    plan_digest: str
    raw_item: RawPrincipalItemSnapshot = field(repr=False)
    host: PrincipalHostObservation
    issuance_time: VerifiedAuthorityTimeEvidence
    verification_digest: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _POLICY_AUTHORITY_TOKEN:
            raise RALValidationError(
                "verified_wave_policy_authority_required",
                "Wave policy authority was not verifier-issued",
            )

    def verify(self) -> None:
        self.host.verify()
        self.issuance_time.verify()
        material = {
            "authority_digest": self.authority.digest,
            "request_digest": self.request_digest,
            "plan_digest": self.plan_digest,
            "raw_item_digest": self.raw_item.evidence_digest,
            "host_observation_digest": self.host.digest,
            "issuance_time_digest": self.issuance_time.verification_digest,
        }
        if sha256_ref(material) != self.verification_digest:
            raise RALValidationError(
                "verified_wave_policy_authority_required",
                "Wave policy authority capability digest differs",
            )

    def verify_current(self, time: VerifiedAuthorityTimeEvidence) -> None:
        self.verify()
        if not isinstance(time, VerifiedAuthorityTimeEvidence):
            raise RALValidationError(
                "verified_authority_time_required",
                "fresh Wave policy authority time is required",
            )
        time.verify_against(self.issuance_time)


@dataclass(frozen=True)
class VerifiedWavePolicyTerminalAuthority:
    authority_ref: str
    authority_digest: str
    authority_value: dict[str, object]
    plan_digest: str
    policy_digest: str
    raw_item: RawPrincipalItemSnapshot = field(repr=False)
    host: PrincipalHostObservation
    issuance_time: VerifiedAuthorityTimeEvidence
    verification_digest: str
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _POLICY_TERMINAL_AUTHORITY_TOKEN:
            raise RALValidationError(
                "verified_wave_policy_terminal_authority_required",
                "terminal authority was not verifier-issued",
            )

    def verify(self) -> None:
        self.host.verify()
        self.issuance_time.verify()
        material_value = dict(self.authority_value)
        observed_digest = material_value.pop("authority_digest", None)
        if observed_digest != self.authority_digest or sha256_ref(material_value) != observed_digest:
            raise RALValidationError(
                "verified_wave_policy_terminal_authority_required",
                "terminal authority bytes differ",
            )
        material = {
            "authority_ref": self.authority_ref,
            "authority_digest": self.authority_digest,
            "plan_digest": self.plan_digest,
            "policy_digest": self.policy_digest,
            "raw_item_digest": self.raw_item.evidence_digest,
            "host_observation_digest": self.host.digest,
            "issuance_time_digest": self.issuance_time.verification_digest,
        }
        if sha256_ref(material) != self.verification_digest:
            raise RALValidationError(
                "verified_wave_policy_terminal_authority_required",
                "terminal authority capability digest differs",
            )

    def verify_current(self, time: VerifiedAuthorityTimeEvidence) -> None:
        self.verify()
        if not isinstance(time, VerifiedAuthorityTimeEvidence):
            raise RALValidationError(
                "verified_authority_time_required",
                "fresh terminal authority time is required",
            )
        time.verify_against(self.issuance_time)

@dataclass(frozen=True)
class WavePolicyActivationResult:
    record: ActiveWavePolicyRecord
    receipt: WavePolicyActivationReceipt
    record_ref: str
    receipt_ref: str


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    canonical = loads_strict(canonical_bytes(dict(value)).decode("utf-8"))
    if not isinstance(canonical, dict):
        raise TypeError("Wave policy value must remain an object")
    return canonical


def _read_object(path: Path, code: str) -> dict[str, object]:
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RALValidationError(code, "Wave policy JSON cannot be read") from error
    if not isinstance(value, dict):
        raise RALValidationError(code, "Wave policy JSON must be an object")
    return value


def _write_new_or_same(path: Path, value: Mapping[str, object]) -> bool:
    content = canonical_bytes(dict(value))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise RALValidationError(
                "wave_policy_immutable_conflict",
                "existing Wave policy bytes differ",
            )
        return False
    return True


def _version_root(storage: RegistryStorage) -> Path:
    return storage.final / "extensions/registrar-operations/v1"


def _policy_path(storage: RegistryStorage, policy_digest: str) -> Path:
    suffix = policy_digest.rsplit(":", 1)[-1]
    return _version_root(storage) / f"policies/wave1-policy-{suffix}.json"


def _active_record_path(storage: RegistryStorage, sequence: int) -> Path:
    return _version_root(storage) / f"active-policy/{sequence:020d}.json"


def activation_receipt_path(storage: RegistryStorage, sequence: int) -> Path:
    return (
        storage.final
        / f"evidence/registration-wave-policy-activation-{sequence:020d}.json"
    )


def _digest_suffix(value: str) -> str:
    return value.rsplit(":", 1)[-1]


def _request_path(storage: RegistryStorage, digest: str) -> Path:
    return _version_root(storage) / (
        f"requests/wave-policy-activation-{_digest_suffix(digest)}.json"
    )


def _activation_authority_path(storage: RegistryStorage, digest: str) -> Path:
    return _version_root(storage) / (
        f"audit/wave-policy-activation-authority-{_digest_suffix(digest)}.json"
    )


def _terminal_authority_path(storage: RegistryStorage, digest: str) -> Path:
    return _version_root(storage) / (
        f"audit/wave-policy-terminal-authority-{_digest_suffix(digest)}.json"
    )


def _acl_path(storage: RegistryStorage, digest: str) -> Path:
    return _version_root(storage) / (
        f"audit/wave-policy-acl-{_digest_suffix(digest)}.json"
    )


def _approval_path(storage: RegistryStorage, digest: str) -> Path:
    return _version_root(storage) / (
        f"audit/application-approval-{_digest_suffix(digest)}.json"
    )


def _parse_plan(value: Mapping[str, object] | RegistrationWavePlan) -> RegistrationWavePlan:
    return value if isinstance(value, RegistrationWavePlan) else RegistrationWavePlan.from_dict(value)


def _parse_policy(
    value: Mapping[str, object] | RegistrationWavePolicy,
) -> RegistrationWavePolicy:
    return value if isinstance(value, RegistrationWavePolicy) else RegistrationWavePolicy.from_dict(value)


def _verify_approvals(
    approvals: Sequence[VerifiedApplicationApproval],
    plan: RegistrationWavePlan,
) -> tuple[VerifiedApplicationApproval, ...]:
    if len(approvals) != 3 or any(
        not isinstance(value, VerifiedApplicationApproval) for value in approvals
    ):
        raise RALValidationError(
            "wave_exact_three_approvals_required",
            "Wave policy requires three verified application approvals",
        )
    parsed = tuple(approvals)
    for value in parsed:
        value.verify()
    expected = [slot["application_digest"] for slot in plan.ordered_slots]
    observed = [value.application_digest for value in parsed]
    approval_digests = [value.approval.digest for value in parsed]
    if observed != expected or len(set(approval_digests)) != 3:
        raise RALValidationError(
            "wave_exact_three_approvals_required",
            "approval order or identity differs from the Wave plan",
        )
    return parsed


def plan_wave_policy_activation(
    plan: Mapping[str, object] | RegistrationWavePlan,
    approvals: Sequence[VerifiedApplicationApproval],
    policy: Mapping[str, object] | RegistrationWavePolicy,
    checkpoint: Mapping[str, object],
    registry_status: Mapping[str, object],
) -> WavePolicyActivationRequest:
    parsed_plan = _parse_plan(plan)
    parsed_policy = _parse_policy(policy)
    verified_approvals = _verify_approvals(approvals, parsed_plan)
    status = _canonical_object(registry_status)
    checkpoint_value = _canonical_object(checkpoint)
    if (
        parsed_policy.policy_id != parsed_plan.policy_ref
        or parsed_policy.digest != parsed_plan.policy_digest
        or status.get("extensions_status") != "active_dormant"
        or status.get("activation_receipt_status") != "verified"
        or status.get("wave_status") not in {None, "absent"}
        or status.get("registry_generation_digest")
        != parsed_plan.registry_generation_digest
        or checkpoint_value.get("checkpoint_ref") != parsed_plan.checkpoint_ref
        or checkpoint_value.get("checkpoint_digest") != parsed_plan.checkpoint_digest
        or checkpoint_value.get("ledger_head") is not None
        or not status.get("dormant_active_policy_ref")
        or not status.get("dormant_active_policy_digest")
    ):
        raise RALValidationError(
            "wave_policy_activation_precondition_mismatch",
            "dormant extension, policy, checkpoint, or plan bindings differ",
        )
    approval_digests = [value.approval.digest for value in verified_approvals]
    seed = sha256_ref(
        {
            "plan_digest": parsed_plan.digest,
            "policy_digest": parsed_policy.digest,
            "application_approval_digests": approval_digests,
            "predecessor_digest": status["dormant_active_policy_digest"],
        }
    )
    return WavePolicyActivationRequest.sealed(
        {
            "schema": "sedb-ral.registration-wave-policy-activation-request/0.1",
            "request_id": f"wave-policy-activation-request:{seed.rsplit(':', 1)[-1][:24]}",
            "wave_plan_ref": f"registration-wave-plan:{parsed_plan.wave_id}",
            "wave_plan_digest": parsed_plan.digest,
            "policy_ref": parsed_policy.policy_id,
            "policy_digest": parsed_policy.digest,
            "application_approval_digests": approval_digests,
            "expected_predecessor_record_ref": status[
                "dormant_active_policy_ref"
            ],
            "expected_predecessor_record_digest": status[
                "dormant_active_policy_digest"
            ],
            "registry_generation_digest": status["registry_generation_digest"],
            "checkpoint_ref": parsed_plan.checkpoint_ref,
            "checkpoint_digest": parsed_plan.checkpoint_digest,
            "requested_at_ref": "time:synthetic-wave-policy-request",
            "not_claimed": ["ledger_append", "resident_registration"],
        }
    )


def verify_wave_policy_activation_authority(
    authority: Mapping[str, object] | WavePolicyActivationAuthority,
    request: Mapping[str, object] | WavePolicyActivationRequest,
    plan: Mapping[str, object] | RegistrationWavePlan,
    principal_item: RawPrincipalItemSnapshot,
    host_observation: PrincipalHostObservation,
    *,
    expected_principal_ref: str,
    time: VerifiedAuthorityTimeEvidence,
) -> VerifiedWavePolicyActivationAuthority:
    if not isinstance(time, VerifiedAuthorityTimeEvidence):
        raise RALValidationError(
            "verified_authority_time_required",
            "Wave policy authority requires verified time evidence",
        )
    parsed = (
        authority
        if isinstance(authority, WavePolicyActivationAuthority)
        else WavePolicyActivationAuthority.from_dict(authority)
    )
    parsed_request = (
        request
        if isinstance(request, WavePolicyActivationRequest)
        else WavePolicyActivationRequest.from_dict(request)
    )
    parsed_plan = _parse_plan(plan)
    expected_intent = {
        "schema": "sedb-ral.registration-wave-policy-activation-intent/0.1",
        "principal_ref": expected_principal_ref,
        "request_ref": parsed_request.request_id,
        "request_digest": parsed_request.digest,
        "policy_ref": parsed_plan.policy_ref,
        "policy_digest": parsed_plan.policy_digest,
        "target_ref": parsed.target_ref,
        "operation": "registration.wave-policy.activate",
    }
    _verify_user_item(principal_item, host_observation, expected_intent)
    if (
        parsed.principal_ref != expected_principal_ref
        or parsed.operation != "registration.wave-policy.activate"
        or parsed.request_ref != parsed_request.request_id
        or parsed.request_digest != parsed_request.digest
        or parsed.policy_ref != parsed_plan.policy_ref
        or parsed.policy_digest != parsed_plan.policy_digest
        or parsed.source_user_item_ref != principal_item.source_item_ref
        or parsed.source_user_item_digest != principal_item.evidence_digest
        or parsed.host_observation_ref != host_observation.observation_ref
        or parsed.host_observation_digest != host_observation.digest
        or parsed.status != "active"
    ):
        raise RALValidationError(
            "wave_policy_activation_authority_mismatch",
            "Wave policy activation authority bindings differ",
        )
    time.verify_current(parsed.valid_from_ref, parsed.expires_at_ref)
    material = {
        "authority_digest": parsed.digest,
        "request_digest": parsed_request.digest,
        "plan_digest": parsed_plan.digest,
        "raw_item_digest": principal_item.evidence_digest,
        "host_observation_digest": host_observation.digest,
        "issuance_time_digest": time.verification_digest,
    }
    return VerifiedWavePolicyActivationAuthority(
        authority=parsed,
        request_digest=parsed_request.digest,
        plan_digest=parsed_plan.digest,
        raw_item=principal_item,
        host=host_observation,
        issuance_time=time,
        verification_digest=sha256_ref(material),
        _token=_POLICY_AUTHORITY_TOKEN,
    )


def verify_wave_policy_terminal_authority(
    authority: Mapping[str, object],
    plan: Mapping[str, object] | RegistrationWavePlan,
    policy: Mapping[str, object] | RegistrationWavePolicy,
    principal_item: RawPrincipalItemSnapshot,
    host_observation: PrincipalHostObservation,
    *,
    expected_principal_ref: str,
    time: VerifiedAuthorityTimeEvidence,
) -> VerifiedWavePolicyTerminalAuthority:
    if not isinstance(time, VerifiedAuthorityTimeEvidence):
        raise RALValidationError(
            "verified_authority_time_required",
            "terminal authority requires verified time evidence",
        )
    canonical = _canonical_object(authority)
    material = dict(canonical)
    actual_digest = material.pop("authority_digest", None)
    required = {
        "schema",
        "authority_ref",
        "principal_ref",
        "operation",
        "wave_plan_digest",
        "policy_digest",
        "valid_from_ref",
        "expires_at_ref",
        "status",
        "source_user_item_ref",
        "source_user_item_digest",
        "host_observation_ref",
        "host_observation_digest",
    }
    parsed_plan = _parse_plan(plan)
    parsed_policy = _parse_policy(policy)
    expected_intent = {
        "schema": "sedb-ral.registration-wave-terminal-intent/0.1",
        "principal_ref": expected_principal_ref,
        "operation": "registration.wave-policy.terminate",
        "wave_plan_digest": parsed_plan.digest,
        "policy_digest": parsed_policy.digest,
    }
    _verify_user_item(principal_item, host_observation, expected_intent)
    if (
        set(material) != required
        or material["schema"]
        != "sedb-ral.registration-wave-terminal-authority/0.1"
        or actual_digest != sha256_ref(material)
        or material["principal_ref"] != expected_principal_ref
        or material["operation"] != "registration.wave-policy.terminate"
        or material["wave_plan_digest"] != parsed_plan.digest
        or material["policy_digest"] != parsed_policy.digest
        or material["status"] != "active"
        or material["source_user_item_ref"] != principal_item.source_item_ref
        or material["source_user_item_digest"] != principal_item.evidence_digest
        or material["host_observation_ref"] != host_observation.observation_ref
        or material["host_observation_digest"] != host_observation.digest
    ):
        raise RALValidationError(
            "wave_policy_terminal_authority_mismatch",
            "Wave policy terminal authority bindings differ",
        )
    time.verify_current(material["valid_from_ref"], material["expires_at_ref"])
    verification_material = {
        "authority_ref": material["authority_ref"],
        "authority_digest": actual_digest,
        "plan_digest": parsed_plan.digest,
        "policy_digest": parsed_policy.digest,
        "raw_item_digest": principal_item.evidence_digest,
        "host_observation_digest": host_observation.digest,
        "issuance_time_digest": time.verification_digest,
    }
    return VerifiedWavePolicyTerminalAuthority(
        authority_ref=str(material["authority_ref"]),
        authority_digest=str(actual_digest),
        authority_value=canonical,
        plan_digest=parsed_plan.digest,
        policy_digest=parsed_policy.digest,
        raw_item=principal_item,
        host=host_observation,
        issuance_time=time,
        verification_digest=sha256_ref(verification_material),
        _token=_POLICY_TERMINAL_AUTHORITY_TOKEN,
    )


def _verify_acl(value: Mapping[str, object]) -> dict[str, object]:
    canonical = _canonical_object(value)
    material = dict(canonical)
    actual = material.pop("observation_digest", None)
    if (
        set(material)
        != {
            "schema",
            "observation_ref",
            "protected",
            "forbidden_writer_count",
            "observed_at_ref",
        }
        or material["schema"] != "sedb-ral.wave-policy-acl-observation/0.1"
        or material["protected"] is not True
        or material["forbidden_writer_count"] != 0
        or actual != sha256_ref(material)
    ):
        raise RALValidationError(
            "wave_policy_acl_invalid", "Wave policy ACL observation differs"
        )
    canonical["observation_digest"] = actual
    return canonical


def _record_ref(sequence: int) -> str:
    return f"active-policy/{sequence:020d}.json"


def _receipt_ref(sequence: int) -> str:
    return f"evidence/registration-wave-policy-activation-{sequence:020d}.json"


def _terminal_ref(sequence: int) -> str:
    return f"evidence/registration-wave-policy-terminal-{sequence:020d}.json"


def _activation_pre_status_digest(status: Mapping[str, object]) -> str:
    return sha256_ref(
        {
            "extensions_status": status["extensions_status"],
            "activation_receipt_status": status["activation_receipt_status"],
            "extension_index_digest": status["extension_index_digest"],
            "registry_generation_digest": status["registry_generation_digest"],
            "dormant_policy_digest": status["dormant_policy_digest"],
            "dormant_active_policy_digest": status[
                "dormant_active_policy_digest"
            ],
        }
    )


def _expected_post_status_digest(record: ActiveWavePolicyRecord) -> str:
    return sha256_ref(
        {
            "sequence": record.sequence,
            "record_digest": record.digest,
            "wave_status": record.status,
            "activation_receipt_status": "verified",
        }
    )


def activate_wave_policy(
    context: SyntheticWaveExecutionContext,
    storage: RegistryStorage,
    request: Mapping[str, object] | WavePolicyActivationRequest,
    approvals: Sequence[VerifiedApplicationApproval],
    authority: VerifiedWavePolicyActivationAuthority,
    acl_observation: Mapping[str, object],
    *,
    policy: Mapping[str, object] | RegistrationWavePolicy,
    plan: Mapping[str, object] | RegistrationWavePlan,
    time: VerifiedAuthorityTimeEvidence,
) -> WavePolicyActivationResult:
    if not isinstance(time, VerifiedAuthorityTimeEvidence):
        raise RALValidationError(
            "verified_authority_time_required",
            "Wave policy activation requires fresh verified time",
        )
    parsed_plan = _parse_plan(plan)
    parsed_policy = _parse_policy(policy)
    verified_approvals = _verify_approvals(approvals, parsed_plan)
    if not isinstance(authority, VerifiedWavePolicyActivationAuthority):
        raise RALValidationError(
            "verified_wave_policy_authority_required",
            "plain authority artifacts cannot activate Wave policy",
        )
    authority.verify_current(time)
    for approval in verified_approvals:
        approval.verify_current(time)
    parsed_request = (
        request
        if isinstance(request, WavePolicyActivationRequest)
        else WavePolicyActivationRequest.from_dict(request)
    )
    acl = _verify_acl(acl_observation)
    time.verify(parsed_policy.valid_from_ref, parsed_policy.expires_at_ref)
    expected_approval_digests = [
        value.approval.digest for value in verified_approvals
    ]
    if (
        authority.request_digest != parsed_request.digest
        or authority.plan_digest != parsed_plan.digest
        or parsed_request.wave_plan_digest != parsed_plan.digest
        or parsed_request.policy_digest != parsed_policy.digest
        or list(parsed_request.application_approval_digests)
        != expected_approval_digests
    ):
        raise RALValidationError(
            "wave_policy_activation_binding_mismatch",
            "request, authority, approvals, plan, or policy differ",
        )
    context.verify_before_io("policy_activate", storage.final)
    status = registry_root_status(storage=storage)
    if status.get("wave_status") not in {"absent", "active_unreceipted"}:
        raise RALValidationError(
            "wave_policy_already_active", "Wave policy already has a terminal receipt"
        )
    if (
        parsed_request.expected_predecessor_record_ref
        != status["dormant_active_policy_ref"]
        or parsed_request.expected_predecessor_record_digest
        != status["dormant_active_policy_digest"]
        or parsed_request.registry_generation_digest
        != status["registry_generation_digest"]
        or parsed_request.checkpoint_digest != parsed_plan.checkpoint_digest
    ):
        raise RALValidationError(
            "wave_policy_activation_binding_mismatch",
            "current dormant status differs from activation request",
        )
    policy_path = _policy_path(storage, parsed_policy.digest)
    record_path = _active_record_path(storage, 1)
    receipt_path = activation_receipt_path(storage, 1)
    evidence_values = [
        (
            _request_path(storage, parsed_request.digest),
            parsed_request.to_dict(),
            f"wave-policy-request:{parsed_request.digest}",
        ),
        (
            _activation_authority_path(storage, authority.authority.digest),
            authority.authority.to_dict(),
            f"wave-policy-authority:{authority.authority.digest}",
        ),
        (
            _acl_path(storage, str(acl["observation_digest"])),
            acl,
            f"wave-policy-acl:{acl['observation_digest']}",
        ),
        *[
            (
                _approval_path(storage, value.approval.digest),
                value.approval.to_dict(),
                f"application-approval:{value.approval.digest}",
            )
            for value in verified_approvals
        ],
    ]
    record = ActiveWavePolicyRecord.sealed(
        {
            "schema": "sedb-ral.registration-wave-active-policy-record/0.1",
            "record_id": "active-policy:1",
            "sequence": 1,
            "predecessor_record_ref": status["dormant_active_policy_ref"],
            "predecessor_record_digest": status["dormant_active_policy_digest"],
            "dormant_policy_digest": status["dormant_policy_digest"],
            "wave_policy_ref": parsed_policy.policy_id,
            "wave_policy_digest": parsed_policy.digest,
            "registry_generation_digest": status["registry_generation_digest"],
            "extension_index_digest": status["extension_index_digest"],
            "checkpoint_ref": parsed_plan.checkpoint_ref,
            "checkpoint_digest": parsed_plan.checkpoint_digest,
            "activation_authority_ref": authority.authority.authority_id,
            "activation_authority_digest": authority.authority.digest,
            "activation_request_ref": parsed_request.request_id,
            "activation_request_digest": parsed_request.digest,
            "status": "active",
            "valid_until_ref": parsed_policy.expires_at_ref,
            "not_claimed": ["resident_registration", "private_access"],
        }
    )
    for path, value, ref in (
        *evidence_values,
        (policy_path, parsed_policy.to_dict(), parsed_policy.policy_id),
        (record_path, record.to_dict(), _record_ref(1)),
    ):
        context.verify_before_io("policy_write", path)
        if _write_new_or_same(path, value):
            context.record_effect("staging_writes", ref)
    _after_active_record_published()
    receipt = WavePolicyActivationReceipt.sealed(
        {
            "schema": "sedb-ral.registration-wave-policy-activation-receipt/0.1",
            "receipt_id": "receipt:wave-policy-activation:1",
            "policy_ref": parsed_policy.policy_id,
            "policy_digest": parsed_policy.digest,
            "active_policy_ref": record.record_id,
            "active_policy_digest": record.digest,
            "predecessor_record_ref": status["dormant_active_policy_ref"],
            "predecessor_record_digest": status[
                "dormant_active_policy_digest"
            ],
            "registry_generation_digest": status["registry_generation_digest"],
            "extension_index_digest": status["extension_index_digest"],
            "checkpoint_ref": parsed_plan.checkpoint_ref,
            "checkpoint_digest": parsed_plan.checkpoint_digest,
            "authority_ref": authority.authority.authority_id,
            "authority_digest": authority.authority.digest,
            "request_ref": parsed_request.request_id,
            "request_digest": parsed_request.digest,
            "application_approval_digests": expected_approval_digests,
            "acl_observation_ref": acl["observation_ref"],
            "acl_observation_digest": acl["observation_digest"],
            "pre_status_digest": _activation_pre_status_digest(status),
            "post_status_digest": _expected_post_status_digest(record),
            "status": "activated",
            "observed_at_ref": time.now_ref,
            "not_claimed": ["resident_registration", "private_access"],
        }
    )
    context.verify_before_io("policy_receipt_write", receipt_path)
    if _write_new_or_same(receipt_path, receipt.to_dict()):
        context.record_effect("staging_writes", _receipt_ref(1))
        context.record_effect("synthetic_receipt_writes", _receipt_ref(1))
    verified_status = registry_root_status(storage=storage)
    if (
        verified_status.get("wave_status") != "active"
        or verified_status.get("wave_activation_receipt_status") != "verified"
    ):
        raise RALValidationError(
            "wave_policy_activation_readback_failed",
            "Wave policy record and receipt did not verify after write",
        )
    return WavePolicyActivationResult(
        record=record,
        receipt=receipt,
        record_ref=_record_ref(1),
        receipt_ref=_receipt_ref(1),
    )


def _read_activation_receipt_evidence(
    storage: RegistryStorage,
    receipt: WavePolicyActivationReceipt,
) -> tuple[
    WavePolicyActivationRequest,
    WavePolicyActivationAuthority,
    dict[str, object],
    tuple[PrincipalApplicationApproval, ...],
]:
    try:
        request = WavePolicyActivationRequest.from_dict(
            _read_object(
                _request_path(storage, receipt.request_digest),
                "wave_policy_activation_request_invalid_json",
            )
        )
        authority = WavePolicyActivationAuthority.from_dict(
            _read_object(
                _activation_authority_path(storage, receipt.authority_digest),
                "wave_policy_activation_authority_invalid_json",
            )
        )
        acl = _verify_acl(
            _read_object(
                _acl_path(storage, receipt.acl_observation_digest),
                "wave_policy_acl_invalid_json",
            )
        )
        approvals = tuple(
            PrincipalApplicationApproval.from_dict(
                _read_object(
                    _approval_path(storage, approval_digest),
                    "wave_policy_approval_invalid_json",
                )
            )
            for approval_digest in receipt.application_approval_digests
        )
    except RALValidationError as error:
        raise RALValidationError(
            "wave_policy_activation_receipt_mismatch",
            "activation receipt evidence is missing or invalid",
        ) from error
    return request, authority, acl, approvals


def wave_policy_status_fields(
    registry_root: Path,
    version_root: Path,
    base_status: Mapping[str, object],
) -> dict[str, object]:
    status_storage = RegistryStorage(
        parent=registry_root.parent,
        final=registry_root,
        synthetic_mode=True,
    )
    active_root = version_root / "active-policy"
    files = sorted(path for path in active_root.glob("*.json") if path.name != "00000000000000000000.json")
    if not files:
        return {
            "wave_status": "absent",
            "wave_policy_ref": None,
            "wave_policy_digest": None,
            "wave_policy_sequence": 0,
            "wave_activation_receipt_status": "absent",
            "wave_policy_valid_from_ref": None,
            "wave_policy_expires_at_ref": None,
        }
    previous_ref = base_status["dormant_active_policy_ref"]
    previous_digest = base_status["dormant_active_policy_digest"]
    latest_record = None
    latest_policy = None
    latest_receipt_status = "missing"
    for expected_sequence, path in enumerate(files, start=1):
        if path.name != f"{expected_sequence:020d}.json":
            raise RALValidationError(
                "wave_policy_sequence_invalid", "Wave active-policy sequence is not contiguous"
            )
        record = ActiveWavePolicyRecord.from_dict(
            _read_object(path, "wave_active_policy_invalid_json")
        )
        policy_path = _policy_path(status_storage, record.wave_policy_digest)
        policy = RegistrationWavePolicy.from_dict(
            _read_object(policy_path, "wave_policy_invalid_json")
        )
        if (
            record.sequence != expected_sequence
            or record.predecessor_record_ref != previous_ref
            or record.predecessor_record_digest != previous_digest
            or record.dormant_policy_digest != base_status["dormant_policy_digest"]
            or record.registry_generation_digest
            != base_status["registry_generation_digest"]
            or record.extension_index_digest != base_status["extension_index_digest"]
            or record.wave_policy_ref != policy.policy_id
            or record.wave_policy_digest != policy.digest
        ):
            raise RALValidationError(
                "wave_policy_record_mismatch", "Wave policy chain bindings differ"
            )
        receipt_path = registry_root / _receipt_ref(expected_sequence)
        terminal_path = registry_root / _terminal_ref(expected_sequence)
        if record.status != "active":
            if not terminal_path.is_file():
                raise RALValidationError(
                    "wave_policy_terminal_event_missing",
                    "terminal Wave policy record lacks terminal event",
                )
            terminal = WaveTerminalEvent.from_dict(
                _read_object(terminal_path, "wave_policy_terminal_event_invalid_json")
            )
            terminal_authority = _read_object(
                _terminal_authority_path(
                    status_storage, terminal.authority_digest
                ),
                "wave_policy_terminal_authority_invalid_json",
            )
            terminal_authority_material = dict(terminal_authority)
            terminal_authority_digest = terminal_authority_material.pop(
                "authority_digest", None
            )
            if terminal.digest != record.activation_request_digest:
                raise RALValidationError(
                    "wave_policy_terminal_event_mismatch",
                    "terminal event digest differs from active record",
                )
            if (
                terminal.event_id != record.activation_request_ref
                or terminal.policy_ref != policy.policy_id
                or terminal.policy_digest != policy.digest
                or terminal.previous_record_ref != previous_ref
                or terminal.previous_record_digest != previous_digest
                or terminal.terminal_status != record.status
                or terminal.authority_ref != record.activation_authority_ref
                or terminal.authority_digest != record.activation_authority_digest
                or terminal_authority_digest != terminal.authority_digest
                or sha256_ref(terminal_authority_material)
                != terminal_authority_digest
                or terminal_authority.get("authority_ref")
                != terminal.authority_ref
                or terminal_authority.get("operation")
                != "registration.wave-policy.terminate"
                or terminal_authority.get("policy_digest") != policy.digest
                or terminal_authority.get("wave_plan_digest")
                != terminal.wave_plan_digest
                or terminal_authority.get("status") != "active"
            ):
                raise RALValidationError(
                    "wave_policy_terminal_event_mismatch",
                    "terminal event bindings differ",
                )
            latest_receipt_status = "terminal_event_verified"
        elif receipt_path.is_file():
            receipt = WavePolicyActivationReceipt.from_dict(
                _read_object(receipt_path, "wave_policy_activation_receipt_invalid_json")
            )
            request, authority, acl, approvals = _read_activation_receipt_evidence(
                status_storage, receipt
            )
            if (
                receipt.policy_ref != policy.policy_id
                or receipt.policy_digest != policy.digest
                or receipt.active_policy_ref != record.record_id
                or receipt.active_policy_digest != record.digest
                or receipt.predecessor_record_ref != previous_ref
                or receipt.predecessor_record_digest != previous_digest
                or receipt.registry_generation_digest
                != base_status["registry_generation_digest"]
                or receipt.extension_index_digest
                != base_status["extension_index_digest"]
                or receipt.checkpoint_ref != record.checkpoint_ref
                or receipt.checkpoint_digest != record.checkpoint_digest
                or receipt.authority_ref != record.activation_authority_ref
                or receipt.authority_digest != record.activation_authority_digest
                or receipt.request_ref != record.activation_request_ref
                or receipt.request_digest != record.activation_request_digest
                or request.request_id != receipt.request_ref
                or request.digest != receipt.request_digest
                or request.policy_digest != policy.digest
                or list(request.application_approval_digests)
                != list(receipt.application_approval_digests)
                or authority.authority_id != receipt.authority_ref
                or authority.digest != receipt.authority_digest
                or authority.request_ref != request.request_id
                or authority.request_digest != request.digest
                or authority.policy_digest != policy.digest
                or acl["observation_ref"] != receipt.acl_observation_ref
                or acl["observation_digest"] != receipt.acl_observation_digest
                or [approval.digest for approval in approvals]
                != list(receipt.application_approval_digests)
                or [approval.application_digest for approval in approvals]
                != list(policy.ordered_application_digests)
                or any(approval.status != "active" for approval in approvals)
                or receipt.pre_status_digest
                != _activation_pre_status_digest(base_status)
                or receipt.post_status_digest != _expected_post_status_digest(record)
            ):
                raise RALValidationError(
                    "wave_policy_activation_receipt_mismatch",
                    "Wave policy activation receipt binds another record",
                )
            latest_receipt_status = "verified"
        elif expected_sequence != len(files):
            raise RALValidationError(
                "wave_policy_unreceipted", "intermediate Wave policy record lacks receipt"
            )
        else:
            latest_receipt_status = "missing"
        previous_ref = _record_ref(expected_sequence)
        previous_digest = record.digest
        latest_record = record
        latest_policy = policy
    if latest_record is None or latest_policy is None:
        raise AssertionError("unreachable Wave status branch")
    wave_status = (
        latest_record.status
        if latest_receipt_status in {"verified", "terminal_event_verified"}
        else "active_unreceipted"
    )
    return {
        "wave_status": wave_status,
        "wave_policy_ref": latest_policy.policy_id,
        "wave_policy_digest": latest_policy.digest,
        "wave_policy_sequence": latest_record.sequence,
        "wave_active_record_ref": _record_ref(latest_record.sequence),
        "wave_active_record_digest": latest_record.digest,
        "wave_checkpoint_ref": latest_record.checkpoint_ref,
        "wave_checkpoint_digest": latest_record.checkpoint_digest,
        "wave_activation_receipt_status": latest_receipt_status,
        "wave_policy_valid_from_ref": latest_policy.valid_from_ref,
        "wave_policy_expires_at_ref": latest_policy.expires_at_ref,
    }


def registration_wave_status(
    context: SyntheticWaveExecutionContext,
    storage: RegistryStorage,
    time: VerifiedAuthorityTimeEvidence,
) -> dict[str, object]:
    if not isinstance(time, VerifiedAuthorityTimeEvidence):
        raise RALValidationError(
            "verified_authority_time_required",
            "Wave policy status requires verified time",
        )
    context.verify_before_io("policy_status", storage.final)
    status = registry_root_status(storage=storage)
    if status.get("wave_status") == "active":
        try:
            time.verify(
                status["wave_policy_valid_from_ref"],
                status["wave_policy_expires_at_ref"],
            )
        except RALValidationError as error:
            if error.code != "authority_time_inactive":
                raise
            status = {**status, "wave_status": "expired"}
    return status


def require_wave_execution(status: Mapping[str, object]) -> None:
    if status.get("wave_status") == "active_unreceipted":
        raise RALValidationError(
            "wave_policy_unreceipted", "Wave policy activation receipt is absent"
        )
    if (
        status.get("wave_status") != "active"
        or status.get("wave_activation_receipt_status") != "verified"
    ):
        raise RALValidationError(
            "wave_policy_inactive", "Wave policy is not active and receipted"
        )


def terminate_wave_policy(
    context: SyntheticWaveExecutionContext,
    storage: RegistryStorage,
    terminal_event: Mapping[str, object] | WaveTerminalEvent,
    authority: VerifiedWavePolicyTerminalAuthority,
    *,
    time: VerifiedAuthorityTimeEvidence,
) -> ActiveWavePolicyRecord:
    if not isinstance(authority, VerifiedWavePolicyTerminalAuthority):
        raise RALValidationError(
            "verified_wave_policy_terminal_authority_required",
            "plain terminal authority cannot stop Wave policy",
        )
    if not isinstance(time, VerifiedAuthorityTimeEvidence):
        raise RALValidationError(
            "verified_authority_time_required",
            "Wave policy termination requires fresh verified time",
        )
    authority.verify_current(time)
    terminal = (
        terminal_event
        if isinstance(terminal_event, WaveTerminalEvent)
        else WaveTerminalEvent.from_dict(terminal_event)
    )
    context.verify_before_io("policy_terminate", storage.final)
    status = registry_root_status(storage=storage)
    if status.get("wave_status") != "active":
        raise RALValidationError(
            "wave_policy_inactive", "only active Wave policy can terminate"
        )
    time.verify(
        status["wave_policy_valid_from_ref"], status["wave_policy_expires_at_ref"]
    )
    if (
        terminal.wave_plan_digest != authority.plan_digest
        or terminal.policy_ref != status["wave_policy_ref"]
        or terminal.policy_digest != authority.policy_digest
        or terminal.policy_digest != status["wave_policy_digest"]
        or terminal.previous_record_ref != status["wave_active_record_ref"]
        or terminal.previous_record_digest != status["wave_active_record_digest"]
        or terminal.authority_ref != authority.authority_ref
        or terminal.authority_digest != authority.authority_digest
        or terminal.terminal_status not in {"stopped", "completed", "expired", "revoked"}
    ):
        raise RALValidationError(
            "wave_policy_terminal_event_mismatch",
            "terminal event differs from current Wave policy",
        )
    sequence = int(status["wave_policy_sequence"]) + 1
    terminal_path = storage.final / _terminal_ref(sequence)
    authority_path = _terminal_authority_path(storage, authority.authority_digest)
    record_path = _active_record_path(storage, sequence)
    record = ActiveWavePolicyRecord.sealed(
        {
            "schema": "sedb-ral.registration-wave-active-policy-record/0.1",
            "record_id": f"active-policy:{sequence}",
            "sequence": sequence,
            "predecessor_record_ref": status["wave_active_record_ref"],
            "predecessor_record_digest": status["wave_active_record_digest"],
            "dormant_policy_digest": status["dormant_policy_digest"],
            "wave_policy_ref": status["wave_policy_ref"],
            "wave_policy_digest": status["wave_policy_digest"],
            "registry_generation_digest": status["registry_generation_digest"],
            "extension_index_digest": status["extension_index_digest"],
            "checkpoint_ref": status["wave_checkpoint_ref"],
            "checkpoint_digest": status["wave_checkpoint_digest"],
            "activation_authority_ref": authority.authority_ref,
            "activation_authority_digest": authority.authority_digest,
            "activation_request_ref": terminal.event_id,
            "activation_request_digest": terminal.digest,
            "status": terminal.terminal_status,
            "valid_until_ref": status["wave_policy_expires_at_ref"],
            "not_claimed": ["rollback", "deletion", "private_access"],
        }
    )
    for path, value, ref in (
        (
            authority_path,
            authority.authority_value,
            f"wave-policy-terminal-authority:{authority.authority_digest}",
        ),
        (terminal_path, terminal.to_dict(), _terminal_ref(sequence)),
        (record_path, record.to_dict(), _record_ref(sequence)),
    ):
        context.verify_before_io("policy_terminal_write", path)
        if _write_new_or_same(path, value):
            context.record_effect("staging_writes", ref)
    verified = registry_root_status(storage=storage)
    if verified.get("wave_status") != terminal.terminal_status:
        raise RALValidationError(
            "wave_policy_terminal_readback_failed",
            "terminal Wave policy record did not verify",
        )
    return record
