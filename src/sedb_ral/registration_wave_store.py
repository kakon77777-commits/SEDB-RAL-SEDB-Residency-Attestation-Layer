from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import validate_contract
from .errors import RALValidationError
from .registration import PreparedRegistration
from .registration_wave_authority import (
    AuthorityTimeEvidence,
    PrincipalHostObservation,
    RawPrincipalItemSnapshot,
    VerifiedApplicationApproval,
    verify_application_approval,
    verify_authority_time_evidence,
)
from .registration_wave_context import SyntheticWaveExecutionContext
from .registration_wave_intake import (
    RawApplicantItemSnapshot,
    VerifiedPreparedCandidate,
    verify_applicant_item_evidence,
    verify_prepared_candidate_bindings,
)
from .registration_wave_models import (
    ApplicantItemEvidence,
    PrincipalApplicationApproval,
    RegistrationWavePreparedCandidate,
    SyntheticWaveSlotExecutionResult,
    SyntheticWaveSlotRecoveryResult,
    WaveHostObservation,
    WaveSlotRequest,
)

_KINDS = (
    "claims",
    "item-evidence",
    "host-observations",
    "candidates",
    "approvals",
    "slot-requests",
    "slot-results",
    "recovery-results",
)


@dataclass(frozen=True)
class StoreResult:
    kind: Literal["created", "duplicate"]
    relative_ref: str
    record_digest: str


def _token(kind: str, identifier: str) -> str:
    return sha256_ref({"kind": kind, "identifier": identifier}).rsplit(":", 1)[-1][:32]


def _read_object(path: Path, code: str) -> dict[str, object]:
    try:
        value = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RALValidationError(code, "Wave store JSON cannot be read") from error
    if not isinstance(value, dict):
        raise RALValidationError(code, "Wave store JSON must be an object")
    return value


def _write_new(path: Path, value: dict[str, object]) -> bool:
    try:
        with path.open("xb") as stream:
            stream.write(canonical_bytes(value))
    except FileExistsError:
        return False
    return True


def _verify_bound(value: dict[str, object], field: str, code: str) -> None:
    material = dict(value)
    actual = material.pop(field, None)
    if not isinstance(actual, str) or sha256_ref(material) != actual:
        raise RALValidationError(code, "Wave store digest differs")


def _closed_evidence(material: dict[str, object]) -> dict[str, object]:
    return {**material, "evidence_digest": sha256_ref(material)}


def _verify_closed_evidence(value: object, schema: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RALValidationError(
            "wave_store_capability_invalid", "capability evidence is absent"
        )
    material = dict(value)
    actual = material.pop("evidence_digest", None)
    if material.get("schema") != schema or actual != sha256_ref(material):
        raise RALValidationError(
            "wave_store_capability_invalid", "capability evidence digest differs"
        )
    return value


def _applicant_raw_value(raw: RawApplicantItemSnapshot) -> dict[str, object]:
    content = loads_strict(raw.content_bytes.decode("utf-8"))
    return {
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
        "content": content,
    }


def _candidate_capability_evidence(
    candidate: VerifiedPreparedCandidate,
) -> dict[str, object]:
    candidate.verify()
    return _closed_evidence(
        {
            "schema": "sedb-ral.verified-prepared-candidate-evidence/0.1",
            "claim": loads_strict(
                candidate.verified_item.raw_item.content_bytes.decode("utf-8")
            ),
            "item": candidate.verified_item.item.to_dict(),
            "host": candidate.verified_item.host.to_dict(),
            "raw_item": _applicant_raw_value(candidate.verified_item.raw_item),
            "compatibility_host_v01": candidate.compatibility_host_v01,
            "prepared": candidate.prepared.to_dict(),
        }
    )


def _rebuild_candidate_capability(
    candidate_value: dict[str, object], evidence_value: object
) -> VerifiedPreparedCandidate:
    evidence = _verify_closed_evidence(
        evidence_value, "sedb-ral.verified-prepared-candidate-evidence/0.1"
    )
    raw_value = evidence.get("raw_item")
    if not isinstance(raw_value, dict) or not isinstance(
        raw_value.get("content"), dict
    ):
        raise RALValidationError(
            "wave_store_capability_invalid", "candidate raw evidence differs"
        )
    try:
        raw = RawApplicantItemSnapshot(
            provider=str(raw_value["provider"]),
            adapter_kind=str(raw_value["adapter_kind"]),
            native_thread_id=str(raw_value["native_thread_id"]),
            native_turn_id=str(raw_value["native_turn_id"]),
            source_item_role=str(raw_value["source_item_role"]),
            source_item_kind=str(raw_value["source_item_kind"]),
            source_item_status=str(raw_value["source_item_status"]),
            source_item_parent_thread_id=str(
                raw_value["source_item_parent_thread_id"]
            ),
            source_item_parent_turn_id=str(raw_value["source_item_parent_turn_id"]),
            applicant_item_ref=str(raw_value["applicant_item_ref"]),
            content_bytes=canonical_bytes(raw_value["content"]),
        )
        verified_item = verify_applicant_item_evidence(
            evidence["claim"], evidence["item"], evidence["host"], raw
        )
        return verify_prepared_candidate_bindings(
            candidate_value,
            verified_item=verified_item,
            compatibility_host_v01=evidence["compatibility_host_v01"],
            prepared=PreparedRegistration.from_dict(evidence["prepared"]),
        )
    except (KeyError, TypeError, UnicodeError, RALValidationError) as error:
        if isinstance(error, RALValidationError) and error.code == "wave_store_capability_invalid":
            raise
        raise RALValidationError(
            "wave_store_capability_invalid", "candidate capability cannot be rebuilt"
        ) from error


def _principal_raw_value(raw: RawPrincipalItemSnapshot) -> dict[str, object]:
    return {
        "provider": raw.provider,
        "adapter_kind": raw.adapter_kind,
        "native_thread_id": raw.native_thread_id,
        "native_turn_id": raw.native_turn_id,
        "source_item_role": raw.source_item_role,
        "source_item_kind": raw.source_item_kind,
        "source_item_status": raw.source_item_status,
        "source_item_parent_thread_id": raw.source_item_parent_thread_id,
        "source_item_parent_turn_id": raw.source_item_parent_turn_id,
        "source_item_ref": raw.source_item_ref,
        "content": loads_strict(raw.content_bytes.decode("utf-8")),
    }


def _principal_host_value(host: PrincipalHostObservation) -> dict[str, object]:
    return {
        "provider": host.provider,
        "adapter_kind": host.adapter_kind,
        "native_thread_id": host.native_thread_id,
        "native_turn_id": host.native_turn_id,
        "source_item_role": host.source_item_role,
        "source_item_kind": host.source_item_kind,
        "source_item_status": host.source_item_status,
        "source_item_ref": host.source_item_ref,
        "observed_origin": host.observed_origin,
        "observed_at_ref": host.observed_at_ref,
        "observation_ref": host.observation_ref,
        "digest": host.digest,
    }


def _time_value(time: object) -> dict[str, object]:
    evidence = time.evidence
    return {
        **evidence._source_material(),
        "source_digest": evidence.source_digest,
        "verification_digest": time.verification_digest,
    }


def _approval_capability_evidence(
    approval: VerifiedApplicationApproval,
) -> dict[str, object]:
    approval.verify()
    return _closed_evidence(
        {
            "schema": "sedb-ral.verified-application-approval-evidence/0.1",
            "application": approval.application,
            "raw_item": _principal_raw_value(approval.raw_item),
            "host": _principal_host_value(approval.host),
            "issuance_time": _time_value(approval.issuance_time),
        }
    )


def _rebuild_approval_capability(
    approval_value: dict[str, object], evidence_value: object
) -> VerifiedApplicationApproval:
    evidence = _verify_closed_evidence(
        evidence_value, "sedb-ral.verified-application-approval-evidence/0.1"
    )
    raw_value = evidence.get("raw_item")
    host_value = evidence.get("host")
    time_value = evidence.get("issuance_time")
    if not all(isinstance(value, dict) for value in (raw_value, host_value, time_value)):
        raise RALValidationError(
            "wave_store_capability_invalid", "approval evidence is incomplete"
        )
    try:
        raw = RawPrincipalItemSnapshot(
            provider=str(raw_value["provider"]),
            adapter_kind=str(raw_value["adapter_kind"]),
            native_thread_id=str(raw_value["native_thread_id"]),
            native_turn_id=str(raw_value["native_turn_id"]),
            source_item_role=str(raw_value["source_item_role"]),
            source_item_kind=str(raw_value["source_item_kind"]),
            source_item_status=str(raw_value["source_item_status"]),
            source_item_parent_thread_id=str(
                raw_value["source_item_parent_thread_id"]
            ),
            source_item_parent_turn_id=str(raw_value["source_item_parent_turn_id"]),
            source_item_ref=str(raw_value["source_item_ref"]),
            content_bytes=canonical_bytes(raw_value["content"]),
        )
        host = PrincipalHostObservation(
            provider=str(host_value["provider"]),
            adapter_kind=str(host_value["adapter_kind"]),
            native_thread_id=str(host_value["native_thread_id"]),
            native_turn_id=str(host_value["native_turn_id"]),
            source_item_role=str(host_value["source_item_role"]),
            source_item_kind=str(host_value["source_item_kind"]),
            source_item_status=str(host_value["source_item_status"]),
            source_item_ref=str(host_value["source_item_ref"]),
            observed_origin=str(host_value["observed_origin"]),
            observed_at_ref=str(host_value["observed_at_ref"]),
            observation_ref=str(host_value["observation_ref"]),
            digest=str(host_value["digest"]),
        )
        raw_time = AuthorityTimeEvidence(
            now_ref=str(time_value["now_ref"]),
            now_epoch_ns=time_value["now_epoch_ns"],
            valid_from_ref=str(time_value["valid_from_ref"]),
            valid_from_epoch_ns=time_value["valid_from_epoch_ns"],
            expires_at_ref=time_value["expires_at_ref"],
            expires_at_epoch_ns=time_value["expires_at_epoch_ns"],
            source_ref=str(time_value["source_ref"]),
            source_digest=str(time_value["source_digest"]),
        )
        verified_time = verify_authority_time_evidence(raw_time)
        if verified_time.verification_digest != time_value["verification_digest"]:
            raise RALValidationError(
                "wave_store_capability_invalid", "approval time capability differs"
            )
        approval = PrincipalApplicationApproval.from_dict(approval_value)
        return verify_application_approval(
            approval,
            evidence["application"],
            raw,
            host,
            expected_principal_ref=str(approval.principal_ref),
            time=verified_time,
        )
    except (KeyError, TypeError, UnicodeError, RALValidationError) as error:
        if isinstance(error, RALValidationError) and error.code == "wave_store_capability_invalid":
            raise
        raise RALValidationError(
            "wave_store_capability_invalid", "approval capability cannot be rebuilt"
        ) from error


class RegistrationWaveStore:
    def __init__(
        self,
        context: SyntheticWaveExecutionContext,
        root: Path,
        expected_wave_digest: str,
    ):
        self.context = context
        self.root = Path(root)
        self.expected_wave_digest = expected_wave_digest
        if self.root.resolve(strict=False) != context.target_root.resolve(strict=False):
            raise RALValidationError(
                "wave_staging_root_refused", "store root differs from context target"
            )
        context.verify_before_io("store_initialize", self.root)
        if self.root.exists():
            if not self.root.is_dir():
                raise RALValidationError(
                    "wave_staging_root_refused", "store root is not a directory"
                )
        else:
            self.root.mkdir(parents=False)
        for kind in _KINDS:
            (self.root / "records" / kind).mkdir(parents=True, exist_ok=True)
        (self.root / "quarantine").mkdir(exist_ok=True)
        manifest_material = {
            "schema": "sedb-ral.registration-wave-store-manifest/0.1",
            "layout_version": "0.1",
            "mode": context.mode.value,
            "expected_wave_digest": expected_wave_digest,
            "record_kinds": list(_KINDS),
            "not_claimed": [
                "canonical_commit",
                "production_registry",
                "private_access",
            ],
        }
        manifest = {
            **manifest_material,
            "manifest_digest": sha256_ref(manifest_material),
        }
        manifest_path = self.root / "STORE-MANIFEST.json"
        context.verify_before_io("store_manifest_write", manifest_path)
        if _write_new(manifest_path, manifest):
            context.journal.record("staging_writes", "wave-store:manifest")
        elif canonical_bytes(_read_object(manifest_path, "wave_store_manifest_invalid")) != canonical_bytes(manifest):
            raise RALValidationError(
                "wave_staging_digest_conflict", "store manifest bytes differ"
            )

    def read_manifest(self) -> dict[str, object]:
        path = self.root / "STORE-MANIFEST.json"
        self.context.verify_before_io("store_manifest_read", path)
        value = _read_object(path, "wave_store_manifest_invalid")
        _verify_bound(value, "manifest_digest", "wave_store_manifest_invalid")
        if (
            value.get("mode") != self.context.mode.value
            or value.get("expected_wave_digest") != self.expected_wave_digest
            or value.get("record_kinds") != list(_KINDS)
        ):
            raise RALValidationError(
                "wave_store_manifest_invalid", "store manifest bindings differ"
            )
        return value

    def _path(self, kind: str, identifier: str) -> Path:
        return self.root / "records" / kind / f"record-{_token(kind, identifier)}.json"

    def _quarantine(
        self,
        *,
        kind: str,
        identifier: str,
        existing_digest: str,
        incoming_digest: str,
    ) -> None:
        material = {
            "schema": "sedb-ral.registration-wave-store-quarantine/0.1",
            "record_kind": kind,
            "record_id_digest": sha256_ref(
                {"kind": kind, "identifier": identifier}
            ),
            "existing_digest": existing_digest,
            "incoming_digest": incoming_digest,
            "error_code": "wave_staging_digest_conflict",
            "not_claimed": ["source_deleted", "conflict_resolved"],
        }
        value = {**material, "quarantine_digest": sha256_ref(material)}
        path = self.root / "quarantine" / (
            f"conflict-{_token(kind, identifier)}-{incoming_digest.rsplit(':', 1)[-1][:16]}.json"
        )
        self.context.verify_before_io("store_quarantine_write", path)
        if _write_new(path, value):
            self.context.journal.record(
                "staging_writes", path.relative_to(self.root).as_posix()
            )

    def _submit(
        self,
        *,
        kind: str,
        identifier: str,
        object_ref: str,
        object_digest: str,
        value: dict[str, object],
        capability_digest: str | None = None,
        capability_evidence: dict[str, object] | None = None,
    ) -> StoreResult:
        if kind not in _KINDS or not identifier:
            raise RALValidationError(
                "wave_store_record_invalid", "store kind or identifier is invalid"
            )
        material = {
            "schema": "sedb-ral.registration-wave-store-record/0.1",
            "record_kind": kind,
            "record_id": identifier,
            "wave_digest": self.expected_wave_digest,
            "object_ref": object_ref,
            "object_digest": object_digest,
            "capability_digest": capability_digest,
            "capability_evidence": capability_evidence,
            "object": value,
        }
        record = {**material, "record_digest": sha256_ref(material)}
        path = self._path(kind, identifier)
        self.context.verify_before_io("store_record_write", path)
        if _write_new(path, record):
            relative = path.relative_to(self.root).as_posix()
            self.context.journal.record("staging_writes", relative)
            return StoreResult("created", relative, str(record["record_digest"]))
        existing = _read_object(path, "wave_store_record_invalid")
        if canonical_bytes(existing) == canonical_bytes(record):
            return StoreResult(
                "duplicate",
                path.relative_to(self.root).as_posix(),
                str(existing["record_digest"]),
            )
        self._quarantine(
            kind=kind,
            identifier=identifier,
            existing_digest=str(existing.get("record_digest", "")),
            incoming_digest=str(record["record_digest"]),
        )
        raise RALValidationError(
            "wave_staging_digest_conflict", "same store ID binds changed bytes"
        )

    def put_claim(self, identifier: str, claim: dict[str, object]) -> StoreResult:
        validate_contract("self-application-claim.schema.json", claim)
        return self._submit(
            kind="claims",
            identifier=identifier,
            object_ref=f"self-application-claim:{identifier}",
            object_digest=sha256_ref(claim),
            value=claim,
        )

    def put_item_evidence(
        self, identifier: str, item: ApplicantItemEvidence
    ) -> StoreResult:
        parsed = ApplicantItemEvidence.from_dict(item.to_dict())
        return self._submit(
            kind="item-evidence",
            identifier=identifier,
            object_ref=str(parsed.item_evidence_id),
            object_digest=parsed.digest,
            value=parsed.to_dict(),
        )

    def put_host_observation(
        self, identifier: str, host: WaveHostObservation
    ) -> StoreResult:
        parsed = WaveHostObservation.from_dict(host.to_dict())
        return self._submit(
            kind="host-observations",
            identifier=identifier,
            object_ref=str(parsed.observation_id),
            object_digest=parsed.digest,
            value=parsed.to_dict(),
        )

    def put_candidate(
        self, identifier: str, candidate: VerifiedPreparedCandidate
    ) -> StoreResult:
        if not isinstance(candidate, VerifiedPreparedCandidate):
            raise RALValidationError(
                "verified_candidate_required", "store requires verified candidate"
            )
        candidate.verify()
        return self._submit(
            kind="candidates",
            identifier=identifier,
            object_ref=str(candidate.candidate.candidate_id),
            object_digest=candidate.digest,
            value=candidate.to_dict(),
            capability_digest=candidate.verification_digest,
            capability_evidence=_candidate_capability_evidence(candidate),
        )

    def put_approval(
        self, identifier: str, approval: VerifiedApplicationApproval
    ) -> StoreResult:
        if not isinstance(approval, VerifiedApplicationApproval):
            raise RALValidationError(
                "verified_application_approval_required",
                "store requires verified application approval",
            )
        approval.verify()
        return self._submit(
            kind="approvals",
            identifier=identifier,
            object_ref=str(approval.approval.approval_id),
            object_digest=approval.approval.digest,
            value=approval.approval.to_dict(),
            capability_digest=approval.verification_digest,
            capability_evidence=_approval_capability_evidence(approval),
        )

    def put_slot_request(
        self, identifier: str, request: WaveSlotRequest
    ) -> StoreResult:
        parsed = WaveSlotRequest.from_dict(request.to_dict())
        return self._submit(
            kind="slot-requests",
            identifier=identifier,
            object_ref=str(parsed.request_id),
            object_digest=parsed.digest,
            value=parsed.to_dict(),
        )

    def get_slot_request(self, identifier: str) -> WaveSlotRequest | None:
        path = self._path("slot-requests", identifier)
        self.context.verify_before_io("store_slot_request_read", path)
        if not path.is_file():
            return None
        record = self._verify_record(path)
        return WaveSlotRequest.from_dict(record["object"])

    def put_slot_result(self, identifier: str, result: object) -> StoreResult:
        if not isinstance(result, SyntheticWaveSlotExecutionResult):
            raise RALValidationError(
                "synthetic_result_type_required",
                "production slot receipts cannot enter synthetic store",
            )
        parsed = SyntheticWaveSlotExecutionResult.from_dict(result.to_dict())
        return self._submit(
            kind="slot-results",
            identifier=identifier,
            object_ref=str(parsed.result_id),
            object_digest=parsed.digest,
            value=parsed.to_dict(),
        )

    def get_slot_result(
        self, identifier: str
    ) -> SyntheticWaveSlotExecutionResult | None:
        path = self._path("slot-results", identifier)
        self.context.verify_before_io("store_slot_result_read", path)
        if not path.is_file():
            return None
        record = self._verify_record(path)
        return SyntheticWaveSlotExecutionResult.from_dict(record["object"])

    def put_recovery_result(self, identifier: str, result: object) -> StoreResult:
        if not isinstance(result, SyntheticWaveSlotRecoveryResult):
            raise RALValidationError(
                "synthetic_result_type_required",
                "production recovery receipts cannot enter synthetic store",
            )
        parsed = SyntheticWaveSlotRecoveryResult.from_dict(result.to_dict())
        return self._submit(
            kind="recovery-results",
            identifier=identifier,
            object_ref=str(parsed.result_id),
            object_digest=parsed.digest,
            value=parsed.to_dict(),
        )

    def get_recovery_result(
        self, identifier: str
    ) -> SyntheticWaveSlotRecoveryResult | None:
        path = self._path("recovery-results", identifier)
        self.context.verify_before_io("store_recovery_result_read", path)
        if not path.is_file():
            return None
        record = self._verify_record(path)
        return SyntheticWaveSlotRecoveryResult.from_dict(record["object"])

    def _verify_record(self, path: Path) -> dict[str, object]:
        value = _read_object(path, "wave_store_record_invalid")
        if set(value) != {
            "schema",
            "record_kind",
            "record_id",
            "wave_digest",
            "object_ref",
            "object_digest",
            "capability_digest",
            "capability_evidence",
            "object",
            "record_digest",
        }:
            raise RALValidationError(
                "wave_store_record_invalid", "record fields differ"
            )
        _verify_bound(value, "record_digest", "wave_store_record_invalid")
        kind = str(value["record_kind"])
        record_id = value["record_id"]
        if (
            not isinstance(record_id, str)
            or not record_id
            or path != self._path(kind, record_id)
        ):
            raise RALValidationError(
                "wave_store_record_path_mismatch",
                "record path does not match its kind and identifier",
            )
        obj = value["object"]
        if not isinstance(obj, dict):
            raise RALValidationError(
                "wave_store_record_invalid", "stored object is not an object"
            )
        parsers = {
            "claims": lambda item: (
                validate_contract("self-application-claim.schema.json", item),
                sha256_ref(item),
            )[1],
            "item-evidence": lambda item: ApplicantItemEvidence.from_dict(item).digest,
            "host-observations": lambda item: WaveHostObservation.from_dict(item).digest,
            "candidates": lambda item: RegistrationWavePreparedCandidate.from_dict(item).digest,
            "approvals": lambda item: PrincipalApplicationApproval.from_dict(item).digest,
            "slot-requests": lambda item: WaveSlotRequest.from_dict(item).digest,
            "slot-results": lambda item: SyntheticWaveSlotExecutionResult.from_dict(item).digest,
            "recovery-results": lambda item: SyntheticWaveSlotRecoveryResult.from_dict(item).digest,
        }
        if kind not in parsers or parsers[kind](obj) != value["object_digest"]:
            raise RALValidationError(
                "wave_store_record_invalid", "stored object digest differs"
            )
        expected_refs = {
            "claims": f"self-application-claim:{record_id}",
            "item-evidence": obj.get("item_evidence_id"),
            "host-observations": obj.get("observation_id"),
            "candidates": obj.get("candidate_id"),
            "approvals": obj.get("approval_id"),
            "slot-requests": obj.get("request_id"),
            "slot-results": obj.get("result_id"),
            "recovery-results": obj.get("result_id"),
        }
        if (
            value["wave_digest"] != self.expected_wave_digest
            or value["object_ref"] != expected_refs[kind]
        ):
            raise RALValidationError(
                "wave_store_record_binding_mismatch",
                "record does not bind this Wave and verified object reference",
            )
        capability_digest = value["capability_digest"]
        capability_evidence = value["capability_evidence"]
        if kind == "candidates":
            rebuilt = _rebuild_candidate_capability(obj, capability_evidence)
            observed_capability_digest = rebuilt.verification_digest
        elif kind == "approvals":
            rebuilt = _rebuild_approval_capability(obj, capability_evidence)
            observed_capability_digest = rebuilt.verification_digest
        else:
            observed_capability_digest = None
            if capability_evidence is not None:
                raise RALValidationError(
                    "wave_store_capability_invalid",
                    "non-capability record carries capability evidence",
                )
        if capability_digest != observed_capability_digest:
            raise RALValidationError(
                "wave_store_capability_invalid",
                "stored capability digest cannot be re-established",
            )
        return value

    def _verify_quarantine(self, path: Path) -> None:
        value = _read_object(path, "wave_store_quarantine_invalid")
        if set(value) != {
            "schema",
            "record_kind",
            "record_id_digest",
            "existing_digest",
            "incoming_digest",
            "error_code",
            "not_claimed",
            "quarantine_digest",
        }:
            raise RALValidationError(
                "wave_store_quarantine_invalid", "quarantine fields differ"
            )
        _verify_bound(
            value, "quarantine_digest", "wave_store_quarantine_invalid"
        )
        if (
            value["schema"]
            != "sedb-ral.registration-wave-store-quarantine/0.1"
            or value["record_kind"] not in _KINDS
            or value["error_code"] != "wave_staging_digest_conflict"
        ):
            raise RALValidationError(
                "wave_store_quarantine_invalid", "quarantine semantics differ"
            )

    def verify(self) -> dict[str, object]:
        self.context.verify_before_io("store_verify", self.root)
        self.read_manifest()
        expected_dirs = {"records", "quarantine", *{f"records/{kind}" for kind in _KINDS}}
        observed_dirs = {
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_dir()
        }
        if observed_dirs != expected_dirs:
            raise RALValidationError(
                "wave_store_layout_invalid", "store directories differ"
            )
        observed_files = {
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        allowed_files = {"STORE-MANIFEST.json"}
        allowed_files.update(
            name
            for name in observed_files
            if any(
                name.startswith(f"records/{kind}/record-")
                and name.endswith(".json")
                for kind in _KINDS
            )
            or (name.startswith("quarantine/conflict-") and name.endswith(".json"))
        )
        if observed_files != allowed_files:
            raise RALValidationError(
                "wave_store_layout_invalid", "store files differ"
            )
        records = [
            self._verify_record(path)
            for path in sorted((self.root / "records").rglob("*.json"))
        ]
        for path in sorted((self.root / "quarantine").glob("*.json")):
            self._verify_quarantine(path)
        inventory = [
            {
                "record_kind": value["record_kind"],
                "object_ref": value["object_ref"],
                "object_digest": value["object_digest"],
                "record_digest": value["record_digest"],
            }
            for value in records
        ]
        return {
            "verified": True,
            "mode": self.context.mode.value,
            "record_count": len(records),
            "inventory_digest": sha256_ref(inventory),
        }
