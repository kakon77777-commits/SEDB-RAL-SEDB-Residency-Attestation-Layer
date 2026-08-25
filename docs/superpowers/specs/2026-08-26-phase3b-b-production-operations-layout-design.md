# SEDB-RAL Phase 3B-B Production Operations Layout Design

Date: 2026-08-26

Status: approved approach A; written design awaiting final document review

## 1. Goal

Activate a versioned, dormant registrar-operations extension inside the accepted
production public registry:

```text
D:\AI_RESIDENCE\REGISTRY\SEDB-RAL\extensions\
```

The extension makes the R3B-A operations contracts and durable workspace layout
available for a later, separately gated real applicant. R3B-B itself registers
no resident, accepts no real intake, appends no ledger event, reads no private
Residence data, and performs no network, provider, Fabric, MCP, or cloud action.

R3B-B is complete only when the exact live root has a verified versioned
extension, a retained pre-activation checkpoint, a retained post-activation
checkpoint, a byte-identical isolated restore, a rollback red control, and zero
resident/private/external effects.

## 2. Accepted baseline

The source baseline is `main@2470be770962556998925a739c3d1099dc830786`,
which merged R3B-A exact candidate
`2cb07f8408c6523c32d5a2dd915a21c0febc14f2` through PR #4.

The live root already contains:

- immutable `registry-manifest.json` from source commit `a7d2bf6`;
- immutable head-zero `control/heads/00000000000000000000.json`;
- empty canonical `ledger/events` and `ledger/anchors`;
- protected parent and root ACLs;
- same-volume checkpoints and isolated recovery rehearsals;
- zero residents, applications, addresses, private reads, network effects, and
  external effects.

The branch baseline passes `696` tests with `4` environment/legacy-evidence
skips when `SEDB_V04B_ARCHIVE` is explicitly pinned.

## 3. Non-negotiable ownership boundary

```text
ledger/                         canonical public resident/address/authority facts
registry-manifest.json          immutable P3-4 root identity
control/heads/                  immutable canonical-ledger head receipts
extensions/                     non-canonical operational control plane
checkpoints/                    recoverable byte snapshots, never facts
rehearsals/                     isolated evidence, never production
AI_HOME                         private resident content, never inspected here
```

The following existing bytes are never overwritten, renamed, or regenerated:

- `registry-manifest.json`;
- `control/heads/00000000000000000000.json`;
- every existing checkpoint, rehearsal, and evidence receipt;
- every file under `ledger/`.

An operations receipt cannot create a resident fact. Only the existing
SEDB-RAL registrar append path may change the canonical ledger, and that path is
not enabled by R3B-B.

## 4. Chosen layout

The first activation publishes this complete tree in one same-volume atomic
directory move:

```text
extensions\
  index\
    00000000000000000000.json
  registrar-operations\
    v1\
      EXTENSION-MANIFEST.json
      ACTIVATION-COMMIT.json
      policies\
        policy-{digest-prefix}.json
      active-policy\
        00000000000000000000.json
      inbox\
      requests\
      receipts\
      audit\
      leases\
      projections\
        public\
      staging\
```

The candidate is built outside the live root at an opaque, exact sibling path:

```text
D:\AI_RESIDENCE\REGISTRY\.SEDB-RAL.operations-{uuid4}\extensions\
```

The final publication operation is an atomic, no-replace move of the candidate
`extensions` directory to the live root. The live root therefore observes one
of two semantic states:

- no `extensions` directory; or
- the complete, digest-verified v1 extension.

A pre-existing final `extensions` path, destination race, partial candidate,
cross-volume candidate, reparse point, hard link, alternate stream, case-fold
collision, or ACL mismatch refuses activation before publication.

## 5. Why the base manifest remains v0.1

Changing the P3-4 manifest would invalidate the accepted byte identity and its
checkpoint/recovery evidence. R3B-B therefore adds an append-only extension
index rather than changing the base manifest.

The first extension-index record binds:

- base registry ID, manifest digest, head control digest, and base tree digest;
- extension kind `registrar-operations`;
- extension version `v1`;
- extension manifest digest and activation commit digest;
- operations generation;
- dormant policy digest and policy activation digest;
- source commit and package version;
- pre-activation checkpoint digest;
- exact activation time evidence status;
- `previous_index_digest = null`;
- explicit non-claims.

Later extensions or versions append the next numbered index record. Existing
index records are never edited, and sequence gaps fail closed.

## 6. Status and digest compatibility

`registry_root_status()` becomes version-aware without changing its existing
meaning:

- `manifest_digest`, `control_digest`, and `tree_digest` continue to describe
  the accepted P3-4 base;
- existing counters retain their current meanings;
- new optional fields report `extensions_status`, `extension_index_digest`,
  `operations_generation`, `activation_receipt_status`, and
  `registry_generation_digest`;
- an absent extension returns `extensions_status = absent`;
- a complete verified extension with its exact host-observed receipt returns
  `extensions_status = active_dormant`;
- a complete moved extension whose receipt is missing or mismatched returns
  `extensions_status = active_dormant_unreceipted` and refuses every operation;
- any present but incomplete or mismatched extension raises a typed error and
  never degrades to `absent`.

`registry_generation_digest` domain-separates and binds the immutable base
status plus the latest extension-index digest. It is not a ledger head and
cannot be used as resident or authority evidence.

R3B-A synthetic functions remain unchanged and continue to reject the
production path. R3B-B introduces separate production-extension contracts and
functions; it does not loosen `synthetic_only`, `production_activation=false`,
or the R3B-A path guard.

## 7. Contracts

R3B-B adds strict, `additionalProperties=false` schemas for:

1. `sedb-ral.production-operations-extension-plan/0.1`
2. `sedb-ral.production-operations-extension-authority/0.1`
3. `sedb-ral.production-operations-extension-manifest/0.1`
4. `sedb-ral.production-operations-activation-commit/0.1`
5. `sedb-ral.production-operations-activation-receipt/0.1`
6. `sedb-ral.registry-extension-index/0.1`
7. `sedb-ral.production-operations-acceptance/0.1`

Every document uses canonical UTF-8 bytes and a domain-separated
`sha256:sedb-ral-json-nfc-codepoint-v1:` digest.

The plan binds the exact target, source commit/package version, registry status,
candidate ID, operations generation, dormant policy, filesystem/volume, owner
SID, ACL fingerprint, time reference, and pre-activation checkpoint.

The authority artifact permits only:

```text
registry.operations-extension.activate
```

It binds the exact plan digest and target. It grants no applicant approval,
registrar decision, resident admission, ledger append, private access,
federation, release, deployment, deletion, or rollback authority.

The digest dependency is acyclic: policy and manifest are bound first; the
activation commit binds them and the plan/authority; the extension index binds
the activation commit; the post-move receipt binds the observed final index and
tree. No candidate document claims that the move has already happened.

## 8. Dormant production policy

The initial production policy is deliberately narrower than the synthetic
R3B-A policy:

- `inspect` and `status` are enabled;
- intake submission and all mutating operations are disabled;
- no operation request may be executed;
- no real applicant artifact may be stored;
- no lease may grant registrar execution authority;
- public export reads remain disabled until a canonical ledger exists;
- private, network, provider, Fabric, MCP, scheduler, delete, and restore
  capabilities remain false.

R3B-C must append a new policy and a new active-policy receipt before one exact
host-bound applicant can be prepared. It may not edit the dormant policy.

## 9. Candidate-first activation flow

The production action follows this exact order:

1. Verify source checkout, package, CI, and acceptance report.
2. Verify the exact live base root and protected ACLs.
3. Prove ledger head-zero and zero residents/applications/addresses.
4. Create and verify a retained pre-activation checkpoint.
5. Bind the exact plan and authority artifacts.
6. Create the opaque same-volume candidate root with protected ACLs.
7. Build the complete `extensions` candidate with create-only writes.
8. Verify contracts, byte map, links/streams/case folding, ACLs, and digests.
9. Re-read the live base status and refuse if any bound value changed.
10. Atomically move candidate `extensions` to live `extensions`, without
    replacement.
11. Verify the live base and extension independently.
12. Create a host-observed activation receipt at
    `evidence/operations-extension-activation-{uuid4}.json`; this receipt is
    evidence of the completed move and is not required to make the move atomic.
13. Create and verify a retained post-activation checkpoint.
14. Restore that checkpoint into a fresh isolated rehearsal root.
15. Run a rollback red control against a disposable copy, then restore a fresh
    byte-identical copy.
16. Write a sanitized acceptance receipt outside canonical ledger facts.

No step may delete or replace the accepted live root. A failure before the
atomic move leaves production unchanged. A failure after the move retains the
published bytes, fails closed, and requires exact-status recovery; it never
silently retries with a new plan or authority digest.

## 10. ACL and filesystem rules

- Final target and candidate must be on the approved NTFS volume.
- Candidate and final extension must not be reparse points.
- Files must have link count one and no alternate streams.
- The candidate ACL must be protected before content creation.
- Effective access must remain limited to the accepted owner,
  Administrators, and SYSTEM; inherited broad Modify/DeleteChild grants fail.
- No ACL on `D:\AI_RESIDENCE` or `D:\AI_RESIDENCE\AI_HOME` is changed.
- Only the exact candidate and final extension paths are mutable by the
  activation script.

## 11. Recovery model

Pre- and post-activation checkpoints are retained by value and have independent
manifests. They are same-volume recovery evidence, not off-site backup.

Restore and rollback rehearsal targets are always isolated. A rehearsal never
targets the live root or live extension. Corruption, missing extension files,
index gaps, digest disagreement, or ACL disagreement produces typed refusal.

No automated rollback deletes a live extension. If the atomic publication has
occurred and final verification fails, the state is retained for diagnosis and
requires a separately reviewed recovery action.

## 12. CLI and Windows action surface

Provider-free CLI commands are added under `sedb-ral registry`:

```text
operations-extension-plan
operations-extension-prepare
operations-extension-status
operations-extension-acceptance
```

The plan, prepare, status, and synthetic acceptance commands never activate the
live path. The actual atomic move is performed only by a Windows action script
that requires explicit plan, authority, expected source commit, and expected
acceptance digest arguments.

No MCP tool, HTTP listener, background service, Board action, Bridge action,
Wake action, provider adapter, or scheduled task is added in R3B-B.

## 13. Acceptance matrix

The deterministic synthetic gate contains at least these cases:

| ID | Case | Required result |
|---|---|---|
| R3B-001 | exact base and candidate | active_dormant |
| R3B-002 | target differs | refuse before candidate |
| R3B-003 | base manifest/control/tree changed | exact typed refusal |
| R3B-004 | non-zero ledger/resident/application/address | refuse |
| R3B-005 | candidate is cross-volume | refuse |
| R3B-006 | candidate/final reparse point | refuse |
| R3B-007 | hard link/ADS/case-fold collision | refuse |
| R3B-008 | inherited broad ACL | refuse |
| R3B-009 | plan or authority digest mismatch | refuse |
| R3B-010 | destination race/existing extensions | no overwrite |
| R3B-011 | missing extension/index/commit/policy byte | fail closed |
| R3B-012 | missing or mismatched post-move receipt | active_dormant_unreceipted; operations refused |
| R3B-013 | index gap or wrong previous digest | fail closed |
| R3B-014 | synthetic R3B-A targets production | still refused |
| R3B-015 | dormant policy receives intake/execute | no append/no store |
| R3B-016 | pre/post checkpoint and fresh restore | byte-identical |
| R3B-017 | rollback corruption red control | detected; live unchanged |
| R3B-018 | repeat activation | idempotent refusal; bytes unchanged |
| R3B-019 | private/network/provider/Fabric/MCP capability scan | zero |
| R3B-020 | package/wheel/installed CLI parity | equal |
| R3B-021 | sanitized receipt scan | no private/secret/native identity leak |

The gate runs twice and requires identical report digests. Each mutation or
injected control must turn its named case red without changing production.

## 14. CI, packaging, and version

- Package candidate version: `0.5.0b1`.
- Windows and Ubuntu run all contract, model, synthetic layout, recovery,
  acceptance, packaging, and no-effect tests.
- Windows additionally runs ACL behavior tests when privileges permit.
- CI never references or mutates the live `D:\AI_RESIDENCE` tree.
- Clean wheel and source-checkout CLIs must produce equivalent synthetic
  acceptance digests.
- The existing explicit `SEDB_V04B_ARCHIVE` locator boundary remains unchanged
  unless its independent patch is separately adopted.

## 15. Production action gate

Neo.K approved approach A and authorized a recoverable R3B-B extension action at
the exact production root after complete tests and CI. That authority applies
only if the implemented target, layout, non-claims, source commit, plan digest,
acceptance digest, and checkpoint sequence match this design.

Any target change, base-byte change, manifest replacement, non-empty ledger,
real applicant content, private access, network/provider effect, or recovery
deletion requires new action-time approval.

## 16. Explicit exclusions

R3B-B does not:

- register or resolve a real resident;
- prepare, approve, reject, withdraw, suspend, revoke, or correct a real
  application;
- append any canonical ledger event;
- activate registrar execution authority;
- load private Residence memory or create a home address;
- change a task-local speaker binding;
- emit or import Fabric events;
- enable LIMEN B6B;
- create cloud or off-site backups;
- merge identity or continuity claims;
- release, deploy, publish a package, or modify secrets.

## 17. Completion boundary and next phase

R3B-B is complete when source, local acceptance, wheel parity, Windows/Ubuntu
CI, exact production preflight, atomic activation, post-activation status,
checkpoint, isolated restore, rollback control, sanitized receipt, and clean Git
state all agree.

Only then may R3B-C begin for one exact host-observed applicant:

```text
task-local binding
→ bounded self-claim
→ host observation
→ immutable application digest
→ exact principal approval
→ one-winner registrar append
→ public RAL projection
→ LIMEN B6A readback
```

R3B-C and any later batch re-declaration remain separate evidence-bearing
actions. A familiar name, model output, task title, or prior memory is never
sufficient registration evidence.
