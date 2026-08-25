# Phase 3B-B Production Operations Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add, verify, package, and safely activate a dormant versioned registrar-operations extension inside the exact SEDB-RAL production public registry without changing canonical ledger facts or private Residence data.

**Architecture:** Keep the accepted P3-4 manifest, head-zero receipt, ledger bytes, and R3B-A synthetic guard immutable. Build a separate production-extension contract and candidate tree, publish the complete top-level `extensions` directory with a same-volume no-replace atomic rename, then bind the host-observed result through a separate receipt and versioned checkpoints.

**Tech Stack:** Python 3.11+, `pytest`, strict JSON Schema 2020-12, canonical UTF-8/NFC SEDB-RAL digests, PowerShell 7/Windows ACL APIs, GitHub Actions on Windows and Ubuntu.

**Spec:** `docs/superpowers/specs/2026-08-26-phase3b-b-production-operations-layout-design.md`

## Global Constraints

- Exact production target: `D:\AI_RESIDENCE\REGISTRY\SEDB-RAL`.
- Exact source baseline: `2470be770962556998925a739c3d1099dc830786`.
- Existing `registry-manifest.json`, head-zero receipt, ledger, checkpoints, rehearsals, and evidence bytes are create-only and never overwritten.
- The extension path is `extensions/registrar-operations/v1`; the complete top-level `extensions` candidate publishes by same-volume no-replace atomic rename.
- R3B-A `synthetic_only=true`, `production_activation=false`, and production-path refusal remain unchanged.
- R3B-B activation requires ledger/application/resident/address counts all equal to zero.
- Initial production policy enables only `inspect` and `status`; all intake and mutation stay disabled.
- No private `AI_HOME` read/write, real applicant data, ledger append, network, provider, Fabric, MCP, scheduler, cloud, release, deployment, deletion, or automatic rollback.
- Candidate package version: `0.5.0b1`.
- The checked SEDB v0.4B archive is passed explicitly as `SEDB_V04B_ARCHIVE=D:\Ai\work together\SEDB\releases\SEDB-v0.4B-local.zip`.
- Every production action is preceded and followed by exact status, checkpoint, ACL, and byte-map evidence.

---

## File map

- `src/sedb_ral/production_operations_contracts.py`: canonical plan, authority, manifest, commit, receipt, index, and acceptance types.
- `src/sedb_ral/production_operations_layout.py`: candidate creation, extension verification, generation digest, and atomic publication.
- `src/sedb_ral/production_operations_recovery.py`: versioned pre/post checkpoint and isolated recovery wrappers.
- `src/sedb_ral/production_operations_acceptance.py`: deterministic R3B-001 through R3B-021 matrix and injected controls.
- `src/sedb_ral/schemas/production-operations-*.schema.json`: strict production-extension schemas.
- `src/sedb_ral/schemas/registry-extension-index.schema.json`: append-only extension-index schema.
- `src/sedb_ral/registry_root.py`: extension-aware exact-tree/status integration while preserving the base digest.
- `src/sedb_ral/registry_recovery.py`: permit versioned extension recovery evidence without changing legacy receipt bytes.
- `src/sedb_ral/cli.py`: provider-free plan, prepare, status, and acceptance commands.
- `scripts/Initialize-ProductionOperationsExtension.ps1`: exact Windows ACL/action wrapper and atomic publication call.
- `scripts/validate_production_operations.py`: deterministic acceptance report entry point.
- `tests/production_operations_helpers.py`: literal synthetic base/candidate fixtures.
- `tests/test_production_operations_contracts.py`: contract and digest tests.
- `tests/test_production_operations_layout.py`: candidate, verification, atomic publish, race, and compatibility tests.
- `tests/test_production_operations_recovery.py`: pre/post checkpoint, restore, and rollback controls.
- `tests/test_production_operations_cli.py`: CLI parity and refusal tests.
- `tests/test_production_operations_acl_script.py`: static and synthetic script contract tests.
- `tests/test_production_operations_acl_windows.py`: real Windows ACL behavior tests.
- `tests/test_production_operations_acceptance.py`: 21-case deterministic gate and mutation controls.
- `tests/test_production_operations_packaging.py`: clean wheel/resource/version/entry-point parity.
- `.github/workflows/phase3b-production-operations.yml`: Windows/Ubuntu synthetic gate.
- `docs/runtime/PHASE3B_B_PRODUCTION_OPERATIONS.md`: operator boundary and exact commands.
- `README.md`: candidate status, exclusions, and verification commands.

---

### Task 1: Strict production-extension contracts

**Files:**
- Create: `src/sedb_ral/production_operations_contracts.py`
- Create: `src/sedb_ral/schemas/production-operations-extension-plan.schema.json`
- Create: `src/sedb_ral/schemas/production-operations-extension-authority.schema.json`
- Create: `src/sedb_ral/schemas/production-operations-extension-manifest.schema.json`
- Create: `src/sedb_ral/schemas/production-operations-policy.schema.json`
- Create: `src/sedb_ral/schemas/production-operations-activation-commit.schema.json`
- Create: `src/sedb_ral/schemas/production-operations-activation-receipt.schema.json`
- Create: `src/sedb_ral/schemas/registry-extension-index.schema.json`
- Create: `src/sedb_ral/schemas/production-operations-acceptance.schema.json`
- Create: `tests/production_operations_helpers.py`
- Create: `tests/test_production_operations_contracts.py`

**Interfaces:**
- Consumes: `bind_document_digest()`, `validate_contract()`, `canonical_bytes()`, and `RALValidationError`.
- Produces: `ProductionOperationsPlan.from_dict()`, `ProductionOperationsAuthority.from_dict()`, `ProductionOperationsManifest.from_dict()`, `ProductionOperationsActivationCommit.from_dict()`, `ProductionOperationsActivationReceipt.from_dict()`, `RegistryExtensionIndex.from_dict()`, `plan_production_operations_extension()`, and `verify_production_operations_authority()`.
- Test helper exports: `base_status()`, `dormant_policy()`, `ready_storage()`,
  `production_plan()`, `production_authority()`,
  `prepared_extension_tree()`, and
  `install_complete_extension_with_receipt(storage)`; each returns literal,
  independently digested fixtures and never reads production.

- [ ] **Step 1: Write failing contract tests**

```python
def test_plan_binds_exact_empty_production_root(base_status, dormant_policy):
    value = plan_production_operations_extension(
        registry_status=base_status,
        candidate_id="9b0c7d46-b94d-4b39-b59f-42f4d458955c",
        operations_generation="operations-generation:9b0c7d46-b94d-4b39-b59f-42f4d458955c",
        policy_digest=dormant_policy["policy_digest"],
        source_commit="2470be770962556998925a739c3d1099dc830786",
        source_package_version="0.5.0b1",
        filesystem="NTFS",
        volume_identity="volume:sha256:" + "1" * 64,
        expected_owner_sid="S-1-5-21-1000",
        acl_fingerprint="sha256:sedb-ral-json-nfc-codepoint-v1:" + "2" * 64,
        pre_checkpoint_digest="sha256:sedb-ral-json-nfc-codepoint-v1:" + "3" * 64,
        time_ref="time:host-wall-clock-unverified:2026-08-26T00:00:00+08:00",
    )
    assert value["final_root"] == r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"
    assert value["extension_ref"] == "extensions/registrar-operations/v1"
    assert value["required_counts"] == {
        "ledger_event_count": 0,
        "application_count": 0,
        "resident_count": 0,
        "address_count": 0,
    }
    ProductionOperationsPlan.from_dict(value)
```

Add literal negative tests for wrong target, non-zero count, non-UUID4 candidate,
wrong source version, missing digest, unknown field, authority operation mismatch,
authority plan mismatch, and every forbidden grant.

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest -q tests/test_production_operations_contracts.py`

Required RED: collection fails because `sedb_ral.production_operations_contracts` does not exist.

- [ ] **Step 3: Add strict schemas and minimal canonical types**

Use frozen dataclasses backed by canonical bytes, matching the existing
`registry_root_contracts.py` pattern. Define:

```python
PRODUCTION_ROOT = r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"
EXTENSION_REF = "extensions/registrar-operations/v1"
ACTIVATION_OPERATION = "registry.operations-extension.activate"

def plan_production_operations_extension(
    *, registry_status: Mapping[str, object], candidate_id: str,
    operations_generation: str, policy_digest: str, source_commit: str,
    source_package_version: str, filesystem: str, volume_identity: str,
    expected_owner_sid: str, acl_fingerprint: str,
    pre_checkpoint_digest: str, time_ref: str,
) -> dict[str, object]:
    required_counts = {
        "ledger_event_count": 0,
        "application_count": 0,
        "resident_count": 0,
        "address_count": 0,
    }
    if registry_status.get("verified") is not True or any(
        registry_status.get(name) != expected
        for name, expected in required_counts.items()
    ):
        raise RALValidationError(
            "production_operations_registry_not_empty",
            "production operations activation requires an empty verified registry",
        )
    _validate_uuid4(candidate_id)
    if operations_generation != f"operations-generation:{candidate_id}":
        raise RALValidationError(
            "production_operations_generation_mismatch",
            "operations generation does not bind candidate ID",
        )
    return bind_document_digest({
        "schema": "sedb-ral.production-operations-extension-plan/0.1",
        "final_root": PRODUCTION_ROOT,
        "extension_ref": EXTENSION_REF,
        "candidate_id": candidate_id,
        "candidate_name": f".SEDB-RAL.operations-{candidate_id}",
        "operations_generation": operations_generation,
        "registry_id": registry_status["registry_id"],
        "registry_manifest_digest": registry_status["manifest_digest"],
        "registry_control_digest": registry_status["control_digest"],
        "base_tree_digest": registry_status["tree_digest"],
        "required_counts": required_counts,
        "policy_digest": policy_digest,
        "source_commit": source_commit,
        "source_package_version": source_package_version,
        "filesystem": filesystem,
        "volume_identity": volume_identity,
        "expected_owner_sid": expected_owner_sid,
        "acl_fingerprint": acl_fingerprint,
        "pre_checkpoint_digest": pre_checkpoint_digest,
        "time_ref": time_ref,
        "not_claimed": [
            "resident_registration", "ledger_append", "private_access",
            "network_send", "provider_call", "fabric_emit", "mcp_call",
        ],
    }, "plan_digest")

def verify_production_operations_authority(
    authority: Mapping[str, object], *, plan_digest: str, exact_root: str
) -> dict[str, object]:
    parsed = ProductionOperationsAuthority.from_dict(authority).to_dict()
    if (
        parsed["operation"] != ACTIVATION_OPERATION
        or parsed["operation_plan_digest"] != plan_digest
        or parsed["target_root"] != exact_root
    ):
        raise RALValidationError(
            "production_operations_authority_mismatch",
            "production operations authority binds another action",
        )
    return parsed
```

Replace both function bodies with explicit field construction and validation;
do not share the R3B-A synthetic manifest schema or change its constants.

- [ ] **Step 4: Run contract/schema tests GREEN**

Run: `python -m pytest -q tests/test_production_operations_contracts.py tests/test_phase3a_operations_contracts.py tests/test_phase3_schema_assets.py`

Required result: all selected tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add src/sedb_ral/production_operations_contracts.py src/sedb_ral/schemas tests/production_operations_helpers.py tests/test_production_operations_contracts.py
git commit -m "feat: define production operations extension contracts"
```

---

### Task 2: Extension-aware base status and verifier

**Files:**
- Create: `src/sedb_ral/production_operations_layout.py`
- Create: `tests/test_production_operations_layout.py`
- Modify: `src/sedb_ral/registry_root.py:292-375`
- Modify: `src/sedb_ral/registry_root.py:736-770`
- Modify: `tests/test_registry_root.py`

**Interfaces:**
- Consumes: Task 1 contracts and existing `_walk()`, `_reject_alternate_streams()`, `_reject_private_markers()`, `registry_source_digest()`, and `_rename_no_replace()`.
- Produces: `verify_production_operations_extension(root, receipt_required=True) -> dict[str, object]`, `registry_generation_digest(base_status, index_digest) -> str`, and extension-aware `registry_root_status()` fields.

- [ ] **Step 1: Write failing legacy-compatibility and extension tests**

```python
def test_absent_extension_preserves_exact_base_digest(ready_storage):
    before = registry_root_status(storage=ready_storage)
    assert before["extensions_status"] == "absent"
    assert before["extension_index_digest"] is None
    assert before["operations_generation"] is None
    assert before["activation_receipt_status"] == "absent"
    assert before["tree_digest"] == registry_source_digest(ready_storage.final)

def test_complete_extension_without_receipt_is_dormant_unreceipted(
    ready_storage, prepared_extension_tree
):
    prepared_extension_tree.rename(ready_storage.final / "extensions")
    status = registry_root_status(storage=ready_storage)
    assert status["extensions_status"] == "active_dormant_unreceipted"
    assert status["activation_receipt_status"] == "missing"
```

Add failures for missing commit, wrong index sequence, wrong previous digest,
unknown top-level extension byte, manifest/index mismatch, reparse point, hard
link, alternate stream, case-fold collision, and a receipt bound to another
index.

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest -q tests/test_production_operations_layout.py tests/test_registry_root.py`

Required RED: `registry_root_status()` rejects `extensions` as unexpected and
does not return extension status fields.

- [ ] **Step 3: Implement separate extension verification**

Keep `registry_source_material()` unchanged so the accepted base `tree_digest`
remains byte-stable. Teach
`_verify_exact_tree(root, allow_recovery_material=True, allow_extensions=True)` to
permit only the exact `extensions` paths verified by
`verify_production_operations_extension()`.

```python
def registry_generation_digest(
    base_status: Mapping[str, object], index_digest: str | None
) -> str:
    return sha256_ref({
        "schema": "sedb-ral.registry-generation/0.1",
        "registry_id": base_status["registry_id"],
        "manifest_digest": base_status["manifest_digest"],
        "control_digest": base_status["control_digest"],
        "base_tree_digest": base_status["tree_digest"],
        "extension_index_digest": index_digest,
    })
```

Return typed `absent`, `active_dormant_unreceipted`, or `active_dormant`; never
map malformed presence to absence.

- [ ] **Step 4: Run extension and legacy tests GREEN**

Run: `python -m pytest -q tests/test_production_operations_layout.py tests/test_registry_root.py tests/test_registry_recovery.py tests/test_phase3a_operations_workspace.py`

Required result: selected tests pass and R3B-A still refuses the production path.

- [ ] **Step 5: Commit Task 2**

```powershell
git add src/sedb_ral/production_operations_layout.py src/sedb_ral/registry_root.py tests/test_production_operations_layout.py tests/test_registry_root.py
git commit -m "feat: verify versioned production operations layouts"
```

---

### Task 3: Candidate preparation and atomic publication

**Files:**
- Modify: `src/sedb_ral/production_operations_layout.py`
- Modify: `tests/production_operations_helpers.py`
- Modify: `tests/test_production_operations_layout.py`

**Interfaces:**
- Consumes: Task 1 plan/authority types and Task 2 verifier.
- Produces: `prepare_production_operations_candidate()`, `verify_production_operations_candidate()`, `publish_production_operations_candidate()`, and `write_activation_receipt()`.

- [ ] **Step 1: Write failing candidate/publication tests**

```python
def test_atomic_publish_moves_only_complete_extensions_tree(
    ready_storage, production_plan, production_authority, acl_observation
):
    prepared = prepare_production_operations_candidate(
        production_plan, production_authority, acl_observation,
        storage=ready_storage,
    )
    verified = verify_production_operations_candidate(
        production_plan, prepared, storage=ready_storage
    )
    result = publish_production_operations_candidate(
        production_plan, verified, storage=ready_storage
    )
    assert result["published"] is True
    assert (ready_storage.final / "extensions").is_dir()
    assert not Path(prepared["candidate_extensions_path"]).exists()
    assert registry_root_status(storage=ready_storage)["extensions_status"] == "active_dormant_unreceipted"
```

Add literal tests for destination race, changed candidate after verification,
base status changed after verification, cross-volume observation, existing
extensions, and repeat publication leaving the byte map unchanged.

- [ ] **Step 2: Run publication tests and verify RED**

Run: `python -m pytest -q tests/test_production_operations_layout.py -k "candidate or publish or race"`

Required RED: candidate/publication functions are absent.

- [ ] **Step 3: Implement create-only candidate and no-replace move**

Build the full literal layout from the spec. Reuse `_rename_no_replace()` only
after checking the candidate verification digest, live base status, same-volume
observation, and absent destination. Keep the post-move receipt separate:

```python
def write_activation_receipt(
    *, root: Path, plan: Mapping[str, object], index: Mapping[str, object],
    observed_time_ref: str,
) -> dict[str, object]:
    receipt_path = root / "evidence" / (
        f"operations-extension-activation-{plan['candidate_id']}.json"
    )
    receipt = bind_document_digest({
        "schema": "sedb-ral.production-operations-activation-receipt/0.1",
        "candidate_id": plan["candidate_id"],
        "registry_id": plan["registry_id"],
        "extension_index_digest": index["index_digest"],
        "observed_final_ref": "extensions/registrar-operations/v1",
        "observed_time_ref": observed_time_ref,
        "not_claimed": ["ledger_append", "resident_registration", "private_access"],
    }, "receipt_digest")
    write_new_json(receipt_path, receipt)
    return receipt
```

- [ ] **Step 4: Verify GREEN and unchanged-base controls**

Run: `python -m pytest -q tests/test_production_operations_layout.py tests/test_registry_root.py`

Required result: publication tests pass; base manifest/head/ledger hashes are
identical before and after the synthetic publication.

- [ ] **Step 5: Commit Task 3**

```powershell
git add src/sedb_ral/production_operations_layout.py tests/production_operations_helpers.py tests/test_production_operations_layout.py
git commit -m "feat: publish production operations extensions atomically"
```

---

### Task 4: Versioned checkpoint and recovery evidence

**Files:**
- Create: `src/sedb_ral/production_operations_recovery.py`
- Create: `tests/test_production_operations_recovery.py`
- Modify: `src/sedb_ral/registry_recovery.py:223-356`
- Modify: `src/sedb_ral/registry_recovery.py:376-525`
- Modify: `src/sedb_ral/registry_root.py:20-55`

**Interfaces:**
- Consumes: extension-aware status and existing snapshot verification.
- Produces: `create_versioned_registry_checkpoint()`, `verify_versioned_registry_checkpoint()`, `rehearse_versioned_registry_restore()`, and `rehearse_versioned_registry_rollback()`.

- [ ] **Step 1: Write failing two-checkpoint tests**

```python
def test_pre_and_post_extension_checkpoints_coexist(ready_storage, recovery_authority):
    pre = create_versioned_registry_checkpoint(
        root=PRODUCTION_ROOT,
        checkpoint_id="31cbfa29-4b0c-4b96-aef0-42e653b3f482",
        phase="pre_activation",
        authority=recovery_authority,
        time_ref="time:host-wall-clock-unverified:2026-08-26T00:01:00+08:00",
        storage=ready_storage,
    )
    install_complete_extension_with_receipt(ready_storage)
    post = create_versioned_registry_checkpoint(
        root=PRODUCTION_ROOT,
        checkpoint_id="a905087e-1a4f-43d3-95bc-32e84e271234",
        phase="post_activation",
        authority=recovery_authority,
        time_ref="time:host-wall-clock-unverified:2026-08-26T00:02:00+08:00",
        storage=ready_storage,
    )
    assert pre["checkpoint_digest"] != post["checkpoint_digest"]
    assert len(list((ready_storage.final / "evidence/checkpoints").glob("*.json"))) == 2
```

Add corruption, missing extension, receipt mismatch, restore-to-live refusal,
rollback red control, and original `evidence/checkpoint-receipt.json` unchanged
tests.

- [ ] **Step 2: Run recovery tests and verify RED**

Run: `python -m pytest -q tests/test_production_operations_recovery.py`

Required RED: versioned recovery APIs and `evidence/checkpoints` layout are absent.

- [ ] **Step 3: Implement versioned wrappers without changing legacy bytes**

Use create-only receipts at:

```text
evidence/checkpoints/checkpoint-{uuid4}.json
evidence/restores/restore-{uuid4}.json
evidence/rollbacks/rollback-{uuid4}.json
```

Snapshot the extension and base by value, include `registry_generation_digest`,
and retain legacy v0.1 APIs unchanged.

- [ ] **Step 4: Run recovery and legacy suites GREEN**

Run: `python -m pytest -q tests/test_production_operations_recovery.py tests/test_registry_recovery.py tests/test_registry_recovery_cli.py`

Required result: all selected tests pass and legacy receipts remain byte-stable.

- [ ] **Step 5: Commit Task 4**

```powershell
git add src/sedb_ral/production_operations_recovery.py src/sedb_ral/registry_recovery.py src/sedb_ral/registry_root.py tests/test_production_operations_recovery.py
git commit -m "feat: checkpoint production operations generations"
```

---

### Task 5: CLI and Windows ACL/action wrapper

**Files:**
- Modify: `src/sedb_ral/cli.py:162-218`
- Modify: `src/sedb_ral/cli.py:830-885`
- Create: `scripts/Initialize-ProductionOperationsExtension.ps1`
- Create: `tests/test_production_operations_cli.py`
- Create: `tests/test_production_operations_acl_script.py`
- Create: `tests/test_production_operations_acl_windows.py`

**Interfaces:**
- Consumes: Tasks 1-4 production APIs.
- Produces CLI commands `operations-extension-plan`, `operations-extension-prepare`, `operations-extension-status`, and `operations-extension-acceptance`; Windows script performs exact ACL observation and calls atomic publication.

- [ ] **Step 1: Write failing CLI and script tests**

```python
def test_status_cli_reports_absent_without_mutation(tmp_path, ready_storage, capfd):
    code = cli_main([
        "registry", "operations-extension-status",
        "--synthetic-storage-root", str(ready_storage.root),
    ])
    value = json.loads(capfd.readouterr().out)
    assert code == 0
    assert value["extensions_status"] == "absent"
    assert value["resident_count"] == 0
```

Script behavior tests must execute against a synthetic storage root and assert
wrong final root, broad ACL, wrong plan digest, non-empty ledger, existing
destination, and cross-volume observation all return non-zero without creating
`extensions`.

- [ ] **Step 2: Run CLI/script tests and verify RED**

Run: `python -m pytest -q tests/test_production_operations_cli.py tests/test_production_operations_acl_script.py`

Required RED: commands and script do not exist.

- [ ] **Step 3: Implement provider-free commands and exact Windows wrapper**

The script parameters are exactly:

```powershell
param(
    [Parameter(Mandatory=$true)][string]$FinalRoot,
    [Parameter(Mandatory=$true)][string]$PlanFile,
    [Parameter(Mandatory=$true)][string]$AuthorityFile,
    [Parameter(Mandatory=$true)][string]$PreCheckpointFile,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$false)][string]$SyntheticStorageRoot,
    [Parameter(Mandatory=$false)][string]$PythonExe = "python"
)
```

It rejects any `FinalRoot` other than the exact production root, protects the
candidate ACL before writes, uses create-new outputs, and never cleans up or
deletes a failed candidate automatically.

- [ ] **Step 4: Run CLI/script/Windows tests GREEN**

Run: `python -m pytest -q tests/test_production_operations_cli.py tests/test_production_operations_acl_script.py tests/test_production_operations_acl_windows.py`

Required result: all runnable tests pass; privilege-only ACL cases skip with an
exact reason when the host lacks link/ACL privilege.

- [ ] **Step 5: Commit Task 5**

```powershell
git add src/sedb_ral/cli.py scripts/Initialize-ProductionOperationsExtension.ps1 tests/test_production_operations_cli.py tests/test_production_operations_acl_script.py tests/test_production_operations_acl_windows.py
git commit -m "feat: expose production operations activation controls"
```

---

### Task 6: Deterministic R3B acceptance matrix

**Files:**
- Create: `src/sedb_ral/production_operations_acceptance.py`
- Create: `scripts/validate_production_operations.py`
- Create: `tests/test_production_operations_acceptance.py`
- Modify: `src/sedb_ral/no_send.py`

**Interfaces:**
- Consumes: Tasks 1-5 and clean source metadata.
- Produces: `ProductionOperationsAcceptanceReport`, `validate_production_operations(repo_root)`, and `write_production_operations_report(report, path)`.

- [ ] **Step 1: Write failing 21-case acceptance tests**

```python
def test_r3b_acceptance_is_complete_and_deterministic(repo_root):
    first = validate_production_operations(repo_root)
    second = validate_production_operations(repo_root)
    assert first.passed is True
    assert [case.case_id for case in first.cases] == [
        f"R3B-{index:03d}" for index in range(1, 22)
    ]
    assert first.report_digest == second.report_digest
    assert first.effects == {
        "production_residents": 0,
        "production_events": 0,
        "real_applicants": 0,
        "private_reads": 0,
        "network_calls": 0,
        "provider_calls": 0,
        "fabric_events": 0,
        "mcp_calls": 0,
    }
```

For every injected control, mutate one literal candidate property and assert its
named case changes from pass to fail while production byte maps remain equal.

- [ ] **Step 2: Run acceptance tests and verify RED**

Run: `python -m pytest -q tests/test_production_operations_acceptance.py`

Required RED: acceptance module does not exist.

- [ ] **Step 3: Implement the report and effect/capability scans**

The report must bind source commit, candidate version, spec digest, ordered case
results, injected controls, package paths, effect counters, and explicit
non-claims. Source scanning rejects sockets, subprocess/provider imports,
private roots, real native task IDs, secrets, and Fabric emission from new code.

- [ ] **Step 4: Run acceptance twice and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_production_operations_acceptance.py
python scripts/validate_production_operations.py --output r3b-b-synthetic-1.json
python scripts/validate_production_operations.py --output r3b-b-synthetic-2.json
```

Required result: tests pass; both report digests match; all 21 cases and injected
controls pass; every forbidden effect counter is zero.

- [ ] **Step 5: Commit Task 6**

```powershell
git add src/sedb_ral/production_operations_acceptance.py src/sedb_ral/no_send.py scripts/validate_production_operations.py tests/test_production_operations_acceptance.py
git commit -m "test: accept dormant production operations layouts"
```

---

### Task 7: Packaging, documentation, and CI

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/sedb_ral/__init__.py`
- Create: `tests/test_production_operations_packaging.py`
- Create: `.github/workflows/phase3b-production-operations.yml`
- Create: `docs/runtime/PHASE3B_B_PRODUCTION_OPERATIONS.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: completed source and acceptance CLI.
- Produces: installable `0.5.0b1` wheel, packaged schemas/scripts, operator documentation, and Windows/Ubuntu CI evidence.

- [ ] **Step 1: Write failing package/version tests**

```python
def test_candidate_version_and_packaged_contracts(built_wheel):
    assert metadata.version("sedb-ral") == "0.5.0b1"
    names = set(wheel_entries(built_wheel))
    assert "sedb_ral/schemas/production-operations-extension-plan.schema.json" in names
    assert "sedb_ral/schemas/registry-extension-index.schema.json" in names
```

Define the wheel entry helper in the same test module:

```python
def wheel_entries(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as bundle:
        return sorted(bundle.namelist())
```

Also install the clean wheel into an isolated venv and compare the acceptance
digest with the source-checkout result.

- [ ] **Step 2: Run packaging tests and verify RED**

Run: `python -m pytest -q tests/test_production_operations_packaging.py`

Required RED: version remains `0.5.0a1` and new resources are not packaged.

- [ ] **Step 3: Update version/resources/docs/workflow**

Set both version declarations to `0.5.0b1`. The CI workflow runs on push and PR
for Windows/Ubuntu, installs `.[test]`, runs the new focused suite, full suite,
compileall, wheel build, installed CLI help, and deterministic acceptance. CI
uses only synthetic temporary roots.

- [ ] **Step 4: Run clean package and full local verification**

Run:

```powershell
$env:SEDB_V04B_ARCHIVE='D:\Ai\work together\SEDB\releases\SEDB-v0.4B-local.zip'
python -m pytest -q
python -m compileall -q src
python -m build --wheel --no-isolation
python scripts/validate_production_operations.py --output r3b-b-final-local.json
git diff --check
```

Required result: zero failures, compile/build exit 0, acceptance pass, clean diff
check, and no production/private/network effects.

- [ ] **Step 5: Commit Task 7**

```powershell
git add pyproject.toml src/sedb_ral/__init__.py tests/test_production_operations_packaging.py .github/workflows/phase3b-production-operations.yml docs/runtime/PHASE3B_B_PRODUCTION_OPERATIONS.md README.md
git commit -m "ci: finalize Phase 3B-B production operations candidate"
```

---

### Task 8: Candidate review, push, PR, and merge gate

**Files:**
- Create outside Git: `D:\Ai\work together\EveMissLab-PMW-Fabric\runtime\task-handoffs\2026-08-26_r3b-b-candidate-checkpoint.md`

**Interfaces:**
- Consumes: exact green Task 7 head.
- Produces: remote candidate branch, CI evidence, durable checkpoint, and a reviewed merge commit; no production mutation.

- [ ] **Step 1: Record exact local evidence**

Run `git status --porcelain=v1`, `git rev-parse HEAD`, full tests, acceptance,
wheel SHA256, and
`git diff $(git merge-base origin/main HEAD) HEAD --check`. Write exact outputs and
non-claims to the durable checkpoint file.

- [ ] **Step 2: Push the exact candidate branch**

Run: `git push -u origin docs/phase3b-b-production-operations-layout`

Required result: remote head equals local head; no force push.

- [ ] **Step 3: Create PR and wait for every required check**

Create a PR against `main` titled `feat: activate versioned registrar operations layout`.
Run `gh pr checks` until Windows/Ubuntu full, focused, build, installed CLI, and
acceptance checks all conclude success.

- [ ] **Step 4: Review exact remote diff and merge**

Verify no existing production manifest/head/ledger fixture bytes changed and no
private/native identity material entered Git. Merge with a merge commit to
retain task provenance. Do not delete the branch or worktree.

- [ ] **Step 5: Verify merged main**

Fetch `origin/main`, record the merge SHA, confirm the candidate is its ancestor,
and run the focused production-operations suite on the merged tree.

---

### Task 9: Exact production R3B-B activation and recovery proof

**Files:**
- Create outside Git: `D:\Ai\work together\EveMissLab-PMW-Fabric\runtime\task-handoffs\2026-08-26-r3b-b-production-activation\`
- Create inside production by approved action only: `D:\AI_RESIDENCE\REGISTRY\SEDB-RAL\extensions\`
- Create inside production by approved action only: versioned checkpoint/recovery/receipt files named by generated UUID4 values.

**Interfaces:**
- Consumes: exact merged source, green remote CI, exact live head-zero status, protected ACL observation, and Neo.K's approved approach-A authority boundary.
- Produces: `active_dormant` extension status, pre/post checkpoint proofs, isolated restore/rollback evidence, and sanitized durable handoff; no resident facts.

- [ ] **Step 1: Reconfirm exact live preflight without mutation**

Run the installed/status commands and assert:

```text
registry_id = registry:dabee562-6af0-496d-94e8-1be9539b32ac
manifest_digest = sha256:sedb-ral-json-nfc-codepoint-v1:ebc9cc8facd63a157b77a744268651d1e6fe803c98b9c3f817e04080479d7b4f
control_digest = sha256:sedb-ral-json-nfc-codepoint-v1:8f3c7a9443646c188b90e4bb28c921f8401b1c7f51bd1a90c1e8004dbb783b38
ledger_event_count = 0
application_count = 0
resident_count = 0
address_count = 0
extensions_status = absent
```

Stop if any value differs.

- [ ] **Step 2: Create the durable action workspace and pre-checkpoint**

```powershell
$actionRoot='D:\Ai\work together\EveMissLab-PMW-Fabric\runtime\task-handoffs\2026-08-26-r3b-b-production-activation'
New-Item -ItemType Directory -Path $actionRoot
$preId=[guid]::NewGuid().ToString()
$candidateId=[guid]::NewGuid().ToString()
$postId=[guid]::NewGuid().ToString()
$restoreId=[guid]::NewGuid().ToString()
$rollbackId=[guid]::NewGuid().ToString()
```

Create a versioned pre-activation checkpoint and write its verified receipt to
`$actionRoot\pre-checkpoint.json`.

- [ ] **Step 3: Bind exact plan, authority, ACL, and candidate**

Generate `plan.json`, `authority.json`, and ACL observations from the exact
merged commit and verified pre-checkpoint digest. Re-read them through strict
contract parsers before execution. The authority operation must equal
`registry.operations-extension.activate` and bind the exact plan digest.

- [ ] **Step 4: Execute the Windows activation wrapper once**

```powershell
pwsh -NoProfile -File scripts/Initialize-ProductionOperationsExtension.ps1 `
  -FinalRoot 'D:\AI_RESIDENCE\REGISTRY\SEDB-RAL' `
  -PlanFile "$actionRoot\plan.json" `
  -AuthorityFile "$actionRoot\authority.json" `
  -PreCheckpointFile "$actionRoot\pre-checkpoint.json" `
  -OutputDirectory $actionRoot `
  -PythonExe python
```

Required result: exit 0; final extension status is `active_dormant`; canonical
event/resident/application/address counts remain zero.

- [ ] **Step 5: Create post-checkpoint, restore, and rollback proof**

Create the versioned post checkpoint, restore it into a fresh isolated rehearsal,
run the corruption red control against a disposable copy, and prove a fresh
restore returns to the exact post-checkpoint byte map. Never target live bytes.

- [ ] **Step 6: Run final live readback and sanitize evidence**

Verify base manifest/head/ledger hashes are unchanged, extension/index/receipt
digests agree, policy is dormant, and all forbidden effect counters are zero.
Write a sanitized durable completion handoff containing only public registry
metadata, exact commits, digests, tests, CI URLs, and non-claims.

- [ ] **Step 7: Stop before R3B-C**

Do not create a real intake, application, authority approval, ledger event,
resident record, LIMEN real projection, or private bootstrap. Report R3B-B
completion and request the exact first-applicant choice for R3B-C.
