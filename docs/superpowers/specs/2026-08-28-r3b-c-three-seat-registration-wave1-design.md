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

### 3.1 Equal standing and non-hierarchy

Slot number, preparation completion time, application ID, ledger sequence,
admission head, and readback completion time are operational ordering evidence
only. They never create or imply:

- historical superiority or priority of existence;
- rank, seniority, prestige, ownership, governance weight, or voting weight;
- broader authority, continuity, memory access, compute priority, budget, or
  future employment/contract preference; or
- a right to merge, rename, suspend, represent, or decide for another resident.

All three successfully admitted residents have equal public registration
standing under the same policy. Projection and LIMEN consumers may use sequence
numbers to replay and audit the ledger, but must not expose a derived resident
rank or use admission order as an authorization input. Any later contract,
governance, compensation, scheduling, or resource relationship requires its
own explicit evidence and cannot cite Wave 1 order as sufficient authority.

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
- `existing_resident_claim = null`;
- `continuity_claim = new | uncertain`;
- one desired `codex_thread` address using the host-observed task locator;
- bounded role-description claim;
- dissent/limits;
- `opt_in = true | false`;
- `relay_is_authorship = false`; and
- explicit nonclaims for verified identity, registrar authority, and private
  access.

The installed generic claim schema also recognizes `continue`, but Wave 1 does
not. `continue`, a non-null existing-resident claim, or any resident/lineage
reference stops that candidate before preparation with
`continuity_evidence_required`. It is never silently converted into a new
resident. Separate lineage/resident evidence and merge authority are required
under a superseding design.

Before policy activation and slot 1, `opt_in=false`, no canonical applicant
item, ambiguous authorship, or any failed slot stops this exact three-seat wave
with zero canonical append. Other valid claims may remain noncanonical and may
be proposed later only through a separately approved superseding wave; this
Wave 1 policy never degrades to two applicants. After a successful canonical
append, any later failure retains earlier residents and stops all pending
slots.

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
collision marks that slot failed. Before slot 1 this stops the exact three-seat
wave with zero append; after an earlier canonical admission it stops every
pending slot while preserving admitted residents.

### 6.1 Applicant item evidence and claim-time observation

Wave 1 introduces a closed `registration-applicant-item-evidence/0.1`:

```text
item_evidence_id
provider
adapter_kind
native_thread_id
native_turn_id
applicant_item_ref
canonical_claim_digest
raw_item_evidence_digest
capture_status = host_observed
observed_origin
observed_at_ref
unavailable_fields
not_claimed
item_evidence_digest
```

`raw_item_evidence_digest` binds the host-retained exact output item evidence;
raw item bytes stay in the bounded host evidence source and are not copied into
Git or the public registry.

The existing `registration-host-observation/0.1` is not silently relaxed.
Wave 1 uses `registration-host-observation/0.2`, which retains all v0.1 fields
and additionally requires:

```text
applicant_item_evidence_ref
applicant_item_evidence_digest
canonical_claim_digest
```

Preparation verifies exact equality across the canonical claim digest, item
evidence, host observation, native thread, native turn and applicant item ref.
An unrelated nonempty turn/item ref, a changed claim with retained item
evidence, or item evidence from another task refuses before ID assignment.

### 6.2 Canonical `codex_thread` locator grammar

Wave 1 accepts only the host-observed canonical lowercase UUID text form:

```text
^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$
```

The parser rejects uppercase hex, braces, whitespace, Unicode hyphens, URI or
path prefixes, short forms, and any normalized substitute. It never casefolds a
locator into another identity. Exact canonical duplicates enter the existing
address-collision gate; noncanonical or confusable text is invalid before
collision evaluation.

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

### 8.1 Principal application approval

Each application uses a closed `principal-application-approval/0.1` artifact:

```text
approval_id
principal_ref
application_ref
application_digest
source_user_item_ref
source_user_item_digest
host_observation_ref
host_observation_digest
approved_scopes = [registration.application.approve]
valid_from_ref
expires_at_ref | null
status = active | revoked | expired | suspended
revoked_by_ref | null
not_claimed
approval_digest
```

The verifier requires host-observed `role=user` and the exact principal item
bytes/digest. Assistant output, registrar output, relay text, remembered
approval, or a model-generated principal token cannot be verified approval.
The artifact approves only the immutable application digest.

### 8.2 Just-in-time slot execution authorization

Canonical append requires a separate
`registration-slot-execution-authorization/0.1` artifact created after the
current pre-head/checkpoint is known:

```text
execution_authorization_id
principal_ref
wave_plan_ref + wave_plan_digest
slot_id + slot_index
operation_request_ref + operation_request_digest
application_approval_ref + application_approval_digest
policy_ref + policy_digest
checkpoint_ref + checkpoint_digest
expected_ledger_head
registry_control_digest
valid_from_ref + expires_at_ref
status + revoked_by_ref
source_user_item_ref + source_user_item_digest
host_observation_ref + host_observation_digest
execution_authorization_digest
```

Application approval cannot execute a slot by itself. Every slot needs a fresh
execution authorization. The registrar-management applicant cannot author or
verify either principal artifact and cannot insert assistant/relay evidence
into the verified principal evidence set.

## 9. Production policy activation

The current production registrar extension is `active_dormant`: inspect and
status are enabled; intake and execution are disabled.

R3B-C must append a new versioned policy and active-policy receipt before any
production intake or execution. Existing dormant policy and activation bytes
remain immutable.

RAL owns these closed contracts:

```text
registration-wave-policy/0.1
registration-wave-policy-activation-request/0.1
registration-wave-policy-activation-authority/0.1
registration-wave-policy-activation-receipt/0.1
registration-wave-terminal-event/0.1
```

Exact production placement is:

```text
policies/wave1-policy-{policy-digest-suffix}.json
active-policy/00000000000000000001.json
active-policy/00000000000000000002.json  # later continuation/terminal transition
```

The sequence number is fixed-width decimal and create-only. Every active-policy
record binds its predecessor record ref/digest, dormant policy digest, Wave 1
policy digest, production registry generation, extension index, checkpoint,
principal activation authority, activation request, status, and record digest.
The first Wave 1 activation succeeds only when sequence 0 is the verified
dormant record; no in-place update or unindexed second active policy is allowed.

The Wave 1 policy is minimal and time/scope bounded:

- exactly three approved application digests;
- exactly three host-observed `codex_thread` locators;
- preparation/readback plus one sequential admission per digest;
- no batch append;
- no correction, merge, suspension, private, network, provider, Fabric, MCP,
  cloud, cleanup, or deletion capability;
- explicit expiration or terminal completion after slot 3 or a stopped wave.

Policy activation is an append-only control event, not a ledger identity fact.
Verified production status exposes active-policy ref/digest, control sequence,
wave status, policy expiry, registry generation and checkpoint digest. Every
intake, wave plan, operation request, execution authorization and slot receipt
binds those current values.

Activation requires exact principal authority, pre/post readback, protected
ACL, reparse/hard-link/alternate-stream guards, and create-only writes. Missing,
stale, mismatched, expired, terminal or unreceipted policy refuses intake,
planning and execution. Base `inspect`, `status`, checkpoint and recovery
readback remain available so a policy failure cannot disable diagnosis.

### 9.1 Registration wave plan and slot binding

One closed `registration-wave-plan/0.1` binds the complete order before any
slot execution:

```text
wave_id
ordered_slots[3] {
  slot_id
  slot_index = 1 | 2 | 3
  application_ref + application_digest
  host_observation_ref + host_observation_digest
}
initial_ledger_state
registry_control_digest
registry_generation_digest
policy_ref + policy_digest
checkpoint_ref + checkpoint_digest
terminal_boundary
not_claimed
wave_plan_digest
```

Slot indices are unique and contiguous; application and host-observation
digests are unique. Reordering or replacing one slot changes the plan digest.
The plan carries no rank, seniority or authority semantics.

Every `registration-wave-slot-request/0.1` binds:

- wave plan ref/digest;
- exact slot ID/index and application digest;
- exact predecessor slot receipt ref/digest, null only for slot 1;
- expected ledger state;
- policy, checkpoint, registry-generation and control digests; and
- its own request digest.

The next executable slot is derived from verified canonical event and slot
receipt prefixes. A current ledger head alone is insufficient. Slot 3 against
H1 is refused when the verified slot-2 receipt/prefix is absent, even if H1 is
otherwise current.

## 10. Sequential canonical admission

Before slot 1, the registrar verifies:

- production root and extension status;
- exact generation, policy, authority, ACL, checkpoint, and ledger head;
- zero existing applicants/residents/addresses/events unless the approved
  plan explicitly states otherwise; and
- all applicant/approval machine gates.

The initial state H0 is typed and unambiguous:

```text
expected_ledger_head = null
CLI spelling = GENESIS
ledger_event_count = 0
registry_control_digest = separately pinned non-null digest
```

`GENESIS`, null ledger head and the registry control/head-zero digest are not
interchangeable values. H1/H2/H3 are canonical chain digests.

For each slot:

1. rebuild and validate the full candidate event chain in isolated staging;
2. verify the exact expected external head immediately before append;
3. append the application atomically through the existing registrar Core;
4. obtain the new exact ledger head and commit receipt;
5. rebuild and validate application/resident/instance/address/binding views;
6. verify production counts and zero private/network/external effects; and
7. only then advance to the next slot.

One `registration-wave-slot-receipt/0.1` records:

- wave/slot/request/execution-authorization/application-approval digests;
- pre-head, post-head and event-count delta;
- every appended event ID/digest in canonical order;
- commit receipt and operation receipt refs/digests;
- application/resident/instance/address/binding projection digests;
- LIMEN B6A result ref/digest or explicit pending status;
- production count/effect deltas; and
- receipt status plus receipt digest.

Receipt status is closed:

```text
accepted
canonical_committed_readback_failed
recovered
refused_no_append
```

`accepted` requires canonical append, projection rebuild and B6A readback.
When canonical events committed but projection/B6A readback fails, the receipt
is `canonical_committed_readback_failed`, the wave stops, and no later slot may
execute. It must not be rewritten as no append or as accepted.

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
successful append is resolved by replay/readback, never by blindly appending
the same resident again.

If the complete canonical event prefix exists but the outer slot receipt was
not durably observed, status is `recovery_required`. The system must not claim
the missing receipt already existed. A separately principal-authorized
`registration-wave-slot-recovery-receipt/0.1` binds the verified event prefix,
pre/post heads, application digest, original execution authorization, current
checkpoint/readback and the newly reconstructed outer evidence. Forged or
partial prefixes remain recovery failures.

Wave policy states are:

```text
active       next exact slot may execute before expiry
stopped      no pending slot may execute
completed    slot 3 and final readback accepted
expired      no intake/plan/execute; inspect/recovery only
revoked      no intake/plan/execute; inspect/recovery only
```

A deliberate stop appends a terminal event and retains pending applications.
Resuming pending slots requires a new append-only continuation policy and active
policy record, fresh checkpoint/control/current-head readback, and fresh
per-slot execution authorization. An unchanged application approval may remain
valid only when its exact digest is unchanged and the approval is still active,
unexpired and unrevoked; it never substitutes for the fresh execution gate.

## 12. LIMEN B6A public readback

After every append, LIMEN B6A receives a freshly rebuilt public RAL view and a
new `limen.registration-readback-observation/0.1` captured from a fresh current
task/turn. Claim-time host observation and applicant item evidence remain
historical application provenance; they cannot prove post-append currentness.

The B6A observation binds:

- exact current native task and fresh turn;
- exact rebuilt RAL view schema, raw bytes digest, public view digest and
  ledger/binding/authority heads;
- the admitted application/resident/address/binding source refs;
- the new output item/envelope ref if present;
- resolution evidence and pre-turn enforcement as separate fields; and
- explicit temporal/currentness limitations.

Required results:

- the admitted exact thread resolves to exactly one resident;
- the other two pending threads remain unresolved until their admissions;
- no display-name, model, title, memory, role, or relay evidence is used;
- cross-resolution among the three task locators is rejected;
- resolution evidence and pre-turn enforcement are recorded separately;
- private access remains refused for all three.

Reusing the claim-time `applicant_item_ref`, claim-time turn, or pre-admission
RAL head in B6A produces `stale_readback_observation` and cannot issue a current
envelope.

The final wave state is not complete until all three individual B6A readbacks
and the combined three-resident collision scan pass.

## 13. Acceptance matrix

| ID | Population | Required result |
|---|---|---|
| W1-001 | three exact applicant-authored claims | three distinct candidate claims |
| W1-002 | one relayed/absent claim before slot 1 | exact three-seat wave stops; zero append |
| W1-003 | opt-in false before slot 1 | exact three-seat wave stops; zero append |
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
| W1-027 | slot 3 against current H1 without slot-2 receipt | order violation; no append |
| W1-028 | changed/reordered/duplicate slot | wave-plan digest/schema refusal |
| W1-029 | missing/substituted predecessor receipt | no append |
| W1-030 | forged/assistant/relayed principal approval | unverified; no preparation authority |
| W1-031 | approval A used for application B | exact-digest refusal |
| W1-032 | application approval without JIT execution authorization | no append |
| W1-033 | registrar self-approval evidence | refused |
| W1-034 | missing/stale/expired/unreceipted active policy | intake/plan/execute refused; status works |
| W1-035 | overwrite dormant or Wave policy bytes | create-only refusal |
| W1-036 | control digest supplied as H0 | typed ledger-state refusal |
| W1-037 | crash after final event before outer receipt | recovery_required |
| W1-038 | forged recovered receipt or partial event prefix | recovery refusal |
| W1-039 | stopped/expired policy with pending slot | no execution |
| W1-040 | continuation with stale head or old execution authority | refusal |
| W1-041 | uppercase/braced/Unicode-hyphen locator | noncanonical locator refusal |
| W1-042 | exact canonical duplicate locator | address collision |
| W1-043 | claim digest differs from host item evidence | preparation refused before ID assignment |
| W1-044 | unrelated nonempty turn/item ref with same locator | preparation refused |
| W1-045 | `continue` or non-null resident claim | continuity_evidence_required; no silent new resident |
| W1-046 | one failed candidate before policy activation | wave policy not activatable; zero append |
| W1-047 | B6A reuses claim-time turn/item | stale_readback_observation |
| W1-048 | fresh B6A observation bound to rebuilt H1/H2/H3 view | current per-slot resolution |

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
