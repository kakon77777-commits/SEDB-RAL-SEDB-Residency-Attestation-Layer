# SEDB-RAL P3-4 Production Public Registry Root Implementation Plan

> **Execution rule:** implement one task at a time with red/green tests, commit each
> completed gate, and provision the production root only after the implementation
> commit is pushed and its remote CI is green.

**Goal:** Build and verify the empty public registry at
`D:\AI_RESIDENCE\REGISTRY\SEDB-RAL` without reading private Residence data or
creating any resident, application, address, or authority event.

**Architecture:** A pure-Python Core owns canonical JSON, plan/authority checks,
candidate layout, no-replace publication, byte manifests, checkpoints, and
isolated rehearsals. A narrow PowerShell adapter owns Windows SID/ACL observation
and mutation. The production runner composes those layers but does not duplicate
their policy.

**Technology:** Python 3.11+, pytest, JSON Schema assets, PowerShell 7/.NET
`DirectorySecurity`, GitHub Actions.

## Global constraints

- The only final target is `D:\AI_RESIDENCE\REGISTRY\SEDB-RAL`.
- Protect both the newly created `REGISTRY` parent and candidate/final child;
  protecting only the child does not defeat parent `DeleteChild` access.
- Permit inherited/container/child FullControl only for the configured owner SID,
  `S-1-5-18` (SYSTEM), and `S-1-5-32-544` (Administrators).
- Reject broad write/create/delete access for Authenticated Users, Users, and
  Everyone.
- Never alter the ACL on `D:\AI_RESIDENCE` or `D:\AI_RESIDENCE\AI_HOME`.
- Never enumerate, read, hash, copy, or mention private Residence children in run
  evidence.
- The final root must be absent; never merge, replace, adopt, or clean an existing
  root.
- The production ledger remains empty. No genesis, resident, application,
  address, authority, or private event is created.
- All mutations require an exact-root plan digest, an authority digest with only
  the five approved P3-4 scopes, and an explicit time receipt.
- Checkpoints are copied by value and labelled `same_volume_local`; they are not
  off-site backup.
- Production provisioning is gated on clean/synchronized source state, local
  verification, pushed implementation, and green remote CI.
- Failed candidates and rehearsals are retained. No recursive deletion is part
  of this plan.

## Task 1: Define strict root contracts

**Files:**

- Create: `src/sedb_ral/registry_root_contracts.py`
- Create: `src/sedb_ral/schemas/registry-root-plan.schema.json`
- Create: `src/sedb_ral/schemas/registry-root-authority.schema.json`
- Create: `src/sedb_ral/schemas/registry-acl-observation.schema.json`
- Create: `src/sedb_ral/schemas/production-registry-manifest.schema.json`
- Create: `src/sedb_ral/schemas/registry-head-receipt.schema.json`
- Test: `tests/test_registry_root_contracts.py`

### Step 1: Write failing contract tests

Cover exact target normalization, UUID-only candidate names, NTFS requirement,
exact operation scopes, forbidden scopes, digest binding, strict schema fields,
and broad-write ACL rejection. Assert P4-002 and P4-004 explicitly.

### Step 2: Run the focused tests and observe failure

```powershell
python -m pytest tests/test_registry_root_contracts.py -q
```

### Step 3: Implement the minimum contracts

Add frozen value objects for `RegistryRootPlan`, `RegistryRootAuthority`,
`RegistryAclObservation`, `ProductionRegistryManifest`, and
`RegistryHeadReceipt`. Use the existing canonical JSON/digest utilities. Require
the exact five approved operation scopes and reject all additions.

Expose:

```python
plan_registry_root(*, final_root, candidate_id, source_commit,
                   source_package_version, time_ref, volume_identity,
                   expected_owner_sid) -> dict
verify_root_authority(*, authority, plan_digest, exact_root) -> None
verify_registry_acl(*, observation, expected_root, expected_owner_sid) -> None
```

The plan-bound owner SID prevents an ACL observation from self-selecting its
trusted owner.

### Step 4: Run focused and schema tests

```powershell
python -m pytest tests/test_registry_root_contracts.py tests/test_phase3_schema_assets.py -q
```

### Step 5: Commit

```powershell
git add src/sedb_ral/registry_root_contracts.py src/sedb_ral/schemas tests/test_registry_root_contracts.py
git commit -m "feat: define production registry root contracts"
```

## Task 2: Build candidate-first initialization and CLI

**Files:**

- Create: `src/sedb_ral/registry_root.py`
- Modify: `src/sedb_ral/cli.py`
- Test: `tests/test_registry_root.py`
- Test: `tests/test_registry_root_cli.py`

### Step 1: Write failing Core tests

Use temporary NTFS-safe fixtures. Cover P4-001, P4-003, P4-005 through P4-008,
and deterministic P4-016. Inject broad ACL, reparse escape where supported,
manifest mutation, external-head mismatch, resident event, private marker, and a
destination race. Assert that failure never mutates an existing final root.

### Step 2: Run focused tests and observe failure

```powershell
python -m pytest tests/test_registry_root.py -q
```

### Step 3: Implement the Core

Expose:

```python
prepare_registry_candidate(plan, authority, parent_acl, candidate_acl) -> dict
verify_registry_candidate(plan, authority, parent_acl, candidate_acl) -> dict
publish_registry_candidate(plan, verification) -> dict
registry_root_status(final_root, expected_plan_digest=None) -> dict
```

Candidate creation uses create-new semantics. Write only the approved exact
layout, manifest, head-zero, and initialization/ACL receipts. Reject reparse
points, alternate streams, unexpected files, device/UNC paths, private markers,
and any non-empty ledger. Re-read every byte before a same-volume `Path.rename`
whose destination must still be absent.

### Step 4: Add CLI commands and failing CLI tests

Add `registry root-plan`, `registry prepare-root`, `registry verify-root`,
`registry publish-root`, and `registry root-status`. Inputs and outputs are JSON
files/stdout; errors are typed and sanitized.

### Step 5: Run focused tests

```powershell
python -m pytest tests/test_registry_root.py tests/test_registry_root_cli.py -q
```

### Step 6: Commit

```powershell
git add src/sedb_ral/registry_root.py src/sedb_ral/cli.py tests/test_registry_root.py tests/test_registry_root_cli.py
git commit -m "feat: initialize empty production registry candidates"
```

## Task 3: Add checkpoint, restore, and rollback rehearsal

**Files:**

- Create: `src/sedb_ral/registry_recovery.py`
- Create: `src/sedb_ral/schemas/registry-checkpoint.schema.json`
- Create: `src/sedb_ral/schemas/registry-restore-receipt.schema.json`
- Create: `src/sedb_ral/schemas/registry-rollback-receipt.schema.json`
- Modify: `src/sedb_ral/cli.py`
- Test: `tests/test_registry_recovery.py`
- Test: `tests/test_registry_recovery_cli.py`

### Step 1: Write failing recovery tests

Cover P4-009 through P4-013: create-only checkpoint, exact byte manifest,
checkpoint mutation turning red, isolated restore, target escape refusal,
rollback corruption turning red with `checkpoint_manifest_digest_mismatch`, and
fresh byte-exact recovery. Verify production byte maps are unchanged.

### Step 2: Run focused tests and observe failure

```powershell
python -m pytest tests/test_registry_recovery.py -q
```

### Step 3: Implement copied-value recovery

Expose:

```python
create_registry_checkpoint(root, checkpoint_id, authority, time_ref) -> dict
verify_registry_checkpoint(checkpoint_root) -> dict
rehearse_registry_restore(root, checkpoint_root, rehearsal_id,
                          authority, time_ref) -> dict
rehearse_registry_rollback(root, checkpoint_root, rehearsal_id,
                           authority, time_ref) -> dict
```

Reject symlinks, junctions, mount points, hard links, ADS, and all output escapes.
Exclude `checkpoints/` and `rehearsals/` from canonical source bytes. Record empty
directory markers explicitly. Never restore over production.

### Step 4: Add CLI commands and run focused tests

Add `registry checkpoint-root`, `registry rehearse-restore`, and
`registry rehearse-rollback`.

```powershell
python -m pytest tests/test_registry_recovery.py tests/test_registry_recovery_cli.py -q
```

### Step 5: Commit

```powershell
git add src/sedb_ral/registry_recovery.py src/sedb_ral/schemas src/sedb_ral/cli.py tests/test_registry_recovery.py tests/test_registry_recovery_cli.py
git commit -m "feat: add isolated registry recovery rehearsals"
```

## Task 4: Add the Windows ACL adapter and one-shot initializer

**Files:**

- Create: `scripts/Get-RegistryAclObservation.ps1`
- Create: `scripts/Initialize-ProductionRegistry.ps1`
- Create: `tests/test_registry_acl_script_contract.py`
- Create: `tests/test_registry_acl_windows.py`

### Step 1: Write failing script-contract tests

Assert scripts contain no `Remove-Item`, network operation, wildcard target,
private-root traversal, or ACL mutation above `REGISTRY`. Require SID-based ACEs,
protected inheritance, `REGISTRY` parent verification, candidate verification,
and exact-root checks.

### Step 2: Run contract tests and observe failure

```powershell
python -m pytest tests/test_registry_acl_script_contract.py -q
```

### Step 3: Implement the ACL adapter

Use .NET `DirectorySecurity` with explicit owner, SYSTEM, and Administrators
SIDs. Disable inheritance without copying broad ACEs. Serialize a normalized
observation containing owner SID, SDDL digest, filesystem/volume identity,
reparse state, and required/forbidden evaluations. Never emit unrelated account
inventory to Git evidence.

### Step 4: Implement the one-shot initializer

The wrapper validates exact paths and authority/plan digests, creates and protects
the absent `REGISTRY` parent, creates/protects the candidate, invokes the Python
Core, then verifies the published final ACL. It stops and retains artifacts on
any uncertainty.

### Step 5: Run Windows-focused tests

```powershell
python -m pytest tests/test_registry_acl_script_contract.py tests/test_registry_acl_windows.py -q
```

### Step 6: Commit

```powershell
git add scripts/Get-RegistryAclObservation.ps1 scripts/Initialize-ProductionRegistry.ps1 tests/test_registry_acl_script_contract.py tests/test_registry_acl_windows.py
git commit -m "feat: protect the production registry ACL boundary"
```

## Task 5: Build P4 acceptance and documentation

**Files:**

- Create: `src/sedb_ral/registry_root_acceptance.py`
- Create: `scripts/validate_registry_root.py`
- Create: `tests/test_registry_root_acceptance.py`
- Create: `docs/runtime/PRODUCTION_REGISTRY_ROOT.md`
- Create: `evidence/production-registry-root/2026-08-25-local-synthetic.json`
- Modify: `.github/workflows/phase3a.yml`
- Modify: `README.md`
- Modify: `pyproject.toml`

### Step 1: Write the failing acceptance test

Require one report with P4-001 through P4-016, all eight injected controls, and
zero resident/private/network/external counters. P4-014 scans only repository
artifacts and sanitized synthetic evidence.

### Step 2: Implement the synthetic validator

Run every case against temporary roots. Produce canonical, deterministic evidence
with relative synthetic references and digests only. Never inspect the production
root in CI.

### Step 3: Wire CI and documentation

Document public/private boundaries, same-volume limitations, exact commands,
failure retention, and separate gates after P3-4. Bump the package to `0.4.0`.

### Step 4: Verify the implementation locally

```powershell
python -m pytest -q
python scripts/validate_registry_root.py --output evidence/production-registry-root/2026-08-25-local-synthetic.json
python scripts/validate_phase1a.py
python scripts/validate_phase1bc.py
python scripts/validate_phase2.py
python scripts/validate_phase3a.py
python scripts/validate_limen_public_view.py
git diff --check
```

### Step 5: Commit, push, and wait for CI

```powershell
git add .github README.md pyproject.toml src scripts tests docs/runtime evidence/production-registry-root
git commit -m "feat: accept production registry root lifecycle"
git push origin main
gh run list --workflow phase3a.yml --branch main --limit 1
gh run watch <run-id> --exit-status
```

Do not create `D:\AI_RESIDENCE\REGISTRY` until the exact pushed commit is green.

## Task 6: Provision and independently verify the production root

### Step 1: Repeat read-only preflight

Confirm exact final and parent absence, D: NTFS/healthy state, no reparse point in
the target ancestry, clean/synchronized `main`, exact pushed commit, and green CI.
Do not enumerate `AI_HOME`.

### Step 2: Create host-bound run artifacts outside Git

In a newly allocated system temporary directory, create:

- exact root/candidate plan and digest;
- authority artifact bound to the plan digest and the five approved scopes;
- explicit temporal receipt marked `host_wall_clock_unverified` unless a stronger
  receipt is actually obtained;
- expected owner SID and filesystem/volume observation.

### Step 3: Run the one-shot initializer

```powershell
pwsh -NoProfile -File scripts/Initialize-ProductionRegistry.ps1 `
  -FinalRoot 'D:\AI_RESIDENCE\REGISTRY\SEDB-RAL' `
  -PlanFile '<temp-plan.json>' `
  -AuthorityFile '<temp-authority.json>' `
  -TimeReceiptFile '<temp-time.json>'
```

No retry, adoption, replacement, or cleanup occurs if this fails.

### Step 4: Verify publication independently

Re-open the final path and prove: protected parent/final ACLs, exact layout,
strict manifest and head-zero digests, empty events/anchors, zero resident,
application, address, and authority records, no reparse/ADS/private markers, and
no production-network/private side effects.

### Step 5: Create checkpoint and run both rehearsals

Use new UUIDs and the same authority gate. Verify the checkpoint bytes, isolated
restore equality, rollback red control, fresh restore equality, and unchanged
production canonical byte map.

### Step 6: Write sanitized receipt and rerun verification

Store only sanitized relative references, digests, scope names, counter totals,
and limitations in `evidence/production-registry-root/2026-08-25-production.json`.
Do not store SDDL, local account names, native session IDs, authority bearer data,
or private paths.

```powershell
python -m pytest -q
python scripts/validate_registry_root.py --verify-production-receipt evidence/production-registry-root/2026-08-25-production.json
git diff --check
```

### Step 7: Commit and push the receipt

```powershell
git add evidence/production-registry-root/2026-08-25-production.json docs/runtime/PRODUCTION_REGISTRY_ROOT.md
git commit -m "docs: record P3-4 production registry acceptance"
git push origin main
gh run list --workflow phase3a.yml --branch main --limit 1
gh run watch <run-id> --exit-status
```

P3-4 is complete only after the pushed receipt commit is green and a final
read-only production check still matches its recorded digests.
