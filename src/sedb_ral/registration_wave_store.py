from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import validate_contract
from .errors import RALValidationError
from .registration_wave_authority import VerifiedApplicationApproval
from .registration_wave_context import SyntheticWaveExecutionContext
from .registration_wave_intake import VerifiedPreparedCandidate
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
    ) -> StoreResult:
        if kind not in _KINDS or not identifier:
            raise RALValidationError(
                "wave_store_record_invalid", "store kind or identifier is invalid"
            )
        material = {
            "schema": "sedb-ral.registration-wave-store-record/0.1",
            "record_kind": kind,
            "record_id": identifier,
            "object_ref": object_ref,
            "object_digest": object_digest,
            "capability_digest": capability_digest,
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
            "object_ref",
            "object_digest",
            "capability_digest",
            "object",
            "record_digest",
        }:
            raise RALValidationError(
                "wave_store_record_invalid", "record fields differ"
            )
        _verify_bound(value, "record_digest", "wave_store_record_invalid")
        kind = str(value["record_kind"])
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
