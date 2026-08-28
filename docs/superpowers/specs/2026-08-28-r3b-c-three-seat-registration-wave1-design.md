# SEDB-RAL R3B-C Three-Seat Registration Wave 1 Design

> **Status:** Neo.K approved design direction; implementation not started
>
> **Date:** 2026-08-28
>
> **Scope:** Three public applicants prepared concurrently and admitted
> sequentially into the existing empty production public registry
>
> **Private authority:** none; LIMEN B6B remains disabled

## 1. Goal

Run the first real public-registration test with three exact current AI tasks
without weakening the existing one-applicant, one-head, one-append safety
model.

The wave feels concurrent to the human operator because all three applicants
author their claims and prepare their applications in one coordinated window.
Canonical admission remains sequential:

```text
three applicant-authored claims in parallel
→ three independent host observations
→ three immutable applications
→ Neo.K approves three exact application digests separately
→ admit slot 1 against head H0, read back H1
→ admit slot 2 against H1, read back H2
→ admit slot 3 against H2, read back H3
→ rebuild public projections
→ LIMEN B6A resolves each exact task binding independently
```

No operation is an all-or-nothing three-applicant transaction.

This document supersedes only the earlier Phase 3 first-wave size of two and
the R3B-B wording that described the next gate as one applicant. Each canonical
admission remains one separate R3B-C action with its own exact head, approval,
receipt, and readback. All other Phase 3 and R3B-B safety boundaries remain in
force.

## 2. Why this is a wave, not batch registration

The production registrar and ledger already define one-winner expected-head
serialization. Replacing that with a new atomic batch would enlarge the first
real-data experiment and make one applicant's error affect two unrelated
subjects.

Wave 1 therefore separates two meanings:

```text
coordination concurrency  = claims and preparation may overlap
canonical concurrency     = forbidden; append order is explicit
```

A successful earlier admission remains canonical if a later admission stops.
The wave report must never summarize that state as three registered.

## 3. Applicant slots and ordering

The task-local intake package, stored outside Git, binds three exact
host-observed applicants to these slots:

```text
slot 1  current coordinator/integration seat
slot 2  local context-memory/storage seat
slot 3  registrar/cloud-identity management seat
```

Canonical ordering is slot 1, then slot 2, then slot 3.

The registrar-management seat is last so two non-registrar applicants exercise
the production path before the registrar seat becomes an applicant. The
registrar seat may execute machine steps for its own application only after
Neo.K supplies a separate exact-digest approval; it cannot approve itself.

Concrete labels, native task IDs, turn IDs, application IDs, resident IDs,
addresses, and digests are prohibited from this Git-tracked design. They
belong only in the bounded external intake/evidence package.

## 4. Public-only boundary

All three applicants enter Wave 1 with:

```text
private_b6b_opt_in = false
private_access = false
continuity_merge_authorized = false
resident_merge_authorized = false
additional_address_inference = false
network_send = false
fabric_publish = false
```

The public registration creates no Residence home, private root reference,
memory-body permission, native-memory synchronization, provider session, cloud
replication, or broadcast subscription.

Later private B6B requires a new resident-specific request and approval after
public readback. Public registration never implies that approval.

## 5. Applicant-authored claim phase

Each applicant answers from its own exact current task. A controller or peer
may deliver the prompt but cannot fill, rewrite, or normalize an absent answer.

Each claim follows `sedb-ral.self-application-claim/0.1` and includes:

- desired display label as a claim;
- no existing resident ID unless separately proven;
- `continuity_claim = new | uncertain`; `continue` remains only a claim;
- one desired `codex_thread` address using the host-observed task locator;
- bounded role-description claim;
- dissent/limits;
- `opt_in = true | false`;
- `relay_is_authorship = false`; and
- explicit nonclaims for verified identity, registrar authority, and private
  access.

`opt_in=false`, no canonical applicant item, or ambiguous authorship stops only
that slot before preparation.

## 6. Host-observation phase

The trusted Codex host attaches observation evidence separately from applicant
text. The observation profile is `codex_app_task_tool`:

```text
required     native_thread_id + native_turn_id
unavailable  native_session_id, with structural reason
```

The host observation must reference the exact applicant output item. A task
title, display label, model, project, role, memory file, quoted transcript,
runtime tag, or another task's binding carries zero identity weight.

A stale or cross-task turn, missing item, unresolved current task, or locator
collision stops that slot without affecting the other prepared candidates.

## 7. Preparation and external staging

Application preparation is noncanonical and performs no production ledger
append.

For every slot it:

1. validates the applicant claim and host observation;
2. assigns independent opaque UUID-based application, resident, instance,
   line, claim, and address IDs;
3. binds one exact `codex_thread` address;
4. sets private/B6B fields false;
5. computes the immutable canonical application digest; and
6. writes the package only to an explicit ACL-reviewed staging root outside
   Git and outside every private Residence.

The implementation plan must select and verify the exact staging root before
any real application bytes are written. No default D-drive search, home
discovery, temp fallback, or task-controlled path is allowed.

Re-preparing retained bytes is idempotent. Changed claim/observation bytes
create a superseding candidate and a new digest; they never mutate a prepared
application in place.

## 8. Principal approval gate

Neo.K reviews three complete prepared applications and approves each exact
digest separately.

An approval envelope may present all three digests together for readability,
but it contains three independent approval entries. Approval of one digest
does not authorize either of the other two, a changed locator, private access,
continuity, identity merge, deletion, network, deployment, or retry against a
different application.

No peer relay, remembered approval, model-generated token, or registrar
signature substitutes for principal approval.

## 9. Production policy activation

The current production registrar extension is `active_dormant`: inspect and
status are enabled; intake and execution are disabled.

R3B-C must append a new versioned policy and active-policy receipt before any
production intake or execution. The policy is minimal and time/scope bounded
to Wave 1:

- exactly three approved application digests;
- exactly three host-observed `codex_thread` locators;
- preparation/readback plus one sequential admission per digest;
- no batch append;
- no correction, merge, suspension, private, network, provider, Fabric, MCP,
  cloud, cleanup, or deletion capability;
- explicit expiration or terminal completion after slot 3 or a stopped wave.

Policy activation is an append-only control event, not a ledger identity fact.
If policy activation is missing, stale, mismatched, or unreceipted, every Wave
1 operation refuses.

## 10. Sequential canonical admission

Before slot 1, the registrar verifies:

- production root and extension status;
- exact generation, policy, authority, ACL, checkpoint, and ledger head;
- zero existing applicants/residents/addresses/events unless the approved
  plan explicitly states otherwise; and
- all applicant/approval machine gates.

For each slot:

1. rebuild and validate the full candidate event chain in isolated staging;
2. verify the exact expected external head immediately before append;
3. append the application atomically through the existing registrar Core;
4. obtain the new exact ledger head and commit receipt;
5. rebuild and validate application/resident/instance/address/binding views;
6. verify production counts and zero private/network/external effects; and
7. only then advance to the next slot.

Slot 2 must use slot 1's accepted head. Slot 3 must use slot 2's accepted head.
A stale expected head or concurrent winner stops before append.

## 11. Failure and recovery semantics

The wave is fail-closed but not atomic across applicants.

```text
failure before slot 1 append  -> zero residents
failure after slot 1          -> one resident; slots 2 and 3 pending
failure after slot 2          -> two residents; slot 3 pending
success after slot 3          -> three residents
```

Already accepted facts are never deleted or rolled back to make the wave look
atomic. Correction, withdrawal, address suspension, authority revocation, or
future opt-out uses append-only events under separate authority.

Crash during candidate staging changes no canonical data. Crash after a
successful append is resolved by replay/readback and idempotent commit-receipt
lookup, never by blindly appending the same resident again.

## 12. LIMEN B6A public readback

After every append, LIMEN B6A receives a freshly rebuilt public RAL view and a
fresh host observation for that applicant.

Required results:

- the admitted exact thread resolves to exactly one resident;
- the other two pending threads remain unresolved until their admissions;
- no display-name, model, title, memory, role, or relay evidence is used;
- cross-resolution among the three task locators is rejected;
- resolution evidence and pre-turn enforcement are recorded separately;
- private access remains refused for all three.

The final wave state is not complete until all three individual B6A readbacks
and the combined three-resident collision scan pass.

## 13. Acceptance matrix

| ID | Population | Required result |
|---|---|---|
| W1-001 | three exact applicant-authored claims | three distinct candidate claims |
| W1-002 | one relayed/absent claim | only that slot stops |
| W1-003 | opt-in false | that slot not prepared |
| W1-004 | task/turn/output mismatch | preparation refused |
| W1-005 | three exact distinct thread locators | no address collision |
| W1-006 | duplicate/case-confusable locator | conflicting; no tie-break |
| W1-007 | retained prepare replay | byte/digest identical |
| W1-008 | changed prepared bytes | new digest; old approval insufficient |
| W1-009 | three separate digest approvals | each authority independently valid |
| W1-010 | registrar self-approval | refused |
| W1-011 | missing/unreceipted Wave 1 policy | all execution refused |
| W1-012 | slot 1 against H0 | one append, head H1 |
| W1-013 | slot 2 still using H0 | stale-head refusal, no append |
| W1-014 | slot 2 against H1 | one append, head H2 |
| W1-015 | slot 3 against H2 | one append, head H3 |
| W1-016 | repeated admitted application | existing receipt; no duplicate resident |
| W1-017 | injected crash before append | canonical bytes unchanged |
| W1-018 | injected crash after append | replay finds existing receipt |
| W1-019 | B6A after slot 1 | slot 1 resolved; slots 2/3 unresolved |
| W1-020 | B6A after slot 2 | slots 1/2 resolved; slot 3 unresolved |
| W1-021 | B6A after slot 3 | three exact independent resolutions |
| W1-022 | cross-resident/task resolution | refused/conflicting |
| W1-023 | private request after public admission | refused; B6B false |
| W1-024 | production/effect counters | exactly three app/resident/address chains; private/network/external zero |
| W1-025 | recovery checkpoint/readback | exact final head and projection reproducible |
| W1-026 | repeated full synthetic wave | deterministic except explicit opaque IDs supplied as fixtures |

Every negative population has an executed positive control that proves the
named gate rather than a dead runtime.

## 14. Evidence package

Wave 1 records:

- source commit/tree, package version, branch and dirty state;
- production root, manifest, registry generation, extension index, policy,
  authority, ACL and checkpoint digests;
- applicant item and host-observation refs;
- three application digests and three principal approval refs;
- per-slot expected/pre/post ledger heads and commit receipts;
- per-slot application/resident/instance/address/binding projection digests;
- per-slot LIMEN B6A resolution and enforcement states;
- all W1 case results and injected controls;
- production count and effect deltas;
- no-private/no-network/no-secret scans;
- restore/rollback evidence; and
- explicit nonclaims.

The durable public report must sanitize native task/turn IDs, principal IDs,
ACL/SID data, staging paths, and applicant content. Exact values remain in the
bounded task-local evidence package.

## 15. Stop boundaries

This design authorizes no implementation or production action by itself.

Neo.K's written approval of this exact specification authorizes collection of
the three bounded applicant-authored claims only. Claim collection performs no
application preparation, policy activation, authority grant, or ledger write.

Separate Neo.K gates remain required for:

1. the implementation plan;
2. creation of real external staging paths;
3. approval of each immutable application digest;
4. Wave 1 policy activation;
5. each of the three canonical admissions;
6. any correction/revocation;
7. any private B6B action; and
8. push, PR, merge, release, deployment, network, cloud, or broadcast.

## 16. Success definition

Wave 1 succeeds only when:

```text
three applicants authored bounded opt-in claims
→ three exact host observations were attached independently
→ Neo.K approved three exact immutable digests
→ three sequential one-winner appends produced H1, H2, H3
→ production projections rebuilt without collision
→ LIMEN B6A independently resolved all three exact task bindings
→ private/network/external effects remained zero
```

A shared label, simultaneous prompt, three prepared files, or one summary
report is never sufficient evidence that three residents were registered.
