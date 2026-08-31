from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path

from .canonical import canonical_bytes, loads_strict
from .errors import RALValidationError
from .registration import RegistrationIds
from .registration_wave_authority import (
    PrincipalHostObservation,
    RawPrincipalItemSnapshot,
    derive_verified_application_authority,
    observe_synthetic_authority_time,
    verify_application_approval,
    verify_authority_time_evidence,
    verify_slot_execution_authorization,
)
from .registration_wave_context import (
    SyntheticWaveExecutionContext,
    WaveEffectJournal,
    WaveExecutionMode,
)
from .registration_wave_engine import (
    PlannedWaveSlot,
    plan_wave_slot,
    simulate_wave_slot,
    verify_synthetic_wave_result_prefix,
)
from .registration_wave_intake import (
    RawApplicantItemSnapshot,
    VerifiedPreparedCandidate,
    prepare_wave_candidate,
    verify_applicant_item_evidence,
)
from .registration_wave_models import (
    PrincipalApplicationApproval,
    RegistrationWavePlan,
    RegistrationWavePolicy,
    SlotExecutionAuthorization,
    WaveSlotRecoveryAuthorization,
    WaveSlotRequest,
)
from .registration_wave_plan import build_wave_plan
from .registration_wave_policy import (
    plan_wave_policy_activation,
    registration_wave_status,
)
from .registration_wave_readback import build_wave_readback_bundle
from .registration_wave_recovery import (
    inspect_wave_slot_prefix,
    recover_synthetic_wave_slot_result,
    verify_wave_slot_recovery_authorization,
)
from .registration_wave_store import RegistrationWaveStore
from .registry_root import RegistryStorage


class _TransportError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def add_registration_wave_parser(commands) -> None:
    wave = commands.add_parser(
        "registration-wave", help="run the synthetic-only three-seat Wave candidate"
    )
    sub = wave.add_subparsers(dest="registration_wave_command")
    for name in (
        "validate-intake",
        "prepare-slot",
        "build-plan",
        "policy-plan",
        "policy-status",
        "slot-plan",
        "slot-admit",
        "slot-recover",
        "wave-status",
        "export-readback",
    ):
        parser = sub.add_parser(name)
        parser.add_argument("request", type=Path)
        parser.add_argument("--output", type=Path)
        if name in {"slot-admit", "slot-recover"}:
            parser.add_argument("--synthetic-root", type=Path)


def _emit(value: object, output: Path | None = None) -> None:
    payload = canonical_bytes(value)
    if output is not None:
        try:
            with output.open("xb") as stream:
                stream.write(payload)
        except FileExistsError as error:
            raise RALValidationError("output_exists", "output already exists") from error
        except OSError as error:
            raise RALValidationError(
                "output_unwritable", "output cannot be written"
            ) from error
    sys.stdout.buffer.write(payload + b"\n")


def _read(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as error:
        raise _TransportError("input_not_utf8") from error
    except OSError as error:
        raise _TransportError("input_unreadable") from error
    try:
        value = loads_strict(text)
    except (json.JSONDecodeError, RALValidationError) as error:
        raise _TransportError("input_invalid_json") from error
    if not isinstance(value, dict):
        raise RALValidationError("wave_cli_request_invalid", "request must be an object")
    return value


def _object(value: object, code: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RALValidationError(code, "value must be an object")
    return value


def _sequence(value: object, code: str) -> list[object]:
    if not isinstance(value, list):
        raise RALValidationError(code, "value must be an array")
    return value


def _context(value: object) -> SyntheticWaveExecutionContext:
    selected = _object(value, "synthetic_wave_context_invalid")
    required = {
        "mode",
        "fixture_root",
        "target_root",
        "fixture_marker_ref",
        "fixture_marker_digest",
        "forbidden_roots",
    }
    if set(selected) != required:
        raise RALValidationError(
            "synthetic_wave_context_invalid", "context fields differ"
        )
    forbidden = _sequence(
        selected["forbidden_roots"], "synthetic_wave_context_invalid"
    )
    if not all(isinstance(item, str) for item in forbidden):
        raise RALValidationError(
            "synthetic_wave_context_invalid", "forbidden roots must be strings"
        )
    return SyntheticWaveExecutionContext.sealed(
        mode=WaveExecutionMode(str(selected["mode"])),
        fixture_root=Path(str(selected["fixture_root"])),
        target_root=Path(str(selected["target_root"])),
        fixture_marker_ref=str(selected["fixture_marker_ref"]),
        fixture_marker_digest=str(selected["fixture_marker_digest"]),
        forbidden_roots=tuple(Path(item) for item in forbidden),
        journal=WaveEffectJournal(),
    )


def _raw_applicant(value: object) -> RawApplicantItemSnapshot:
    selected = _object(value, "applicant_raw_item_invalid")
    content = _object(selected.get("content"), "applicant_raw_item_invalid")
    fields = {
        "provider",
        "adapter_kind",
        "native_thread_id",
        "native_turn_id",
        "source_item_role",
        "source_item_kind",
        "source_item_status",
        "source_item_parent_thread_id",
        "source_item_parent_turn_id",
        "applicant_item_ref",
        "content",
    }
    if set(selected) != fields:
        raise RALValidationError(
            "applicant_raw_item_invalid", "raw applicant fields differ"
        )
    return RawApplicantItemSnapshot(
        provider=str(selected["provider"]),
        adapter_kind=str(selected["adapter_kind"]),
        native_thread_id=str(selected["native_thread_id"]),
        native_turn_id=str(selected["native_turn_id"]),
        source_item_role=str(selected["source_item_role"]),
        source_item_kind=str(selected["source_item_kind"]),
        source_item_status=str(selected["source_item_status"]),
        source_item_parent_thread_id=str(selected["source_item_parent_thread_id"]),
        source_item_parent_turn_id=str(selected["source_item_parent_turn_id"]),
        applicant_item_ref=str(selected["applicant_item_ref"]),
        content_bytes=canonical_bytes(content),
    )


def _raw_principal(value: object) -> RawPrincipalItemSnapshot:
    selected = _object(value, "principal_raw_item_invalid")
    content = _object(selected.get("content"), "principal_raw_item_invalid")
    fields = {
        "provider",
        "adapter_kind",
        "native_thread_id",
        "native_turn_id",
        "source_item_role",
        "source_item_kind",
        "source_item_status",
        "source_item_parent_thread_id",
        "source_item_parent_turn_id",
        "source_item_ref",
        "content",
    }
    if set(selected) != fields:
        raise RALValidationError(
            "principal_raw_item_invalid", "raw principal fields differ"
        )
    return RawPrincipalItemSnapshot(
        provider=str(selected["provider"]),
        adapter_kind=str(selected["adapter_kind"]),
        native_thread_id=str(selected["native_thread_id"]),
        native_turn_id=str(selected["native_turn_id"]),
        source_item_role=str(selected["source_item_role"]),
        source_item_kind=str(selected["source_item_kind"]),
        source_item_status=str(selected["source_item_status"]),
        source_item_parent_thread_id=str(selected["source_item_parent_thread_id"]),
        source_item_parent_turn_id=str(selected["source_item_parent_turn_id"]),
        source_item_ref=str(selected["source_item_ref"]),
        content_bytes=canonical_bytes(content),
    )


def _principal_host(value: object) -> PrincipalHostObservation:
    selected = _object(value, "principal_host_observation_invalid")
    try:
        host = PrincipalHostObservation(**selected)
    except TypeError as error:
        raise RALValidationError(
            "principal_host_observation_invalid", "host fields differ"
        ) from error
    host.verify()
    return host


def _time(value: object):
    selected = _object(value, "authority_time_invalid")
    required = {
        "now_ref",
        "now_epoch_ns",
        "valid_from_ref",
        "valid_from_epoch_ns",
        "expires_at_ref",
        "expires_at_epoch_ns",
    }
    if set(selected) != required:
        raise RALValidationError("authority_time_invalid", "time fields differ")
    return verify_authority_time_evidence(
        observe_synthetic_authority_time(
            now_ref=str(selected["now_ref"]),
            now_epoch_ns=int(selected["now_epoch_ns"]),
            valid_from_ref=str(selected["valid_from_ref"]),
            valid_from_epoch_ns=int(selected["valid_from_epoch_ns"]),
            expires_at_ref=(
                None
                if selected["expires_at_ref"] is None
                else str(selected["expires_at_ref"])
            ),
            expires_at_epoch_ns=(
                None
                if selected["expires_at_epoch_ns"] is None
                else int(selected["expires_at_epoch_ns"])
            ),
        )
    )


def _ids(value: object) -> RegistrationIds:
    selected = _object(value, "registration_ids_invalid")
    return RegistrationIds.from_dict(selected)


def _candidate(
    value: object, *, context_override: SyntheticWaveExecutionContext | None = None
) -> VerifiedPreparedCandidate:
    selected = _object(value, "wave_candidate_input_invalid")
    candidate_context = context_override or _context(selected.get("context"))
    raw = _raw_applicant(selected.get("raw_item"))
    ids = _ids(selected.get("ids"))
    return prepare_wave_candidate(
        candidate_context,
        _object(selected.get("claim"), "self_application_claim_invalid"),
        _object(selected.get("item"), "applicant_item_evidence_invalid"),
        _object(selected.get("host"), "registration_host_observation_invalid"),
        raw,
        lambda: ids,
    )


def _candidate_with_shared_context(
    value: object, context: SyntheticWaveExecutionContext
) -> VerifiedPreparedCandidate:
    selected = dict(_object(value, "wave_candidate_input_invalid"))
    selected.pop("context", None)
    return _candidate(selected, context_override=context)


def _plan_request(value: Mapping[str, object]) -> tuple[
    RegistrationWavePlan,
    tuple[VerifiedPreparedCandidate, ...],
]:
    context = _context(value.get("context"))
    candidates = tuple(
        _candidate_with_shared_context(item, context)
        for item in _sequence(value.get("candidates"), "wave_candidates_invalid")
    )
    plan = build_wave_plan(
        candidates,
        RegistrationWavePolicy.from_dict(
            _object(value.get("policy"), "registration_wave_policy_invalid")
        ),
        _object(
            value.get("plan_registry_status", value.get("registry_status")),
            "registry_status_invalid",
        ),
        _object(value.get("checkpoint"), "checkpoint_invalid"),
    )
    return plan, candidates


def _approval(value: object, candidate: VerifiedPreparedCandidate, time):
    selected = _object(value, "application_approval_input_invalid")
    return verify_application_approval(
        PrincipalApplicationApproval.from_dict(
            _object(selected.get("approval"), "application_approval_invalid")
        ),
        candidate.prepared.application,
        _raw_principal(selected.get("raw_item")),
        _principal_host(selected.get("host")),
        expected_principal_ref=str(selected.get("expected_principal_ref")),
        time=time,
    )


def _plan_and_approvals(value: Mapping[str, object]):
    plan, candidates = _plan_request(value)
    time = _time(value.get("authority_time", value.get("time")))
    approval_values = _sequence(value.get("approvals"), "wave_approvals_invalid")
    if len(approval_values) != len(candidates):
        raise RALValidationError(
            "wave_exact_three_approvals_required", "approval count differs"
        )
    approvals = tuple(
        _approval(item, candidate, time)
        for item, candidate in zip(approval_values, candidates, strict=True)
    )
    return plan, candidates, approvals, time


def _store(value: Mapping[str, object], plan: RegistrationWavePlan):
    context = _context(value.get("store_context"))
    return RegistrationWaveStore(
        context,
        Path(str(value.get("store_root"))),
        plan.digest,
    )


def _planned_slot(value: Mapping[str, object]) -> tuple[
    PlannedWaveSlot,
    RegistrationWaveStore,
    SyntheticWaveExecutionContext,
]:
    plan, candidates, approvals, time = _plan_and_approvals(value)
    policy_time = _time(value.get("policy_time", value.get("time")))
    slot_index = int(value.get("slot_index", 0))
    if slot_index not in {1, 2, 3}:
        raise RALValidationError("wave_slot_index_invalid", "slot index is invalid")
    store = _store(value, plan)
    context = _context(value.get("execution_context"))
    ledger_root = Path(str(value.get("ledger_root")))
    prefix = verify_synthetic_wave_result_prefix(context, plan, store, ledger_root)
    request = WaveSlotRequest.from_dict(
        _object(value.get("slot_request"), "wave_slot_request_invalid")
    )
    authorization_input = _object(
        value.get("execution_authorization"), "slot_execution_authorization_invalid"
    )
    raw = _raw_principal(authorization_input.get("raw_item"))
    host = _principal_host(authorization_input.get("host"))
    policy = RegistrationWavePolicy.from_dict(
        _object(value.get("policy"), "registration_wave_policy_invalid")
    )
    authorization = verify_slot_execution_authorization(
        SlotExecutionAuthorization.from_dict(
            _object(
                authorization_input.get("authorization"),
                "slot_execution_authorization_invalid",
            )
        ),
        plan,
        request,
        approvals[slot_index - 1],
        policy,
        _object(value.get("checkpoint"), "checkpoint_invalid"),
        _object(value.get("current_status"), "wave_current_status_invalid"),
        raw,
        host,
        expected_principal_ref=str(
            authorization_input.get("expected_principal_ref")
        ),
        time=time,
    )
    application_authority = derive_verified_application_authority(
        candidates[slot_index - 1].application_digest,
        authorization,
        time,
    )
    policy_context = _context(value.get("policy_context"))
    policy_storage = RegistryStorage.synthetic(
        Path(str(value.get("synthetic_storage_root")))
    )
    planned = plan_wave_slot(
        context,
        candidate=candidates[slot_index - 1],
        wave_plan=plan,
        slot_request=request,
        execution_authorization=authorization,
        result_prefix=prefix,
        policy_context=policy_context,
        policy_storage=policy_storage,
        policy_time=policy_time,
        application_authority=application_authority,
        ctcl_receipt=_object(value.get("ctcl_receipt"), "ctcl_receipt_invalid"),
        ledger_root=ledger_root,
        staging_parent=Path(str(value.get("staging_parent"))),
    )
    return planned, store, context


def _effect_value(context: SyntheticWaveExecutionContext) -> dict[str, object]:
    journal = context.journal
    return {
        name: getattr(journal, name)
        for name in (
            "fixture_reads",
            "staging_writes",
            "synthetic_ledger_writes",
            "synthetic_receipt_writes",
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
    }


def _handle(value: dict[str, object], command: str) -> object:
    if command == "validate-intake":
        verified = verify_applicant_item_evidence(
            _object(value.get("claim"), "self_application_claim_invalid"),
            _object(value.get("item"), "applicant_item_evidence_invalid"),
            _object(value.get("host"), "registration_host_observation_invalid"),
            _raw_applicant(value.get("raw_item")),
        )
        return {
            "schema": "sedb-ral.registration-wave-intake-validation/0.1",
            "verified": True,
            "item_evidence_digest": verified.item.digest,
            "host_observation_digest": verified.host.digest,
            "canonical_claim_digest": verified.claim_digest,
            "verification_digest": verified.verification_digest,
        }
    if command == "prepare-slot":
        verified = _candidate(value)
        return verified.to_dict()
    if command == "build-plan":
        return _plan_request(value)[0].to_dict()
    if command == "policy-plan":
        plan, _candidates, approvals, _time_value = _plan_and_approvals(value)
        request = plan_wave_policy_activation(
            plan,
            approvals,
            RegistrationWavePolicy.from_dict(
                _object(value.get("policy"), "registration_wave_policy_invalid")
            ),
            _object(value.get("checkpoint"), "checkpoint_invalid"),
            _object(value.get("registry_status"), "registry_status_invalid"),
        )
        return request.to_dict()
    if command in {"policy-status", "wave-status"}:
        context = _context(value.get("context"))
        status = registration_wave_status(
            context,
            RegistryStorage.synthetic(
                Path(str(value.get("synthetic_storage_root")))
            ),
            _time(value.get("time")),
        )
        return {**status, "effects": _effect_value(context)}
    if command == "slot-plan":
        planned, _store_value, _context_value = _planned_slot(value)
        return {
            "schema": "sedb-ral.synthetic-wave-slot-plan-summary/0.1",
            "plan_digest": planned.plan_digest,
            "wave_plan_digest": planned.wave_plan.digest,
            "slot_request_digest": planned.slot_request.digest,
            "candidate_digest": planned.candidate.digest,
            "decision": planned.decision.decision,
            "execution_scope": "synthetic",
            "production_wave_run": "NOT_RUN",
        }
    if command == "slot-admit":
        planned, store, context = _planned_slot(value)
        result = simulate_wave_slot(
            context,
            planned,
            store,
            time=planned.policy_time,
        )
        return result.to_dict()
    if command == "slot-recover":
        planned, store, context = _planned_slot(value)
        inspection = inspect_wave_slot_prefix(
            context, planned, store
        )
        recovery_input = _object(
            value.get("recovery_authorization"),
            "wave_recovery_authorization_invalid",
        )
        raw = _raw_principal(recovery_input.get("raw_item"))
        host = _principal_host(recovery_input.get("host"))
        authority = verify_wave_slot_recovery_authorization(
            WaveSlotRecoveryAuthorization.from_dict(
                _object(
                    recovery_input.get("authorization"),
                    "wave_recovery_authorization_invalid",
                )
            ),
            inspection,
            planned,
            raw,
            host,
            expected_principal_ref=str(
                recovery_input.get("expected_principal_ref")
            ),
            time=planned.policy_time,
        )
        return recover_synthetic_wave_slot_result(
            context,
            authority,
            inspection,
            planned,
            store,
            time=planned.policy_time,
        ).to_dict()
    if command == "export-readback":
        context = _context(value.get("context"))
        plan = RegistrationWavePlan.from_dict(
            _object(value.get("plan"), "registration_wave_plan_invalid")
        )
        store = _store(value, plan)
        identifiers = _sequence(
            value.get("slot_result_ids"), "wave_slot_result_ids_invalid"
        )
        if not identifiers or not all(isinstance(item, str) for item in identifiers):
            raise RALValidationError(
                "wave_slot_result_ids_invalid", "slot IDs must be strings"
            )
        capabilities = tuple(store.get_verified_slot_result(item) for item in identifiers)
        if any(item is None for item in capabilities):
            raise RALValidationError(
                "verified_synthetic_result_required", "slot result is absent"
            )
        return build_wave_readback_bundle(
            context,
            Path(str(value.get("ledger_root"))),
            str(value.get("expected_head")),
            plan,
            capabilities,
        ).to_dict()
    raise RALValidationError("cli_usage_error", "unknown registration-wave command")


def handle_registration_wave(args) -> int:
    command = args.registration_wave_command
    if command in {"slot-admit", "slot-recover"} and args.synthetic_root is None:
        _emit(
            {
                "decision": "reject",
                "reason_codes": ["production_wave_execution_not_authorized"],
            }
        )
        return 2
    try:
        request = _read(args.request)
        if command in {"slot-admit", "slot-recover"}:
            execution_context = _object(
                request.get("execution_context"), "synthetic_wave_context_invalid"
            )
            if Path(str(execution_context.get("target_root"))).resolve(
                strict=False
            ) != args.synthetic_root.resolve(strict=False):
                raise RALValidationError(
                    "synthetic_wave_boundary_refused",
                    "explicit synthetic root differs from the sealed context",
                )
        result = _handle(request, command)
        _emit(result, args.output)
        return 0
    except _TransportError as error:
        _emit({"decision": "error", "reason_codes": [error.code]})
        return 1
    except (RALValidationError, OSError, UnicodeError, KeyError, TypeError) as error:
        code = error.code if isinstance(error, RALValidationError) else "input_invalid"
        _emit({"decision": "reject", "reason_codes": [code]})
        return 2
