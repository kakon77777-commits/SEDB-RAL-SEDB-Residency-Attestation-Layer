# SEDB-RAL Phase 3B-A Registrar Operations Core Rebased Design

> **Status:** J0 ownership approved by Neo.K; scoped branch implementation,
> tests, commits, and routine push authorized; merge and production mutation
> remain separately gated
>
> **Date:** 2026-08-25
>
> **Repository base:** `origin/main@077606f08576b38e93762d7eb4d8720b36766fc1`
>
> **Branch:** `feat/phase3b-a-operations-rebased`
>
> **Scope:** provider-free synthetic registrar operations Core over the accepted
> Phase 3A registrar and P3-4 public-registry contracts

## 1. Decision

Phase 3B is split into independently authorized lines:

```text
R3B-A synthetic operations contracts/store/engine/CLI/acceptance
→ J1 RAL public-projection ↔ Fabric adapter conformance
→ R3B-B versioned production-layout extension
→ R3B-C one exact host-bound real applicant
```

This specification covers **R3B-A only**. It produces working, packaged,
deterministic software, but every canonical write occurs in a disposable
synthetic registry and operations workspace. It does not change the existing
production root.

## 2. Accepted baseline

Current main already provides:

- Phase 3A applicant preparation, decision, staging, exact-head admission,
  idempotency, partial-prefix recovery detection, CLI, and 24-case acceptance;
- the LIMEN public-view exporter in SEDB-RAL;
- SEDB-RAL 0.4.0;
- the exact production public root
  `D:\AI_RESIDENCE\REGISTRY\SEDB-RAL`;
- immutable `registry-manifest.json` and head-zero control receipt;
- protected parent/final ACL policy;
- same-volume checkpoint, isolated restore, rollback red control, and
  production receipt;
- final full local gate `629 passed, 2 skipped` and six-job Windows/Ubuntu CI.

R3B-A wraps these interfaces. It must not fork the ledger chain,
canonicalization, registrar event sequence, public projection, production root
manifest, or recovery format.

## 3. Included scope

- strict operation-policy, intake, operator-observation, request, receipt, and
  foreign-schema-pin contracts;
- a create-new synthetic operations workspace bound to one exact synthetic
  registry status and root-generation digest;
- durable intake/request/receipt/audit stores with digest/idempotency checks;
- one-winner operation leases with receiver-observed host/process evidence;
- read-only inspect and status;
- applicant preparation and decision through existing Phase 3A functions;
- exact-head synthetic plan/execute through existing registrar functions;
- typed synthetic rejection, withdrawal, address suspension, and
  operation-authority revocation requests; only actions supported by current
  accepted ledger builders may append, while unsupported actions fail closed;
- deterministic public export through the existing SEDB-RAL public-view Core;
- provider-free CLI and one-shot local file inspector;
- two-run synthetic acceptance, package/wheel parity, no-send/private-path
  gates, and cross-platform CI;
- J1-ready schema pins without copying Fabric schemas.

## 4. Excluded scope

- adding `inbox/`, `locks/`, `policy.json`, `operations/`, or any other byte to
  the deployed production root;
- changing P3-4 `registry-manifest.json`, head-zero, checkpoint, rehearsal, ACL,
  or receipt bytes;
- real applicant intake, preparation, authority approval, admission, correction,
  suspension, revocation, or withdrawal;
- resolving a remembered name, task title, provider, model, or runtime into a
  resident;
- Fabric event emission/import, realm activation, network send, provider call,
  Bridge, Wake, Board, Herdr, Claude, MCP, HTTP, or scheduler;
- B6B/private Residence access, private bootstrap, memory reads/writes, cloud or
  off-site replication;
- merge, release, deployment, or protected/default-branch mutation.

## 5. Canonical ownership

SEDB-RAL owns:

- resident/application/address/instance/line semantics;
- registry-effective authority validation and state;
- admission/correction/revocation/suspension meaning;
- ledger, head, registry identity, root-generation binding, operation
  request/receipt/idempotency state;
- public projection content and redaction decisions.

Fabric owns portable carrier/realm/replica/delivery/materialization/adoption
semantics. R3B-A contains no Fabric schema copy and emits no Fabric event.

## 6. Synthetic storage boundary

R3B-A creates an operations workspace beside a disposable synthetic registry:

```text
<temporary-run>/
  registry/                     existing P3-4 synthetic root lifecycle
  operations/
    OPERATIONS-MANIFEST.json
    policies/
      policy-{digest-token}.json
    active-policy/
      00000000000000000000.json
    inbox/
    requests/
    receipts/
    audit/
    leases/
    projections/
      public/
    staging/
```

The operations workspace is not canonical resident storage. Canonical resident
facts remain only in the synthetic registry ledger. Request, receipt, audit,
lease, and projection records cannot create resident facts without an exact
Phase 3A commit.

The operations manifest binds:

```text
schema                       sedb-ral.registrar-operations-manifest/0.1
operations_generation        opaque UUID-based generation
registry_id                  exact registry status value
registry_manifest_digest     exact P3-4 manifest digest
registry_control_digest      exact retained control digest
registry_source_tree_digest  exact canonical source-tree digest
policy_activation_ref        active-policy/00000000000000000000.json
synthetic_only               true
production_activation        false
fabric_schema_pins           empty or J1-provided exact pins
created_time_ref             explicit synthetic/unavailable temporal ref
not_claimed                  production activation, identity proof, private access,
                             federation, deployment
manifest_digest              canonical bound digest
```

Any configured path equal to or under the deployed production root is refused
with `operations_production_activation_not_authorized` before directory
creation.

## 7. Contract set

### 7.1 Operations policy

`sedb-ral.registrar-operations-policy/0.1` declares exact accepted profiles,
operation scopes, maximum P0/P1 intake sizes, checkpoint requirements,
synthetic-only state, public fields, lease duration, and capability flags:

```text
production_mutation = false
real_applicant       = false
private_access       = false
network_send         = false
fabric_emit          = false
```

Policy files are immutable. Activation appends a control receipt; it never edits
an active policy.

### 7.2 Intake

`sedb-ral.registrar-intake/0.1` carries immutable references and digests for an
applicant-authored claim and receiver-authored host observation. It cannot carry
trusted root, head, policy, operator, authority, checkpoint, or private-path
fields. Arrival is not preparation, approval, identity resolution, or admission.

### 7.3 Operator observation

`sedb-ral.registrar-operator-observation/0.1` records receiver-observed task,
adapter, origin, principal-authorship evidence status, host/process evidence,
and unavailable fields. A model label or possession of the CLI is never enough.

### 7.4 Operation request

`sedb-ral.registrar-operation-request/0.1` binds:

```text
operation_id
operation_kind
intake_digest / application_digest / target_ref as applicable
authority_artifact_ref and digest as applicable
operator_observation_ref and digest
policy_digest
operations_generation
registry_id
registry_manifest_digest
expected_ledger_head
checkpoint_evidence_ref and digest as required by policy
foreign_evidence_pins
created_time_ref
not_claimed
operation_digest
```

Operation kinds in R3B-A:

```text
inspect | prepare | plan | execute | reject | withdraw |
suspend_address | revoke_authority | status | export_public
```

### 7.5 Operation receipt

`sedb-ral.registrar-operation-receipt/0.1` records the exact request/policy/root
generation, pre/post head, outcome, existing Phase 3A receipt ref/digest,
projection ref/digest, typed error state, side-effect counters, and receipt
digest.

### 7.6 Foreign schema pin

`sedb-ral.foreign-schema-pin/0.1` contains only:

```text
schema_id
schema_version
source_repository
source_commit
raw_sha256
profile_ref
```

Wave 1 accepts an empty pin list. J1 may add exact Fabric pins after both
candidates stabilize. R3B-A never packages foreign schema bytes.

## 8. Operation states

Derived states are:

```text
received
inspected
prepared
awaiting_principal_authority
planned
staged
committed
projected
complete
rejected
deferred
recovery_required
quarantined
```

No mutable status file is canonical. State derives from immutable intake,
request, audit, ledger, and receipt evidence.

## 9. Authority and execution gate

Mutation of the disposable synthetic ledger requires all of:

```text
valid operation request
AND exact synthetic operations generation
AND exact P3-4 synthetic registry identity/manifest/control digest
AND active exact policy digest
AND receiver-observed operator evidence
AND active principal-authored authority artifact
AND exact operation scope and target/application digest
AND exact expected ledger head
AND required checkpoint evidence
→ staging may begin
```

The engine rechecks policy, operations generation, registry status, authority,
checkpoint, and head immediately before the existing Phase 3A commit call.

## 10. Workflow

```text
submit intake create-new
→ inspect without mutation authority
→ prepare immutable application on explicit request
→ expose exact digest
→ receive synthetic principal authority fixture
→ submit exact operation request
→ acquire one create-new lease
→ verify operations manifest/policy/registry/checkpoint/head
→ call existing build_admission_plan in isolated staging
→ verify staged candidate and projections
→ recheck every gate
→ call existing commit_admission_plan on synthetic ledger only
→ write immutable operation receipt and audit record
→ rebuild existing public view
→ release lease through an immutable release observation
```

Failure before the Phase 3A append changes no canonical ledger byte. A complete
retry returns the existing receipt. Partial prefix remains `recovery_required`.

## 11. Idempotency and leases

- Same intake ID and core digest: return existing record.
- Same intake ID and different digest: quarantine.
- Same operation ID and core digest after completion: return existing receipt.
- Same operation ID and different digest: quarantine.
- One create-new lease winner; loser receives `operation_in_progress`.
- Lease payload binds operation ID/digest, operations generation, receiver host
  observation, bounded expiry claim, and lease digest.
- Stale-lease recovery is unavailable in Wave 1 unless a scoped synthetic
  recovery request and host/process observation both verify.
- No process ID, mtime, or disappearance of a file silently grants recovery.

## 12. Public export

R3B-A reuses SEDB-RAL's existing public projection and exact-head exporter. It
may add an operation receipt referring to the output but cannot redefine:

- resident or address semantics;
- public field eligibility;
- locator redaction/digest rules;
- conflict preservation;
- exact source event/head references.

The export is deterministic and rebuildable. It contains no operations policy,
operator observation, authority body, applicant discussion, private path, token,
or Fabric delivery state.

## 13. J0/J1 seam discipline

The approved J0 durable architecture response is the Wave 1 seam candidate.
Fields, enum values, and reason codes do not silently drift.

If implementation needs a seam change before J1, the proposer writes a
create-new durable delta containing old value, new value, reason, compatibility,
affected fixtures, and SHA-256, then notifies the other task before code adopts
the change.

J1 adds only digest-pinned conformance:

```text
RAL public projection schema + bytes owned by RAL
Fabric adapter/envelope/adoption schemas owned by Fabric
adapter profile pins source schema ID/version/commit/SHA
no schema or canonical ledger copied across repositories
```

## 14. Cross-task incident consumer gate

Fabric owns `pmw.adapter-visibility-evidence/0.1` and its completed/empty-read/
local-transcript/durable-handoff corpus. Wave 1 R3B-A does not reproduce that
schema.

At J1, one digest-pinned RAL integration fixture must prove that such evidence:

- does not mean no response;
- does not mean portable delivery acknowledged;
- does not prove authorship, identity, applicant opt-in, withdrawal, or
  admission authority;
- may permit inspection of an explicitly referenced durable artifact only
  through ordinary intake validation.

## 15. CLI surface

```text
sedb-ral operations init-synthetic PLAN --output RECEIPT
sedb-ral operations verify ROOT --expected-generation DIGEST
sedb-ral operations intake-add INTAKE --root ROOT
sedb-ral operations request-add REQUEST --root ROOT
sedb-ral operations plan OPERATION_ID --root ROOT
sedb-ral operations execute OPERATION_ID --root ROOT --expected-head GENESIS|DIGEST
sedb-ral operations status OPERATION_ID --root ROOT
sedb-ral operations export-public --root ROOT --expected-head DIGEST --output FILE
```

All machine output is canonical UTF-8 plus one LF. Commands distinguish
unreadable input, semantic rejection, unmeasured/deferred evidence,
conflict/recovery-required, and success.

## 16. Acceptance

R3B-A acceptance contains 18 cases:

| ID | Case | Expected |
|---|---|---|
| R3A-001 | Synthetic workspace init | exact layout and bound manifest |
| R3A-002 | Production/private/Git target | refuse before creation |
| R3A-003 | Policy mutation | digest mismatch |
| R3A-004 | Intake duplicate same digest | one intake record |
| R3A-005 | Intake same ID/different digest | quarantined |
| R3A-006 | Applicant supplies operator/root/head/authority | ignored/rejected as evidence |
| R3A-007 | Inspect without mutation authority | read-only success |
| R3A-008 | Prepare explicit synthetic intake | immutable digest |
| R3A-009 | Execute without exact authority | deferred, no append |
| R3A-010 | Policy/generation/head stale at execute | reject before append |
| R3A-011 | Complete duplicate execute | existing receipt |
| R3A-012 | Partial Phase 3A prefix | recovery_required |
| R3A-013 | Concurrent lease | one winner |
| R3A-014 | Address suspension without accepted builder | typed unsupported; no append |
| R3A-015 | Authority revocation fixture | later execute refused |
| R3A-016 | Public export | deterministic and sanitized |
| R3A-017 | No-send/private/foreign-schema-copy gates | zero forbidden capability/content |
| R3A-018 | Full rehearsal twice | byte-stable execution/report digests |

Every negative family has a positive control and an observed deliberately
injected RED. Acceptance records zero production-root, real-applicant, private,
network, external-send, Fabric-event, and provider effects.

## 17. Packaging and version

- Candidate package target: `0.5.0a1`.
- Promotion to 0.5.0, merge, tag, release, or deployment is outside this scope.
- All R3B-A schemas ship once through the existing schema package wildcard.
- Clean-wheel CLI/Core bytes and schema IDs match source checkout results.
- Python floor remains 3.11.

## 18. SEDB v0.4B archive locator split

Commit `b48f25b` remains useful because it discovers the sibling SEDB archive
from linked worktrees; current main's fallback resolves only the main-checkout
sibling. It is not part of R3B-A semantics.

Disposition:

1. preserve the old Phase 3B branch unchanged as provenance;
2. extract the locator into a separate branch/commit based on current main;
3. reconcile current env fallback with explicit/env/worktree-aware discovery;
4. keep archive absence an explicit skip for archive-dependent tests;
5. do not mix locator review with operations Core review.

R3B-A worktree baselines use explicit `SEDB_V04B_ARCHIVE` until that independent
patch is merged under separate authority.

## 19. Completion criteria

R3B-A is a candidate only when:

1. all pre-existing tests remain green;
2. 18/18 cases and all injected controls pass twice deterministically;
3. direct Core, CLI, clean wheel, Windows, and Ubuntu agree;
4. production-root/private/network/provider/Fabric-effect counters remain zero;
5. existing Phase 3A/P3-4/LIMEN schemas and digests are not forked;
6. the Fabric seam remains pins/references only;
7. branch commits and routine push are complete and worktree is clean;
8. one final necessary cross-seat seam review occurs before J1;
9. no merge or production activation is claimed.

## 20. Later gates

- **J1:** exact cross-repo schema pins and conformance vectors.
- **R3B-B:** versioned extension of the live production root, wrapper-stage
  diagnostics, ACL/checkpoint/head plan, separate Neo.K mutation approval.
- **R3B-C:** exact host-observed applicant, immutable application digest,
  principal authority, retained head, explicit Neo.K approval.
- **F2:** live Fabric realm import/export/notification and any network/provider
  effects under separate authority.
- **B6B/cloud:** private bootstrap and cloud/off-site replication remain separate.
