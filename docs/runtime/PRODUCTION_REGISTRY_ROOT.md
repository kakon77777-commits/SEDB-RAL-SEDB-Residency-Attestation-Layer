# P3-4 Production Public Registry Root

SEDB-RAL 0.4.0 adds the candidate-first lifecycle for the exact public root:

```text
D:\AI_RESIDENCE\REGISTRY\SEDB-RAL
```

This boundary is public registry infrastructure. It is not a resident home,
memory store, applicant package, or private Residence projection. P3-4 creates
no ledger genesis event and no resident, application, address, or authority
event.

## Production acceptance: 2026-08-25

The exact root was initialized from source commit `a7d2bf6` after GitHub Actions
run `32841941812` completed all six Ubuntu/Windows jobs successfully. Final
independent replay verified:

```text
manifest/head-zero valid
ledger events/anchors 0/0
applications/residents/addresses 0/0/0
private/network/external effects 0/0/0
parent/final protected ACL policy match
same-volume checkpoint valid
isolated restore byte-identical
rollback corruption detected
fresh restore byte-identical
production canonical digest unchanged
```

The first PowerShell initializer invocation stopped after candidate preparation
and emitted its typed failure receipt. The candidate remained intact, independently
verified under the same plan/authority, and was published once through the Core
no-replace operation. The first rollback CLI wrapper invocation stopped before a
rollback target existed; the same checkpoint/authority then completed once through
the shared Core. No cleanup or replacement occurred. This wrapper history is part
of the sanitized production receipt rather than being hidden.

See
[`2026-08-25-production.json`](../../evidence/production-registry-root/2026-08-25-production.json)
for the strict digest-bound receipt. It contains no owner SID, SDDL, account name,
temporary path, native task/session identifier, or authority ID.

## Safety model

Initialization requires all of the following before candidate bytes are
written:

- the exact final root is absent;
- the new `REGISTRY` parent and candidate are both ACL-protected;
- the plan binds NTFS volume identity and expected owner SID;
- owner, SYSTEM, and Administrators have FullControl;
- every other write-capable SID is absent;
- the authority binds the same plan digest, exact root, and only the five P3-4
  scopes;
- an explicit temporal receipt is supplied without upgrading a host wall clock
  to CTCL or third-party time.

The ACL policy fingerprint excludes observation path/time but binds owner,
SDDL hash, filesystem/volume, inheritance/reparse state, and the evaluated
permission sets. Therefore an ACL-preserving candidate-to-final rename retains
the same policy fingerprint while both logical paths remain separately checked.

Publication uses an OS no-replace rename. If the destination appears, the
operation stops; it never merges, replaces, adopts, or cleans an existing root.
A failed candidate is retained and the PowerShell adapter emits a sanitized
failure receipt. Cleanup requires separate deletion authority.

## Logical layout

```text
registry-manifest.json
ledger/events/                         empty
ledger/anchors/                        empty
control/heads/00000000000000000000.json
checkpoints/checkpoint-{uuid4}/
rehearsals/restore-{uuid4}/
rehearsals/rollback-{uuid4}/
evidence/
```

Only `ledger/` can hold canonical registry facts. Control heads detect exact
ledger rollback. Checkpoints and rehearsals are copied-value recovery evidence,
not canonical facts.

## Core and CLI

Plan and candidate commands:

```text
sedb-ral registry root-plan ... --expected-owner-sid SID
sedb-ral registry prepare-root PLAN AUTHORITY PARENT_ACL CANDIDATE_ACL
sedb-ral registry verify-root PLAN AUTHORITY PARENT_ACL CANDIDATE_ACL
sedb-ral registry publish-root PLAN VERIFICATION
sedb-ral registry root-status --expected-plan-digest DIGEST
```

Recovery commands:

```text
sedb-ral registry checkpoint-root --root ROOT --checkpoint-id UUID --authority AUTHORITY --time-ref REF
sedb-ral registry rehearse-restore --root ROOT --checkpoint-root CHECKPOINT --rehearsal-id UUID --authority AUTHORITY --time-ref REF
sedb-ral registry rehearse-rollback --root ROOT --checkpoint-root CHECKPOINT --rehearsal-id UUID --authority AUTHORITY --time-ref REF
```

`--synthetic-storage-root` explicitly maps the logical production path into a
temporary test root. It is used by acceptance and Windows ACL integration tests;
omitting it selects the exact production path.

The one-shot Windows adapter composes ACL mutation and the same Core:

```powershell
pwsh -NoProfile -File scripts/Initialize-ProductionRegistry.ps1 `
  -FinalRoot 'D:\AI_RESIDENCE\REGISTRY\SEDB-RAL' `
  -PlanFile '<plan.json>' `
  -AuthorityFile '<authority.json>' `
  -TimeReceiptFile '<time.json>' `
  -OutputDirectory '<new-empty-output-directory>'
```

It never changes the ACL of `D:\AI_RESIDENCE` or any private home, never reads
private Residence content, and contains no cleanup, network, send, deployment,
or resident-registration operation.

## Recovery meaning

The checkpoint copies the manifest, empty ledger directories, head-zero, and
initialization/ACL receipts by value. Links, reparse points, alternate data
streams, output escapes, and hard links are rejected.

Restore targets only `rehearsals/restore-{uuid4}`. Rollback deliberately mutates
an isolated copy, requires `checkpoint_manifest_digest_mismatch`, and then
proves a fresh restore equals the immutable checkpoint. The production source
byte digest must remain unchanged.

All checkpoint material is `same_volume_local`. Passing does not prove off-site
backup, volume-loss recovery, ransomware recovery, administrator-compromise
recovery, or private-memory restoration.

## Synthetic acceptance

```powershell
python -m pytest -q `
  tests/test_registry_root_contracts.py `
  tests/test_registry_root.py `
  tests/test_registry_root_cli.py `
  tests/test_registry_recovery.py `
  tests/test_registry_recovery_cli.py `
  tests/test_registry_acl_script_contract.py `
  tests/test_registry_acl_windows.py `
  tests/test_registry_root_acceptance.py
python scripts/validate_registry_root.py `
  --output registry-root-synthetic.json
```

The report requires P4-001 through P4-016, all eight injected controls, two
identical execution digests, and zero resident/private/network/external effects.
It contains only sanitized digests and relative source metadata. Synthetic
acceptance does not create the production root.

## Separate gates after P3-4

P3-4 does not authorize or imply a resident admission. A real applicant still
requires a host-observed native task binding, applicant-authored opt-in, an
immutable application, explicit approval of its exact digest, sequential ledger
admission, LIMEN public audit, and a separate private B6B opt-in.
