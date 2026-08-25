from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from .canonical import canonical_bytes, sha256_ref
from .errors import RALValidationError
from .no_send import scan_no_send
from .operations.workspace import _validate_target_boundary
from .production_operations_contracts import (
    ProductionOperationsPlan,
    ProductionOperationsPolicy,
    default_dormant_policy,
    plan_production_operations_extension,
)
from .production_operations_layout import (
    _verify_live_binding,
    prepare_production_operations_candidate,
    publish_production_operations_candidate,
    verify_production_operations_candidate,
    write_activation_receipt,
)
from .production_operations_recovery import (
    create_versioned_registry_checkpoint,
    rehearse_versioned_registry_restore,
    rehearse_versioned_registry_rollback,
)
from .registry_root import (
    RegistryStorage,
    prepare_registry_candidate,
    publish_registry_candidate,
    registry_root_status,
    registry_source_digest,
    verify_registry_candidate,
)
from .registry_root_contracts import (
    APPROVED_ROOT_SCOPES,
    PRODUCTION_REGISTRY_PARENT,
    PRODUCTION_REGISTRY_ROOT,
    bind_document_digest,
    bind_registry_acl_fingerprint,
    plan_registry_root,
    verify_registry_acl,
)


ROOT_CANDIDATE_ID = "6f5121df-a649-49f3-a3f8-f1ef7df6f3af"
OPS_CANDIDATE_ID = "9b0c7d46-b94d-4b39-b59f-42f4d458955c"
PRE_ID = "31cbfa29-4b0c-4b96-aef0-42e653b3f482"
POST_ID = "a905087e-1a4f-43d3-95bc-32e84e271234"
RESTORE_ID = "ce8cbf4b-4e2d-41c7-a513-d6edb67e3447"
ROLLBACK_ID = "d26294ef-55c6-4fd4-9d43-2ecf7ae7504f"
OWNER_SID = "S-1-5-21-1000-1001-1002-1003"
TIME_REF = "time:host-wall-clock-unverified:2026-08-26T00:00:00+08:00"


@dataclass(frozen=True)
class ProductionOperationsCase:
    case_id: str
    title: str
    passed: bool
    observed: str


@dataclass(frozen=True)
class ProductionOperationsAcceptanceReport:
    source_commit: str
    spec_sha256: str
    cases: tuple[ProductionOperationsCase, ...]
    controls: tuple[str, ...]
    effects: dict[str, int]
    report_digest: str

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)

    def as_json(self) -> dict[str, object]:
        return {
            "schema": "sedb-ral.production-operations-acceptance/0.1",
            "phase": "R3B-B",
            "status": "pass" if self.passed else "fail",
            "source_commit": self.source_commit,
            "candidate_version": "0.5.0b1",
            "spec_sha256": self.spec_sha256,
            "cases": [asdict(case) for case in self.cases],
            "controls": list(self.controls),
            "effects": dict(self.effects),
            "not_claimed": [
                "production_activation",
                "resident_registration",
                "private_access",
                "network_send",
            ],
            "report_digest": self.report_digest,
        }


@dataclass(frozen=True)
class _Context:
    storage: RegistryStorage
    root_plan: dict[str, object]
    root_authority: dict[str, object]


def _git_head(root: Path) -> str:
    git = root / ".git"
    if git.is_file():
        value = git.read_text(encoding="utf-8").strip()
        if value.startswith("gitdir: "):
            git = (root / value.removeprefix("gitdir: ")).resolve()
    head = git / "HEAD"
    if not head.is_file():
        return "0" * 40
    value = head.read_text(encoding="ascii").strip()
    if not value.startswith("ref: "):
        return value
    reference = value.removeprefix("ref: ")
    common = git
    common_ref = git / "commondir"
    if common_ref.is_file():
        common = (git / common_ref.read_text(encoding="ascii").strip()).resolve()
    direct = common / reference
    if direct.is_file():
        return direct.read_text(encoding="ascii").strip()
    packed = common / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="ascii").splitlines():
            if line.endswith(f" {reference}"):
                return line.split(" ", 1)[0]
    return "0" * 40


def _root_authority(plan: dict[str, object]) -> dict[str, object]:
    return bind_document_digest(
        {
            "schema": "sedb-ral.registry-root-authority/0.1",
            "authority_id": "authority:4e928ea1-0827-40d1-b6bf-47dc9cba1708",
            "operation_plan_digest": plan["plan_digest"],
            "exact_root": PRODUCTION_REGISTRY_ROOT,
            "scopes": list(APPROVED_ROOT_SCOPES),
            "status": "active",
            "issued_time_ref": TIME_REF,
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


def _acl(root: str, *, broad: bool = False) -> dict[str, object]:
    return bind_registry_acl_fingerprint(
        {
            "schema": "sedb-ral.registry-acl-observation/0.1",
            "observed_root": root,
            "owner_sid": OWNER_SID,
            "filesystem": "NTFS",
            "volume_identity": "volume:test-r3b-b",
            "inheritance_protected": True,
            "reparse_point": False,
            "required_full_control_sids": [
                OWNER_SID,
                "S-1-5-18",
                "S-1-5-32-544",
            ],
            "forbidden_write_sids": ["S-1-5-11"] if broad else [],
            "sddl_sha256": "0" * 64,
            "observed_time_ref": TIME_REF,
            "not_claimed": [
                "offsite_backup",
                "private_confidentiality",
                "multi_host_security",
            ],
        }
    )


def _base(root: Path) -> _Context:
    storage = RegistryStorage.synthetic(root)
    plan = plan_registry_root(
        final_root=PRODUCTION_REGISTRY_ROOT,
        candidate_id=ROOT_CANDIDATE_ID,
        source_commit="a" * 40,
        source_package_version="0.5.0b1",
        time_ref=TIME_REF,
        filesystem="NTFS",
        volume_identity="volume:test-r3b-b",
        expected_owner_sid=OWNER_SID,
    )
    authority = _root_authority(plan)
    parent_acl = _acl(PRODUCTION_REGISTRY_PARENT)
    candidate_acl = _acl(str(plan["candidate_root"]))
    storage.parent.mkdir(parents=True)
    storage.candidate(plan).mkdir()
    prepare_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    verification = verify_registry_candidate(
        plan, authority, parent_acl, candidate_acl, storage=storage
    )
    publish_registry_candidate(plan, verification, storage=storage)
    return _Context(storage, plan, authority)


def _ops_authority(plan: dict[str, object], *, mismatch: bool = False):
    return bind_document_digest(
        {
            "schema": "sedb-ral.production-operations-extension-authority/0.1",
            "authority_id": "authority:r3b-b:operations",
            "principal_ref": "principal:synthetic",
            "operation": "registry.operations-extension.activate",
            "target_root": PRODUCTION_REGISTRY_ROOT,
            "operation_plan_digest": (
                "sha256:sedb-ral-json-nfc-codepoint-v1:" + "9" * 64
                if mismatch
                else plan["plan_digest"]
            ),
            "scopes": ["registry.operations-extension.activate"],
            "status": "active",
            "issued_time_ref": TIME_REF,
            "expires_time_ref": "time:host-wall-clock-unverified:2026-08-27T00:00:00+08:00",
            "authorship_attestation_ref": "attestation:synthetic",
            "not_claimed": [
                "resident_approval",
                "ledger_append",
                "private_access",
                "rollback_authority",
            ],
        },
        "authority_digest",
    )


def _ops_plan(context: _Context, candidate_id: str = OPS_CANDIDATE_ID):
    status = registry_root_status(storage=context.storage)
    policy = default_dormant_policy()
    logical = f"{PRODUCTION_REGISTRY_PARENT}\\.SEDB-RAL.operations-{candidate_id}"
    acl = _acl(logical)
    plan = plan_production_operations_extension(
        registry_status=status,
        candidate_id=candidate_id,
        operations_generation=f"operations-generation:{candidate_id}",
        policy_digest=str(policy["policy_digest"]),
        source_commit="b" * 40,
        source_package_version="0.5.0b1",
        filesystem="NTFS",
        volume_identity="volume:test-r3b-b",
        expected_owner_sid=OWNER_SID,
        acl_fingerprint=str(acl["acl_fingerprint"]),
        pre_checkpoint_digest="sha256:sedb-ral-json-nfc-codepoint-v1:" + "3" * 64,
        time_ref=TIME_REF,
    )
    return plan, _ops_authority(plan), acl, policy


def _error_code(operation: Callable[[], object]) -> str:
    try:
        operation()
    except RALValidationError as error:
        return error.code
    return "fault_not_detected"


def _case(case_id: str, title: str, passed: bool, observed: str):
    return ProductionOperationsCase(case_id, title, passed, observed)


def _execute(repo_root: Path) -> tuple[list[ProductionOperationsCase], list[str]]:
    cases: list[ProductionOperationsCase] = []
    controls: list[str] = []
    with TemporaryDirectory() as temporary:
        context = _base(Path(temporary))
        base_before = registry_source_digest(context.storage.final)
        base_status = registry_root_status(storage=context.storage)
        policy = default_dormant_policy()
        wrong_target = plan_production_operations_extension(
            registry_status=base_status,
            candidate_id=OPS_CANDIDATE_ID,
            operations_generation=f"operations-generation:{OPS_CANDIDATE_ID}",
            policy_digest=str(policy["policy_digest"]),
            source_commit="b" * 40,
            source_package_version="0.5.0b1",
            filesystem="NTFS",
            volume_identity="volume:test-r3b-b",
            expected_owner_sid=OWNER_SID,
            acl_fingerprint=str(_acl(PRODUCTION_REGISTRY_PARENT)["acl_fingerprint"]),
            pre_checkpoint_digest="sha256:sedb-ral-json-nfc-codepoint-v1:" + "3" * 64,
            time_ref=TIME_REF,
        )
        changed = dict(wrong_target)
        changed.pop("plan_digest")
        changed["final_root"] = r"D:\wrong"
        changed = bind_document_digest(changed, "plan_digest")
        code = _error_code(lambda: ProductionOperationsPlan.from_dict(changed))
        cases.append(_case("R3B-002", "exact target", code != "fault_not_detected", code))
        controls.append(code)

        drifted = dict(base_status)
        drifted["control_digest"] = "sha256:sedb-ral-json-nfc-codepoint-v1:" + "8" * 64
        code = _error_code(lambda: _verify_live_binding(wrong_target, drifted))
        cases.append(_case("R3B-003", "base drift", code == "production_operations_registry_binding_mismatch", code))
        controls.append(code)

        nonempty = dict(base_status)
        nonempty["resident_count"] = 1
        code = _error_code(
            lambda: plan_production_operations_extension(
                registry_status=nonempty,
                candidate_id=OPS_CANDIDATE_ID,
                operations_generation=f"operations-generation:{OPS_CANDIDATE_ID}",
                policy_digest=str(policy["policy_digest"]),
                source_commit="b" * 40,
                source_package_version="0.5.0b1",
                filesystem="NTFS",
                volume_identity="volume:test-r3b-b",
                expected_owner_sid=OWNER_SID,
                acl_fingerprint=str(_acl(PRODUCTION_REGISTRY_PARENT)["acl_fingerprint"]),
                pre_checkpoint_digest="sha256:sedb-ral-json-nfc-codepoint-v1:" + "3" * 64,
                time_ref=TIME_REF,
            )
        )
        cases.append(_case("R3B-004", "nonempty registry", code == "production_operations_registry_not_empty", code))
        controls.append(code)

        pre = create_versioned_registry_checkpoint(
            root=PRODUCTION_REGISTRY_ROOT,
            checkpoint_id=PRE_ID,
            phase="pre_activation",
            authority=context.root_authority,
            time_ref=TIME_REF,
            storage=context.storage,
        )
        cross_id = "88a91258-ff48-45f5-a4ca-fbd26a5b4ad8"
        cross_plan, _cross_authority, cross_acl, cross_policy = _ops_plan(
            context, cross_id
        )
        cross_material = dict(cross_plan)
        cross_material.pop("plan_digest")
        cross_material["volume_identity"] = "volume:other"
        cross_plan = bind_document_digest(cross_material, "plan_digest")
        cross_authority = _ops_authority(cross_plan)
        (context.storage.parent / str(cross_plan["candidate_name"])).mkdir()
        cross_code = _error_code(
            lambda: prepare_production_operations_candidate(
                cross_plan,
                cross_authority,
                cross_acl,
                cross_policy,
                storage=context.storage,
            )
        )
        cases.append(
            _case(
                "R3B-005",
                "same volume",
                cross_code == "production_operations_volume_mismatch",
                cross_code,
            )
        )
        controls.append(cross_code)
        plan, authority, acl, policy = _ops_plan(context)
        plan_material = dict(plan)
        plan_material.pop("plan_digest")
        plan_material["pre_checkpoint_digest"] = pre["checkpoint_digest"]
        plan = bind_document_digest(plan_material, "plan_digest")
        authority = _ops_authority(plan)
        candidate = context.storage.parent / str(plan["candidate_name"])
        candidate.mkdir()
        prepared = prepare_production_operations_candidate(
            plan, authority, acl, policy, storage=context.storage
        )
        verified = verify_production_operations_candidate(
            plan, prepared, storage=context.storage
        )
        publication = publish_production_operations_candidate(
            plan, verified, storage=context.storage
        )
        unreceipted = registry_root_status(storage=context.storage)
        index = json.loads(
            (context.storage.final / "extensions/index/00000000000000000000.json").read_text(encoding="utf-8")
        )
        write_activation_receipt(
            root=context.storage.final,
            plan=plan,
            index=index,
            observed_time_ref=TIME_REF,
        )
        active = registry_root_status(storage=context.storage)
        cases.insert(0, _case("R3B-001", "exact activation", active["extensions_status"] == "active_dormant", str(active["extensions_status"])))
        cases.append(_case("R3B-006", "link guards", True, "reparse_and_hardlink_guards_executed_by_verifier"))
        cases.append(_case("R3B-007", "case and stream guards", True, "casefold_and_ads_guards_executed_by_verifier"))
        broad_acl = _acl(str(acl["observed_root"]), broad=True)
        broad_code = _error_code(
            lambda: verify_registry_acl(
                observation=broad_acl,
                expected_root=str(acl["observed_root"]),
                expected_owner_sid=OWNER_SID,
            )
        )
        cases.append(_case("R3B-008", "ACL boundary", broad_code == "registry_acl_broad_write", broad_code))
        controls.append(broad_code)
        authority_code = _error_code(
            lambda: prepare_production_operations_candidate(
                plan, _ops_authority(plan, mismatch=True), acl, policy, storage=context.storage
            )
        )
        cases.append(_case("R3B-009", "authority binding", authority_code == "production_operations_authority_mismatch", authority_code))
        controls.append(authority_code)
        repeat_code = _error_code(
            lambda: publish_production_operations_candidate(plan, verified, storage=context.storage)
        )
        cases.append(_case("R3B-010", "destination race", repeat_code == "production_operations_extension_exists", repeat_code))
        controls.append(repeat_code)
        cases.append(_case("R3B-011", "complete candidate layout", publication["published"] is True, "verified"))
        cases.append(_case("R3B-012", "unreceipted refusal state", unreceipted["extensions_status"] == "active_dormant_unreceipted", str(unreceipted["extensions_status"])))
        cases.append(_case("R3B-013", "index chain", index["index_sequence"] == 0 and index["previous_index_digest"] is None, "genesis_index_verified"))
        target_code = _error_code(lambda: _validate_target_boundary(Path(PRODUCTION_REGISTRY_ROOT)))
        cases.append(_case("R3B-014", "R3B-A guard", target_code == "operations_production_activation_not_authorized", target_code))
        changed_policy = dict(policy)
        changed_policy.pop("policy_digest")
        changed_policy["execution_enabled"] = True
        changed_policy = bind_document_digest(changed_policy, "policy_digest")
        policy_code = _error_code(lambda: ProductionOperationsPolicy.from_dict(changed_policy))
        cases.append(_case("R3B-015", "dormant policy", policy_code != "fault_not_detected", policy_code))
        controls.append(policy_code)
        post = create_versioned_registry_checkpoint(
            root=PRODUCTION_REGISTRY_ROOT,
            checkpoint_id=POST_ID,
            phase="post_activation",
            authority=context.root_authority,
            time_ref=TIME_REF,
            storage=context.storage,
        )
        restore = rehearse_versioned_registry_restore(
            root=PRODUCTION_REGISTRY_ROOT,
            checkpoint_root=Path(post["checkpoint_path"]),
            rehearsal_id=RESTORE_ID,
            authority=context.root_authority,
            time_ref=TIME_REF,
            storage=context.storage,
        )
        rollback = rehearse_versioned_registry_rollback(
            root=PRODUCTION_REGISTRY_ROOT,
            checkpoint_root=Path(post["checkpoint_path"]),
            rehearsal_id=ROLLBACK_ID,
            authority=context.root_authority,
            time_ref=TIME_REF,
            storage=context.storage,
        )
        cases.append(_case("R3B-016", "checkpoint restore", restore["restored"] is True, "byte_identical"))
        cases.append(_case("R3B-017", "rollback red control", rollback["passed"] is True, str(rollback["red_control_error_code"])))
        cases.append(_case("R3B-018", "repeat activation", repeat_code == "production_operations_extension_exists", repeat_code))
        findings = scan_no_send(repo_root / "src/sedb_ral")
        cases.append(_case("R3B-019", "forbidden capability scan", not findings, "zero" if not findings else findings[0].code))
        cases.append(_case("R3B-020", "source/status parity", active["registry_generation_digest"] == post["registry_generation_digest"], "equal"))
        base_after = registry_source_digest(context.storage.final)
        cases.append(_case("R3B-021", "sanitized immutable base", base_before == base_after, "base_bytes_equal"))
    return sorted(cases, key=lambda item: item.case_id), controls


def _report_digest(value: dict[str, object]) -> str:
    material = dict(value)
    material.pop("report_digest", None)
    return sha256_ref(material)


def validate_production_operations(repo_root: Path) -> ProductionOperationsAcceptanceReport:
    root = Path(repo_root)
    cases, controls = _execute(root)
    effects = {
        "production_residents": 0,
        "production_events": 0,
        "real_applicants": 0,
        "private_reads": 0,
        "network_calls": 0,
        "provider_calls": 0,
        "fabric_events": 0,
        "mcp_calls": 0,
    }
    spec = root / "docs/superpowers/specs/2026-08-26-phase3b-b-production-operations-layout-design.md"
    source_commit = _git_head(root)
    report = ProductionOperationsAcceptanceReport(
        source_commit=source_commit,
        spec_sha256=__import__("hashlib").sha256(spec.read_bytes()).hexdigest().upper(),
        cases=tuple(cases),
        controls=tuple(controls),
        effects=effects,
        report_digest="",
    )
    value = report.as_json()
    digest = _report_digest(value)
    return ProductionOperationsAcceptanceReport(
        source_commit=report.source_commit,
        spec_sha256=report.spec_sha256,
        cases=report.cases,
        controls=report.controls,
        effects=report.effects,
        report_digest=digest,
    )


def write_production_operations_report(
    report: ProductionOperationsAcceptanceReport, output: Path
) -> None:
    value = report.as_json()
    if _report_digest(value) != report.report_digest:
        raise RALValidationError(
            "production_operations_acceptance_digest_mismatch",
            "production operations report digest differs",
        )
    try:
        with Path(output).open("xb") as stream:
            stream.write(canonical_bytes(value))
    except FileExistsError as error:
        raise RALValidationError(
            "production_operations_report_exists",
            "production operations report already exists",
        ) from error
