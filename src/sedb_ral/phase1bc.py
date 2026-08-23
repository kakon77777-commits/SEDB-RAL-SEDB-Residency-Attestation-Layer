from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from .adapters.codex_queue import normalize_codex_queue
from .application import commit_application, evaluate_application
from .delivery import reconstruct_delivery
from .errors import RALValidationError
from .incidents import (
    load_incidents,
    negative_gate_cases,
    validate_required_negative_cases,
)
from .ledger import read_verified_events
from .no_send import scan_no_send
from .phase1a import validate_phase1a
from .sqlite_projection import rebuild_sqlite, table_row_counts


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
    no_send_findings: tuple[str, ...]
    sqlite_row_counts: dict[str, int]
    sqlite_bytes_identical: bool
    incident_count: int
    delivery_stage: str | None
    executed_faults: tuple[ExecutedFault, ...]
    error_codes: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "phase1a_passed": self.phase1a_passed,
            "no_send_findings": list(self.no_send_findings),
            "sqlite_row_counts": self.sqlite_row_counts,
            "sqlite_bytes_identical": self.sqlite_bytes_identical,
            "incident_count": self.incident_count,
            "delivery_stage": self.delivery_stage,
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


def _fault_sqlite_projection_mutation(
    root: Path, temporary: Path
) -> ExecutedFault:
    events = _sample_events(root, temporary)
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


def validate_phase1bc(root: Path) -> Phase1BCReport:
    root = Path(root)
    errors: list[str] = []
    phase1a = validate_phase1a(root)
    if not phase1a.passed:
        errors.append("phase1a_gate_failed")

    schema_root = root / "src/sedb_ral/schemas"
    for path in sorted(schema_root.glob("*.schema.json")):
        try:
            Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
        except Exception as error:
            errors.append(f"schema_invalid:{path.name}:{_error_code(error)}")

    findings = scan_no_send(root / "src/sedb_ral")
    no_send_findings = tuple(item.code for item in findings)
    if findings:
        errors.append("no_send_violation")

    sqlite_counts: dict[str, int] = {}
    sqlite_bytes_identical = False
    faults: list[ExecutedFault] = []
    try:
        with tempfile.TemporaryDirectory(prefix="sedb-ral-phase1bc-") as name:
            temporary = Path(name)
            events = _sample_events(root, temporary)
            first = rebuild_sqlite(events, temporary / "first.sqlite3")
            second = rebuild_sqlite(events, temporary / "second.sqlite3")
            sqlite_counts = table_row_counts(first)
            sqlite_bytes_identical = first.read_bytes() == second.read_bytes()
            if not sqlite_bytes_identical:
                errors.append("sqlite_rebuild_nondeterministic")
            if sqlite_counts["applications"] != 1 or sqlite_counts["residents"] != 1:
                errors.append("sqlite_projection_incomplete")
            controls = (
                lambda: _fault_phase1a_missing_negative_fixture(root),
                lambda: _fault_sqlite_projection_mutation(
                    root, temporary / "mutation"
                ),
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

    try:
        fixture = _load(root / "fixtures/application/authorized-zero-address.json")
        decision = evaluate_application(
            fixture["application"],
            fixture["authorities"],
            verified_attestation_refs=frozenset({"attestation:neo:1"}),
        )
        if (
            decision.decision != fixture["expected_decision"]
            or list(decision.reason_codes) != fixture["expected_reason_codes"]
        ):
            errors.append("application_fixture_mismatch")
    except Exception as error:
        errors.append(_error_code(error))

    incident_count = 0
    try:
        incidents = load_incidents(root / "corpus/incidents.jsonl")
        incident_count = len(incidents)
        errors.extend(validate_required_negative_cases(negative_gate_cases(incidents)))
    except Exception as error:
        errors.append(_error_code(error))

    delivery_stage = None
    try:
        observation = normalize_codex_queue(
            _load(root / "fixtures/adapters/codex-queue/materialized-and-acknowledged.json")
        )
        delivery = reconstruct_delivery((observation,))
        delivery_stage = delivery.stage
        if delivery.stage != "instance_acknowledged" or delivery.observed_origin is not None:
            errors.append("delivery_fixture_mismatch")
    except Exception as error:
        errors.append(_error_code(error))

    for fault in faults:
        if not fault.executed or fault.observed_red_code != fault.expected_red_code:
            errors.append(f"fault_control_failed:{fault.test_name}")
    unique_errors = tuple(sorted(set(errors)))
    return Phase1BCReport(
        passed=not unique_errors,
        phase1a_passed=phase1a.passed,
        no_send_findings=no_send_findings,
        sqlite_row_counts=sqlite_counts,
        sqlite_bytes_identical=sqlite_bytes_identical,
        incident_count=incident_count,
        delivery_stage=delivery_stage,
        executed_faults=tuple(faults),
        error_codes=unique_errors,
    )
