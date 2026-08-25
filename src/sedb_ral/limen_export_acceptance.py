from __future__ import annotations

import copy
import hashlib
import io
import re
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from . import __version__
from .canonical import canonical_bytes, loads_strict, sha256_ref
from .cli import main as cli_main
from .errors import RALValidationError
from .ledger import read_verified_events
from .limen_public_view import (
    build_limen_public_view,
    limen_contract_digest,
)
from .no_send import scan_no_send
from .projection import RegistryProjection, project_events
from .registrar import build_admission_plan, commit_admission_plan
from .registration import RegistrationIds, prepare_registration
from .registration_admission import evaluate_prepared_registration

EXPECTED_CASE_IDS = tuple(f"S6A-{index:03d}" for index in range(1, 9))
EXPECTED_CONTROLS = (
    "thread-collision-no-tiebreak",
    "instance-ambiguity-no-selection",
    "line-ambiguity-no-selection",
    "inactive-binding-no-resolution",
    "app-server-session-not-inferred",
    "package-no-send",
)
_NOT_CLAIMED = (
    "limen_consumption",
    "real_identity_resolution",
    "host_enforcement",
    "private_access",
    "production_registry",
    "release_or_deployment",
)
_HEAD = "sha256:sedb-ral-chain-v1:" + "a" * 64


@dataclass(frozen=True)
class ExportCase:
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
class ExportControl:
    name: str
    expected_code: str
    observed_code: str
    executed: bool
    passed: bool

    def as_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "expected_code": self.expected_code,
            "observed_code": self.observed_code,
            "executed": self.executed,
            "status": "PASS" if self.passed else "FAIL",
        }


@dataclass(frozen=True)
class _RunEvidence:
    cases: tuple[ExportCase, ...]
    controls: tuple[ExportControl, ...]
    contract_digest: str
    view_digest: str
    ledger_head: str
    execution_digest: str
    source_scan: dict[str, object]


@dataclass(frozen=True)
class LimenPublicViewReport:
    passed: bool
    implementation_commit: str
    candidate_source_digest: str
    cases: tuple[ExportCase, ...]
    controls: tuple[ExportControl, ...]
    contract_digest: str
    view_digest: str
    ledger_head: str
    execution_digest: str
    repeated_execution_digest: str
    repeated_run_match: bool
    source_scan: dict[str, object]
    error_codes: tuple[str, ...]
    report_digest: str
    network_calls: int = 0
    private_reads: int = 0
    registry_writes: int = 0
    real_resident_count: int = 0
    synthetic_resident_count: int = 2

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(item.case_id for item in self.cases)

    @property
    def control_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.controls)

    def _material(self) -> dict[str, object]:
        return {
            "schema": "sedb-ral.limen-public-view-acceptance/0.1",
            "passed": self.passed,
            "package_version": __version__,
            "implementation_commit": self.implementation_commit,
            "candidate_source_digest": self.candidate_source_digest,
            "case_ids": list(self.case_ids),
            "cases": [item.as_json() for item in self.cases],
            "controls": [item.as_json() for item in self.controls],
            "case_counts": {
                "pass": sum(item.passed for item in self.cases),
                "fail": sum(not item.passed for item in self.cases),
            },
            "contract_digest": self.contract_digest,
            "view_digest": self.view_digest,
            "ledger_head": self.ledger_head,
            "execution_digest": self.execution_digest,
            "repeated_execution_digest": self.repeated_execution_digest,
            "repeated_run_match": self.repeated_run_match,
            "source_scan": self.source_scan,
            "network_calls": self.network_calls,
            "private_reads": self.private_reads,
            "registry_writes": self.registry_writes,
            "real_resident_count": self.real_resident_count,
            "synthetic_resident_count": self.synthetic_resident_count,
            "synthetic_registry_writes": 1,
            "limen_consumption_verified": False,
            "host_enforcement_verified": False,
            "private_residence_accessed": False,
            "production_registry_configured": False,
            "not_claimed": list(_NOT_CLAIMED),
            "error_codes": list(self.error_codes),
        }

    def as_json(self) -> dict[str, object]:
        return {**self._material(), "report_digest": self.report_digest}


class _StdoutCapture:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def write(self, value: str) -> int:
        encoded = value.encode("utf-8")
        self.buffer.write(encoded)
        return len(value)

    def flush(self) -> None:
        pass


def _instance(resident_id: str, suffix: str = "001") -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "instance_id": f"instance:{resident_id}:{suffix}",
        "resident_ref": resident_id,
        "runtime_tag": "runtime:codex-app",
        "started_time_ref": "ctcl:instant:test",
        "ended_time_ref": None,
    }


def _line_claim(
    resident_id: str, instance_id: str, line_id: str, suffix: str
) -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "claim_id": f"claim:{resident_id}:line:{suffix}",
        "claimant_ref": resident_id,
        "subject_ref": resident_id,
        "predicate": "continuity_line_id",
        "object": line_id,
        "claimed_time": "ctcl:instant:test",
        "claimed_authored_by_instance": instance_id,
        "claimed_on_behalf_of_line": None,
    }


def _resident(
    resident_id: str = "resident:test-alpha",
    *,
    label: str = "Test Alpha",
    locator: str = "thread:test-alpha",
    address_status: str = "active",
    adapter_kind: str = "codex_app_task_tool",
    instance_count: int = 1,
    line_ids: tuple[str, ...] = ("line:test-alpha",),
) -> dict[str, object]:
    instances = [
        _instance(resident_id, f"{index + 1:03d}")
        for index in range(instance_count)
    ]
    claims = (
        []
        if not instances
        else [
            _line_claim(
                resident_id,
                instances[0]["instance_id"],
                line_id,
                str(index + 1),
            )
            for index, line_id in enumerate(line_ids)
        ]
    )
    return {
        "schema_version": "0.1",
        "resident_id": resident_id,
        "display_label": label,
        "status": "active",
        "application_ref": f"application:{resident_id}",
        "identifier_refs": [],
        "instances": instances,
        "addresses": [
            {
                "schema_version": "0.1",
                "address_id": f"address:{resident_id}:thread",
                "namespace": "codex_thread",
                "adapter_kind": adapter_kind,
                "locator": locator,
                "target_ref": resident_id,
                "status": address_status,
            }
        ],
        "claims": claims,
    }


def _projection(*residents: dict[str, object]) -> RegistryProjection:
    ordered = tuple(sorted(residents, key=lambda item: item["resident_id"]))
    event_ids = tuple(
        f"evt_resident_registered_{index + 1:03d}"
        for index in range(len(ordered))
    )
    return RegistryProjection(
        applications={
            item["application_ref"]: {
                "application_id": item["application_ref"],
                "status": "accepted",
                "authority_ref": f"authority:{item['resident_id']}",
                "authority_digest": (
                    "sha256:sedb-ral-json-nfc-codepoint-v1:" + "b" * 64
                ),
                "authority_grant_event_id": f"evt_authority:{item['resident_id']}",
            }
            for item in ordered
        },
        residents={item["resident_id"]: item for item in ordered},
        directory={
            item["resident_id"]: {
                "display_label": item["display_label"],
                "status": item["status"],
                "addresses": copy.deepcopy(item["addresses"]),
                "instance_refs": [
                    instance["instance_id"] for instance in item["instances"]
                ],
            }
            for item in ordered
        },
        claims={
            claim["claim_id"]: claim
            for item in ordered
            for claim in item["claims"]
        },
        resident_source_event_ids={
            item["resident_id"]: event_ids[index]
            for index, item in enumerate(ordered)
        },
        applied_corrections=(),
        unapplied_event_ids=(),
        unapplied_reasons={},
        source_event_ids=event_ids,
    )


def _export(*residents: dict[str, object]):
    return build_limen_public_view(
        _projection(*residents),
        ledger_head=_HEAD,
        sequence=max(1, len(residents)),
    )


def _case(
    cases: list[ExportCase],
    case_id: str,
    name: str,
    expected: str,
    operation,
) -> None:
    try:
        result = operation()
        observed = result if isinstance(result, str) else "ok"
    except RALValidationError as error:
        observed = error.code
    cases.append(
        ExportCase(case_id, name, expected, observed, observed == expected)
    )


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise RALValidationError(code, "export acceptance condition failed")


def _conflict_code(view) -> str:
    conflicts = view.to_dict()["projection_conflicts"]
    return "missing_conflict" if not conflicts else conflicts[0]["error_code"]


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


def _registration_ids() -> RegistrationIds:
    return RegistrationIds(
        prepared_id="prepared:7b5a4b15",
        application_id="application:42ce0eb1",
        resident_id="resident:75c9559e",
        instance_id="instance:bb68ace7",
        continuity_line_id="line:cb6d31e7",
        address_ids=("address:79b497c5",),
        claim_ids=(
            "claim:81f5895d",
            "claim:10757453",
            "claim:b2fc8d91",
        ),
    )


def _self_claim() -> dict[str, object]:
    return {
        "schema": "sedb-ral.self-application-claim/0.1",
        "applicant_claim_only": True,
        "desired_display_label": "Export Alpha",
        "existing_resident_claim": None,
        "continuity_claim": "new",
        "desired_addresses": [
            {
                "namespace": "codex_thread",
                "identifier_kind": "codex_thread",
                "locator": "thread:export-alpha",
            }
        ],
        "role_description_claim": "Synthetic exporter fixture",
        "dissent_or_limits": [],
        "opt_in": True,
        "relay_is_authorship": False,
        "not_claimed": [
            "verified_identity",
            "registrar_authority",
            "private_access",
        ],
    }


def _host_observation() -> dict[str, object]:
    return {
        "schema": "sedb-ral.registration-host-observation/0.1",
        "observation_id": "observation:export-alpha",
        "provider": "openai",
        "adapter_kind": "codex_app_task_tool",
        "identifier_kind": "codex_thread",
        "native_thread_id": "thread:export-alpha",
        "native_session_id": None,
        "native_turn_id": "turn:export-alpha",
        "unavailable_fields": [
            {
                "field": "native_session_id",
                "reason": (
                    "structurally_unavailable_from_codex_app_task_tool"
                ),
            }
        ],
        "observed_origin": "host:synthetic-export-runner",
        "observed_at_ref": "ctcl:instant:test-registration",
        "applicant_item_ref": "item:export-alpha",
        "not_claimed": ["pre_turn_output_enforcement"],
    }


def _authority(application_digest: str) -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "authority_id": "authority:export-alpha",
        "principal_ref": "principal:test",
        "subject_kind": "application_digest",
        "subject_ref": application_digest,
        "scopes": ["registry.application.accept"],
        "status": "active",
        "issued_time_ref": "ctcl:instant:test-authority",
        "revoked_by_event": None,
        "authorship_attestation_ref": "attestation:export-principal",
    }


def _tree_fingerprint(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _ctcl(root: Path) -> dict[str, object]:
    value = loads_strict(
        (root / "fixtures/ctcl/registered-anchor.json").read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(value, dict):
        raise RALValidationError("ctcl_receipt_invalid", "not an object")
    return value


def _cli_parity(root: Path, run_root: Path) -> tuple[str, str]:
    prepared = prepare_registration(
        _self_claim(), _host_observation(), _registration_ids()
    )
    authority = _authority(prepared.application_digest)
    verified = frozenset({"attestation:export-principal"})
    decision = evaluate_prepared_registration(
        prepared,
        [authority],
        verified_attestation_refs=verified,
        projection=_empty_projection(),
    )
    ledger = run_root / "ledger"
    plan = build_admission_plan(
        ledger,
        prepared,
        decision,
        authority,
        _ctcl(root),
        expected_head=None,
        verified_attestation_refs=verified,
        staging_parent=run_root / "staging",
    )
    receipt = commit_admission_plan(
        ledger,
        plan,
        prepared,
        decision,
        authority,
        _ctcl(root),
        verified_attestation_refs=verified,
    )
    events = read_verified_events(ledger, receipt.final_head)
    direct = build_limen_public_view(
        project_events(events),
        ledger_head=receipt.final_head,
        sequence=int(events[-1]["ledger_seq"]),
    )
    before = _tree_fingerprint(ledger)
    output = run_root / "cli-public-view.json"
    capture = _StdoutCapture()
    with redirect_stdout(capture):
        code = cli_main(
            [
                "registry",
                "limen-view",
                "--ledger-root",
                str(ledger),
                "--expected-head",
                receipt.final_head,
                "--output",
                str(output),
            ]
        )
    _require(code == 0, "cli_parity_failed")
    _require(
        output.read_bytes() == canonical_bytes(direct.to_dict()),
        "cli_parity_failed",
    )
    emitted = loads_strict(capture.buffer.getvalue().decode("utf-8"))
    _require(emitted == direct.to_dict(), "cli_parity_failed")
    _require(before == _tree_fingerprint(ledger), "cli_mutated_registry")
    return receipt.final_head, direct.digest


def _source_scan(root: Path) -> dict[str, object]:
    findings = scan_no_send(root / "src/sedb_ral")
    _require(not findings, "package_no_send_failed")
    paths = (
        root / "src/sedb_ral/limen_public_view.py",
        root / "src/sedb_ral/limen_export_acceptance.py",
        root / "profiles/limen-ral-view-v0.2-mapping.json",
    )
    task_pattern = re.compile(
        r"\b01[a-f0-9]{6}-[a-f0-9]{4}-[a-f0-9]{4}-"
        r"[a-f0-9]{4}-[a-f0-9]{12}\b"
    )
    private_marker = "D:" + "\\AI_" + "RESIDENCE"
    task_ids = 0
    private_markers = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        task_ids += len(task_pattern.findall(text))
        private_markers += text.count(private_marker)
    _require(task_ids == 0, "real_task_id_present")
    _require(private_markers == 0, "private_marker_present")
    return {
        "package_no_send_findings": 0,
        "real_task_ids": task_ids,
        "private_markers": private_markers,
        "scanned_files": [path.relative_to(root).as_posix() for path in paths],
    }


def _execute_once(root: Path, run_root: Path) -> _RunEvidence:
    cases: list[ExportCase] = []
    alpha = _resident()
    beta = _resident(
        "resident:test-beta",
        label="Test Beta",
        locator="thread:test-beta",
        line_ids=("line:test-beta",),
    )

    _case(
        cases,
        "S6A-001",
        "exact task-tool public binding",
        "ok",
        lambda: "ok" if len(_export(alpha).to_dict()["bindings"]) == 1 else "missing",
    )
    _case(
        cases,
        "S6A-002",
        "homonymous labels remain separate",
        "ok",
        lambda: (
            "ok"
            if len(
                _export(
                    {**alpha, "display_label": "Same Label"},
                    {**beta, "display_label": "Same Label"},
                ).to_dict()["bindings"]
            )
            == 2
            else "homonym_collapsed"
        ),
    )
    collision_beta = copy.deepcopy(beta)
    collision_beta["addresses"][0]["locator"] = "thread:test-alpha"
    _case(
        cases,
        "S6A-003",
        "active thread collision has no winner",
        "address_binding_conflict",
        lambda: _conflict_code(_export(alpha, collision_beta)),
    )
    _case(
        cases,
        "S6A-004",
        "ambiguous instance is not selected",
        "instance_binding_ambiguous",
        lambda: _conflict_code(_export(_resident(instance_count=2))),
    )
    _case(
        cases,
        "S6A-005",
        "ambiguous continuity line is not selected",
        "continuity_line_ambiguous",
        lambda: _conflict_code(
            _export(_resident(line_ids=("line:test-alpha", "line:test-other")))
        ),
    )
    _case(
        cases,
        "S6A-006",
        "inactive address remains nonactive",
        "suspended",
        lambda: _export(_resident(address_status="suspended")).to_dict()[
            "bindings"
        ][0]["status"],
    )
    parity: dict[str, str] = {}

    def parity_case() -> str:
        ledger_head, view_digest = _cli_parity(root, run_root)
        parity.update({"ledger_head": ledger_head, "view_digest": view_digest})
        return "ok"

    _case(
        cases,
        "S6A-007",
        "exact-head CLI Core parity",
        "ok",
        parity_case,
    )

    source_scan: dict[str, object] = {}

    def repeat_and_scan() -> str:
        first = _export(alpha, beta)
        second = _export(beta, alpha)
        _require(first.digest == second.digest, "repeat_mismatch")
        source_scan.update(_source_scan(root))
        return "ok"

    _case(
        cases,
        "S6A-008",
        "repeated export and no-send boundary",
        "ok",
        repeat_and_scan,
    )

    app_server = _export(_resident(adapter_kind="codex_app_server"))
    control_values = {
        "thread-collision-no-tiebreak": _conflict_code(
            _export(alpha, collision_beta)
        ),
        "instance-ambiguity-no-selection": _conflict_code(
            _export(_resident(instance_count=2))
        ),
        "line-ambiguity-no-selection": _conflict_code(
            _export(_resident(line_ids=("line:test-alpha", "line:test-other")))
        ),
        "inactive-binding-no-resolution": _export(
            _resident(address_status="suspended")
        ).to_dict()["bindings"][0]["status"],
        "app-server-session-not-inferred": _conflict_code(app_server),
        "package-no-send": (
            "clean" if source_scan.get("package_no_send_findings") == 0 else "dirty"
        ),
    }
    expected = {
        "thread-collision-no-tiebreak": "address_binding_conflict",
        "instance-ambiguity-no-selection": "instance_binding_ambiguous",
        "line-ambiguity-no-selection": "continuity_line_ambiguous",
        "inactive-binding-no-resolution": "suspended",
        "app-server-session-not-inferred": "adapter_profile_unsupported",
        "package-no-send": "clean",
    }
    controls = tuple(
        ExportControl(
            name=name,
            expected_code=expected[name],
            observed_code=control_values[name],
            executed=True,
            passed=control_values[name] == expected[name],
        )
        for name in EXPECTED_CONTROLS
    )
    execution_value = {
        "cases": [item.as_json() for item in cases],
        "controls": [item.as_json() for item in controls],
        "contract_digest": limen_contract_digest(),
        "view_digest": parity.get("view_digest", "unavailable"),
        "ledger_head": parity.get("ledger_head", "unavailable"),
        "source_scan": source_scan,
    }
    return _RunEvidence(
        cases=tuple(cases),
        controls=controls,
        contract_digest=limen_contract_digest(),
        view_digest=parity.get("view_digest", "unavailable"),
        ledger_head=parity.get("ledger_head", "unavailable"),
        execution_digest=sha256_ref(execution_value),
        source_scan=source_scan,
    )


def _git_head(root: Path) -> str:
    head = root / ".git/HEAD"
    if not head.is_file():
        return "unavailable"
    value = head.read_text(encoding="ascii").strip()
    if not value.startswith("ref: "):
        return value
    reference = root / ".git" / value.removeprefix("ref: ")
    return (
        reference.read_text(encoding="ascii").strip()
        if reference.is_file()
        else "unavailable"
    )


def _candidate_source_digest(root: Path) -> str:
    relative_paths = (
        "profiles/limen-ral-view-v0.2-mapping.json",
        "src/sedb_ral/schemas/limen-ral-view-v0.2.schema.json",
        "src/sedb_ral/limen_public_view.py",
        "src/sedb_ral/limen_export_acceptance.py",
        "src/sedb_ral/cli.py",
        "scripts/validate_limen_public_view.py",
        "tests/test_limen_public_view_contract.py",
        "tests/test_limen_public_view_export.py",
        "tests/test_limen_public_view_cli.py",
        "tests/test_limen_public_view_gate.py",
        "docs/runtime/LIMEN_PUBLIC_VIEW_V02.md",
        ".github/workflows/phase3a.yml",
        "README.md",
        "pyproject.toml",
        "src/sedb_ral/__init__.py",
    )
    values = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in relative_paths
        if (root / relative).is_file()
    }
    return sha256_ref({"files": values})


def validate_limen_public_view(
    root: Path, *, output_root: Path | None = None
) -> LimenPublicViewReport:
    root = Path(root).resolve()
    parent = None if output_root is None else Path(output_root)
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="sedb-ral-limen-export-a-", dir=parent) as path:
        first = _execute_once(root, Path(path))
    with TemporaryDirectory(prefix="sedb-ral-limen-export-b-", dir=parent) as path:
        second = _execute_once(root, Path(path))
    repeated = first.execution_digest == second.execution_digest
    errors = []
    if tuple(item.case_id for item in first.cases) != EXPECTED_CASE_IDS:
        errors.append("case_inventory_mismatch")
    if tuple(item.name for item in first.controls) != EXPECTED_CONTROLS:
        errors.append("control_inventory_mismatch")
    if not all(item.passed for item in first.cases):
        errors.append("case_failed")
    if not all(item.executed and item.passed for item in first.controls):
        errors.append("control_failed")
    if not repeated:
        errors.append("repeat_mismatch")
    fields = {
        "passed": not errors,
        "implementation_commit": _git_head(root),
        "candidate_source_digest": _candidate_source_digest(root),
        "cases": first.cases,
        "controls": first.controls,
        "contract_digest": first.contract_digest,
        "view_digest": first.view_digest,
        "ledger_head": first.ledger_head,
        "execution_digest": first.execution_digest,
        "repeated_execution_digest": second.execution_digest,
        "repeated_run_match": repeated,
        "source_scan": first.source_scan,
        "error_codes": tuple(errors),
    }
    provisional = LimenPublicViewReport(**fields, report_digest="")
    return LimenPublicViewReport(
        **fields, report_digest=sha256_ref(provisional._material())
    )


def write_limen_public_view_report(
    report: LimenPublicViewReport, destination: Path
) -> Path:
    if not report.passed:
        raise RALValidationError(
            "limen_export_report_not_passed", "only passing evidence may be written"
        )
    if sha256_ref(report._material()) != report.report_digest:
        raise RALValidationError(
            "limen_export_report_digest_mismatch", "report digest differs"
        )
    destination = Path(destination)
    with destination.open("xb") as stream:
        stream.write(canonical_bytes(report.as_json()) + b"\n")
    return destination
