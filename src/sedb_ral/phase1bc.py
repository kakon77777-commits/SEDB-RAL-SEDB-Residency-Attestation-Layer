from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from .adapters.codex_queue import normalize_codex_queue
from .application import commit_application, evaluate_application
from .delivery import (
    matrix_adapter_submits,
    reconstruct_delivery,
    validate_adapter_matrix,
)
from .errors import RALValidationError
from .explain import explain_claim
from .incidents import (
    load_incidents,
    negative_gate_cases,
    validate_required_negative_cases,
)
from .ledger import read_verified_events
from .no_send import scan_no_send
from .phase1a import validate_phase1a
from .projection import project_events
from .sqlite_projection import rebuild_sqlite, table_row_counts
from .transcript import render_turn

_INCIDENT_COUNT = 29
_INCIDENT_SHA256 = (
    "9a4a504621d6837b0724cbfebc7a9db84a5f260103d9ce585a3087a39a6a3828"
)

_REQUIRED_SCHEMAS = (
    "adapter-matrix.schema.json",
    "adapter-observation.schema.json",
    "address.schema.json",
    "application.schema.json",
    "attestation.schema.json",
    "authority-envelope.schema.json",
    "binding.schema.json",
    "claim.schema.json",
    "correction-tombstone.schema.json",
    "ctcl-receipt.schema.json",
    "identifier-discrimination.schema.json",
    "identifier-field.schema.json",
    "incident-record.schema.json",
    "instance.schema.json",
    "ledger-event.schema.json",
    "observation.schema.json",
    "resident.schema.json",
    "transcript-binding.schema.json",
)
_REQUIRED_RUNTIME = (
    "src/sedb_ral/__init__.py",
    "src/sedb_ral/adapters/__init__.py",
    "src/sedb_ral/adapters/codex_queue.py",
    "src/sedb_ral/application.py",
    "src/sedb_ral/authority.py",
    "src/sedb_ral/canonical.py",
    "src/sedb_ral/cli.py",
    "src/sedb_ral/contracts.py",
    "src/sedb_ral/ctcl.py",
    "src/sedb_ral/delivery.py",
    "src/sedb_ral/errors.py",
    "src/sedb_ral/explain.py",
    "src/sedb_ral/identifier.py",
    "src/sedb_ral/incidents.py",
    "src/sedb_ral/ledger.py",
    "src/sedb_ral/no_send.py",
    "src/sedb_ral/phase1a.py",
    "src/sedb_ral/phase1bc.py",
    "src/sedb_ral/projection.py",
    "src/sedb_ral/sqlite_projection.py",
    "src/sedb_ral/transcript.py",
)
_REQUIRED_FIXTURES = (
    "fixtures/adapters/codex-queue/materialized-and-acknowledged.json",
    "fixtures/adapters/codex-queue/partial-transcript.json",
    "fixtures/adapters/codex-queue/prefix-collision.json",
    "fixtures/adapters/codex-queue/presented-instance-mismatch.json",
    "fixtures/adapters/codex-queue/structurally-unavailable.json",
    "fixtures/adapters/codex-queue/transport-accepted.json",
    "fixtures/adapters/matrix.json",
    "fixtures/application/authorized-zero-address.json",
    "fixtures/application/missing-authority.json",
    "fixtures/application/revoked-authority.json",
    "fixtures/ctcl/reading.json",
    "fixtures/ctcl/registered-anchor.json",
    "fixtures/identifier/mixed_population/manifest.json",
    "fixtures/identifier/mixed_population/one-resident.json",
    "fixtures/identifier/negative/shared-runtime-tag.json",
    "fixtures/identifier/positive/resident-address.json",
    "fixtures/ledger/event-001.json",
    "fixtures/ledger/event-002.json",
)
_REQUIRED_CORPUS = ("corpus/incidents.jsonl", "corpus/incidents.md")
_REQUIRED_TESTS = (
    "tests/test_application_commit.py",
    "tests/test_application_decision.py",
    "tests/test_codex_queue_adapter.py",
    "tests/test_delivery.py",
    "tests/test_explain.py",
    "tests/test_incidents.py",
    "tests/test_ledger.py",
    "tests/test_no_send.py",
    "tests/test_packaging.py",
    "tests/test_phase1a_checkpoint.py",
    "tests/test_phase1a_gate.py",
    "tests/test_phase1b_contracts.py",
    "tests/test_phase1bc_gate.py",
    "tests/test_projection.py",
    "tests/test_sqlite_projection.py",
    "tests/test_transcript.py",
)
_REQUIRED_VALIDATION_INPUTS = (
    "PHASE1A_CHECKPOINT.json",
    "VALIDATION_PHASE_1A.json",
    "pyproject.toml",
    "scripts/build_manifest.py",
    "scripts/render_incidents.py",
    "scripts/validate_phase1a.py",
    "scripts/validate_phase1bc.py",
)


REQUIRED_PHASE1BC_ARTIFACTS = tuple(
    sorted(
        {
            *(
                f"src/sedb_ral/schemas/{name}"
                for name in _REQUIRED_SCHEMAS
            ),
            *_REQUIRED_RUNTIME,
            *_REQUIRED_FIXTURES,
            *_REQUIRED_CORPUS,
            *_REQUIRED_TESTS,
            *_REQUIRED_VALIDATION_INPUTS,
        }
    )
)


def required_phase1bc_artifacts() -> tuple[str, ...]:
    return REQUIRED_PHASE1BC_ARTIFACTS


@dataclass(frozen=True)
class ExecutedFault:
    test_name: str
    expected_red_code: str
    observed_red_code: str
    executed: bool

    def as_json(self) -> dict[str, object]:
        return {
            "test_name": self.test_name,
            "expected_red_code": self.expected_red_code,
            "observed_red_code": self.observed_red_code,
            "executed": self.executed,
        }


@dataclass(frozen=True)
class Phase1BCReport:
    passed: bool
    phase1a_passed: bool
    required_artifact_count: int
    no_send_findings: tuple[str, ...]
    sqlite_row_counts: dict[str, int]
    sqlite_bytes_identical: bool
    incident_count: int
    incident_sha256: str
    delivery_stage: str | None
    executed_positive_controls: tuple[ExecutedFault, ...]
    executed_faults: tuple[ExecutedFault, ...]
    error_codes: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "phase1a_passed": self.phase1a_passed,
            "required_artifact_count": self.required_artifact_count,
            "no_send_findings": list(self.no_send_findings),
            "sqlite_row_counts": self.sqlite_row_counts,
            "sqlite_bytes_identical": self.sqlite_bytes_identical,
            "incident_count": self.incident_count,
            "incident_sha256": self.incident_sha256,
            "delivery_stage": self.delivery_stage,
            "executed_positive_controls": [
                item.as_json() for item in self.executed_positive_controls
            ],
            "executed_faults": [item.as_json() for item in self.executed_faults],
            "error_codes": list(self.error_codes),
        }


def _error_code(error: Exception) -> str:
    if isinstance(error, RALValidationError):
        return error.code
    if isinstance(error, json.JSONDecodeError):
        return "input_invalid_json"
    if isinstance(error, UnicodeError):
        return "input_not_utf8"
    if isinstance(error, OSError):
        return "input_unreadable"
    return "phase1bc_gate_error"


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RALValidationError("fixture_not_object", str(path))
    return value


def _required_artifact_errors(root: Path) -> tuple[str, ...]:
    return tuple(
        f"required_artifact_missing:{relative}"
        for relative in required_phase1bc_artifacts()
        if not (root / relative).is_file()
    )


def _sample_events(root: Path, temporary: Path) -> tuple[dict[str, object], ...]:
    fixture = _load(root / "fixtures/application/authorized-zero-address.json")
    anchor = _load(root / "fixtures/ctcl/registered-anchor.json")
    application = fixture["application"]
    authorities = fixture["authorities"]
    decision = evaluate_application(
        application,
        authorities,
        verified_attestation_refs=frozenset({"attestation:neo:1"}),
    )
    receipt = commit_application(
        temporary / "ledger",
        application,
        decision,
        authorities[0],
        anchor,
        expected_head=None,
        verified_attestation_refs=frozenset({"attestation:neo:1"}),
    )
    return read_verified_events(temporary / "ledger", receipt.chain_digest)


def _positive(name: str, action: Callable[[], bool]) -> ExecutedFault:
    try:
        observed = "positive" if action() else "positive_not_observed"
    except Exception as error:
        observed = _error_code(error)
    return ExecutedFault(name, "positive", observed, True)


def _fault_exception(
    name: str, expected: str, action: Callable[[], object]
) -> ExecutedFault:
    try:
        action()
    except Exception as error:
        observed = _error_code(error)
    else:
        observed = "fault_not_detected"
    return ExecutedFault(name, expected, observed, True)


def _fault_phase1a_missing_negative_fixture(root: Path) -> ExecutedFault:
    with tempfile.TemporaryDirectory(prefix="sedb-ral-phase1bc-fault-") as name:
        copied = Path(name) / "repo"
        shutil.copytree(
            root / "src/sedb_ral/schemas", copied / "src/sedb_ral/schemas"
        )
        shutil.copytree(root / "fixtures", copied / "fixtures")
        (copied / "fixtures/identifier/negative/shared-runtime-tag.json").unlink()
        report = validate_phase1a(copied)
    observed = (
        "negative_fixture_missing"
        if "negative_fixture_missing" in report.error_codes
        else "fault_not_detected"
    )
    return ExecutedFault(
        "phase1a_missing_negative_fixture",
        "negative_fixture_missing",
        observed,
        True,
    )


def _fault_required_transcript_schema(root: Path) -> ExecutedFault:
    expected = (
        "required_artifact_missing:"
        "src/sedb_ral/schemas/transcript-binding.schema.json"
    )
    with tempfile.TemporaryDirectory(prefix="sedb-ral-phase1bc-census-") as name:
        copied = Path(name) / "repo"
        for relative in required_phase1bc_artifacts():
            destination = copied / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / relative, destination)
        (copied / "src/sedb_ral/schemas/transcript-binding.schema.json").unlink()
        observed = (
            expected
            if expected in _required_artifact_errors(copied)
            else "fault_not_detected"
        )
    return ExecutedFault(
        "required_transcript_schema_missing", expected, observed, True
    )


def _fault_sqlite_projection_mutation(
    events: tuple[dict[str, object], ...], temporary: Path
) -> ExecutedFault:
    first = rebuild_sqlite(events, temporary / "first.sqlite3")
    second = rebuild_sqlite(events, temporary / "second.sqlite3")
    connection = sqlite3.connect(second)
    try:
        connection.execute("UPDATE applications SET status = 'corrupted'")
        connection.commit()
    finally:
        connection.close()
    observed = (
        "sqlite_projection_mismatch"
        if first.read_bytes() != second.read_bytes()
        else "fault_not_detected"
    )
    return ExecutedFault(
        "sqlite_projection_mutation",
        "sqlite_projection_mismatch",
        observed,
        True,
    )


def _fault_no_send(name: str, source: str, expected: str) -> ExecutedFault:
    with tempfile.TemporaryDirectory(prefix="sedb-ral-phase1bc-fault-") as temporary:
        root = Path(temporary)
        (root / "copied.py").write_text(source, encoding="utf-8")
        codes = {item.code for item in scan_no_send(root)}
    return ExecutedFault(
        name,
        expected,
        expected if expected in codes else "fault_not_detected",
        True,
    )


def _fault_missing_no_send_root(temporary: Path) -> ExecutedFault:
    expected = "package_root_missing"
    codes = {item.code for item in scan_no_send(temporary / "missing-package")}
    return ExecutedFault(
        "no_send_package_missing",
        expected,
        expected if expected in codes else "fault_not_detected",
        True,
    )


def _claim_population(root: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    fixture = _load(root / "fixtures/application/authorized-zero-address.json")
    claim = fixture["application"]["claims"][0]
    attestations = []
    for index in (1, 2):
        attestations.append(
            {
                "schema_version": "0.1",
                "attestation_id": f"attestation:gate:{index}",
                "claim_ref": claim["claim_id"],
                "evidence_basis": "own_execution",
                "verification_status": "verified",
                "record_status": "active",
                "observer_independence_status": "independent",
                "evidence_independence_status": "independent",
                "independence_scope": "resident:test",
                "evidence_root_refs": [f"evidence:root:{index}"],
                "derivation_parent_refs": [],
                "evidence_refs": [f"evidence:execution:{index}"],
                "scope": ["resident:test"],
                "temporal_validity": "valid",
                "not_claimed": [],
            }
        )
    events = [
        {
            "ledger_seq": 1,
            "event_id": "evt_claim_gate",
            "event_type": "claim.recorded",
            "payload": {"claim": claim},
        },
        *[
            {
                "ledger_seq": index + 2,
                "event_id": f"evt_attestation_gate_{index}",
                "event_type": "attestation.recorded",
                "payload": {"attestation": attestation},
            }
            for index, attestation in enumerate(attestations)
        ],
    ]
    policy = {
        "policy_id": "policy:gate:claim-reliance",
        "authorization_scope": "registry.claim.rely",
        "required_evidence_bases": ["own_execution"],
        "required_verification_status": "verified",
        "required_record_status": "active",
        "required_temporal_validity": "valid",
        "required_scope_refs": ["resident:test"],
        "minimum_distinct_evidence_roots": 2,
        "required_observer_independence_status": "independent",
        "required_evidence_independence_status": "independent",
        "comparability_relations": [["own_execution"]],
    }
    return events, policy


def _transcript_population() -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "transcript_id": "transcript:gate:1",
        "bindings": [
            {
                "label": "Relay",
                "bound_identifier": "instance:relay:1",
                "identifier_kind": "resident_id",
                "bound_at_ref": "ctcl:instant:3a40eb8b-121f-4c6a-b66f-b28db4740fb4",
                "scope": "transcript",
                "rebinds": None,
                "visual_token": "blue-1",
                "visual_scope": "transcript",
                "palette_version": "eml-palette-1",
                "contrast_standard": "WCAG-2.2-SC-1.4.11>=3:1",
                "verified_backgrounds": [],
                "deficiency_set": ["protanopia", "deuteranopia", "tritanopia"],
                "accessibility_verification_status": "unmeasured",
            }
        ],
        "turns": [
            {
                "turn_id": "turn:gate:1",
                "speaker_label": "Relay",
                "body": "hello",
                "relay": {
                    "relayed_by": "instance:relay:1",
                    "relay_is_authorship": False,
                    "original_claimed_author": "Original",
                    "observed_origin": None,
                },
            }
        ],
    }


def _correction_population(
    events: tuple[dict[str, object], ...]
) -> list[dict[str, object]]:
    values = list(copy.deepcopy(events))
    target = next(
        item for item in values if item["event_type"] == "resident.registered"
    )
    replacement = copy.deepcopy(target["payload"]["claims"][0])
    replacement["claim_id"] = "claim:gate:replacement"
    replacement["object"] = "Corrected Gate Label"
    values.append(
        {
            "ledger_seq": len(values) + 1,
            "event_id": "evt_claim_gate_replacement",
            "event_type": "claim.recorded",
            "payload": {"claim": replacement},
        }
    )
    values.append(
        {
            "ledger_seq": len(values) + 1,
            "event_id": "evt_correction_gate",
            "event_type": "record.corrected",
            "payload": {
                "correction": {
                    "schema_version": "0.1",
                    "correction_id": "correction:gate:1",
                    "target_event_id": target["event_id"],
                    "action": "correct",
                    "replacement_ref": replacement["claim_id"],
                    "reason": "integrated gate correction control",
                },
                "target_kind": "resident",
                "target_ref": "resident:test",
                "changes": {"display_label": "Corrected Gate Label"},
            },
        }
    )
    return values


def validate_phase1bc(root: Path) -> Phase1BCReport:
    root = Path(root)
    errors: list[str] = list(_required_artifact_errors(root))
    phase1a = validate_phase1a(root)
    if not phase1a.passed:
        errors.append("phase1a_gate_failed")

    schema_root = root / "src/sedb_ral/schemas"
    for name in _REQUIRED_SCHEMAS:
        path = schema_root / name
        if not path.is_file():
            continue
        try:
            Draft202012Validator.check_schema(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except Exception as error:
            errors.append(f"schema_invalid:{name}:{_error_code(error)}")

    findings = scan_no_send(root / "src/sedb_ral")
    no_send_findings = tuple(item.code for item in findings)
    if findings:
        errors.append("no_send_violation")

    sqlite_counts: dict[str, int] = {}
    sqlite_bytes_identical = False
    delivery_stage = None
    positives: list[ExecutedFault] = []
    faults: list[ExecutedFault] = []
    try:
        with tempfile.TemporaryDirectory(prefix="sedb-ral-phase1bc-") as name:
            temporary = Path(name)
            events = _sample_events(root, temporary / "sample")
            first = rebuild_sqlite(events, temporary / "first.sqlite3")
            second = rebuild_sqlite(events, temporary / "second.sqlite3")
            sqlite_counts = table_row_counts(first)
            sqlite_bytes_identical = first.read_bytes() == second.read_bytes()
            if not sqlite_bytes_identical:
                errors.append("sqlite_rebuild_nondeterministic")
            if (
                sqlite_counts.get("applications") != 1
                or sqlite_counts.get("residents") != 1
            ):
                errors.append("sqlite_projection_incomplete")

            fixture = _load(
                root / "fixtures/application/authorized-zero-address.json"
            )
            correction_events = _correction_population(events)
            claim_events, policy = _claim_population(root)
            transcript = _transcript_population()
            matrix = _load(root / "fixtures/adapters/matrix.json")
            adapter = normalize_codex_queue(
                _load(
                    root
                    / "fixtures/adapters/codex-queue/"
                    "materialized-and-acknowledged.json"
                )
            )
            delivery = reconstruct_delivery((adapter,))
            delivery_stage = delivery.stage

            positives.extend(
                [
                    _positive(
                        "admission_positive",
                        lambda: evaluate_application(
                            fixture["application"],
                            fixture["authorities"],
                            verified_attestation_refs=frozenset(
                                {"attestation:neo:1"}
                            ),
                        ).decision
                        == "accept",
                    ),
                    _positive(
                        "projection_correction_positive",
                        lambda: project_events(correction_events)
                        .residents["resident:test"]["display_label"]
                        == "Corrected Gate Label",
                    ),
                    _positive(
                        "claim_explanation_positive",
                        lambda: explain_claim(
                            claim_events,
                            "claim:test:1",
                            policy=policy,
                        ).sufficiency
                        == "sufficient",
                    ),
                    _positive(
                        "transcript_binding_positive",
                        lambda: render_turn(
                            transcript, "turn:gate:1", rich=False
                        )
                        == "Relay: hello",
                    ),
                    _positive(
                        "adapter_matrix_delivery_positive",
                        lambda: (
                            validate_adapter_matrix(matrix) is None
                            and matrix_adapter_submits(
                                matrix, "codex_queue_to_codex_conversation"
                            )
                            is True
                            and delivery.stage == "instance_acknowledged"
                            and delivery.observed_origin is None
                        ),
                    ),
                    _positive(
                        "sqlite_projection_positive",
                        lambda: sqlite_bytes_identical
                        and sqlite_counts.get("bindings") == 1,
                    ),
                    _positive(
                        "no_send_positive",
                        lambda: scan_no_send(root / "src/sedb_ral") == (),
                    ),
                ]
            )

            controls: tuple[Callable[[], ExecutedFault], ...] = (
                lambda: _fault_phase1a_missing_negative_fixture(root),
                lambda: _fault_required_transcript_schema(root),
                lambda: _fault_admission(fixture),
                lambda: _fault_projection(correction_events),
                lambda: _fault_claim(claim_events, policy),
                lambda: _fault_transcript(transcript),
                lambda: _fault_adapter_matrix(matrix),
                lambda: _fault_sqlite_projection_mutation(
                    events, temporary / "mutation"
                ),
                lambda: _fault_missing_no_send_root(temporary),
                lambda: _fault_no_send(
                    "no_send_socket_call",
                    "import socket\nsocket.create_connection(('example.test', 443))\n",
                    "forbidden_call:socket.create_connection",
                ),
                lambda: _fault_no_send(
                    "no_send_sedb_import",
                    "import sedb\n",
                    "forbidden_import:sedb",
                ),
            )
            for control in controls:
                try:
                    faults.append(control())
                except Exception as error:
                    errors.append(_error_code(error))
    except Exception as error:
        errors.append(_error_code(error))

    incident_count = 0
    incident_sha256 = ""
    try:
        incident_path = root / "corpus/incidents.jsonl"
        raw = incident_path.read_bytes()
        incident_sha256 = hashlib.sha256(raw).hexdigest()
        incidents = load_incidents(incident_path)
        incident_count = len(incidents)
        if incident_count != _INCIDENT_COUNT:
            errors.append("incident_count_mismatch")
        if incident_sha256 != _INCIDENT_SHA256:
            errors.append("incident_sha256_mismatch")
        errors.extend(
            validate_required_negative_cases(negative_gate_cases(incidents))
        )
    except Exception as error:
        errors.append(_error_code(error))

    for control in [*positives, *faults]:
        if (
            not control.executed
            or control.observed_red_code != control.expected_red_code
        ):
            errors.append(f"control_failed:{control.test_name}")
    unique_errors = tuple(sorted(set(errors)))
    return Phase1BCReport(
        passed=not unique_errors,
        phase1a_passed=phase1a.passed,
        required_artifact_count=len(required_phase1bc_artifacts()),
        no_send_findings=no_send_findings,
        sqlite_row_counts=sqlite_counts,
        sqlite_bytes_identical=sqlite_bytes_identical,
        incident_count=incident_count,
        incident_sha256=incident_sha256,
        delivery_stage=delivery_stage,
        executed_positive_controls=tuple(positives),
        executed_faults=tuple(faults),
        error_codes=unique_errors,
    )


def _fault_admission(fixture: Mapping[str, object]) -> ExecutedFault:
    application = copy.deepcopy(fixture["application"])
    application["claims"][0]["subject_ref"] = "resident:other"
    decision = evaluate_application(
        application,
        fixture["authorities"],
        verified_attestation_refs=frozenset({"attestation:neo:1"}),
    )
    expected = "application_claim_subject_mismatch"
    observed = (
        expected if decision.reason_codes == (expected,) else "fault_not_detected"
    )
    return ExecutedFault("admission_cross_resident", expected, observed, True)


def _fault_projection(events: list[dict[str, object]]) -> ExecutedFault:
    corrupted = copy.deepcopy(events)
    accepted = next(
        item
        for item in corrupted
        if item["event_type"] == "application.accepted"
    )
    corrupted[-1]["payload"]["correction"]["target_event_id"] = accepted[
        "event_id"
    ]
    projection = project_events(corrupted)
    expected = "correction_target_event_mismatch"
    observed = projection.unapplied_reasons.get(
        "evt_correction_gate", "fault_not_detected"
    )
    return ExecutedFault(
        "projection_wrong_correction_target", expected, observed, True
    )


def _fault_claim(
    events: list[dict[str, object]], policy: Mapping[str, object]
) -> ExecutedFault:
    corrupted = copy.deepcopy(events)
    corrupted[1]["payload"]["attestation"]["scope"] = ["resident:other"]
    result = explain_claim(
        corrupted, "claim:test:1", policy=copy.deepcopy(policy)
    )
    expected = "scope_overlap_missing"
    observed = (
        expected
        if result.sufficiency_reason_codes == (expected,)
        else "fault_not_detected"
    )
    return ExecutedFault(
        "claim_explanation_scope_mismatch", expected, observed, True
    )


def _fault_transcript(transcript: Mapping[str, object]) -> ExecutedFault:
    corrupted = copy.deepcopy(transcript)
    corrupted["turns"][0]["speaker_label"] = "Unbound"
    return _fault_exception(
        "transcript_unbound_turn",
        "speaker_resolution_indeterminate",
        lambda: render_turn(corrupted, "turn:gate:1", rich=False),
    )


def _fault_adapter_matrix(matrix: Mapping[str, object]) -> ExecutedFault:
    corrupted = copy.deepcopy(matrix)
    corrupted["routes"][0]["adapter_submits"] = "unmeasured"
    return _fault_exception(
        "adapter_matrix_invalid_submit",
        "schema_invalid",
        lambda: validate_adapter_matrix(corrupted),
    )
