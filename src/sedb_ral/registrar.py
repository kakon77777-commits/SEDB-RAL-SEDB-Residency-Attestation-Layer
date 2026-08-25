from __future__ import annotations

import shutil
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from .application import (
    ApplicationDecision,
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
) -> ApplicationDecision:
    return ApplicationDecision(
        decision=decision.decision,
        reason_codes=decision.reason_codes,
        application_digest=decision.application_digest,
        authority_ref=decision.authority_ref,
        mutated=decision.mutated,
    )


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
    source_events = _source_events(canonical_root, plan.source_head)
    source_projection = project_events(source_events)
    _validate_decision(
        prepared,
        decision,
        authority,
        verified_attestation_refs,
        source_projection,
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
