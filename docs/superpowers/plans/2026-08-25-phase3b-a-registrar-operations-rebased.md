# SEDB-RAL Phase 3B-A Registrar Operations Core Rebased Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-free, synthetic-only registrar operations Core that
wraps existing Phase 3A/P3-4 primitives without changing the deployed
production registry or copying Fabric contracts.

**Architecture:** A strict `sedb_ral.operations` package owns immutable policy,
intake, operator observation, operation request/receipt, store, lease, engine,
and CLI behavior inside disposable workspaces. The engine delegates applicant
preparation, decision, staging, commit, projection, and public export to the
existing Phase 3A and LIMEN-view modules. Foreign contracts enter only as exact
schema pins; J1 adapter conformance is a later gate.

**Tech Stack:** Python 3.11+, stdlib dataclasses/pathlib/hashlib/uuid,
JSON Schema Draft 2020-12, pytest, existing SEDB-RAL canonical/registrar/
projection/registry-root primitives, GitHub Actions Windows and Ubuntu.

**Spec:**
`docs/superpowers/specs/2026-08-25-phase3b-a-registrar-operations-rebased-design.md`

## Global Constraints

- Base is `origin/main@077606f08576b38e93762d7eb4d8720b36766fc1`.
- Work only in `feat/phase3b-a-operations-rebased` linked worktree.
- Do not modify the old `docs/phase3b-registrar-operations-core` worktree.
- Do not modify `D:\AI_RESIDENCE\REGISTRY\SEDB-RAL` or private Residence.
- Do not create a real applicant, native-task binding, authority, or canonical
  production event.
- Every mutation targets a disposable temporary synthetic registry/workspace.
- Reuse `prepare_registration`, `evaluate_prepared_registration`,
  `build_admission_plan`, `commit_admission_plan`, `project_events`, and
  `build_limen_public_view`; do not fork their semantics.
- Do not package or copy Fabric schemas. Use exact `$id`/version/commit/SHA pins.
- J0 fields/enums/reason codes do not drift silently; write a durable seam delta
  before adopting any cross-repo change.
- No network, provider, Bridge, Wake, Board, Herdr, Claude, MCP, HTTP, scheduler,
  Fabric event emission, private read, cloud, or off-site capability.
- Package candidate target is `0.5.0a1`; merge/release/deployment is not claimed.
- Worktree test commands set
  `SEDB_V04B_ARCHIVE=D:\Ai\work together\SEDB\releases\SEDB-v0.4B-local.zip`
  until the independent archive-locator patch is reviewed.

---

### Task 1: Strict Operations Contracts and Typed Models

**Files:**

- Create: `src/sedb_ral/schemas/registrar-operations-manifest.schema.json`
- Create: `src/sedb_ral/schemas/registrar-operations-policy.schema.json`
- Create: `src/sedb_ral/schemas/registrar-intake.schema.json`
- Create: `src/sedb_ral/schemas/registrar-operator-observation.schema.json`
- Create: `src/sedb_ral/schemas/registrar-operation-request.schema.json`
- Create: `src/sedb_ral/schemas/registrar-operation-receipt.schema.json`
- Create: `src/sedb_ral/schemas/foreign-schema-pin.schema.json`
- Create: `src/sedb_ral/operations/__init__.py`
- Create: `src/sedb_ral/operations/models.py`
- Create: `tests/phase3a_operations_helpers.py`
- Create: `tests/test_phase3a_operations_contracts.py`

**Interfaces:**

- Consumes: `canonical_bytes`, `loads_strict`, `sha256_ref`,
  `validate_contract`, `RALValidationError`.
- Produces:

```python
@dataclass(frozen=True)
class ForeignSchemaPin:
    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ForeignSchemaPin: ...
    def to_dict(self) -> dict[str, object]: ...

@dataclass(frozen=True)
class OperationsPolicy: ...
@dataclass(frozen=True)
class RegistrarIntake: ...
@dataclass(frozen=True)
class OperatorObservation: ...
@dataclass(frozen=True)
class OperationRequest: ...
@dataclass(frozen=True)
class OperationReceipt: ...
@dataclass(frozen=True)
class OperationsManifest: ...
```

Every model verifies strict fields/schema and a digest over material excluding
its digest field. `OperationRequest.digest` binds policy, operations generation,
registry identity/manifest, expected head, operator observation, authority,
checkpoint, target/application, and foreign pins.

- [ ] **Step 1: Write RED contract tests**

```python
def test_operation_digest_binds_every_authority_and_concurrency_gate():
    original = valid_operation_request()
    for field, changed in (
        ("policy_digest", digest("other-policy")),
        ("operations_generation", "operations-generation:other"),
        ("registry_manifest_digest", digest("other-registry")),
        ("expected_ledger_head", digest("other-head")),
        ("operator_observation_digest", digest("other-operator")),
        ("authority_artifact_digest", digest("other-authority")),
        ("checkpoint_evidence_digest", digest("other-checkpoint")),
    ):
        mutated = {**original, field: changed}
        assert OperationRequest.from_dict(mutated).digest != (
            OperationRequest.from_dict(original).digest
        )

def test_intake_rejects_applicant_supplied_operational_evidence():
    for forbidden in (
        "canonical_root", "expected_head", "operator_ref", "policy_digest",
        "authority", "checkpoint_ref", "private_path",
    ):
        with pytest.raises(RALValidationError) as caught:
            RegistrarIntake.from_dict({**valid_intake(), forbidden: "claim"})
        assert caught.value.code == "registrar_intake_forbidden_field"

def test_foreign_pin_has_no_schema_body():
    value = valid_foreign_pin()
    value["schema_body"] = {"type": "object"}
    with pytest.raises(RALValidationError) as caught:
        ForeignSchemaPin.from_dict(value)
    assert caught.value.code == "schema_invalid"
```

- [ ] **Step 2: Run RED**

Run:

```powershell
$env:PYTHONPATH='src'
$env:SEDB_V04B_ARCHIVE='D:\Ai\work together\SEDB\releases\SEDB-v0.4B-local.zip'
python -m pytest tests/test_phase3a_operations_contracts.py -q
```

Expected: collection error for missing `sedb_ral.operations.models`.

- [ ] **Step 3: Implement canonical models and strict schemas**

Use one private `_CanonicalContract` storing canonical bytes. Validate the bound
digest before semantic checks so a byte mutation returns the typed digest error.
Require exact J0 operation kinds and exact negative capability flags.

- [ ] **Step 4: Run GREEN and schema meta-tests**

```powershell
python -m pytest tests/test_phase3a_operations_contracts.py tests/test_phase3_schema_assets.py -q
python -m ruff check src/sedb_ral/operations/models.py tests/test_phase3a_operations_contracts.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/schemas/registrar-*.schema.json src/sedb_ral/schemas/foreign-schema-pin.schema.json src/sedb_ral/operations tests/phase3a_operations_helpers.py tests/test_phase3a_operations_contracts.py
git commit -m "feat: define rebased registrar operations contracts"
```

---

### Task 2: Synthetic Workspace, Policy Activation, and Root Binding

**Files:**

- Create: `src/sedb_ral/operations/workspace.py`
- Create: `tests/test_phase3a_operations_workspace.py`

**Interfaces:**

- Consumes: Task 1 models; `RegistryStorage.synthetic`,
  `prepare_registry_candidate`, `verify_registry_candidate`,
  `publish_registry_candidate`, `registry_root_status`.
- Produces:

```python
@dataclass(frozen=True)
class OperationsWorkspace:
    root: Path
    manifest: OperationsManifest

def plan_synthetic_workspace(
    *, registry_status: Mapping[str, object], policy: OperationsPolicy,
    workspace_id: str, time_ref: str, target: Path,
) -> dict[str, object]: ...

def initialize_synthetic_workspace(
    plan: Mapping[str, object], policy: OperationsPolicy,
) -> OperationsWorkspace: ...

def verify_operations_workspace(
    root: Path, *, expected_generation: str,
    registry_status: Mapping[str, object],
) -> OperationsWorkspace: ...

def activate_policy(
    workspace: OperationsWorkspace, policy: OperationsPolicy,
    *, expected_active_sequence: int,
) -> dict[str, object]: ...
```

- [ ] **Step 1: Write RED tests**

Cover exact layout, create-new output, manifest binding, immutable policy,
activation chain, registry status drift, and target refusal.

```python
def test_production_registry_target_refuses_before_creation(tmp_path):
    plan = valid_workspace_plan(
        target=Path(r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL")
    )
    with pytest.raises(RALValidationError) as caught:
        initialize_synthetic_workspace(plan, valid_policy())
    assert caught.value.code == "operations_production_activation_not_authorized"

def test_workspace_binds_exact_synthetic_registry_status(tmp_path):
    workspace, status = initialized_workspace(tmp_path)
    changed = {**status, "manifest_digest": digest("other")}
    with pytest.raises(RALValidationError) as caught:
        verify_operations_workspace(
            workspace.root,
            expected_generation=workspace.manifest.operations_generation,
            registry_status=changed,
        )
    assert caught.value.code == "operations_registry_binding_mismatch"
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/test_phase3a_operations_workspace.py -q
```

Expected: missing workspace module.

- [ ] **Step 3: Implement exact synthetic layout**

Use create-new directories/files only. Reject Git roots, the production root,
private Residence lexical/resolved paths, device/UNC paths, reparse points, ADS,
hard links, case-fold collisions, missing/extra entries, and non-synthetic policy.

- [ ] **Step 4: Run GREEN with existing P3-4 root regressions**

```powershell
python -m pytest tests/test_phase3a_operations_workspace.py tests/test_registry_root.py tests/test_registry_recovery.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/operations/workspace.py tests/test_phase3a_operations_workspace.py
git commit -m "feat: bind synthetic registrar operations workspace"
```

---

### Task 3: Durable Intake, Request, Receipt, Audit, and Lease Store

**Files:**

- Create: `src/sedb_ral/operations/store.py`
- Create: `tests/test_phase3a_operations_store.py`
- Create: `tests/test_phase3a_operations_leases.py`

**Interfaces:**

- Consumes: `OperationsWorkspace`, Task 1 models.
- Produces:

```python
@dataclass(frozen=True)
class StoreResult:
    kind: Literal["created", "duplicate", "quarantined"]
    relative_ref: str
    record_digest: str

@dataclass(frozen=True)
class LeaseResult:
    acquired: bool
    error_code: str | None
    lease_ref: str | None
    lease_digest: str | None

class OperationsStore:
    def submit_intake(self, intake: RegistrarIntake) -> StoreResult: ...
    def submit_request(self, request: OperationRequest) -> StoreResult: ...
    def write_receipt(self, receipt: OperationReceipt) -> StoreResult: ...
    def append_audit(self, value: Mapping[str, object]) -> StoreResult: ...
    def status(self, operation_id: str) -> dict[str, object]: ...
    def acquire_lease(
        self, request: OperationRequest, observation: OperatorObservation,
    ) -> LeaseResult: ...
    def record_lease_release(
        self, request: OperationRequest, lease_digest: str,
    ) -> dict[str, object]: ...
```

- [ ] **Step 1: Write RED store tests**

```python
def test_same_intake_is_idempotent_and_conflicting_intake_is_quarantined(tmp_path):
    store = operations_store(tmp_path)
    first = store.submit_intake(RegistrarIntake.from_dict(valid_intake()))
    same = store.submit_intake(RegistrarIntake.from_dict(valid_intake()))
    conflict = store.submit_intake(
        RegistrarIntake.from_dict(valid_intake(claim_digest=digest("other")))
    )
    assert (first.kind, same.kind, conflict.kind) == (
        "created", "duplicate", "quarantined"
    )

def test_concurrent_lease_has_exactly_one_winner(tmp_path):
    store, request, observation = store_request_fixture(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(
            lambda _: store.acquire_lease(request, observation), range(2)
        ))
    assert sum(item.acquired for item in results) == 1
    assert sorted(item.error_code for item in results if not item.acquired) == [
        "operation_in_progress"
    ]
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/test_phase3a_operations_store.py tests/test_phase3a_operations_leases.py -q
```

- [ ] **Step 3: Implement create-new stores and leases**

Use hashed opaque filename tokens, canonical bytes, `xb` publication, and exact
digest comparisons. Quarantine writes a new immutable observation; it does not
move/delete the conflicting source. Lease release appends an audit observation
and never deletes a lease as proof of completion.

- [ ] **Step 4: Run GREEN and repeat concurrency 20 times**

```powershell
python -m pytest tests/test_phase3a_operations_store.py tests/test_phase3a_operations_leases.py -q
1..20 | ForEach-Object {
  python -m pytest tests/test_phase3a_operations_leases.py::test_concurrent_lease_has_exactly_one_winner -q
  if ($LASTEXITCODE -ne 0) { throw "lease control failed" }
}
```

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/operations/store.py tests/test_phase3a_operations_store.py tests/test_phase3a_operations_leases.py
git commit -m "feat: persist registrar operations idempotently"
```

---

### Task 4: Operational Engine over Existing Phase 3A Core

**Files:**

- Create: `src/sedb_ral/operations/engine.py`
- Create: `tests/test_phase3a_operations_engine.py`
- Create: `tests/test_phase3a_operations_recovery.py`

**Interfaces:**

- Consumes:
  `prepare_registration`, `PreparedRegistration`,
  `evaluate_prepared_registration`, `RegistrationDecision`,
  `build_admission_plan`, `RegistrarAdmissionPlan`,
  `commit_admission_plan`, `inspect_registration_prefix`,
  `find_committed_registration`, `verify_ledger`, `read_verified_events`,
  Tasks 1–3.
- Produces:

```python
@dataclass(frozen=True)
class PlannedOperation:
    request_digest: str
    prepared_digest: str | None
    decision_digest: str | None
    registrar_plan_digest: str | None
    source_head: str | None
    candidate_head: str | None
    plan_digest: str

class RegistrarOperationsEngine:
    def inspect(self, operation_id: str) -> dict[str, object]: ...
    def prepare(
        self, operation_id: str, claim: Mapping[str, object],
        host_observation: Mapping[str, object], registration_ids: RegistrationIds,
    ) -> PreparedRegistration: ...
    def plan(
        self, operation_id: str, *, authority: Mapping[str, object],
        ctcl_receipt: Mapping[str, object], verified_attestation_refs: frozenset[str],
    ) -> PlannedOperation: ...
    def execute(
        self, operation_id: str, plan: PlannedOperation,
        *, authority: Mapping[str, object], ctcl_receipt: Mapping[str, object],
        verified_attestation_refs: frozenset[str],
    ) -> OperationReceipt: ...
```

- [ ] **Step 1: Write RED engine tests**

Cover read-only inspect, preparation, missing authority, stale policy,
generation, checkpoint, head, complete retry, partial prefix, and zero commit
calls on every stale gate.

```python
@pytest.mark.parametrize("mutation,code", (
    ("policy", "operations_policy_stale"),
    ("generation", "operations_generation_mismatch"),
    ("registry_manifest", "operations_registry_binding_mismatch"),
    ("head", "external_anchor_mismatch"),
    ("checkpoint", "operations_checkpoint_stale"),
))
def test_execute_rechecks_every_gate_before_phase3a_commit(
    tmp_path, monkeypatch, mutation, code
):
    engine, plan, inputs = planned_engine(tmp_path)
    called = False
    def forbidden_commit(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("commit must not run")
    monkeypatch.setattr("sedb_ral.operations.engine.commit_admission_plan", forbidden_commit)
    mutate_gate(engine, mutation)
    with pytest.raises(RALValidationError) as caught:
        engine.execute(plan.operation_id, plan, **inputs)
    assert caught.value.code == code
    assert called is False
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/test_phase3a_operations_engine.py tests/test_phase3a_operations_recovery.py -q
```

- [ ] **Step 3: Implement orchestration only**

Convert retained records back through Task 1 models; use existing Phase 3A
preparation/decision/plan/commit without copying logic. Recompute every gate
immediately before commit. After complete commit, write the operation receipt;
on retry, use `find_committed_registration` and the existing receipt.

- [ ] **Step 4: Run GREEN with Phase 3A regressions**

```powershell
python -m pytest tests/test_phase3a_operations_engine.py tests/test_phase3a_operations_recovery.py tests/test_phase3_registrar_plan.py tests/test_phase3_registrar_recovery.py tests/test_phase3_registration_admission.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/operations/engine.py tests/test_phase3a_operations_engine.py tests/test_phase3a_operations_recovery.py
git commit -m "feat: execute synthetic registrar operations safely"
```

---

### Task 5: Synthetic Actions and Existing Public Export

**Files:**

- Create: `src/sedb_ral/operations/actions.py`
- Create: `src/sedb_ral/operations/public_export.py`
- Create: `tests/test_phase3a_operations_actions.py`
- Create: `tests/test_phase3a_operations_public_export.py`
- Create: `profiles/ral-fabric-seam-v0.1.json`

**Interfaces:**

- Consumes: existing ledger event/correction/authority contracts,
  `project_events`, `build_limen_public_view`, `limen_contract_digest`,
  Tasks 1–4.
- Produces:

```python
def reject_application(engine, request: OperationRequest) -> OperationReceipt: ...
def withdraw_application(engine, request: OperationRequest) -> OperationReceipt: ...
def suspend_address(engine, request: OperationRequest) -> OperationReceipt: ...
def revoke_operation_authority(
    engine, request: OperationRequest
) -> OperationReceipt: ...

def export_public(
    *, ledger_root: Path, expected_head: str, sequence: int,
    destination: Path,
) -> dict[str, object]: ...

def seam_source_manifest() -> dict[str, object]: ...
```

The seam manifest exposes only the RAL public schema ID, version, source commit,
raw SHA-256, public-export profile ID, and no Fabric schema bytes.

- [ ] **Step 1: Write RED action/export tests**

Prove unsupported rejection/withdrawal/address-suspension requests produce
typed no-append receipts, accepted authority revocation is append-only, later
execute refuses after revocation, and exact-head export is deterministic,
create-new, and free of private/operator/authority/Fabric content.

```python
def test_public_export_contains_no_operations_or_foreign_transport_fields(tmp_path):
    output = export_fixture(tmp_path)
    serialized = canonical_bytes(output).lower()
    for marker in (
        b"operator_observation", b"authority_artifact", b"policy_digest",
        b"private", b"ai_home", b"fabric", b"realm", b"delivery",
    ):
        assert marker not in serialized

def test_seam_manifest_pins_ral_source_without_copying_foreign_schema():
    value = seam_source_manifest()
    assert value["schema_id"] == (
        "https://evemisslab.com/schemas/limen/ral-view-v0.2.json"
    )
    assert len(value["raw_sha256"]) == 64
    assert "schema_body" not in value
    assert value["foreign_schema_pins"] == []
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest tests/test_phase3a_operations_actions.py tests/test_phase3a_operations_public_export.py -q
```

- [ ] **Step 3: Implement only operations not already owned elsewhere**

Use existing ledger correction/revocation primitives. If a requested action has
no accepted underlying event contract, return `operation_kind_not_implemented`
without append rather than inventing a new canonical event in R3B-A.

- [ ] **Step 4: Run GREEN with public-view regressions**

```powershell
python -m pytest tests/test_phase3a_operations_actions.py tests/test_phase3a_operations_public_export.py tests/test_limen_public_view_contract.py tests/test_limen_public_view_export.py tests/test_limen_public_view_gate.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/operations/actions.py src/sedb_ral/operations/public_export.py tests/test_phase3a_operations_actions.py tests/test_phase3a_operations_public_export.py profiles/ral-fabric-seam-v0.1.json
git commit -m "feat: operate and export synthetic registrar state"
```

---

### Task 6: Operations CLI and Capability Boundary

**Files:**

- Create: `src/sedb_ral/operations/cli.py`
- Modify: `src/sedb_ral/cli.py`
- Create: `tests/test_phase3a_operations_cli.py`
- Create: `tests/test_phase3a_operations_no_send.py`

**Interfaces:**

- Consumes: Tasks 1–5.
- Produces: commands from spec section 15 and
  `run_once(workspace_root: Path) -> tuple[dict[str, object], ...]` for local
  create-new inbox inspection.

- [ ] **Step 1: Write RED CLI/Core parity tests**

Cover every command, canonical one-LF output, duplicate keys, missing exact
head/generation, create-new outputs, typed exit codes, no path/stack leakage,
and tree fingerprints before/after read-only commands.

```python
def test_operations_execute_requires_exact_head_and_generation(capfd):
    assert main(["operations", "execute"]) == 2
    value = json.loads(capfd.readouterr().out)
    assert value["reason_codes"] == ["cli_usage_error"]

def test_status_cli_leaves_workspace_unchanged(tmp_path, capfd):
    workspace, operation_id = completed_operation(tmp_path)
    before = tree_fingerprint(workspace.root)
    assert main([
        "operations", "status", operation_id,
        "--root", str(workspace.root),
    ]) == 0
    assert tree_fingerprint(workspace.root) == before
```

- [ ] **Step 2: Write RED no-send/source-boundary test**

AST-scan `src/sedb_ral/operations` for socket/HTTP/subprocess/provider/Bridge/
Wake/MCP/private-Residence APIs and dynamically inject one socket call into a
temporary copy to prove `forbidden_call:socket.create_connection` turns red.

- [ ] **Step 3: Run RED**

```powershell
python -m pytest tests/test_phase3a_operations_cli.py tests/test_phase3a_operations_no_send.py -q
```

- [ ] **Step 4: Implement thin handlers and local run-once inspector**

Handlers parse strict JSON into Task 1 models and call shared Core. The inspector
does not watch continuously, start processes, send messages, or infer authority.

- [ ] **Step 5: Run GREEN and existing CLI regressions**

```powershell
python -m pytest tests/test_phase3a_operations_cli.py tests/test_phase3a_operations_no_send.py tests/test_cli_smoke.py tests/test_phase3_cli.py tests/test_limen_public_view_cli.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add src/sedb_ral/operations/cli.py src/sedb_ral/cli.py tests/test_phase3a_operations_cli.py tests/test_phase3a_operations_no_send.py
git commit -m "feat: expose synthetic registrar operations CLI"
```

---

### Task 7: R3B-A Acceptance, Packaging, Docs, and CI

**Files:**

- Create: `src/sedb_ral/phase3a_operations.py`
- Create: `scripts/validate_phase3a_operations.py`
- Create: `tests/test_phase3a_operations_gate.py`
- Create: `tests/test_phase3a_operations_packaging.py`
- Create: `evidence/phase3a-operations/2026-08-25-local.json`
- Create: `docs/runtime/PHASE3B_A_REGISTRAR_OPERATIONS.md`
- Create: `.github/workflows/phase3a-operations.yml`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `src/sedb_ral/__init__.py`

**Interfaces:**

- Consumes: Tasks 1–6 and existing Phase 1–3A/P3-4/LIMEN gates.
- Produces:

```python
EXPECTED_CASE_IDS = tuple(f"R3A-{index:03d}" for index in range(1, 19))

def validate_phase3a_operations(root: Path) -> OperationsAcceptanceReport: ...
def write_operations_report(
    report: OperationsAcceptanceReport, destination: Path
) -> Path: ...
```

- [ ] **Step 1: Write RED integrated acceptance tests**

Require 18 exact cases, all injected controls, two execution digests equal,
candidate version `0.5.0a1`, zero production/private/network/provider/Fabric
effects, exact existing-schema digest reuse, and source scan free of foreign
schema bodies.

```python
def test_r3b_a_acceptance_inventory_and_side_effects():
    report = validate_phase3a_operations(ROOT)
    assert report.passed is True
    assert report.case_ids == EXPECTED_CASE_IDS
    assert report.repeated_run_match is True
    assert report.production_root_writes == 0
    assert report.real_applicants == 0
    assert report.private_reads == 0
    assert report.network_calls == 0
    assert report.fabric_events == 0
```

- [ ] **Step 2: Write RED clean-wheel tests**

Build a wheel from a copied source tree; install outside checkout; verify version,
packaged schema IDs, operations CLI help, contract validation, and absence of
profiles/evidence/private paths from the wheel where not package data.

- [ ] **Step 3: Run RED**

```powershell
python -m pytest tests/test_phase3a_operations_gate.py tests/test_phase3a_operations_packaging.py -q
```

- [ ] **Step 4: Implement two-run acceptance and documentation**

Use two independent `TemporaryDirectory` roots and fixed opaque IDs/time refs.
Reports contain only relative synthetic refs and digests. Update docs with the
R3B-A/B/C split and J1 seam boundary.

- [ ] **Step 5: Add cross-platform CI**

The workflow runs Windows/Ubuntu Python 3.11, installs `.[test]`, executes all
`test_phase3a_operations_*.py`, generates evidence, and uploads it. It never
mounts or inspects the production root.

- [ ] **Step 6: Run full local verification**

```powershell
$env:PYTHONPATH='src'
$env:SEDB_V04B_ARCHIVE='D:\Ai\work together\SEDB\releases\SEDB-v0.4B-local.zip'
python -m pytest -q
python scripts/validate_phase1a.py
python scripts/validate_phase1bc.py
python scripts/validate_phase2.py --sedb-archive $env:SEDB_V04B_ARCHIVE
python scripts/validate_phase3a.py --output (Join-Path $env:TEMP 'phase3a-r3b-a.json')
python scripts/validate_registry_root.py --output (Join-Path $env:TEMP 'registry-r3b-a.json')
python scripts/validate_phase3a_operations.py --output evidence/phase3a-operations/2026-08-25-local.json
python -m ruff check src/sedb_ral/operations src/sedb_ral/phase3a_operations.py tests/test_phase3a_operations_*.py
git diff --check
```

Expected: no failures; only existing documented platform skips.

- [ ] **Step 7: Commit and routine-push candidate branch**

```powershell
git add .github/workflows/phase3a-operations.yml README.md pyproject.toml src/sedb_ral/__init__.py src/sedb_ral/phase3a_operations.py scripts/validate_phase3a_operations.py tests/test_phase3a_operations_gate.py tests/test_phase3a_operations_packaging.py evidence/phase3a-operations/2026-08-25-local.json docs/runtime/PHASE3B_A_REGISTRAR_OPERATIONS.md
git commit -m "feat: complete rebased Phase 3B-A operations core"
git push -u origin feat/phase3b-a-operations-rebased
```

Do not merge.

- [ ] **Step 8: Wait for CI and prepare J1 handoff**

Record exact branch head, workflow run, job conclusions, schema IDs/digests,
public RAL source pin, test counts, worktree status, and no-effect counters in a
create-new durable handoff. J1 begins only after the Fabric Wave 1 candidate is
also clean and remotely proven or explicitly marked local-only.

---

## Spec Coverage

| Spec sections | Plan tasks |
|---|---|
| 1–5 decision/baseline/scope/ownership | Global Constraints, Tasks 1–7 |
| 6 synthetic storage | Task 2 |
| 7 contracts | Task 1 |
| 8–11 states/authority/workflow/idempotency | Tasks 3–4 |
| 12 public export | Task 5 |
| 13–14 J0/J1 and incident consumer gate | Tasks 1, 5, 7/J1 handoff |
| 15 CLI | Task 6 |
| 16 acceptance | Task 7 |
| 17 packaging/version | Task 7 |
| 18 archive locator split | Separate branch; explicit worktree baseline pin |
| 19–20 completion/later gates | Task 7 and durable J1 handoff |

## Execution Boundary

Implement Tasks 1–7 sequentially in the isolated R3B-A worktree. No task in
this plan authorizes merge, production-root layout change, real applicant,
Fabric event emission, live federation, private Residence, B6B, cloud/off-site
replication, or provider invocation.
