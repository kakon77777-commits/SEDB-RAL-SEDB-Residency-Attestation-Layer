from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from . import __version__
from .canonical import canonical_bytes, loads_strict, sha256_ref
from .errors import RALValidationError
from .ledger import read_verified_events
from .no_send import scan_no_send
from .projection import RegistryProjection, continuity_line_for, project_events
from .registrar import (
    RegistrarAdmissionPlan,
    build_admission_plan,
    commit_admission_plan,
)
from .registration import (
    PreparedRegistration,
    RegistrationIds,
    prepare_registration,
)
from .registration_admission import (
    RegistrationDecision,
    evaluate_prepared_registration,
)

EXPECTED_CASE_IDS = tuple(f"P3-{index:03d}" for index in range(1, 25))
EXPECTED_CONTROLS = (
    "applicant-opt-out",
    "applicant-host-address-mismatch",
    "host-origin-unverified",
    "opaque-id-name-leak",
    "authority-missing",
    "authority-authorship-unverified",
    "address-binding-conflict",
    "prepared-digest-mutation",
    "expected-head-mismatch",
    "staging-projection-mutation",
    "partial-transaction",
    "package-no-send",
)
_CONTROL_CASES = {
    "applicant-opt-out": "P3-002",
    "applicant-host-address-mismatch": "P3-003",
    "host-origin-unverified": "P3-004",
    "opaque-id-name-leak": "P3-005",
    "authority-missing": "P3-008",
    "authority-authorship-unverified": "P3-009",
    "address-binding-conflict": "P3-011",
    "prepared-digest-mutation": "P3-013",
    "expected-head-mismatch": "P3-017",
    "staging-projection-mutation": "P3-019",
    "partial-transaction": "P3-021",
    "package-no-send": "P3-024",
}
_NOT_CLAIMED = (
    "real_applicant_registration",
    "production_registry",
    "registrar_mcp",
    "limen_b6",
    "private_residence_access",
    "release_or_deployment",
)
_VERIFIED = frozenset({"attestation:test-principal"})


@dataclass(frozen=True)
class Phase3ACase:
    case_id: str
    name: str
    expected_code: str
    observed_code: str
    passed: bool

    def as_json(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "name": self.name,
            "expected_code": self.expected_code,
            "observed_code": self.observed_code,
            "status": "PASS" if self.passed else "FAIL",
        }


@dataclass(frozen=True)
class Phase3AControl:
    name: str
    case_id: str
    expected_code: str
    observed_code: str
    executed: bool
    passed: bool

    def as_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "case_id": self.case_id,
            "expected_code": self.expected_code,
            "observed_code": self.observed_code,
            "executed": self.executed,
            "status": "PASS" if self.passed else "FAIL",
        }


@dataclass(frozen=True)
class _RunEvidence:
    cases: tuple[Phase3ACase, ...]
    controls: tuple[Phase3AControl, ...]
    staging_head: str | None
    canonical_head: str | None
    package_scan: dict[str, object]
    execution_digest: str


@dataclass(frozen=True)
class Phase3AReport:
    passed: bool
    implementation_commit: str
    candidate_source_digest: str
    schema_digests: dict[str, str]
    cases: tuple[Phase3ACase, ...]
    controls: tuple[Phase3AControl, ...]
    staging_head: str | None
    canonical_head: str | None
    execution_digest: str
    repeated_execution_digest: str
    repeated_run_match: bool
    package_scan: dict[str, object]
    error_codes: tuple[str, ...]
    report_digest: str
    network_calls: int = 0
    private_reads: int = 0
    real_applicant_count: int = 0
    synthetic_applicant_count: int = 2

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(item.case_id for item in self.cases)

    @property
    def control_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.controls)

    def _material(self) -> dict[str, object]:
        return {
            "schema": "sedb-ral.phase3a-acceptance/0.1",
            "passed": self.passed,
            "candidate_version": __version__,
            "implementation_commit": self.implementation_commit,
            "candidate_source_digest": self.candidate_source_digest,
            "source_invocation": (
                "PYTHONPATH=src python scripts/validate_phase3a.py "
                "--output <explicit-path>"
            ),
            "schema_digests": self.schema_digests,
            "case_ids": list(self.case_ids),
            "cases": [item.as_json() for item in self.cases],
            "controls": [item.as_json() for item in self.controls],
            "case_counts": {
                "pass": sum(item.passed for item in self.cases),
                "fail": sum(not item.passed for item in self.cases),
                "blocked": 0,
            },
            "staging_head": self.staging_head,
            "canonical_head": self.canonical_head,
            "execution_digest": self.execution_digest,
            "repeated_execution_digest": self.repeated_execution_digest,
            "repeated_run_match": self.repeated_run_match,
            "package_scan": self.package_scan,
            "network_calls": self.network_calls,
            "private_reads": self.private_reads,
            "real_applicant_count": self.real_applicant_count,
            "synthetic_applicant_count": self.synthetic_applicant_count,
            "canonical_write_scope": "temporary-synthetic-only",
            "production_registry_created": False,
            "registrar_mcp_implemented": False,
            "limen_b6_implemented": False,
            "private_residence_accessed": False,
            "release_or_deployment": False,
            "not_claimed": list(_NOT_CLAIMED),
            "error_codes": list(self.error_codes),
        }

    def as_json(self) -> dict[str, object]:
        return {**self._material(), "report_digest": self.report_digest}


def _empty_projection() -> RegistryProjection:
    return RegistryProjection(
        applications={},
        residents={},
        directory={},
        claims={},
        resident_source_event_ids={},
        applied_corrections=(),
        unapplied_event_ids=(),
        unapplied_reasons={},
        source_event_ids=(),
    )


def _ids(prefix: str = "alpha") -> RegistrationIds:
    tokens = {
        "alpha": (
            "7b5a4b15",
            "42ce0eb1",
            "75c9559e",
            "bb68ace7",
            "cb6d31e7",
            "79b497c5",
            "81f5895d",
            "10757453",
            "b2fc8d91",
        ),
        "beta": (
            "2f2635d4",
            "aab9a46c",
            "62c1b027",
            "67c29194",
            "5dc9745a",
            "e41bcb77",
            "0eb29057",
            "092bdb6d",
            "5fc7fa42",
        ),
    }[prefix]
    return RegistrationIds(
        prepared_id=f"prepared:{tokens[0]}",
        application_id=f"application:{tokens[1]}",
        resident_id=f"resident:{tokens[2]}",
        instance_id=f"instance:{tokens[3]}",
        continuity_line_id=f"line:{tokens[4]}",
        address_ids=(f"address:codex-thread:{tokens[5]}",),
        claim_ids=(
            f"claim:display:{tokens[6]}",
            f"claim:role:{tokens[7]}",
            f"claim:line:{tokens[8]}",
        ),
    )


def _claim(
    *,
    label: str = "Synthetic Resident",
    thread: str = "thread:test-alpha",
    opt_in: bool = True,
    continuity: str = "new",
    existing: str | None = None,
) -> dict[str, object]:
    return {
        "schema": "sedb-ral.self-application-claim/0.1",
        "applicant_claim_only": True,
        "desired_display_label": label,
        "existing_resident_claim": existing,
        "continuity_claim": continuity,
        "desired_addresses": [
            {
                "namespace": "codex_thread",
                "identifier_kind": "codex_thread",
                "locator": thread,
            }
        ],
        "role_description_claim": "Synthetic registration tester",
        "dissent_or_limits": ["No private access"],
        "opt_in": opt_in,
        "relay_is_authorship": False,
        "not_claimed": [
            "verified_identity",
            "registrar_authority",
            "private_access",
        ],
    }


def _host(
    *,
    thread: str = "thread:test-alpha",
    origin: str = "host:codex-app-thread-tools",
    suffix: str = "alpha",
) -> dict[str, object]:
    return {
        "schema": "sedb-ral.registration-host-observation/0.1",
        "observation_id": f"observation:test-{suffix}",
        "provider": "openai",
        "adapter_kind": "codex_app_task_tool",
        "identifier_kind": "codex_thread",
        "native_thread_id": thread,
        "native_session_id": None,
        "native_turn_id": f"turn:test-{suffix}",
        "unavailable_fields": [
            {
                "field": "native_session_id",
                "reason": (
                    "structurally_unavailable_from_codex_app_task_tool"
                ),
            }
        ],
        "observed_origin": origin,
        "observed_at_ref": "ctcl:instant:test-registration",
        "applicant_item_ref": f"item:test-{suffix}",
        "not_claimed": ["pre_turn_output_enforcement"],
    }


def _authority(
    prepared: PreparedRegistration, suffix: str = "alpha"
) -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "authority_id": f"authority:test-principal-{suffix}",
        "principal_ref": "principal:test",
        "subject_kind": "application_digest",
        "subject_ref": prepared.application_digest,
        "scopes": ["registry.application.accept"],
        "status": "active",
        "issued_time_ref": "ctcl:instant:test-authority",
        "revoked_by_event": None,
        "authorship_attestation_ref": "attestation:test-principal",
    }


def _resident_projection(
    *,
    label: str = "Other Resident",
    locator: str | None = None,
    address_status: str = "active",
    second_line: bool = False,
) -> RegistryProjection:
    resident_id = "resident:test-other"
    instance_id = "instance:test-other"
    claims = [
        {
            "schema_version": "0.1",
            "claim_id": "claim:test-other-line",
            "claimant_ref": resident_id,
            "subject_ref": resident_id,
            "predicate": "continuity_line_id",
            "object": "line:test-other",
            "claimed_time": "ctcl:instant:test-existing",
            "claimed_authored_by_instance": instance_id,
            "claimed_on_behalf_of_line": None,
        }
    ]
    if second_line:
        other = copy.deepcopy(claims[0])
        other["claim_id"] = "claim:test-other-line-conflict"
        other["object"] = "line:test-conflict"
        claims.append(other)
    addresses = []
    if locator is not None:
        addresses.append(
            {
                "schema_version": "0.1",
                "address_id": "address:test-other",
                "namespace": "codex_thread",
                "adapter_kind": "codex_app_task_tool",
                "locator": locator,
                "target_ref": resident_id,
                "status": address_status,
            }
        )
    resident = {
        "schema_version": "0.1",
        "resident_id": resident_id,
        "display_label": label,
        "status": "active",
        "application_ref": "application:test-other",
        "identifier_refs": [],
        "instances": [
            {
                "schema_version": "0.1",
                "instance_id": instance_id,
                "resident_ref": resident_id,
                "runtime_tag": "runtime:test",
                "started_time_ref": "ctcl:instant:test-existing",
                "ended_time_ref": None,
            }
        ],
        "addresses": addresses,
        "claims": claims,
    }
    projection = _empty_projection()
    projection.residents[resident_id] = resident
    projection.directory[resident_id] = {
        "display_label": label,
        "status": "active",
        "addresses": addresses,
        "instance_refs": [instance_id],
    }
    projection.claims.update({item["claim_id"]: item for item in claims})
    return projection


def _error_code(error: Exception) -> str:
    if isinstance(error, RALValidationError):
        return error.code
    if isinstance(error, (OSError, UnicodeError, json.JSONDecodeError)):
        return "phase3a_input_error"
    return "phase3a_unexpected_error"


def _case(
    cases: list[Phase3ACase],
    case_id: str,
    name: str,
    expected_code: str,
    operation: Callable[[], str | None],
) -> None:
    try:
        result = operation()
        observed = result if isinstance(result, str) else "ok" if result is None else "fault_not_detected"
    except (
        RALValidationError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        observed = _error_code(error)
    cases.append(
        Phase3ACase(
            case_id=case_id,
            name=name,
            expected_code=expected_code,
            observed_code=observed,
            passed=observed == expected_code,
        )
    )


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise RALValidationError(code, "Phase 3A acceptance condition failed")


def _load_ctcl(root: Path) -> dict[str, object]:
    value = loads_strict(
        (root / "fixtures/ctcl/registered-anchor.json").read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(value, dict):
        raise RALValidationError("ctcl_receipt_invalid", "not an object")
    return value


def _trim_prefix(root: Path, keep: int) -> None:
    event_paths = sorted((root / "events").rglob("*.json"))
    anchor_paths = sorted((root / "anchors").glob("*.json"))
    for path in event_paths[keep:]:
        path.unlink()
    for path in anchor_paths[keep:]:
        path.unlink()


def _phase3_source_paths(root: Path) -> tuple[Path, ...]:
    exact = (
        ".gitignore",
        "pyproject.toml",
        "src/sedb_ral/__init__.py",
        "src/sedb_ral/cli.py",
        "src/sedb_ral/registration.py",
        "src/sedb_ral/registration_admission.py",
        "src/sedb_ral/registrar.py",
        "src/sedb_ral/phase3a.py",
        "src/sedb_ral/schemas/self-application-claim.schema.json",
        "src/sedb_ral/schemas/registration-host-observation.schema.json",
        "src/sedb_ral/schemas/prepared-registration.schema.json",
        "scripts/validate_phase3a.py",
        "tests/test_phase3_registration_prepare.py",
        "tests/test_phase3_registration_admission.py",
        "tests/test_phase3_registrar_plan.py",
        "tests/test_phase3_registrar_recovery.py",
        "tests/test_phase3_cli.py",
        "tests/test_phase3a_gate.py",
        "docs/runtime/PHASE3A_REGISTRAR_CORE.md",
        ".github/workflows/phase3a.yml",
        "README.md",
    )
    return tuple(root / relative for relative in exact if (root / relative).is_file())


def _candidate_source_digest(root: Path) -> str:
    values = {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in _phase3_source_paths(root)
    }
    return sha256_ref({"files": values})


def _schema_digests(root: Path) -> dict[str, str]:
    names = (
        "prepared-registration.schema.json",
        "registration-host-observation.schema.json",
        "self-application-claim.schema.json",
    )
    return {
        name: hashlib.sha256(
            (root / "src/sedb_ral/schemas" / name).read_bytes()
        ).hexdigest()
        for name in names
    }


def _git_head(root: Path) -> str:
    git = root / ".git"
    if git.is_file():
        line = git.read_text(encoding="utf-8").strip()
        if line.startswith("gitdir: "):
            git = (root / line.removeprefix("gitdir: ")).resolve()
    head = git / "HEAD"
    if not head.is_file():
        return "unavailable"
    value = head.read_text(encoding="ascii").strip()
    if not value.startswith("ref: "):
        return value
    reference = value.removeprefix("ref: ")
    ref_path = git / reference
    if ref_path.is_file():
        return ref_path.read_text(encoding="ascii").strip()
    packed = git / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="ascii").splitlines():
            if line.endswith(f" {reference}"):
                return line.split(" ", 1)[0]
    return "unavailable"


def _package_boundary(root: Path, run_root: Path) -> tuple[str, dict[str, object]]:
    findings = scan_no_send(root / "src/sedb_ral")
    _require(not findings, "package_no_send_failed")
    task_pattern = re.compile(
        r"\b01[a-f0-9]{6}-[a-f0-9]{4}-[a-f0-9]{4}-"
        r"[a-f0-9]{4}-[a-f0-9]{12}\b"
    )
    private_marker = "D:" + "\\AI_" + "RESIDENCE"
    secret_patterns = (
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )
    task_ids = 0
    private_markers = 0
    credential_markers = 0
    for path in _phase3_source_paths(root):
        text = path.read_text(encoding="utf-8")
        task_ids += len(task_pattern.findall(text))
        private_markers += text.count(private_marker)
        credential_markers += sum(
            len(pattern.findall(text)) for pattern in secret_patterns
        )
    _require(task_ids == 0, "real_codex_task_id_present")
    _require(private_markers == 0, "private_root_marker_present")
    _require(credential_markers == 0, "credential_marker_present")
    production_roots = (
        root / "registry/events",
        root / "production-ledger/events",
        root / "canonical-registry/events",
    )
    _require(
        not any(path.exists() for path in production_roots),
        "production_ledger_present",
    )

    injected = run_root / "no-send-injected"
    injected.mkdir()
    (injected / "network.py").write_text(
        "import socket\nsocket.create_connection(('example.test', 443))\n",
        encoding="utf-8",
    )
    injected_codes = {item.code for item in scan_no_send(injected)}
    expected = "forbidden_call:socket.create_connection"
    _require(expected in injected_codes, "package_no_send_control_failed")
    return expected, {
        "package_no_send_findings": 0,
        "scanned_phase3_files": len(_phase3_source_paths(root)),
        "real_codex_task_ids": task_ids,
        "private_root_markers": private_markers,
        "credential_markers": credential_markers,
        "production_ledger_directories": 0,
        "injected_control_code": expected,
    }


def _execute_once(root: Path, run_root: Path) -> _RunEvidence:
    cases: list[Phase3ACase] = []
    state: dict[str, object] = {}
    ids = _ids()
    claim = _claim()
    host = _host()
    ctcl = _load_ctcl(root)

    def prepare_positive() -> str:
        state["prepared"] = prepare_registration(claim, host, ids)
        return "ok"

    _case(cases, "P3-001", "prepare opted-in self claim", "ok", prepare_positive)
    _case(
        cases,
        "P3-002",
        "applicant opt-out",
        "applicant_opt_out",
        lambda: prepare_registration(_claim(opt_in=False), host, ids),
    )
    _case(
        cases,
        "P3-003",
        "applicant and host address mismatch",
        "applicant_address_host_mismatch",
        lambda: prepare_registration(
            _claim(thread="thread:test-other"), host, ids
        ),
    )
    _case(
        cases,
        "P3-004",
        "host origin is not host-observed",
        "schema_invalid",
        lambda: prepare_registration(
            claim, _host(origin="model:self-report"), ids
        ),
    )
    leaked_ids = replace(ids, application_id="application:synthetic-resident")
    _case(
        cases,
        "P3-005",
        "display label embedded in opaque ID",
        "registration_id_not_opaque",
        lambda: prepare_registration(claim, host, leaked_ids),
    )

    def session_absence() -> str:
        prepared = state["prepared"]
        _require(
            prepared.host_observation["native_session_id"] is None,
            "session_absence_lost",
        )
        _require(
            prepared.host_observation["unavailable_fields"]
            == [
                {
                    "field": "native_session_id",
                    "reason": (
                        "structurally_unavailable_from_codex_app_task_tool"
                    ),
                }
            ],
            "session_absence_reason_lost",
        )
        return "ok"

    _case(
        cases,
        "P3-006",
        "task-tool session absence preserved",
        "ok",
        session_absence,
    )

    prepared = state["prepared"]
    authority = _authority(prepared)

    def exact_authority() -> str:
        decision = evaluate_prepared_registration(
            prepared,
            [authority],
            verified_attestation_refs=_VERIFIED,
            projection=_empty_projection(),
        )
        _require(decision.decision == "accept", "authority_not_accepted")
        state["decision"] = decision
        return "ok"

    _case(cases, "P3-007", "exact digest authority", "ok", exact_authority)
    _case(
        cases,
        "P3-008",
        "authority missing",
        "authority_missing",
        lambda: evaluate_prepared_registration(
            prepared,
            [],
            verified_attestation_refs=frozenset(),
            projection=_empty_projection(),
        ).reason_codes[0],
    )
    _case(
        cases,
        "P3-009",
        "authority authorship unverified",
        "authority_authorship_unverified",
        lambda: evaluate_prepared_registration(
            prepared,
            [authority],
            verified_attestation_refs=frozenset(),
            projection=_empty_projection(),
        ).reason_codes[0],
    )
    _case(
        cases,
        "P3-010",
        "homonymous label is not identity collision",
        "ok",
        lambda: (
            "ok"
            if evaluate_prepared_registration(
                prepared,
                [authority],
                verified_attestation_refs=_VERIFIED,
                projection=_resident_projection(label="Synthetic Resident"),
            ).decision
            == "accept"
            else "homonymous_label_rejected"
        ),
    )
    _case(
        cases,
        "P3-011",
        "active native address collision",
        "address_binding_conflict",
        lambda: evaluate_prepared_registration(
            prepared,
            [authority],
            verified_attestation_refs=_VERIFIED,
            projection=_resident_projection(locator="thread:test-alpha"),
        ).reason_codes[0],
    )
    _case(
        cases,
        "P3-012",
        "revoked native address does not reserve locator",
        "ok",
        lambda: (
            "ok"
            if evaluate_prepared_registration(
                prepared,
                [authority],
                verified_attestation_refs=_VERIFIED,
                projection=_resident_projection(
                    locator="thread:test-alpha", address_status="revoked"
                ),
            ).decision
            == "accept"
            else "inactive_address_reserved"
        ),
    )

    def mutate_prepared() -> str:
        changed = copy.deepcopy(prepared)
        changed.application["display_label"] = "Tampered"
        return evaluate_prepared_registration(
            changed,
            [],
            verified_attestation_refs=frozenset(),
            projection=_empty_projection(),
        ).decision

    _case(
        cases,
        "P3-013",
        "prepared application digest mutation",
        "prepared_application_digest_mismatch",
        mutate_prepared,
    )
    continuation = prepare_registration(
        _claim(continuity="continue", existing="resident:missing"),
        host,
        ids,
    )
    continuation_authority = _authority(continuation, "continuation")
    _case(
        cases,
        "P3-014",
        "continuity resident missing",
        "continuity_resident_missing",
        lambda: evaluate_prepared_registration(
            continuation,
            [continuation_authority],
            verified_attestation_refs=_VERIFIED,
            projection=_empty_projection(),
        ).reason_codes[0],
    )
    _case(
        cases,
        "P3-015",
        "continuity line ambiguity",
        "continuity_line_ambiguous",
        lambda: continuity_line_for(
            "resident:test-other",
            _resident_projection(second_line=True),
        ),
    )

    decision = state["decision"]
    canonical = run_root / "canonical"
    staging = run_root / "staging"

    def stage_candidate() -> str:
        plan = build_admission_plan(
            canonical,
            prepared,
            decision,
            authority,
            ctcl,
            expected_head=None,
            verified_attestation_refs=_VERIFIED,
            staging_parent=staging,
        )
        _require(not canonical.exists(), "staging_mutated_canonical")
        _require(not list(staging.iterdir()), "staging_not_cleaned")
        state["plan"] = plan
        return "ok"

    _case(
        cases,
        "P3-016",
        "isolated staging leaves canonical root absent",
        "ok",
        stage_candidate,
    )
    _case(
        cases,
        "P3-017",
        "wrong expected head",
        "external_anchor_mismatch",
        lambda: build_admission_plan(
            run_root / "wrong-head-canonical",
            prepared,
            decision,
            authority,
            ctcl,
            expected_head="sha256:sedb-ral-chain-v1:" + "0" * 64,
            verified_attestation_refs=_VERIFIED,
            staging_parent=run_root / "wrong-head-stage",
        ),
    )

    plan = state["plan"]

    def commit_candidate() -> str:
        receipt = commit_admission_plan(
            canonical,
            plan,
            prepared,
            decision,
            authority,
            ctcl,
            verified_attestation_refs=_VERIFIED,
        )
        _require(receipt.final_head == plan.candidate_head, "commit_head_mismatch")
        state["receipt"] = receipt
        return "ok"

    _case(cases, "P3-018", "exact staged commit", "ok", commit_candidate)

    def projection_mutation() -> str:
        mutation_root = run_root / "projection-mutation-canonical"
        mutation_plan = build_admission_plan(
            mutation_root,
            prepared,
            decision,
            authority,
            ctcl,
            expected_head=None,
            verified_attestation_refs=_VERIFIED,
            staging_parent=run_root / "projection-mutation-stage",
        )
        changed = replace(
            mutation_plan,
            projection_digest=(
                "sha256:sedb-ral-json-nfc-codepoint-v1:" + "0" * 64
            ),
            plan_digest="",
        )
        changed = replace(changed, plan_digest=sha256_ref(changed._material()))
        try:
            commit_admission_plan(
                mutation_root,
                changed,
                prepared,
                decision,
                authority,
                ctcl,
                verified_attestation_refs=_VERIFIED,
            )
        except RALValidationError:
            _require(not mutation_root.exists(), "mutation_wrote_canonical")
            raise
        return "fault_not_detected"

    _case(
        cases,
        "P3-019",
        "recomputed staging projection mutation",
        "registrar_staged_candidate_mismatch",
        projection_mutation,
    )

    def retry_candidate() -> str:
        receipt = commit_admission_plan(
            canonical,
            plan,
            prepared,
            decision,
            authority,
            ctcl,
            verified_attestation_refs=_VERIFIED,
        )
        _require(receipt.idempotent and not receipt.committed, "retry_not_idempotent")
        return "ok"

    _case(cases, "P3-020", "identical retry", "ok", retry_candidate)

    def partial_prefix() -> str:
        partial_root = run_root / "partial-canonical"
        partial_plan = build_admission_plan(
            partial_root,
            prepared,
            decision,
            authority,
            ctcl,
            expected_head=None,
            verified_attestation_refs=_VERIFIED,
            staging_parent=run_root / "partial-stage",
        )
        commit_admission_plan(
            partial_root,
            partial_plan,
            prepared,
            decision,
            authority,
            ctcl,
            verified_attestation_refs=_VERIFIED,
        )
        _trim_prefix(partial_root, 2)
        before = {
            path.relative_to(partial_root).as_posix(): path.read_bytes()
            for path in partial_root.rglob("*.json")
        }
        try:
            commit_admission_plan(
                partial_root,
                partial_plan,
                prepared,
                decision,
                authority,
                ctcl,
                verified_attestation_refs=_VERIFIED,
            )
        except RALValidationError:
            after = {
                path.relative_to(partial_root).as_posix(): path.read_bytes()
                for path in partial_root.rglob("*.json")
            }
            _require(before == after, "partial_prefix_mutated")
            raise
        return "fault_not_detected"

    _case(
        cases,
        "P3-021",
        "valid partial transaction prefix",
        "registrar_partial_transaction",
        partial_prefix,
    )

    def serialization_parity() -> str:
        restored_prepared = PreparedRegistration.from_dict(prepared.to_dict())
        restored_decision = RegistrationDecision.from_dict(decision.to_dict())
        restored_plan = RegistrarAdmissionPlan.from_dict(plan.to_dict())
        _require(
            canonical_bytes(restored_prepared.to_dict())
            == canonical_bytes(prepared.to_dict()),
            "prepared_roundtrip_mismatch",
        )
        _require(
            canonical_bytes(restored_decision.to_dict())
            == canonical_bytes(decision.to_dict()),
            "decision_roundtrip_mismatch",
        )
        _require(
            canonical_bytes(restored_plan.to_dict())
            == canonical_bytes(plan.to_dict()),
            "plan_roundtrip_mismatch",
        )
        return "ok"

    _case(
        cases,
        "P3-022",
        "canonical Core serialization parity",
        "ok",
        serialization_parity,
    )

    def second_applicant() -> str:
        first_receipt = state["receipt"]
        beta_ids = _ids("beta")
        beta = prepare_registration(
            _claim(
                label="Second Synthetic Resident",
                thread="thread:test-beta",
            ),
            _host(thread="thread:test-beta", suffix="beta"),
            beta_ids,
        )
        beta_authority = _authority(beta, "beta")
        source_events = read_verified_events(canonical, first_receipt.final_head)
        beta_decision = evaluate_prepared_registration(
            beta,
            [beta_authority],
            verified_attestation_refs=_VERIFIED,
            projection=project_events(source_events),
        )
        beta_plan = build_admission_plan(
            canonical,
            beta,
            beta_decision,
            beta_authority,
            ctcl,
            expected_head=first_receipt.final_head,
            verified_attestation_refs=_VERIFIED,
            staging_parent=run_root / "beta-stage",
        )
        beta_receipt = commit_admission_plan(
            canonical,
            beta_plan,
            beta,
            beta_decision,
            beta_authority,
            ctcl,
            verified_attestation_refs=_VERIFIED,
        )
        final_projection = project_events(
            read_verified_events(canonical, beta_receipt.final_head)
        )
        _require(len(final_projection.residents) == 2, "second_resident_missing")
        state["final_head"] = beta_receipt.final_head
        return "ok"

    _case(
        cases,
        "P3-023",
        "second applicant after retained head",
        "ok",
        second_applicant,
    )

    package_result: dict[str, object] = {}

    def package_boundary() -> str:
        observed, details = _package_boundary(root, run_root)
        package_result.update(details)
        return observed

    _case(
        cases,
        "P3-024",
        "package no-send and private-boundary control",
        "forbidden_call:socket.create_connection",
        package_boundary,
    )

    case_by_id = {item.case_id: item for item in cases}
    controls = tuple(
        Phase3AControl(
            name=name,
            case_id=case_id,
            expected_code=case_by_id[case_id].expected_code,
            observed_code=case_by_id[case_id].observed_code,
            executed=True,
            passed=case_by_id[case_id].passed,
        )
        for name, case_id in (
            (name, _CONTROL_CASES[name]) for name in EXPECTED_CONTROLS
        )
    )
    execution_value = {
        "cases": [item.as_json() for item in cases],
        "controls": [item.as_json() for item in controls],
        "staging_head": plan.candidate_head,
        "canonical_head": state.get("final_head"),
        "package_scan": package_result,
    }
    return _RunEvidence(
        cases=tuple(cases),
        controls=controls,
        staging_head=plan.candidate_head,
        canonical_head=state.get("final_head"),
        package_scan=package_result,
        execution_digest=sha256_ref(execution_value),
    )


def validate_phase3a(
    root: Path, *, output_root: Path | None = None
) -> Phase3AReport:
    root = Path(root).resolve()
    if output_root is None:
        temporary_parent = None
    else:
        temporary_parent = Path(output_root)
        temporary_parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix="sedb-ral-phase3a-first-", dir=temporary_parent
    ) as first_path:
        first = _execute_once(root, Path(first_path))
    with TemporaryDirectory(
        prefix="sedb-ral-phase3a-second-", dir=temporary_parent
    ) as second_path:
        second = _execute_once(root, Path(second_path))

    repeated_match = first.execution_digest == second.execution_digest
    errors: list[str] = []
    if tuple(item.case_id for item in first.cases) != EXPECTED_CASE_IDS:
        errors.append("phase3a_case_inventory_mismatch")
    if tuple(item.name for item in first.controls) != EXPECTED_CONTROLS:
        errors.append("phase3a_control_inventory_mismatch")
    if not all(item.passed for item in first.cases):
        errors.append("phase3a_case_failed")
    if not all(item.executed and item.passed for item in first.controls):
        errors.append("phase3a_control_failed")
    if not repeated_match:
        errors.append("phase3a_repeat_mismatch")
    passed = not errors
    fields = {
        "passed": passed,
        "implementation_commit": _git_head(root),
        "candidate_source_digest": _candidate_source_digest(root),
        "schema_digests": _schema_digests(root),
        "cases": first.cases,
        "controls": first.controls,
        "staging_head": first.staging_head,
        "canonical_head": first.canonical_head,
        "execution_digest": first.execution_digest,
        "repeated_execution_digest": second.execution_digest,
        "repeated_run_match": repeated_match,
        "package_scan": first.package_scan,
        "error_codes": tuple(errors),
    }
    provisional = Phase3AReport(**fields, report_digest="")
    return Phase3AReport(
        **fields,
        report_digest=sha256_ref(provisional._material()),
    )


def write_phase3a_report(
    report: Phase3AReport, destination: Path
) -> Path:
    if not report.passed:
        raise RALValidationError(
            "phase3a_report_not_passed", "only a passing report may be written"
        )
    if sha256_ref(report._material()) != report.report_digest:
        raise RALValidationError(
            "phase3a_report_digest_mismatch", "report digest differs"
        )
    destination = Path(destination)
    with destination.open("xb") as stream:
        stream.write(canonical_bytes(report.as_json()) + b"\n")
    return destination
