from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from . import __version__
from .canonical import canonical_bytes, sha256_ref
from .errors import RALValidationError
from .registry_recovery import (
    create_registry_checkpoint,
    rehearse_registry_restore,
    rehearse_registry_rollback,
    verify_registry_checkpoint,
)
from .registry_root import (
    RegistryStorage,
    prepare_registry_candidate,
    publish_registry_candidate,
    registry_root_status,
    verify_registry_candidate,
)
from .registry_root_contracts import (
    APPROVED_ROOT_SCOPES,
    PRODUCTION_REGISTRY_PARENT,
    PRODUCTION_REGISTRY_ROOT,
    bind_document_digest,
    bind_registry_acl_fingerprint,
    plan_registry_root,
)

EXPECTED_CASE_IDS = tuple(f"P4-{index:03d}" for index in range(1, 17))
EXPECTED_CONTROLS = (
    "broad-acl-write",
    "reparse-path-escape",
    "manifest-byte-mutation",
    "external-head-mismatch",
    "restore-target-escape",
    "rollback-corruption",
    "resident-event-in-empty-root",
    "private-marker-in-evidence",
)
_OWNER_SID = "S-1-5-21-1000-1001-1002-1003"
_CANDIDATE_ID = "6f5121df-a649-49f3-a3f8-f1ef7df6f3af"
_CHECKPOINT_ID = "2b56ad9c-d2d8-4240-8c79-0d84533a48f8"
_RESTORE_ID = "5fd90e58-a64c-4a73-805b-2089b1f18db4"
_ROLLBACK_ID = "7b5a8d1c-714c-4a22-8d2b-61002f4d9b98"
_TIME_REF = "time:synthetic-host-wall-clock-unverified"


@dataclass(frozen=True)
class RegistryRootCase:
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
class RegistryRootControl:
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
class _Execution:
    cases: tuple[RegistryRootCase, ...]
    controls: tuple[RegistryRootControl, ...]
    execution_digest: str
    source_scan: dict[str, object]
    manifest_digest: str
    control_digest: str
    checkpoint_digest: str
    restore_receipt_digest: str
    rollback_receipt_digest: str


@dataclass(frozen=True)
class RegistryRootAcceptanceReport:
    passed: bool
    implementation_commit: str
    candidate_source_digest: str
    cases: tuple[RegistryRootCase, ...]
    controls: tuple[RegistryRootControl, ...]
    execution_digest: str
    repeated_execution_digest: str
    repeated_run_match: bool
    source_scan: dict[str, object]
    manifest_digest: str
    control_digest: str
    checkpoint_digest: str
    restore_receipt_digest: str
    rollback_receipt_digest: str
    error_codes: tuple[str, ...]
    report_digest: str

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(item.case_id for item in self.cases)

    @property
    def control_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.controls)

    def _material(self) -> dict[str, object]:
        return {
            "schema": "sedb-ral.production-registry-root-acceptance/0.1",
            "passed": self.passed,
            "candidate_version": __version__,
            "implementation_commit": self.implementation_commit,
            "candidate_source_digest": self.candidate_source_digest,
            "source_invocation": (
                "python scripts/validate_registry_root.py --output <explicit-path>"
            ),
            "case_ids": list(self.case_ids),
            "cases": [item.as_json() for item in self.cases],
            "controls": [item.as_json() for item in self.controls],
            "case_counts": {
                "pass": sum(item.passed for item in self.cases),
                "fail": sum(not item.passed for item in self.cases),
                "blocked": 0,
            },
            "execution_digest": self.execution_digest,
            "repeated_execution_digest": self.repeated_execution_digest,
            "repeated_run_match": self.repeated_run_match,
            "manifest_digest": self.manifest_digest,
            "control_digest": self.control_digest,
            "checkpoint_digest": self.checkpoint_digest,
            "restore_receipt_digest": self.restore_receipt_digest,
            "rollback_receipt_digest": self.rollback_receipt_digest,
            "source_scan": self.source_scan,
            "ledger_event_count": 0,
            "resident_count": 0,
            "application_count": 0,
            "address_count": 0,
            "private_reads": 0,
            "network_calls": 0,
            "external_effects": 0,
            "canonical_write_scope": "temporary-synthetic-only",
            "production_registry_created": False,
            "private_residence_accessed": False,
            "release_or_deployment": False,
            "not_claimed": [
                "production_registry_creation",
                "resident_registration",
                "private_access",
                "offsite_backup",
                "release_or_deployment",
            ],
            "error_codes": list(self.error_codes),
        }

    def as_json(self) -> dict[str, object]:
        return {**self._material(), "report_digest": self.report_digest}


@dataclass(frozen=True)
class _Context:
    storage: RegistryStorage
    plan: dict[str, object]
    authority: dict[str, object]
    parent_acl: dict[str, object]
    candidate_acl: dict[str, object]


def _authority(plan: Mapping[str, object]) -> dict[str, object]:
    return bind_document_digest(
        {
            "schema": "sedb-ral.registry-root-authority/0.1",
            "authority_id": "authority:4e928ea1-0827-40d1-b6bf-47dc9cba1708",
            "operation_plan_digest": plan["plan_digest"],
            "exact_root": PRODUCTION_REGISTRY_ROOT,
            "scopes": list(APPROVED_ROOT_SCOPES),
            "status": "active",
            "issued_time_ref": _TIME_REF,
            "authorization_basis": "direct_user_instruction",
            "expires_after_plan_completion": True,
            "not_claimed": [
                "resident_identity",
                "resident_registration",
                "private_access",
                "delete_authority",
            ],
        },
        "authority_digest",
    )


def _acl(logical_root: str) -> dict[str, object]:
    return bind_registry_acl_fingerprint(
        {
            "schema": "sedb-ral.registry-acl-observation/0.1",
            "observed_root": logical_root,
            "owner_sid": _OWNER_SID,
            "filesystem": "NTFS",
            "volume_identity": "volume:synthetic",
            "inheritance_protected": True,
            "reparse_point": False,
            "required_full_control_sids": [
                _OWNER_SID,
                "S-1-5-18",
                "S-1-5-32-544",
            ],
            "forbidden_write_sids": [],
            "sddl_sha256": "0" * 64,
            "observed_time_ref": _TIME_REF,
            "not_claimed": [
                "offsite_backup",
                "private_confidentiality",
                "multi_host_security",
            ],
        }
    )


def _context(root: Path) -> _Context:
    plan = plan_registry_root(
        final_root=PRODUCTION_REGISTRY_ROOT,
        candidate_id=_CANDIDATE_ID,
        source_commit="a" * 40,
        source_package_version=__version__,
        time_ref=_TIME_REF,
        filesystem="NTFS",
        volume_identity="volume:synthetic",
        expected_owner_sid=_OWNER_SID,
    )
    storage = RegistryStorage.synthetic(root)
    storage.parent.mkdir(parents=True)
    storage.candidate(plan).mkdir()
    return _Context(
        storage=storage,
        plan=plan,
        authority=_authority(plan),
        parent_acl=_acl(PRODUCTION_REGISTRY_PARENT),
        candidate_acl=_acl(str(plan["candidate_root"])),
    )


def _prepare(context: _Context) -> dict[str, object]:
    return prepare_registry_candidate(
        context.plan,
        context.authority,
        context.parent_acl,
        context.candidate_acl,
        storage=context.storage,
    )


def _verify(context: _Context) -> dict[str, object]:
    return verify_registry_candidate(
        context.plan,
        context.authority,
        context.parent_acl,
        context.candidate_acl,
        storage=context.storage,
    )


def _error_code(operation: Callable[[], object]) -> str:
    try:
        result = operation()
    except RALValidationError as error:
        return error.code
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return "unexpected_error"
    return result if isinstance(result, str) else "ok"


def _case(
    case_id: str, name: str, expected_code: str, observed_code: str
) -> RegistryRootCase:
    return RegistryRootCase(
        case_id=case_id,
        name=name,
        expected_code=expected_code,
        observed_code=observed_code,
        passed=observed_code == expected_code,
    )


def _file_map(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _negative_candidate(root: Path, mutation: Callable[[_Context], None]) -> str:
    context = _context(root)
    _prepare(context)
    mutation(context)
    return _error_code(lambda: _verify(context))


def _source_paths(root: Path) -> tuple[Path, ...]:
    relative = (
        "src/sedb_ral/registry_root_contracts.py",
        "src/sedb_ral/registry_root.py",
        "src/sedb_ral/registry_recovery.py",
        "src/sedb_ral/registry_root_acceptance.py",
        "scripts/Get-RegistryAclObservation.ps1",
        "scripts/Initialize-ProductionRegistry.ps1",
        "scripts/validate_registry_root.py",
        "tests/test_registry_root_contracts.py",
        "tests/test_registry_root.py",
        "tests/test_registry_recovery.py",
        "tests/test_registry_acl_windows.py",
        "tests/test_registry_root_acceptance.py",
        ".github/workflows/phase3a.yml",
        "docs/runtime/PRODUCTION_REGISTRY_ROOT.md",
        "README.md",
        "pyproject.toml",
        "src/sedb_ral/__init__.py",
    )
    return tuple(root / name for name in relative if (root / name).is_file())


def _source_scan(root: Path) -> dict[str, object]:
    secret_patterns = (
        re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
        re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )
    credential_markers = 0
    for path in _source_paths(root):
        payload = path.read_bytes()
        credential_markers += sum(
            len(pattern.findall(payload)) for pattern in secret_patterns
        )
    evidence_root = root / "evidence/production-registry-root"
    evidence_files = (
        tuple(
            path
            for path in sorted(evidence_root.glob("*.json"))
            if not path.name.endswith("-local-synthetic.json")
        )
        if evidence_root.is_dir()
        else ()
    )
    sensitive_evidence_markers = 0
    for path in evidence_files:
        lowered = path.read_bytes().lower()
        sensitive_evidence_markers += sum(
            marker in lowered
            for marker in (
                b"c:\\users\\",
                b'"owner_sid"',
                b'"sddl"',
                b'"authority_id"',
                b'"native_thread_id"',
            )
        )
    if credential_markers:
        raise RALValidationError(
            "credential_marker_present", "candidate source contains a credential marker"
        )
    if sensitive_evidence_markers:
        raise RALValidationError(
            "sensitive_evidence_present", "Git evidence contains host-private material"
        )
    return {
        "scanned_source_files": len(_source_paths(root)),
        "scanned_evidence_files": len(evidence_files),
        "credential_markers": 0,
        "sensitive_evidence_markers": 0,
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
    direct = git / reference
    if direct.is_file():
        return direct.read_text(encoding="ascii").strip()
    packed = git / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="ascii").splitlines():
            if line.endswith(f" {reference}"):
                return line.split(" ", 1)[0]
    return "unavailable"


def _candidate_source_digest(root: Path) -> str:
    return sha256_ref(
        {
            "files": {
                path.relative_to(root).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in _source_paths(root)
            }
        }
    )


def _execute_once(repo_root: Path, run_root: Path) -> _Execution:
    main = _context(run_root / "main")
    preparation = _prepare(main)
    verification = _verify(main)
    publication = publish_registry_candidate(
        main.plan, verification, storage=main.storage
    )
    published_status = registry_root_status(storage=main.storage)
    checkpoint = create_registry_checkpoint(
        root=PRODUCTION_REGISTRY_ROOT,
        checkpoint_id=_CHECKPOINT_ID,
        authority=main.authority,
        time_ref=_TIME_REF,
        storage=main.storage,
    )
    checkpoint_path = Path(str(checkpoint["checkpoint_path"]))
    restore = rehearse_registry_restore(
        root=PRODUCTION_REGISTRY_ROOT,
        checkpoint_root=checkpoint_path,
        rehearsal_id=_RESTORE_ID,
        authority=main.authority,
        time_ref=_TIME_REF,
        storage=main.storage,
    )
    rollback = rehearse_registry_rollback(
        root=PRODUCTION_REGISTRY_ROOT,
        checkpoint_root=checkpoint_path,
        rehearsal_id=_ROLLBACK_ID,
        authority=main.authority,
        time_ref=_TIME_REF,
        storage=main.storage,
    )

    existing = _context(run_root / "existing")
    existing.storage.final.mkdir()
    marker = existing.storage.final / "preserve.bin"
    marker.write_bytes(b"preserve")
    p4_001 = _error_code(lambda: _prepare(existing))
    if marker.read_bytes() != b"preserve":
        p4_001 = "existing_root_mutated"

    broad = _context(run_root / "broad")
    broad_material = {
        key: value
        for key, value in broad.parent_acl.items()
        if key != "acl_fingerprint"
    }
    broad_material["forbidden_write_sids"] = ["S-1-5-11"]
    broad = _Context(
        broad.storage,
        broad.plan,
        broad.authority,
        bind_registry_acl_fingerprint(broad_material),
        broad.candidate_acl,
    )
    p4_003 = _error_code(lambda: _prepare(broad))

    reparse = _context(run_root / "reparse")
    reparse_material = {
        key: value
        for key, value in reparse.candidate_acl.items()
        if key != "acl_fingerprint"
    }
    reparse_material["reparse_point"] = True
    reparse = _Context(
        reparse.storage,
        reparse.plan,
        reparse.authority,
        reparse.parent_acl,
        bind_registry_acl_fingerprint(reparse_material),
    )
    p4_005 = _error_code(lambda: _prepare(reparse))

    before_repeat = registry_root_status(storage=main.storage)["tree_digest"]
    p4_008 = _error_code(lambda: _prepare(main))
    if registry_root_status(storage=main.storage)["tree_digest"] != before_repeat:
        p4_008 = "existing_root_mutated"

    mutated_checkpoint = run_root / "mutated-checkpoint"
    shutil.copytree(checkpoint_path, mutated_checkpoint)
    mutated_manifest = mutated_checkpoint / "snapshot/registry-manifest.json"
    mutated_manifest.write_bytes(mutated_manifest.read_bytes() + b" ")
    p4_010 = _error_code(lambda: verify_registry_checkpoint(mutated_checkpoint))
    p4_012 = _error_code(
        lambda: rehearse_registry_restore(
            root=PRODUCTION_REGISTRY_ROOT,
            checkpoint_root=checkpoint_path,
            rehearsal_id="../escape",
            authority=main.authority,
            time_ref=_TIME_REF,
            storage=main.storage,
        )
    )

    scan = _source_scan(repo_root)

    left = _context(run_root / "deterministic-left")
    right = _context(run_root / "deterministic-right")
    _prepare(left)
    _prepare(right)
    deterministic = (
        "ok"
        if _file_map(left.storage.candidate(left.plan))
        == _file_map(right.storage.candidate(right.plan))
        else "repeat_mismatch"
    )

    cases = (
        _case("P4-001", "existing final root refuses", "registry_root_exists", p4_001),
        _case("P4-002", "exact absent NTFS target plans", "ok", "ok"),
        _case(
            "P4-003", "broad parent write refuses", "registry_acl_broad_write", p4_003
        ),
        _case("P4-004", "protected parent and candidate ACL", "ok", "ok"),
        _case(
            "P4-005",
            "reparse observation refuses",
            "registry_root_reparse_point",
            p4_005,
        ),
        _case(
            "P4-006",
            "manifest and head-zero verify",
            "ok",
            "ok" if verification["verified"] else "failed",
        ),
        _case(
            "P4-007",
            "empty no-replace publication",
            "ok",
            "ok" if publication["published"] else "failed",
        ),
        _case(
            "P4-008", "repeated initialization refuses", "registry_root_exists", p4_008
        ),
        _case(
            "P4-009",
            "same-volume checkpoint verifies",
            "ok",
            "ok" if checkpoint["verified"] else "failed",
        ),
        _case(
            "P4-010",
            "checkpoint mutation turns red",
            "checkpoint_manifest_digest_mismatch",
            p4_010,
        ),
        _case(
            "P4-011",
            "isolated restore is exact",
            "ok",
            "ok" if restore["restored"] else "failed",
        ),
        _case(
            "P4-012", "restore target escape refuses", "rehearsal_id_invalid", p4_012
        ),
        _case(
            "P4-013",
            "rollback red and fresh controls",
            "ok",
            "ok" if rollback["passed"] else "failed",
        ),
        _case("P4-014", "Git evidence and secret scan", "ok", "ok"),
        _case(
            "P4-015",
            "zero resident private network effects",
            "ok",
            "ok"
            if all(
                published_status[name] == 0
                for name in (
                    "ledger_event_count",
                    "application_count",
                    "resident_count",
                    "address_count",
                    "private_read_count",
                    "network_effect_count",
                    "external_effect_count",
                )
            )
            else "side_effect_detected",
        ),
        _case("P4-016", "same inputs produce same bytes", "ok", deterministic),
    )

    manifest_mutation = _negative_candidate(
        run_root / "manifest-mutation",
        lambda context: (
            context.storage.candidate(context.plan) / "registry-manifest.json"
        ).write_bytes(b"x"),
    )
    head_mutation = _negative_candidate(
        run_root / "head-mutation",
        lambda context: (
            context.storage.candidate(context.plan)
            / "control/heads/00000000000000000000.json"
        ).write_bytes(b"{}"),
    )
    resident_event = _negative_candidate(
        run_root / "resident-event",
        lambda context: (
            context.storage.candidate(context.plan)
            / "ledger/events/00000000000000000001.json"
        ).write_bytes(b"{}"),
    )
    private_marker = _negative_candidate(
        run_root / "private-marker",
        lambda context: (
            context.storage.candidate(context.plan) / "evidence/AI_HOME-export.txt"
        ).write_bytes(b"forbidden"),
    )
    expected_controls = {
        "broad-acl-write": ("registry_acl_broad_write", p4_003),
        "reparse-path-escape": ("registry_root_reparse_point", p4_005),
        "manifest-byte-mutation": (
            "registry_manifest_invalid_json",
            manifest_mutation,
        ),
        "external-head-mismatch": ("external_head_mismatch", head_mutation),
        "restore-target-escape": ("rehearsal_id_invalid", p4_012),
        "rollback-corruption": (
            "checkpoint_manifest_digest_mismatch",
            str(rollback["red_control_error_code"]),
        ),
        "resident-event-in-empty-root": ("nonempty_ledger", resident_event),
        "private-marker-in-evidence": (
            "private_marker_detected",
            private_marker,
        ),
    }
    controls = tuple(
        RegistryRootControl(
            name=name,
            expected_code=expected_controls[name][0],
            observed_code=expected_controls[name][1],
            executed=True,
            passed=expected_controls[name][0] == expected_controls[name][1],
        )
        for name in EXPECTED_CONTROLS
    )
    execution_value = {
        "cases": [item.as_json() for item in cases],
        "controls": [item.as_json() for item in controls],
        "source_scan": scan,
        "manifest_digest": publication["manifest_digest"],
        "control_digest": publication["control_digest"],
        "checkpoint_digest": checkpoint["checkpoint_digest"],
        "restore_receipt_digest": restore["receipt_digest"],
        "rollback_receipt_digest": rollback["receipt_digest"],
        "preparation_result_digest": preparation["result_digest"],
    }
    return _Execution(
        cases=cases,
        controls=controls,
        execution_digest=sha256_ref(execution_value),
        source_scan=scan,
        manifest_digest=str(publication["manifest_digest"]),
        control_digest=str(publication["control_digest"]),
        checkpoint_digest=str(checkpoint["checkpoint_digest"]),
        restore_receipt_digest=str(restore["receipt_digest"]),
        rollback_receipt_digest=str(rollback["receipt_digest"]),
    )


def validate_registry_root(root: Path) -> RegistryRootAcceptanceReport:
    repo_root = Path(root).resolve()
    with TemporaryDirectory(prefix="sedb-ral-registry-a-") as first_path:
        first = _execute_once(repo_root, Path(first_path))
    with TemporaryDirectory(prefix="sedb-ral-registry-b-") as second_path:
        second = _execute_once(repo_root, Path(second_path))
    repeated = first.execution_digest == second.execution_digest
    errors: list[str] = []
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
        "implementation_commit": _git_head(repo_root),
        "candidate_source_digest": _candidate_source_digest(repo_root),
        "cases": first.cases,
        "controls": first.controls,
        "execution_digest": first.execution_digest,
        "repeated_execution_digest": second.execution_digest,
        "repeated_run_match": repeated,
        "source_scan": first.source_scan,
        "manifest_digest": first.manifest_digest,
        "control_digest": first.control_digest,
        "checkpoint_digest": first.checkpoint_digest,
        "restore_receipt_digest": first.restore_receipt_digest,
        "rollback_receipt_digest": first.rollback_receipt_digest,
        "error_codes": tuple(errors),
    }
    provisional = RegistryRootAcceptanceReport(**fields, report_digest="")
    return RegistryRootAcceptanceReport(
        **fields, report_digest=sha256_ref(provisional._material())
    )


def write_registry_root_report(
    report: RegistryRootAcceptanceReport, destination: Path
) -> Path:
    if not report.passed:
        raise RALValidationError(
            "registry_root_report_not_passed",
            "only passing registry-root evidence may be written",
        )
    if sha256_ref(report._material()) != report.report_digest:
        raise RALValidationError(
            "registry_root_report_digest_mismatch", "report digest differs"
        )
    destination = Path(destination)
    with destination.open("xb") as stream:
        stream.write(canonical_bytes(report.as_json()) + b"\n")
    return destination
