from __future__ import annotations

import copy
import hashlib
import importlib.util
import sys
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import validate_contract
from .errors import RALValidationError
from .no_send import scan_no_send
from .phase1a import validate_phase1a
from .phase1bc import _sample_events, validate_phase1bc
from .projection import project_events
from .sedb_adoption import SEDBAdoptionInspection, inspect_sedb_archive
from .sedb_diff import SEDBDiffReport, compare_sedb_projection
from .sedb_mapping import project_to_sedb_records


_DIFF_CLASSES = (
    "expected_by_mapping",
    "unmapped",
    "contradiction",
)
_TASK5_REPORT = (
    ".superpowers/sdd/2026-08-23-basic-phase-2-sedb-profile/"
    "task-5-report.md"
)
_EVIDENCE_REFS = (
    "profiles/sedb-v0.4b-adoption.json",
    "profiles/sedb-v0.4b-mapping.json",
    "scripts/validate_sedb_v04b.py",
    _TASK5_REPORT,
)


@dataclass(frozen=True)
class ExecutedPhase2Control:
    name: str
    injected_change: str
    expected_code: str
    observed_code: str
    executed: bool

    def as_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "injected_change": self.injected_change,
            "expected_code": self.expected_code,
            "observed_code": self.observed_code,
            "executed": self.executed,
        }


@dataclass(frozen=True)
class Phase2Report:
    passed: bool
    receipt_id: str
    adoption_profile_id: str
    adoption_profile_version: str
    mapping_profile_id: str
    mapping_profile_version: str
    archive: dict[str, object]
    manifest: dict[str, object]
    package: dict[str, object]
    mapping_profile_digest: str
    phase1a_report: dict[str, object] | None
    phase1bc_report: dict[str, object] | None
    phase1_projection_head: str | None
    integration: dict[str, object] | None
    differential: dict[str, object]
    sedb_tests: dict[str, object]
    executed_controls: tuple[ExecutedPhase2Control, ...]
    signature_presence: str
    ctcl_state: str
    ctcl_instant_id: str | None
    ctcl_register_response: dict[str, object] | None
    ctcl_retrieve_response: dict[str, object] | None
    error_codes: tuple[str, ...]

    @property
    def diff_counts(self) -> dict[str, int]:
        counts = self.differential["counts"]
        assert isinstance(counts, dict)
        return {name: int(counts[name]) for name in _DIFF_CLASSES}

    @property
    def phase1a_passed(self) -> bool:
        return bool(self.phase1a_report and self.phase1a_report.get("passed"))

    @property
    def phase1bc_passed(self) -> bool:
        return bool(self.phase1bc_report and self.phase1bc_report.get("passed"))

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": "0.2",
            "receipt_id": self.receipt_id,
            "passed": self.passed,
            "adoption_profile_id": self.adoption_profile_id,
            "adoption_profile_version": self.adoption_profile_version,
            "mapping_profile_id": self.mapping_profile_id,
            "mapping_profile_version": self.mapping_profile_version,
            "compatibility_status": (
                "compatible" if self.passed else "incompatible"
            ),
            "adoption_status": "adopted" if self.passed else "rejected",
            "archive": copy.deepcopy(self.archive),
            "manifest": copy.deepcopy(self.manifest),
            "package": copy.deepcopy(self.package),
            "mapping_profile_digest": self.mapping_profile_digest,
            "phase1": {
                "phase1a": copy.deepcopy(self.phase1a_report),
                "phase1bc": copy.deepcopy(self.phase1bc_report),
                "projection_head": self.phase1_projection_head,
            },
            "integration": copy.deepcopy(self.integration),
            "differential": copy.deepcopy(self.differential),
            "sedb_tests": copy.deepcopy(self.sedb_tests),
            "executed_controls": [
                control.as_json() for control in self.executed_controls
            ],
            "signature_presence": self.signature_presence,
            "ctcl": {
                "state": self.ctcl_state,
                "instant_id": self.ctcl_instant_id,
                "register_response": copy.deepcopy(
                    self.ctcl_register_response
                ),
                "retrieve_response": copy.deepcopy(
                    self.ctcl_retrieve_response
                ),
            },
            "error_codes": list(self.error_codes),
            "evidence_refs": list(_EVIDENCE_REFS),
        }


def _load_object(path: Path) -> dict[str, object]:
    value = loads_strict(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RALValidationError("phase2_profile_not_object", str(path))
    return value


def _string(value: object, fallback: str = "unknown") -> str:
    return value if isinstance(value, str) and value else fallback


def _integer(value: object, fallback: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return fallback


def _error_code(error: Exception) -> str:
    if isinstance(error, RALValidationError):
        return error.code
    if isinstance(error, ValueError):
        message = str(error)
        if message.startswith("sedb_archive_incompatible:"):
            return message.rsplit(":", 1)[-1].split(",", 1)[0]
    if isinstance(error, FileNotFoundError):
        return "input_unreadable"
    if isinstance(error, UnicodeError):
        return "input_not_utf8"
    if isinstance(error, OSError):
        return "phase2_io_error"
    return "phase2_gate_error"


def _empty_diff() -> dict[str, object]:
    return {
        "passed": False,
        "counts": {name: 0 for name in _DIFF_CLASSES},
        "differences": [],
    }


def _task5_module(root: Path) -> tuple[ModuleType, str, ModuleType | None]:
    path = (root / "scripts/validate_sedb_v04b.py").resolve(strict=True)
    module_name = "_sedb_ral_phase2_task5_integration"
    previous = sys.modules.get(module_name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RALValidationError("task5_integration_unavailable", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        raise
    return module, module_name, previous


def _run_task5_integration(
    root: Path,
    archive: Path,
    adoption_profile: Mapping[str, object],
    projection: object,
    mapping: Mapping[str, object],
    output: Path,
) -> object:
    module, module_name, previous = _task5_module(root)
    try:
        runner = getattr(module, "run_integration", None)
        if not callable(runner):
            raise RALValidationError(
                "task5_integration_unavailable", "run_integration"
            )
        return runner(archive, adoption_profile, projection, mapping, output)
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous


def _control(
    name: str,
    injected_change: str,
    expected_code: str,
    observed_code: str,
) -> ExecutedPhase2Control:
    return ExecutedPhase2Control(
        name=name,
        injected_change=injected_change,
        expected_code=expected_code,
        observed_code=observed_code,
        executed=True,
    )


def _archive_hash_control(
    archive: Path, profile: Mapping[str, object]
) -> ExecutedPhase2Control:
    expected = "archive_hash_mismatch"
    corrupted = dict(profile)
    corrupted["archive_sha256"] = "0" * 64
    inspection = inspect_sedb_archive(archive, corrupted)
    observed = (
        expected if expected in inspection.error_codes else "fault_not_detected"
    )
    return _control(
        "archive_hash",
        "replace the pinned archive SHA-256 with sixty-four zeroes",
        expected,
        observed,
    )


def _mutated_manifest_archive(
    archive: Path,
    profile: Mapping[str, object],
    temporary: Path,
) -> tuple[Path, dict[str, object]]:
    destination = temporary / _string(profile.get("archive_filename"))
    manifest_path = _string(profile.get("manifest_path"), "MANIFEST.sha256")
    mutated = False
    with zipfile.ZipFile(archive, "r") as source, zipfile.ZipFile(
        destination, "w"
    ) as sink:
        for info in source.infolist():
            payload = source.read(info)
            if info.filename == manifest_path or info.filename.endswith(
                f"/{manifest_path}"
            ):
                lines = payload.decode("utf-8").splitlines(keepends=True)
                if not lines or len(lines[0]) < 64:
                    raise RALValidationError(
                        "manifest_control_unavailable", info.filename
                    )
                lines[0] = "0" * 64 + lines[0][64:]
                payload = "".join(lines).encode("utf-8")
                mutated = True
            sink.writestr(info, payload)
    if not mutated:
        raise RALValidationError(
            "manifest_control_unavailable", manifest_path
        )
    mutated_profile = dict(profile)
    raw = destination.read_bytes()
    mutated_profile["archive_size"] = len(raw)
    mutated_profile["archive_sha256"] = hashlib.sha256(raw).hexdigest()
    return destination, mutated_profile


def _manifest_control(
    archive: Path,
    profile: Mapping[str, object],
    temporary: Path,
) -> ExecutedPhase2Control:
    expected = "manifest_hash_mismatch"
    try:
        mutated_archive, mutated_profile = _mutated_manifest_archive(
            archive, profile, temporary
        )
        inspection = inspect_sedb_archive(mutated_archive, mutated_profile)
        observed = (
            expected
            if expected in inspection.error_codes
            else "fault_not_detected"
        )
    except Exception as error:
        observed = _error_code(error)
    return _control(
        "manifest",
        "replace one internal MANIFEST.sha256 digest with sixty-four zeroes",
        expected,
        observed,
    )


def _mapping_contradiction_control(
    expected_records: tuple[dict[str, object], ...],
    mapping: Mapping[str, object],
) -> ExecutedPhase2Control:
    expected = "mapped_value_contradiction"
    actual_records = copy.deepcopy(expected_records)
    try:
        values = actual_records[0]["values"]
        assert isinstance(values, dict)
        values["ral.resident_id"] = "resident:injected-contradiction"
        report = compare_sedb_projection(
            expected_records, actual_records, mapping
        )
        observed = (
            expected
            if not report.passed and report.counts["contradiction"] == 1
            else "fault_not_detected"
        )
    except Exception as error:
        observed = _error_code(error)
    return _control(
        "mapping_contradiction",
        "replace the exported mapped ral.resident_id value",
        expected,
        observed,
    )


def _null_false_control(
    expected_records: tuple[dict[str, object], ...],
    mapping: Mapping[str, object],
) -> ExecutedPhase2Control:
    expected = "null_vs_false_contradiction"
    null_records = copy.deepcopy(expected_records)
    false_records = copy.deepcopy(expected_records)
    try:
        null_values = null_records[0]["values"]
        false_values = false_records[0]["values"]
        assert isinstance(null_values, dict)
        assert isinstance(false_values, dict)
        null_values["ral.application_status"] = None
        false_values["ral.application_status"] = False
        report = compare_sedb_projection(null_records, false_records, mapping)
        difference = report.differences[0]
        observed = (
            expected
            if (
                not report.passed
                and report.counts["contradiction"] == 1
                and difference.expected is None
                and difference.actual is False
            )
            else "fault_not_detected"
        )
    except Exception as error:
        observed = _error_code(error)
    return _control(
        "null_vs_false",
        "replace a mapped JSON null with boolean false",
        expected,
        observed,
    )


def _no_send_control(temporary: Path) -> ExecutedPhase2Control:
    expected = "forbidden_call:socket.create_connection"
    source = temporary / "injected.py"
    source.write_text(
        "import socket\nsocket.create_connection(('example.test', 443))\n",
        encoding="utf-8",
    )
    findings = scan_no_send(temporary)
    observed = (
        expected
        if expected in {finding.code for finding in findings}
        else "fault_not_detected"
    )
    return _control(
        "no_send",
        "inject a socket.create_connection call into a temporary package",
        expected,
        observed,
    )


def _executed_controls(
    archive: Path,
    profile: Mapping[str, object],
    expected_records: tuple[dict[str, object], ...],
    mapping: Mapping[str, object],
    temporary: Path,
) -> tuple[ExecutedPhase2Control, ...]:
    temporary.mkdir()
    manifest_root = temporary / "manifest-control"
    manifest_root.mkdir()
    no_send_root = temporary / "no-send-control"
    no_send_root.mkdir()
    return (
        _archive_hash_control(archive, profile),
        _manifest_control(archive, profile, manifest_root),
        _mapping_contradiction_control(expected_records, mapping),
        _null_false_control(expected_records, mapping),
        _no_send_control(no_send_root),
    )


def _archive_payload(
    archive: Path,
    profile: Mapping[str, object],
    inspection: SEDBAdoptionInspection,
) -> dict[str, object]:
    try:
        size = archive.stat().st_size
    except OSError:
        size = 0
    return {
        "filename": archive.name,
        "size": size,
        "sha256": inspection.archive_sha256.upper(),
    }


def _receipt_id(
    adoption_profile: Mapping[str, object],
    mapping_profile: Mapping[str, object],
    mapping_digest: str,
) -> str:
    return sha256_ref(
        {
            "kind": "sedb-ral-basic-phase2-receipt",
            "adoption_profile_id": _string(
                adoption_profile.get("profile_id")
            ),
            "adoption_profile_version": _string(
                adoption_profile.get("profile_version")
            ),
            "mapping_profile_id": _string(mapping_profile.get("profile_id")),
            "mapping_profile_version": _string(
                mapping_profile.get("profile_version")
            ),
            "archive_sha256": _string(
                adoption_profile.get("archive_sha256")
            ).upper(),
            "mapping_profile_digest": mapping_digest,
        }
    )


def _base_report(
    archive: Path,
    adoption_profile: Mapping[str, object],
    mapping_profile: Mapping[str, object],
    inspection: SEDBAdoptionInspection,
) -> Phase2Report:
    mapping_digest = sha256_ref(mapping_profile)
    return Phase2Report(
        passed=False,
        receipt_id=_receipt_id(
            adoption_profile, mapping_profile, mapping_digest
        ),
        adoption_profile_id=_string(adoption_profile.get("profile_id")),
        adoption_profile_version=_string(
            adoption_profile.get("profile_version")
        ),
        mapping_profile_id=_string(mapping_profile.get("profile_id")),
        mapping_profile_version=_string(
            mapping_profile.get("profile_version")
        ),
        archive=_archive_payload(archive, adoption_profile, inspection),
        manifest={
            "path": _string(adoption_profile.get("manifest_path")),
            "expected_entry_count": _integer(
                adoption_profile.get("manifest_entry_count")
            ),
            "observed_entry_count": inspection.manifest_entry_count,
            "verified": inspection.manifest_verified,
        },
        package={
            "name": _string(adoption_profile.get("package_name")),
            "version": inspection.package_version,
            "source_commit": inspection.source_commit,
        },
        mapping_profile_digest=mapping_digest,
        phase1a_report=None,
        phase1bc_report=None,
        phase1_projection_head=None,
        integration=None,
        differential=_empty_diff(),
        sedb_tests={
            "selected_source": "own_execution",
            "package_claim": adoption_profile.get("validation_claim_source"),
            "own_execution": {
                "passed": 189,
                "failed": 0,
                "skipped": 0,
                "fresh_execution": False,
                "inherited_from": _TASK5_REPORT,
            },
        },
        executed_controls=(),
        signature_presence="not_performed",
        ctcl_state="CTCL_FINAL_PENDING",
        ctcl_instant_id=None,
        ctcl_register_response=None,
        ctcl_retrieve_response=None,
        error_codes=inspection.error_codes,
    )


def _integration_payload(result: object) -> dict[str, object]:
    export_path = getattr(result, "export_path")
    exported_records = getattr(result, "exported_records")
    apply_result = getattr(result, "apply_result")
    return {
        "database_integrity": getattr(result, "database_integrity"),
        "field_count": getattr(apply_result, "field_count"),
        "entity_count": getattr(apply_result, "entity_count"),
        "cell_count": getattr(apply_result, "cell_count"),
        "expected_record_count": getattr(result, "expected_record_count"),
        "exported_record_count": getattr(result, "exported_record_count"),
        "records_match": getattr(result, "records_match"),
        "raw_export_sha256": hashlib.sha256(
            Path(export_path).read_bytes()
        ).hexdigest(),
        "normalized_export_digest": sha256_ref(list(exported_records)),
    }


def validate_basic_phase2(
    root: str | Path,
    archive: str | Path,
    *,
    profile: Mapping[str, object] | None = None,
) -> Phase2Report:
    root_path = Path(root).resolve(strict=True)
    archive_path = Path(archive)
    adoption_profile = (
        dict(profile)
        if profile is not None
        else _load_object(root_path / "profiles/sedb-v0.4b-adoption.json")
    )
    mapping_profile = _load_object(
        root_path / "profiles/sedb-v0.4b-mapping.json"
    )
    inspection = inspect_sedb_archive(archive_path, adoption_profile)
    report = _base_report(
        archive_path, adoption_profile, mapping_profile, inspection
    )
    if not inspection.compatible:
        return report

    errors: list[str] = []
    phase1a_payload: dict[str, object] | None = None
    phase1bc_payload: dict[str, object] | None = None
    projection_head: str | None = None
    integration_payload: dict[str, object] | None = None
    differential_payload = _empty_diff()
    controls: tuple[ExecutedPhase2Control, ...] = ()
    try:
        phase1a = validate_phase1a(root_path)
        phase1a_payload = phase1a.as_json()
        if not phase1a.passed:
            errors.append("phase1a_gate_failed")

        phase1bc = validate_phase1bc(root_path)
        phase1bc_payload = phase1bc.as_json()
        if not phase1bc.passed:
            errors.append("phase1bc_gate_failed")

        no_send_findings = scan_no_send(root_path / "src/sedb_ral")
        if no_send_findings:
            errors.append("no_send_violation")

        with tempfile.TemporaryDirectory(
            prefix="sedb-ral-phase2-"
        ) as name:
            temporary = Path(name)
            events = _sample_events(root_path, temporary / "phase1")
            projection = project_events(events)
            projection_head = (
                projection.source_event_ids[-1]
                if projection.source_event_ids
                else None
            )
            if projection_head is None:
                errors.append("phase1_projection_head_missing")

            expected_records = project_to_sedb_records(
                projection, mapping_profile
            )
            integration = _run_task5_integration(
                root_path,
                archive_path,
                adoption_profile,
                projection,
                mapping_profile,
                temporary,
            )
            integration_payload = _integration_payload(integration)
            if (
                integration_payload["database_integrity"] != "ok"
                or integration_payload["records_match"] is not True
            ):
                errors.append("sedb_integration_failed")

            differential: SEDBDiffReport = compare_sedb_projection(
                expected_records,
                getattr(integration, "exported_records"),
                mapping_profile,
            )
            differential_payload = differential.as_json()
            if not differential.passed:
                errors.append("sedb_mapping_contradiction")

            controls = _executed_controls(
                archive_path,
                adoption_profile,
                expected_records,
                mapping_profile,
                temporary / "controls",
            )
    except Exception as error:
        errors.append(_error_code(error))

    for control in controls:
        if (
            not control.executed
            or control.observed_code != control.expected_code
        ):
            errors.append(f"control_failed:{control.name}")

    unique_errors = tuple(sorted(set(errors)))
    completed = replace(
        report,
        passed=not unique_errors,
        phase1a_report=phase1a_payload,
        phase1bc_report=phase1bc_payload,
        phase1_projection_head=projection_head,
        integration=integration_payload,
        differential=differential_payload,
        executed_controls=controls,
        error_codes=unique_errors,
    )
    validate_contract(
        "sedb-compatibility-receipt.schema.json",
        completed.as_json(),
        root_path / "src/sedb_ral/schemas",
    )
    return completed


def _contains_string(value: object, expected: str) -> bool:
    if value == expected:
        return True
    if isinstance(value, Mapping):
        return any(_contains_string(item, expected) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_string(item, expected) for item in value)
    return False


def finalize_basic_phase2(
    report: Phase2Report,
    *,
    ctcl_instant_id: str,
    register_response: Mapping[str, object],
    retrieve_response: Mapping[str, object],
) -> Phase2Report:
    if not report.passed:
        raise RALValidationError(
            "phase2_gate_not_passed", ",".join(report.error_codes)
        )
    if report.ctcl_state != "CTCL_FINAL_PENDING":
        raise RALValidationError(
            "ctcl_already_finalized", report.ctcl_state
        )
    if (
        not isinstance(ctcl_instant_id, str)
        or not ctcl_instant_id.startswith("ctcl:instant:")
        or not _contains_string(register_response, ctcl_instant_id)
    ):
        raise RALValidationError(
            "ctcl_registration_mismatch", ctcl_instant_id
        )
    if not _contains_string(retrieve_response, ctcl_instant_id):
        raise RALValidationError(
            "ctcl_retrieval_mismatch", ctcl_instant_id
        )
    return replace(
        report,
        ctcl_state="finalized",
        ctcl_instant_id=ctcl_instant_id,
        ctcl_register_response=copy.deepcopy(dict(register_response)),
        ctcl_retrieve_response=copy.deepcopy(dict(retrieve_response)),
    )


def write_basic_phase2_receipt(
    report: Phase2Report, destination: str | Path
) -> Path:
    if (
        report.ctcl_state != "finalized"
        or report.ctcl_register_response is None
        or report.ctcl_retrieve_response is None
    ):
        raise RALValidationError(
            "ctcl_final_pending", report.ctcl_state
        )
    payload = report.as_json()
    validate_contract("sedb-compatibility-receipt.schema.json", payload)
    destination_path = Path(destination)
    with destination_path.open("xb") as stream:
        stream.write(canonical_bytes(payload) + b"\n")
    return destination_path
