# SEDB-RAL P3-4 Production Public Registry Root Design

Date: 2026-08-25

Status: approved; implementation plan written and authorized for execution

## 1. Goal

Create and verify an empty production **public registry** root at:

```text
D:\AI_RESIDENCE\REGISTRY\SEDB-RAL\
```

The root will hold canonical SEDB-RAL ledger/control/checkpoint material. It is
a sibling boundary to private AI Residence content, not part of any resident's
memory.

This phase proves storage ownership, ACLs, manifest integrity, external-head
handling, checkpoint creation, isolated restore, and rollback rehearsal before
the first real application is prepared or admitted.

## 2. Current measured state

Read-only preflight on 2026-08-25 observed:

```text
D:\AI_RESIDENCE\AI_HOME                    exists
D:\AI_RESIDENCE\REGISTRY                   absent
D:\AI_RESIDENCE\REGISTRY\SEDB-RAL          absent
D: filesystem                               NTFS
D: health                                   Healthy / OK
D:\AI_RESIDENCE owner                       current interactive account
```

The parent `D:\AI_RESIDENCE` ACL currently includes:

```text
Administrators       FullControl
SYSTEM               FullControl
Authenticated Users  Modify
Users                ReadAndExecute
```

The production registry must not inherit the broad `Authenticated Users:
Modify` permission unchanged.

Both SEDB-RAL and LIMEN source checkouts were clean and synchronized before
this design was written. Existing registry/application evidence is synthetic;
there is no production resident ledger to migrate.

## 3. Authorization captured

Neo.K explicitly authorized creation and testing of the production public
registry root after being shown the exact path and the following boundary:

- create an empty public registry;
- review and constrain ACLs;
- create manifest, retained-head, checkpoint, restore, and rollback evidence;
- do not register a resident;
- do not read private `AI_HOME` content;
- do not infer a current resident identity;
- do not begin B6B private bootstrap.

This authorization does not cover deletion, replacement of an existing root,
real applicant admission, private access, publication, release, or deployment.

## 4. Non-goals

P3-4 does not:

- prepare or submit a real self-application;
- choose the first resident;
- approve an application digest;
- append `authority.granted`, `application.*`, or `resident.registered` events;
- copy names, native task IDs, or applicant packages into Git;
- open, enumerate, hash, or back up `D:\AI_RESIDENCE\AI_HOME`;
- create a private-memory index or production private database;
- claim an on-disk checkpoint is an off-site backup;
- alter Codex, Claude, MCP, Bridge, Wake, browser, login, or AppData state;
- enable HTTP/network listeners, publication, release, or deployment.

## 5. Ownership and canonicality

```text
SEDB-RAL ledger files       canonical public resident/address/authority facts
SEDB-RAL control receipts  retained external-head and root-governance evidence
SEDB-RAL checkpoints       recoverable byte snapshots; not canonical facts
SEDB-RAL rehearsals        disposable/retained test copies; never production
AI Residence               canonical private resident content; never copied here
Git checkout               code, schemas, synthetic fixtures, sanitized evidence
```

The canonical ledger is only the `ledger/` subtree. Control, checkpoint,
rehearsal, and evidence files cannot create or mutate resident facts.

## 6. Directory layout

The published root has this exact top-level layout:

```text
D:\AI_RESIDENCE\REGISTRY\SEDB-RAL\
  registry-manifest.json
  ledger\
    events\
    anchors\
  control\
    heads\
      00000000000000000000.json
  checkpoints\
    checkpoint-{uuid4}\
      CHECKPOINT.json
      MANIFEST.sha256
      snapshot\
  rehearsals\
    restore-{uuid4}\
      RESTORE-RECEIPT.json
      restored\
  evidence\
    initialization-receipt.json
    acl-receipt.json
    checkpoint-receipt.json
    restore-rehearsal-receipt.json
    rollback-rehearsal-receipt.json
```

Opaque IDs are UUID-based and never contain resident names, task titles,
native identifiers, private paths, model labels, or roles.

`events/` and `anchors/` exist but are empty after initialization. Creating
the root does not create a ledger genesis event.

## 7. ACL design

The newly created `D:\AI_RESIDENCE\REGISTRY` parent and the candidate root are
both created with protected ACL inheritance before any manifest or control
record is published. Protecting only the child is insufficient because a broad
parent `DeleteChild` grant could still remove or rename it.

Required effective access:

```text
configured registry owner SID FullControl  container + children
NT AUTHORITY\SYSTEM    FullControl  container + children
BUILTIN\Administrators FullControl  container + children
```

Forbidden effective write access:

```text
NT AUTHORITY\Authenticated Users  Modify/Write/Create/Delete
BUILTIN\Users                     Modify/Write/Create/Delete
Everyone                          any write permission
```

No deny ACE is introduced unless required to neutralize an inherited allow;
the preferred design disables inheritance, copies only reviewed administrative
entries, removes broad write grants, and then verifies effective permissions.

The ACL receipt records:

- normalized resolved root path;
- owner SID/name;
- SDDL and SHA-256 fingerprint;
- filesystem and volume identity;
- required/forbidden principal evaluation;
- reparse-point result;
- check time reference;
- `not_claimed: offsite_backup, private_confidentiality, multi_host_security`.

ACL changes are limited to the newly created `REGISTRY` parent and its
candidate/public registry tree. No ACL on `D:\AI_RESIDENCE` or `AI_HOME` is
changed.

## 8. Candidate-first publication

Initialization never writes directly into a pre-existing final root.

Sequence:

1. Resolve the exact final path and confirm it is absent.
2. Confirm `REGISTRY` is absent, create it, immediately apply its protected
   ACL, and verify that broad parent write/delete-child grants are absent.
3. Create a sibling candidate named `.SEDB-RAL.init-{uuid4}` inside the
   protected `REGISTRY` parent.
4. Apply and verify the protected ACL on the candidate.
5. Create the exact layout, manifest, head-zero receipt, and initialization
   evidence inside the candidate.
6. Reject any reparse point, alternate data stream, device path, UNC path,
   case-fold collision, unexpected file, or private marker.
7. Independently re-read and verify every byte and digest.
8. Publish by a same-volume no-replace rename to `SEDB-RAL`.
9. Re-open the final path, verify identity/ACL/manifest/digests, and emit the
   final publication receipt to the caller without another root mutation.

If the final path appears at any point, initialization fails closed. It never
merges, replaces, cleans, or adopts an unknown existing directory.

If candidate publication fails, the candidate is retained with a typed failure
receipt. Recursive cleanup requires separate explicit deletion authorization.

## 9. Registry manifest

`registry-manifest.json` uses schema
`sedb-ral.production-registry-manifest/0.1` and exact fields:

```text
schema
registry_id
root_kind: public_registry
canonical_ledger_ref: ledger
control_heads_ref: control/heads
checkpoints_ref: checkpoints
rehearsals_ref: rehearsals
evidence_ref: evidence
source_package_name: sedb-ral
source_package_version
source_commit
canonicalization_version
chain_version
filesystem
volume_identity
acl_fingerprint
initialized_time_ref
initial_control_ref
not_claimed
manifest_digest
```

`manifest_digest` binds canonical manifest material excluding itself. The
manifest contains no resident, address, task, session, applicant, principal,
private root, credential, or secret.

`initialized_time_ref` must be supplied by an explicit temporal receipt. A
wall-clock string is not upgraded to CTCL/third-party time evidence.

## 10. Retained external head

The ledger verifier calls a non-empty ledger verified only when the caller
supplies the exact externally retained head.

P3-4 creates immutable head-zero receipt:

```text
control/heads/00000000000000000000.json
```

Schema `sedb-ral.registry-head-receipt/0.1` fields:

```text
schema
registry_id
control_sequence: 0
ledger_event_count: 0
ledger_head: null
last_event_id: null
manifest_digest
previous_control_digest: null
recorded_time_ref
not_claimed
control_digest
```

Future head receipts are append-only immutable files with increasing control
sequence and `previous_control_digest`. P3-4 creates only sequence zero.

The control head is external to the canonical `ledger/` subtree, which detects
paired ledger-tail rollback when an exact head is retained. Because it remains
on the same physical volume/root family, this design does not claim off-site
retention or disaster recovery.

## 11. Checkpoint format

An initialization checkpoint is created only after final root verification.

`MANIFEST.sha256` lists exact relative paths and raw SHA-256 values for:

- `registry-manifest.json`;
- `ledger/events/` empty-directory marker in checkpoint metadata;
- `ledger/anchors/` empty-directory marker in checkpoint metadata;
- `control/heads/00000000000000000000.json`;
- initialization and ACL receipts required by the checkpoint policy.

`CHECKPOINT.json` uses schema `sedb-ral.registry-checkpoint/0.1` and records:

```text
checkpoint_id
registry_id
source_root_digest
source_control_digest
source_ledger_head: null
source_event_count: 0
manifest_sha256
snapshot_root: snapshot
created_time_ref
storage_scope: same_volume_local
not_claimed
checkpoint_digest
```

Files are copied by value into a new create-only checkpoint directory. Hard
links, junctions, symlinks, mount points, and other reparse points are refused.

## 12. Isolated restore rehearsal

Restore never targets the production `ledger/` or root.

Sequence:

1. Create `rehearsals/restore-{uuid4}/restored` with create-only semantics.
2. Copy checkpoint snapshot bytes into that isolated target.
3. Validate paths before and after each copy.
4. Recompute the checkpoint manifest and checkpoint digest.
5. Verify the restored registry manifest and head-zero control receipt.
6. Verify the restored ledger is empty and contains no event/anchor files.
7. Compare the source/snapshot/restored byte maps exactly.
8. Write immutable `RESTORE-RECEIPT.json` and public evidence receipt.

The rehearsal directory is excluded from canonical ledger and checkpoint
source material. It is retained for review; deletion is not part of P3-4.

## 13. Rollback rehearsal

Rollback is demonstrated only inside a second isolated rehearsal copy:

1. Copy the verified restored tree into a new rehearsal candidate.
2. Inject one synthetic noncanonical marker in the rehearsal copy.
3. Prove manifest verification turns red with
   `checkpoint_manifest_digest_mismatch`.
4. Create a separate fresh restore target from the immutable checkpoint.
5. Prove the fresh target returns to the exact checkpoint byte map.
6. Record before-corruption, red-control, and restored digests.

No production byte is changed during rollback rehearsal. Passing rollback
means the local checkpoint is internally usable; it does not prove recovery
from volume loss, ransomware, administrator compromise, or off-site disaster.

## 14. CLI/Core boundary

The implementation will expose one shared Core through CLI commands:

```text
sedb-ral registry init-root
sedb-ral registry root-status
sedb-ral registry checkpoint-root
sedb-ral registry rehearse-restore
sedb-ral registry rehearse-rollback
```

All mutating commands require:

- the exact configured root;
- an expected absence/head/control digest;
- explicit temporal receipt;
- create-new output semantics;
- exact operation name;
- authority artifact scoped to P3-4 root initialization/recovery rehearsal.

The direct Core and CLI must produce canonical-byte-equivalent receipts. CLI
errors omit private paths, credentials, stacks, and unrelated directory
contents.

No MCP registrar mutation is enabled by this phase. A future local MCP wrapper
may expose the same Core only after CLI/Core acceptance and a separate config
gate.

## 15. Authority model

The direct user authorization in this task is recorded as a candidate for
these exact operation scopes:

```text
registry.root.initialize
registry.root.inspect_acl
registry.root.checkpoint
registry.root.rehearse_restore
registry.root.rehearse_rollback
```

It does not authorize:

```text
registry.application.accept
registry.resident.register
registry.address.bind
registry.root.delete
private.bootstrap
private.recall
memory.write
external.send
publish
release
deploy
```

The implementation plan must define a host-authenticated authority artifact or
equivalent action-time confirmation bound to the exact root/candidate plan
digest before external writes begin.

## 16. Acceptance matrix

| ID | Case | Expected |
|---|---|---|
| P4-001 | Final root already exists | refuse; no merge/replace |
| P4-002 | Exact root absent on expected NTFS volume | candidate may start |
| P4-003 | Candidate inherits broad write ACL | fail before publication |
| P4-004 | Protected parent and candidate ACL | required principals pass; broad writes/delete-child absent |
| P4-005 | Candidate contains reparse point/ADS/device/UNC escape | refuse |
| P4-006 | Strict manifest and head-zero receipt | canonical digests valid |
| P4-007 | Empty production publish | exact layout; zero residents/events |
| P4-008 | Repeated init | refuse existing root; original bytes unchanged |
| P4-009 | Checkpoint create | create-only same-volume snapshot and manifest |
| P4-010 | Checkpoint byte mutation | manifest verification red |
| P4-011 | Isolated restore | byte-identical restored tree |
| P4-012 | Restore target escapes rehearsal root | refuse before write |
| P4-013 | Rollback red control | corruption detected, fresh restore exact |
| P4-014 | Git/private/secret scan | zero production/private content in repo evidence |
| P4-015 | Side-effect accounting | zero resident/private/network/external effects |
| P4-016 | Same inputs/plan digest | deterministic candidate/evidence digests |

Critical injected controls:

```text
broad-acl-write
reparse-path-escape
manifest-byte-mutation
external-head-mismatch
restore-target-escape
rollback-corruption
resident-event-in-empty-root
private-marker-in-evidence
```

## 17. Evidence package

Every run records:

```text
source commit and candidate tree digest
exact normalized root/candidate paths
volume/filesystem/health evidence
owner/ACL SDDL and fingerprint
authority/plan digest
manifest/control/checkpoint/restore/rollback digests
selected test IDs and injected controls
pre/post exact path existence and byte maps
ledger event/resident/application/address counts
network/private/registry-resident/external counters
secret/private/reparse scan
same-volume-local limitation
not_claimed
```

Public Git evidence contains sanitized relative references and digests. It does
not contain a full ACL account inventory beyond the approved local owner and
standard system/administrator principals, private content, credentials,
resident names, native IDs, or absolute private paths.

## 18. Failure and recovery rules

- Existing final root: stop and request review.
- ACL verification failure: retain unpublished candidate; no final root.
- Manifest/control mismatch: retain candidate/checkpoint; no adoption.
- Publication uncertainty: inspect exact final/candidate paths and digests;
  never retry as a new initialization until classified.
- Partial checkpoint: mark invalid; never restore from it.
- Restore mismatch: retain evidence; production remains untouched.
- Rollback red control fails to turn red: phase fails.
- Cleanup request: requires a separately named target and explicit deletion
  authorization.

No mtime, directory order, familiar name, or model judgment resolves a
conflict.

## 19. Rollout sequence after P3-4

```text
P3-4 empty production registry + recovery proof
→ select one exact native applicant task
→ applicant-authored self-application and opt-in
→ prepare immutable application outside Git
→ Neo.K reviews and approves exact digest
→ sequential canonical admission with retained head
→ public LIMEN B6A resolution audit
→ resident-specific B6B private opt-in
```

Each arrow is a separate authority gate. P3-4 completion cannot be cited as
resident admission or private opt-in.

## 20. Success definition

P3-4 succeeds only when evidence proves:

```text
the exact public root was absent
→ a protected candidate was built and verified
→ no-replace publication produced the exact empty root
→ manifest and external head-zero receipt verify
→ same-volume checkpoint bytes verify
→ isolated restore is byte-identical
→ injected rollback corruption turns red
→ a fresh restore returns to the exact checkpoint
→ zero resident/private/network/external side effects occurred
```

It does not succeed merely because directories were created or a CLI returned
zero.
