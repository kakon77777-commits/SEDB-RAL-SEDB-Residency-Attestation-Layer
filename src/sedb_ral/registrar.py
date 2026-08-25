from __future__ import annotations

import shutil
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from .application import (
    application_digest,
    authority_digest,
    commit_application,
)
from .canonical import sha256_ref
from .ctcl import validate_ctcl_receipt
from .errors import RALValidationError
from .ledger import LedgerStatus, read_verified_events, verify_ledger
from .projection import (
    RegistryProjection,
    continuity_line_for,
    project_events,
)
from .registration import (
    PreparedRegistration,
    validate_prepared_registration,
)
from .registration_admission import (
    RegistrationDecision,
    evaluate_prepared_registration,
)
from .sqlite_projection import rebuild_sqlite

_PLAN_NOT_CLAIMED = (
    "canonical_commit",
    "private_access",
    "recovery_authorization",
)


def _projection_value(projection: RegistryProjection) -> dict[str, object]:
    return {
        "applications": projection.applications,
        "residents": projection.residents,
        "directory": projection.directory,
        "claims": projection.claims,
        "resident_source_event_ids": projection.resident_source_event_ids,
        "applied_corrections": list(projection.applied_corrections),
        "unapplied_event_ids": list(projection.unapplied_event_ids),
        "unapplied_reasons": projection.unapplied_reasons,
        "source_event_ids": list(projection.source_event_ids),
        "attestations": {
            resident_id: list(values)
            for resident_id, values in projection.attestations.items()
        },
    }


def projection_digest(projection: RegistryProjection) -> str:
    return sha256_ref(_projection_value(projection))


@dataclass(frozen=True)
class RegistrarAdmissionPlan:
    source_head: str | None
    prepared_digest: str
    application_digest: str
    decision_digest: str
    authority_digest: str
    ctcl_digest: str
    verified_attestation_refs: tuple[str, ...]
    candidate_event_ids: tuple[str, ...]
    candidate_head: str
    projection_digest: str
    plan_digest: str
    not_claimed: tuple[str, ...] = _PLAN_NOT_CLAIMED

    def _material(self) -> dict[str, object]:
        return {
            "schema": "sedb-ral.registrar-admission-plan/0.1",
            "source_head": self.source_head,
            "prepared_digest": self.prepared_digest,
            "application_digest": self.application_digest,
            "decision_digest": self.decision_digest,
            "authority_digest": self.authority_digest,
            "ctcl_digest": self.ctcl_digest,
            "verified_attestation_refs": list(
                self.verified_attestation_refs
            ),
            "candidate_event_ids": list(self.candidate_event_ids),
            "candidate_head": self.candidate_head,
            "projection_digest": self.projection_digest,
            "not_claimed": list(self.not_claimed),
        }

    @property
    def digest(self) -> str:
        return self.plan_digest

    def to_dict(self) -> dict[str, object]:
        return {**self._material(), "plan_digest": self.plan_digest}

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> RegistrarAdmissionPlan:
        expected = {
            "schema",
            "source_head",
            "prepared_digest",
            "application_digest",
            "decision_digest",
            "authority_digest",
            "ctcl_digest",
            "verified_attestation_refs",
            "candidate_event_ids",
            "candidate_head",
            "projection_digest",
            "not_claimed",
            "plan_digest",
        }
        if set(value) != expected:
            raise RALValidationError(
                "registrar_plan_invalid", "registrar plan fields differ"
            )
        list_fields = (
            "verified_attestation_refs",
            "candidate_event_ids",
            "not_claimed",
        )
        string_fields = (
            "prepared_digest",
            "application_digest",
            "decision_digest",
            "authority_digest",
            "ctcl_digest",
            "candidate_head",
            "projection_digest",
            "plan_digest",
        )
        if (
            value["schema"] != "sedb-ral.registrar-admission-plan/0.1"
            or any(
                not isinstance(value[field], list)
                or not all(isinstance(item, str) for item in value[field])
                for field in list_fields
            )
            or any(
                not isinstance(value[field], str) or not value[field]
                for field in string_fields
            )
            or value["source_head"] is not None
            and not isinstance(value["source_head"], str)
        ):
            raise RALValidationError(
                "registrar_plan_invalid", "registrar plan values differ"
            )
        plan = cls(
            source_head=value["source_head"],
            prepared_digest=value["prepared_digest"],
            application_digest=value["application_digest"],
            decision_digest=value["decision_digest"],
            authority_digest=value["authority_digest"],
            ctcl_digest=value["ctcl_digest"],
            verified_attestation_refs=tuple(
                value["verified_attestation_refs"]
            ),
            candidate_event_ids=tuple(value["candidate_event_ids"]),
            candidate_head=value["candidate_head"],
            projection_digest=value["projection_digest"],
            plan_digest=value["plan_digest"],
            not_claimed=tuple(value["not_claimed"]),
        )
        _validate_plan(plan)
        return plan


@dataclass(frozen=True)
class RegistrarCommitReceipt:
    application_digest: str
    prepared_digest: str
    source_head: str | None
    final_head: str
    event_ids: tuple[str, ...]
    projection_digest: str
    committed: bool
    idempotent: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "sedb-ral.registrar-commit-receipt/0.1",
            "application_digest": self.application_digest,
            "prepared_digest": self.prepared_digest,
            "source_head": self.source_head,
            "final_head": self.final_head,
            "event_ids": list(self.event_ids),
            "projection_digest": self.projection_digest,
            "committed": self.committed,
            "idempotent": self.idempotent,
        }


def _source_events(
    root: Path, expected_head: str | None
) -> tuple[dict[str, object], ...]:
    root = Path(root)
    if expected_head is not None:
        return read_verified_events(root, expected_head)
    verification = verify_ledger(root)
    if verification.status is LedgerStatus.INVALID:
        code = (
            verification.error_codes[0]
            if verification.error_codes
            else "ledger_invalid"
        )
        raise RALValidationError(code, "new registrar root is invalid")
    if verification.status is not LedgerStatus.EMPTY:
        raise RALValidationError(
            "external_anchor_mismatch",
            "a non-empty registrar ledger requires its exact retained head",
        )
    if root.exists() and any(root.iterdir()):
        raise RALValidationError(
            "storage_layout_invalid",
            "a new registrar root must be absent or empty",
        )
    return ()


def _copy_verified_ledger(source: Path, destination: Path) -> None:
    for name in ("events", "anchors"):
        source_path = source / name
        if source_path.exists():
            shutil.copytree(source_path, destination / name)


def _application_decision(
    decision: RegistrationDecision,
) -> RegistrationDecision:
    return decision


def _validate_decision(
    prepared: PreparedRegistration,
    decision: RegistrationDecision,
    authority: Mapping[str, object],
    verified_attestation_refs: AbstractSet[str],
    projection: RegistryProjection,
) -> None:
    fresh = evaluate_prepared_registration(
        prepared,
        [authority],
        verified_attestation_refs=verified_attestation_refs,
        projection=projection,
    )
    if fresh.to_dict() != decision.to_dict():
        raise RALValidationError(
            "registration_decision_stale",
            "the staged decision differs from current inputs or projection",
        )
    if fresh.decision != "accept":
        raise RALValidationError(
            "decision_not_accepted",
            "registrar staging requires an accepted decision",
        )


def _validate_candidate_projection(
    projection: RegistryProjection,
    prepared: PreparedRegistration,
) -> None:
    if projection.unapplied_event_ids:
        raise RALValidationError(
            "registrar_candidate_unapplied",
            "candidate projection contains unapplied events",
        )
    application = prepared.application
    application_id = str(application["application_id"])
    resident_id = str(application["claimed_resident_id"])
    projected_application = projection.applications.get(application_id)
    if projected_application is None:
        raise RALValidationError(
            "registrar_candidate_application_missing",
            "candidate projection omitted the application",
        )
    if projected_application.get("status") != "accepted":
        raise RALValidationError(
            "registrar_candidate_application_unaccepted",
            "candidate application is not accepted",
        )
    for key, expected in application.items():
        if projected_application.get(key) != expected:
            raise RALValidationError(
                "registrar_candidate_application_mismatch",
                f"candidate application field differs: {key}",
            )
    if (
        projected_application.get("application_digest")
        != prepared.application_digest
    ):
        raise RALValidationError(
            "registrar_candidate_application_mismatch",
            "candidate application digest differs",
        )

    resident = projection.residents.get(resident_id)
    if resident is None:
        raise RALValidationError(
            "registrar_candidate_resident_missing",
            "candidate projection omitted the resident",
        )
    expected_resident_fields = {
        "display_label": application["display_label"],
        "application_ref": application_id,
        "status": "active",
        "instances": application["instance_claims"],
        "addresses": application["addresses"],
        "claims": application["claims"],
    }
    for key, expected in expected_resident_fields.items():
        if resident.get(key) != expected:
            raise RALValidationError(
                "registrar_candidate_resident_mismatch",
                f"candidate resident field differs: {key}",
            )
    if continuity_line_for(resident_id, projection) != prepared.continuity_line_id:
        raise RALValidationError(
            "registrar_candidate_line_mismatch",
            "candidate continuity line differs",
        )


def _validate_plan(plan: RegistrarAdmissionPlan) -> None:
    if sha256_ref(plan._material()) != plan.plan_digest:
        raise RALValidationError(
            "registrar_plan_digest_mismatch",
            "the admission plan differs from its staged digest",
        )


def _input_fingerprints(
    prepared: PreparedRegistration,
    decision: RegistrationDecision,
    authority: Mapping[str, object],
    ctcl_receipt: Mapping[str, object],
    verified_attestation_refs: AbstractSet[str],
) -> tuple[str, str, str, str, tuple[str, ...]]:
    validate_prepared_registration(prepared)
    validate_ctcl_receipt(ctcl_receipt)
    return (
        prepared.digest,
        decision.digest,
        authority_digest(authority),
        sha256_ref(dict(ctcl_receipt)),
        tuple(sorted(verified_attestation_refs)),
    )


def _candidate_in_temporary_ledger(
    canonical_root: Path,
    source_events: tuple[dict[str, object], ...],
    prepared: PreparedRegistration,
    decision: RegistrationDecision,
    authority: Mapping[str, object],
    ctcl_receipt: Mapping[str, object],
    *,
    expected_head: str | None,
    verified_attestation_refs: AbstractSet[str],
    staging_parent: Path,
) -> tuple[tuple[str, ...], str, str]:
    staging_parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix="sedb-ral-registrar-", dir=staging_parent
    ) as temporary:
        staging_root = Path(temporary)
        if source_events:
            _copy_verified_ledger(canonical_root, staging_root)
        receipt = commit_application(
            staging_root,
            prepared.application,
            _application_decision(decision),
            authority,
            ctcl_receipt,
            expected_head=expected_head,
            verified_attestation_refs=verified_attestation_refs,
        )
        candidate_events = read_verified_events(
            staging_root, receipt.chain_digest
        )
        projection = project_events(candidate_events)
        _validate_candidate_projection(projection, prepared)
        rebuild_sqlite(candidate_events, staging_root / "projection.sqlite3")
        return (
            receipt.event_ids,
            receipt.chain_digest,
            projection_digest(projection),
        )


def build_admission_plan(
    canonical_root: Path,
    prepared: PreparedRegistration,
    decision: RegistrationDecision,
    authority: Mapping[str, object],
    ctcl_receipt: Mapping[str, object],
    *,
    expected_head: str | None,
    verified_attestation_refs: AbstractSet[str],
    staging_parent: Path,
) -> RegistrarAdmissionPlan:
    canonical_root = Path(canonical_root)
    source_events = _source_events(canonical_root, expected_head)
    fingerprints = _input_fingerprints(
        prepared,
        decision,
        authority,
        ctcl_receipt,
        verified_attestation_refs,
    )
    source_projection = project_events(source_events)
    _validate_decision(
        prepared,
        decision,
        authority,
        verified_attestation_refs,
        source_projection,
    )
    event_ids, candidate_head, candidate_projection_digest = (
        _candidate_in_temporary_ledger(
            canonical_root,
            source_events,
            prepared,
            decision,
            authority,
            ctcl_receipt,
            expected_head=expected_head,
            verified_attestation_refs=verified_attestation_refs,
            staging_parent=Path(staging_parent),
        )
    )
    fields = {
        "source_head": expected_head,
        "prepared_digest": fingerprints[0],
        "application_digest": prepared.application_digest,
        "decision_digest": fingerprints[1],
        "authority_digest": fingerprints[2],
        "ctcl_digest": fingerprints[3],
        "verified_attestation_refs": fingerprints[4],
        "candidate_event_ids": event_ids,
        "candidate_head": candidate_head,
        "projection_digest": candidate_projection_digest,
    }
    provisional = RegistrarAdmissionPlan(**fields, plan_digest="")
    return RegistrarAdmissionPlan(
        **fields,
        plan_digest=sha256_ref(provisional._material()),
    )


def _check_plan_inputs(
    plan: RegistrarAdmissionPlan,
    prepared: PreparedRegistration,
    decision: RegistrationDecision,
    authority: Mapping[str, object],
    ctcl_receipt: Mapping[str, object],
    verified_attestation_refs: AbstractSet[str],
) -> None:
    fingerprints = _input_fingerprints(
        prepared,
        decision,
        authority,
        ctcl_receipt,
        verified_attestation_refs,
    )
    if (
        fingerprints[0] != plan.prepared_digest
        or prepared.application_digest != plan.application_digest
        or fingerprints[1] != plan.decision_digest
        or fingerprints[2] != plan.authority_digest
        or fingerprints[3] != plan.ctcl_digest
        or fingerprints[4] != plan.verified_attestation_refs
    ):
        raise RALValidationError(
            "registrar_input_stale",
            "commit inputs differ from the staged plan",
        )


def _events_by_type(
    events: tuple[Mapping[str, object], ...], event_type: str
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        event for event in events if event.get("event_type") == event_type
    )


def _matching_grants(
    events: tuple[Mapping[str, object], ...], target_digest: str
) -> tuple[Mapping[str, object], ...]:
    matches = []
    for event in _events_by_type(events, "authority.granted"):
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        authority = payload.get("authority")
        if (
            isinstance(authority, Mapping)
            and authority.get("subject_kind") == "application_digest"
            and authority.get("subject_ref") == target_digest
        ):
            matches.append(event)
    return tuple(matches)


def _address_id_conflicts(
    events: tuple[Mapping[str, object], ...],
) -> bool:
    addresses: dict[str, object] = {}
    for event in _events_by_type(events, "resident.registered"):
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        values = payload.get("addresses")
        if not isinstance(values, list):
            continue
        for address in values:
            if not isinstance(address, Mapping):
                continue
            address_id = address.get("address_id")
            if not isinstance(address_id, str):
                continue
            canonical = sha256_ref(dict(address))
            previous = addresses.setdefault(address_id, canonical)
            if previous != canonical:
                return True
    return False


def _decision_prepared_digest(submitted: Mapping[str, object]) -> str:
    payload = submitted["payload"]
    decision = payload.get("decision")
    if not isinstance(decision, Mapping):
        return "unavailable:not-recorded"
    prepared_digest = decision.get("prepared_digest")
    if not isinstance(prepared_digest, str) or not prepared_digest:
        return "unavailable:not-recorded"
    decision_digest = decision.get("digest")
    if isinstance(decision_digest, str):
        material = dict(decision)
        material.pop("digest")
        if sha256_ref(material) != decision_digest:
            raise RALValidationError(
                "registrar_registration_conflict",
                "recorded Phase 3 decision digest differs",
            )
    return prepared_digest


def _registration_evidence(
    values: tuple[Mapping[str, object], ...], target_digest: str
) -> tuple[str, dict[str, object] | None]:
    events = tuple(sorted(values, key=lambda item: item["ledger_seq"]))
    grants = _matching_grants(events, target_digest)
    submissions = tuple(
        event
        for event in _events_by_type(events, "application.submitted")
        if isinstance(event.get("payload"), Mapping)
        and event["payload"].get("application_digest") == target_digest
    )
    acceptances = tuple(
        event
        for event in _events_by_type(events, "application.accepted")
        if isinstance(event.get("payload"), Mapping)
        and event["payload"].get("application_digest") == target_digest
    )
    if not submissions:
        if acceptances:
            return "conflicting", None
        return ("partial", None) if grants else ("absent", None)
    if len(submissions) != 1 or len(acceptances) > 1:
        return "conflicting", None

    submitted = submissions[0]
    submitted_payload = submitted["payload"]
    application = submitted_payload.get("application")
    if not isinstance(application, Mapping):
        return "conflicting", None
    try:
        if application_digest(application) != target_digest:
            return "conflicting", None
    except (KeyError, TypeError, RALValidationError):
        return "conflicting", None
    application_id = application.get("application_id")
    resident_id = application.get("claimed_resident_id")
    if not isinstance(application_id, str) or not isinstance(resident_id, str):
        return "conflicting", None

    for event in _events_by_type(events, "application.submitted"):
        payload = event.get("payload")
        other = payload.get("application") if isinstance(payload, Mapping) else None
        if (
            isinstance(other, Mapping)
            and other.get("application_id") == application_id
            and payload.get("application_digest") != target_digest
        ):
            return "conflicting", None

    registered = tuple(
        event
        for event in _events_by_type(events, "resident.registered")
        if isinstance(event.get("payload"), Mapping)
        and isinstance(event["payload"].get("resident"), Mapping)
        and (
            event["payload"]["resident"].get("application_ref")
            == application_id
            or event["payload"]["resident"].get("resident_id")
            == resident_id
        )
    )
    if len(registered) > 1 or _address_id_conflicts(events):
        return "conflicting", None
    if not acceptances:
        return ("conflicting", None) if registered else ("partial", None)
    accepted = acceptances[0]
    accepted_payload = accepted["payload"]
    if accepted_payload.get("application_id") != application_id:
        return "conflicting", None
    same_id_acceptances = tuple(
        event
        for event in _events_by_type(events, "application.accepted")
        if isinstance(event.get("payload"), Mapping)
        and event["payload"].get("application_id") == application_id
    )
    if any(
        event["payload"].get("application_digest") != target_digest
        for event in same_id_acceptances
    ):
        return "conflicting", None
    if not registered:
        return "partial", None
    registered_event = registered[0]
    registered_payload = registered_event["payload"]
    resident = registered_payload["resident"]
    if (
        resident.get("application_ref") != application_id
        or resident.get("resident_id") != resident_id
        or resident.get("display_label") != application.get("display_label")
        or registered_payload.get("instances")
        != application.get("instance_claims")
        or registered_payload.get("addresses") != application.get("addresses")
        or registered_payload.get("claims") != application.get("claims")
    ):
        return "conflicting", None
    if not (
        submitted["ledger_seq"]
        < accepted["ledger_seq"]
        < registered_event["ledger_seq"]
    ):
        return "conflicting", None

    grant_event_id = accepted_payload.get("authority_grant_event_id")
    grant = next(
        (event for event in events if event.get("event_id") == grant_event_id),
        None,
    )
    if grant is None or grant.get("event_type") != "authority.granted":
        return "conflicting", None
    grant_payload = grant.get("payload")
    authority = (
        grant_payload.get("authority")
        if isinstance(grant_payload, Mapping)
        else None
    )
    if not isinstance(authority, Mapping):
        return "conflicting", None
    try:
        grant_digest = authority_digest(authority)
    except (TypeError, RALValidationError):
        return "conflicting", None
    if (
        grant["ledger_seq"] >= accepted["ledger_seq"]
        or authority.get("subject_kind") != "application_digest"
        or authority.get("subject_ref") != target_digest
        or authority.get("status") != "active"
        or grant_payload.get("authority_digest") != grant_digest
        or accepted_payload.get("authority_id")
        != authority.get("authority_id")
        or accepted_payload.get("authority_digest") != grant_digest
    ):
        return "conflicting", None
    for event in _events_by_type(events, "authority.revoked"):
        payload = event.get("payload")
        if (
            isinstance(payload, Mapping)
            and payload.get("authority_grant_event_id") == grant_event_id
            and event["ledger_seq"] < registered_event["ledger_seq"]
        ):
            return "conflicting", None

    projection = project_events(events)
    target_event_ids = {
        submitted["event_id"],
        accepted["event_id"],
        registered_event["event_id"],
    }
    if target_event_ids.intersection(projection.unapplied_event_ids):
        return "conflicting", None
    projected = projection.residents.get(resident_id)
    if (
        projected is None
        or projected.get("application_ref") != application_id
        or projection.applications.get(application_id, {}).get("status")
        != "accepted"
    ):
        return "conflicting", None

    include_grant = (
        grant["ledger_seq"] + 1 == submitted["ledger_seq"]
        and submitted.get("causal_parent_ids") == [grant["event_id"]]
    )
    related = (
        (grant, submitted, accepted, registered_event)
        if include_grant
        else (submitted, accepted, registered_event)
    )
    first_integrity = related[0].get("integrity")
    final_integrity = registered_event.get("integrity")
    if not isinstance(first_integrity, Mapping) or not isinstance(
        final_integrity, Mapping
    ):
        return "conflicting", None
    source_head = first_integrity.get("previous_chain_digest")
    final_head = final_integrity.get("chain_digest")
    if source_head is not None and not isinstance(source_head, str):
        return "conflicting", None
    if not isinstance(final_head, str):
        return "conflicting", None
    try:
        prepared_digest = _decision_prepared_digest(submitted)
    except RALValidationError:
        return "conflicting", None
    return "complete", {
        "application_digest": target_digest,
        "prepared_digest": prepared_digest,
        "source_head": source_head,
        "final_head": final_head,
        "event_ids": tuple(str(event["event_id"]) for event in related),
        "projection_digest": projection_digest(projection),
    }


def inspect_registration_prefix(
    events: tuple[Mapping[str, object], ...]
    | list[Mapping[str, object]],
    application_digest: str,
) -> str:
    try:
        status, _ = _registration_evidence(
            tuple(events), application_digest
        )
    except (KeyError, TypeError, RALValidationError):
        return "conflicting"
    return status


def find_committed_registration(
    events: tuple[Mapping[str, object], ...]
    | list[Mapping[str, object]],
    application_digest: str,
) -> RegistrarCommitReceipt | None:
    try:
        status, evidence = _registration_evidence(
            tuple(events), application_digest
        )
    except (KeyError, TypeError, RALValidationError):
        return None
    if status != "complete" or evidence is None:
        return None
    return RegistrarCommitReceipt(
        application_digest=str(evidence["application_digest"]),
        prepared_digest=str(evidence["prepared_digest"]),
        source_head=evidence["source_head"],
        final_head=str(evidence["final_head"]),
        event_ids=evidence["event_ids"],
        projection_digest=str(evidence["projection_digest"]),
        committed=False,
        idempotent=True,
    )


def _inspect_current_outcome(
    canonical_root: Path,
    plan: RegistrarAdmissionPlan,
    prepared: PreparedRegistration,
) -> RegistrarCommitReceipt | None:
    exact = verify_ledger(
        canonical_root,
        expected_final_chain_digest=plan.candidate_head,
    )
    if exact.valid:
        events = read_verified_events(canonical_root, plan.candidate_head)
        status = inspect_registration_prefix(
            events, prepared.application_digest
        )
        if status == "complete":
            found = find_committed_registration(
                events, prepared.application_digest
            )
            candidate_tail = tuple(
                event["event_id"] for event in events[-len(plan.candidate_event_ids) :]
            )
            projection = project_events(events)
            if (
                found is None
                or found.prepared_digest != plan.prepared_digest
                or candidate_tail != plan.candidate_event_ids
                or projection_digest(projection) != plan.projection_digest
            ):
                raise RALValidationError(
                    "registrar_registration_conflict",
                    "existing complete registration differs from the plan",
                )
            return RegistrarCommitReceipt(
                application_digest=plan.application_digest,
                prepared_digest=plan.prepared_digest,
                source_head=plan.source_head,
                final_head=plan.candidate_head,
                event_ids=plan.candidate_event_ids,
                projection_digest=plan.projection_digest,
                committed=False,
                idempotent=True,
            )
        code = (
            "registrar_partial_transaction"
            if status == "partial"
            else "registrar_registration_conflict"
        )
        raise RALValidationError(code, "candidate head has invalid outcome")

    current = verify_ledger(canonical_root)
    if current.status is LedgerStatus.EMPTY:
        return None
    if current.status is LedgerStatus.INVALID:
        non_anchor_errors = tuple(
            code
            for code in current.error_codes
            if code != "external_anchor_mismatch"
        )
        if non_anchor_errors:
            raise RALValidationError(
                non_anchor_errors[0], "current registrar ledger is invalid"
            )
    if current.final_chain_digest is None:
        return None
    events = read_verified_events(
        canonical_root, current.final_chain_digest
    )
    status = inspect_registration_prefix(events, prepared.application_digest)
    if status == "partial":
        raise RALValidationError(
            "registrar_partial_transaction",
            "a valid registration prefix requires explicit recovery",
        )
    if status == "conflicting":
        raise RALValidationError(
            "registrar_registration_conflict",
            "canonical evidence conflicts with the staged registration",
        )
    if status == "complete":
        raise RALValidationError(
            "external_anchor_mismatch",
            "registration exists under a different current ledger head",
        )
    return None


def commit_admission_plan(
    canonical_root: Path,
    plan: RegistrarAdmissionPlan,
    prepared: PreparedRegistration,
    decision: RegistrationDecision,
    authority: Mapping[str, object],
    ctcl_receipt: Mapping[str, object],
    *,
    verified_attestation_refs: AbstractSet[str],
) -> RegistrarCommitReceipt:
    _validate_plan(plan)
    _check_plan_inputs(
        plan,
        prepared,
        decision,
        authority,
        ctcl_receipt,
        verified_attestation_refs,
    )
    canonical_root = Path(canonical_root)
    existing = _inspect_current_outcome(canonical_root, plan, prepared)
    if existing is not None:
        return existing
    source_events = _source_events(canonical_root, plan.source_head)
    source_projection = project_events(source_events)
    _validate_decision(
        prepared,
        decision,
        authority,
        verified_attestation_refs,
        source_projection,
    )
    with TemporaryDirectory(
        prefix="sedb-ral-registrar-restage-"
    ) as restaging_parent:
        restaged = _candidate_in_temporary_ledger(
            canonical_root,
            source_events,
            prepared,
            decision,
            authority,
            ctcl_receipt,
            expected_head=plan.source_head,
            verified_attestation_refs=verified_attestation_refs,
            staging_parent=Path(restaging_parent),
        )
    if restaged != (
        plan.candidate_event_ids,
        plan.candidate_head,
        plan.projection_digest,
    ):
        raise RALValidationError(
            "registrar_staged_candidate_mismatch",
            "fresh staging differs from the supplied admission plan",
        )
    result = commit_application(
        canonical_root,
        prepared.application,
        _application_decision(decision),
        authority,
        ctcl_receipt,
        expected_head=plan.source_head,
        verified_attestation_refs=verified_attestation_refs,
    )
    if (
        result.event_ids != plan.candidate_event_ids
        or result.chain_digest != plan.candidate_head
    ):
        raise RALValidationError(
            "registrar_candidate_commit_mismatch",
            "canonical append differs from the staged event sequence",
        )
    events = read_verified_events(canonical_root, result.chain_digest)
    projection = project_events(events)
    _validate_candidate_projection(projection, prepared)
    with TemporaryDirectory(prefix="sedb-ral-registrar-verify-") as temporary:
        rebuild_sqlite(events, Path(temporary) / "projection.sqlite3")
    committed_projection_digest = projection_digest(projection)
    if committed_projection_digest != plan.projection_digest:
        raise RALValidationError(
            "registrar_candidate_projection_mismatch",
            "canonical projection differs from staged projection",
        )
    return RegistrarCommitReceipt(
        application_digest=prepared.application_digest,
        prepared_digest=prepared.digest,
        source_head=plan.source_head,
        final_head=result.chain_digest,
        event_ids=result.event_ids,
        projection_digest=committed_projection_digest,
        committed=True,
        idempotent=False,
    )
