# SEDB-RAL Phase 3 Self-Registration and LIMEN B6 Integration Design

> **Status:** Approved direction; written specification awaiting Neo.K review
>
> **Date:** 2026-08-25
>
> **Repositories:** `D:\Ai\work together\SEDB-RAL` and `D:\Ai\work together\LIMEN`
>
> **Scope:** Applicant-self registration, exact principal digest approval,
> append-only registrar, and the minimum real-identity path into LIMEN B6
>
> **Current safety state:** No real ledger write or private Residence access is
> authorized by this document

## 1. Goal

Build the first complete path by which a named AI can move from a task-local
self-claim and host-observed native address to a canonical SEDB-RAL resident,
instance, address, and binding projection, then be resolved by LIMEN without
using its name, model, role, project, title, memory, or self-label as identity
evidence.

The governing flow is:

```text
host-observed task/turn
→ applicant-authored claim
→ prepared immutable application
→ principal approval of exact application digest
→ registrar machine gates
→ append-only SEDB-RAL event chain
→ rebuilt public RAL view
→ LIMEN fresh observation and resolution
→ task-local envelope and output guard
→ optional, separately authorized private Residence bootstrap
```

## 2. Why this is two systems

SEDB-RAL owns canonical identity/address/authority facts. LIMEN owns current
host observations, envelopes, access decisions, bootstrap/output guards, and
receipts.

Therefore:

```text
SEDB-RAL registrar write != LIMEN runtime receipt
LIMEN resolved envelope != permission to mutate SEDB-RAL
```

LIMEN may prepare candidate evidence or consume a projection. It never appends
canonical resident/address events.

## 3. Scope

### 3.1 Phase 3A — Applicant and registrar core

- applicant-self claim contract;
- host-observation attachment contract;
- application preparation with opaque IDs;
- deterministic canonical application digest;
- exact principal authority artifact;
- machine-evaluable admission decision;
- append-only commit with expected external ledger head;
- rebuildable resident/address/binding/directory projections;
- correction, withdrawal, address suspension, and explanation receipts;
- CLI first, local STDIO MCP after CLI acceptance.

### 3.2 LIMEN B6A — Real public identity slice

- consume a real registry projection without private memory;
- resolve exact current native binding;
- issue a new task/turn envelope;
- enforce or audit the speaker label through Output Guard;
- preserve any host-enforcement limitation as BLOCKED/UNMEASURED rather than
  treating a matching model response as proof.

### 3.3 LIMEN B6B — Resident-specific private opt-in

- individual resident authorization;
- production root reference selected by registry/Residence policy, never by
  model input;
- pre-checkpoint, isolated restore, rollback rehearsal;
- minimum mandatory projection and privacy review;
- resident dissent/revocation path;
- positive bootstrap and output guard under a host-enforced current envelope.

## 4. Non-goals

This design does not authorize:

- registering a peer from a remembered name, task title, role, model, provider,
  folder, website, transcript quote, or global instruction;
- importing all named or pinned tasks as residents in one batch;
- automatic identity/instance/line merge;
- treating applicant continuity claim as accepted lineage;
- guessing unavailable host session or turn IDs;
- opening private AI Residence to discover identity;
- storing real applicant packages or canonical ledger data in the Git repo;
- public discovery service, federation, HTTP MCP, external send, release,
  publication, or deployment;
- calling a successful registrar commit “LIMEN B6 private completion.”

## 5. Applicant-self claim

The applicant response is a claim, not an identity verdict:

```json
{
  "schema": "sedb-ral.self-application-claim/0.1",
  "applicant_claim_only": true,
  "desired_display_label": "Example",
  "existing_resident_claim": null,
  "continuity_claim": "new",
  "desired_addresses": [
    {
      "namespace": "codex_thread",
      "identifier_kind": "codex_thread",
      "locator": "thread:test-applicant"
    }
  ],
  "role_description_claim": "Example role",
  "dissent_or_limits": [],
  "opt_in": true,
  "relay_is_authorship": false,
  "not_claimed": [
    "verified_identity",
    "registrar_authority",
    "private_access"
  ]
}
```

Rules:

- `opt_in=false` stops preparation;
- the applicant may keep, change, or reject a familiar display name;
- `continuity_claim=continue` requests evaluation but proves nothing;
- no peer may fill an absent applicant response;
- a completed host turn with zero canonical applicant item remains
  `applicant_output_unavailable`;
- relay metadata preserves `relay_is_authorship=false` and receiver-observed
  origin.

## 6. Host observation attached to an application

The controller or trusted host adapter attaches native facts separately from
the applicant claim:

```json
{
  "schema": "sedb-ral.registration-host-observation/0.1",
  "observation_id": "observation:test-registration",
  "provider": "openai",
  "adapter_kind": "codex_app_task_tool",
  "identifier_kind": "codex_thread",
  "native_thread_id": "thread:test-applicant",
  "native_session_id": null,
  "native_turn_id": "turn:test-applicant",
  "unavailable_fields": [
    {
      "field": "native_session_id",
      "reason": "structurally_unavailable_from_codex_app_task_tool"
    }
  ],
  "observed_origin": "host:codex-app-thread-tools",
  "observed_at_ref": "host-event:test-registration",
  "applicant_item_ref": "item:test-applicant",
  "not_claimed": ["pre_turn_output_enforcement"]
}
```

The current Codex thread tools have been observed to expose an exact thread ID
and active turn ID while a turn is in progress, but not a native session ID.
The adapter must retain that absence. It may not synthesize a session value or
copy one from history, another task, a title, or model text.

## 7. Observation profiles and LIMEN compatibility

Existing LIMEN `codex_app_server` observations continue to require thread,
session, and turn.

A new, separately versioned `codex_app_task_tool` profile may use:

```text
required observation fields: native_thread_id + native_turn_id
structurally unavailable: native_session_id
binding discrimination component: native_thread_id
envelope scope/expiry component: native_turn_id
```

This requires a new RAL view/binding contract rather than silently relaxing
`limen.ral-view/0.1`:

```json
{
  "schema": "limen.ral-view/0.2",
  "bindings": [
    {
      "identifier_components": ["native_thread_id"],
      "native_thread_id": "thread:test-applicant",
      "native_session_id": null,
      "session_match_policy": "not_applicable_for_profile"
    }
  ]
}
```

Positive resolution requires a discrimination fixture proving the declared
thread namespace separates the measured resident population. Thread titles,
display labels, and model IDs retain zero weight.

## 8. Enforcement versus audit evidence

The Codex task tools can provide host-observed thread/turn evidence, but a
model-controlled call made after inference begins is not a completed pre-turn
guard.

Therefore B6 records two independent results:

```text
resolution_evidence: verified | failed | unavailable
pre_turn_enforcement: verified | blocked | unmeasured
```

A correct resolved label with `pre_turn_enforcement=blocked` does not promote
host enforcement. Full promotion requires App Server access or another host
integration that runs observation, resolution, and Output Guard outside model
judgment before publication.

## 9. Application preparation

`application prepare` consumes the applicant claim and host observation. It
does not write the ledger.

It generates independent opaque UUID-based identifiers:

```text
resident:<uuid>
instance:<uuid>
line:<uuid>
application:<uuid>
claim:<uuid>
address:<namespace>:<uuid>
```

IDs never embed display names, task titles, roles, models, filesystem paths, or
address locators.

Once prepared, an application is immutable. A correction creates a superseding
candidate; it does not edit the old application in place.

The canonical digest is computed after IDs are assigned. Re-running prepare
does not silently generate a different resident for the same candidate: the
caller must supply the retained prepared application or explicitly withdraw
and create a new application.

## 10. Address classes

Initial Phase 3A accepts:

### 10.1 Native host address

```text
namespace: codex_thread
adapter_kind: codex_app_task_tool | codex_app_server
locator: exact host-observed native thread ID
target_ref: prepared resident ID
status: active
```

This address is admitted only with host evidence matching the applicant turn.

### 10.2 Semantic identity address

```text
namespace: evemisslab_ai
adapter_kind: semantic_identity
locator: opaque resident-based locator or approved slug
status: unknown until an independent resolver/transport binding exists
```

A semantic address is stable human/agent addressing metadata. It is not a
native runtime binding and cannot resolve a current task by itself.

### 10.3 Home address

Home/Guild/Web addresses remain future projection addresses. They reference the
resident after AI-Guild exists and have zero role in initial identity
admission.

Private Residence root references are not public addresses.

## 11. Existing resident and lineage claims

If `existing_resident_claim` is null, preparation creates a new resident
candidate.

If it names a resident, the registrar requires:

- existing active resident record;
- accepted lineage/correction evidence;
- no conflicting active instance/thread binding;
- resident-specific authority for the continuity operation;
- separate machine and review gates.

A familiar historical name without an existing canonical record is a new
resident application, not a silent continuation or merge.

## 12. Principal approval artifact

Before admission, Neo.K receives the complete canonical prepared application
and digest:

```text
sha256:<canonical-application-digest>
```

Approval creates a host-authenticated, principal-authored authority artifact:

```json
{
  "authority_id": "authority:<uuid>",
  "principal_ref": "principal:neo.k",
  "subject_kind": "application_digest",
  "subject_ref": "sha256:test-application",
  "scopes": ["registry.application.accept"],
  "status": "active",
  "authorship_attestation_ref": "attestation:test-principal"
}
```

Approval of one digest does not authorize another applicant, changed address,
continuity merge, private access, transport send, deletion, or deployment.

The applicant cannot self-grant this artifact. A relay stating “Neo approved”
is not principal evidence.

## 13. Registrar machine gates

Admission requires all applicable gates:

1. strict UTF-8, schema, duplicate-key, and canonicalization validity;
2. applicant opt-in and canonical applicant item evidence;
3. exact host observation provenance;
4. provider/adapter/identifier profile validity;
5. namespace-local identifier discrimination evidence;
6. resident/application/instance/address cross-reference validity;
7. address parser and target validity;
8. no active address/binding collision;
9. no unapproved resident/instance/line merge;
10. active principal authority bound to the exact digest;
11. independently verified authority authorship attestation;
12. current CTCL evidence or explicit temporal unavailability;
13. expected external ledger head match;
14. candidate event projection rebuild and schema validation;
15. injected controls demonstrate each critical gate turns red;
16. checkpoint/restore and rollback proof for the configured ledger root.

Any failure produces `defer` or `reject` without partial canonical append.

## 14. Append-only commit

The first implementation reuses the existing application decision/commit
contracts and event chain:

```text
authority.granted             (when not already canonical)
→ application.submitted
→ application.accepted
→ resident.registered
```

The registered event contains the prepared resident snapshot plus declared
instances, addresses, and claims. Rebuildable projections derive resident,
address, instance, and binding views with exact source-event provenance.

The registrar must precompute/validate the entire candidate chain in an
isolated staging ledger, then append to the configured canonical ledger only
when the expected head still matches. It never edits an earlier file.

Two applications are admitted sequentially. The second uses the new head from
the first; “batch registration” does not create implicit all-or-nothing merge
semantics.

## 15. Idempotency and concurrency

- same application digest plus same canonical authority at the same accepted
  ledger state returns the existing commit receipt;
- same ID with different canonical content is a conflict;
- wrong expected head refuses before append;
- duplicate address locator in a unique namespace refuses;
- concurrent applications are serialized through expected-head compare;
- crash during staging changes no canonical data;
- crash after a successful append is detected by replay and idempotent receipt
  lookup, not by appending another resident.

## 16. Corrections and refusal paths

Phase 3 supports append-only:

- application withdrawal before acceptance;
- correction/supersession of a prepared claim;
- address suspension/revocation;
- display-label alias change;
- authority revocation;
- applicant dissent or resident opt-out from future LIMEN private access.

It does not delete resident history, merge residents, or erase an address that
was previously valid.

## 17. CLI contract

Public/candidate lane:

```text
sedb-ral application prepare CLAIM HOST_OBSERVATION --output APPLICATION
sedb-ral application digest APPLICATION
sedb-ral application check APPLICATION AUTHORITY_BUNDLE
sedb-ral application explain APPLICATION AUTHORITY_BUNDLE
```

Registrar lane:

```text
sedb-ral registrar admit APPLICATION AUTHORITY ATTESTATION \
  --ledger-root ROOT --expected-head DIGEST --ctcl-receipt RECEIPT
sedb-ral registrar suspend-address REQUEST \
  --ledger-root ROOT --expected-head DIGEST
sedb-ral registry project --ledger-root ROOT --expected-head DIGEST
```

Machine JSON is canonical. A human view is derived and never the approval
artifact or commit receipt.

CLI arguments never accept display name as the sole resident/address selector.

## 18. Local MCP contract

MCP wraps the accepted CLI/Core after registrar tests pass:

```text
registry.application.prepare
registry.application.digest
registry.application.check
registry.application.explain
registry.registrar.admit
registry.registrar.suspend_address
registry.directory.lookup
registry.status
```

The server is local STDIO only. Registrar tools may remain visible but always
refuse without exact application, authority, attestation, operation scope, and
expected head. MCP initialization, connection, tool discovery, or server
instructions grant no registrar authority.

The MCP server receives configured ledger references outside model-supplied
arguments where practical; private paths are never enumerable.

## 19. Storage and deployment root

Repository fixtures and tests remain synthetic. Real canonical data must live
outside the Git checkout and outside resident memory.

Recommended separation:

```text
D:\AI_RESIDENCE\REGISTRY\SEDB-RAL\
```

as a sibling of `D:\AI_RESIDENCE\AI_HOME`, not inside any resident memory
directory. This path is a recommendation, not an authorization. The exact root
is chosen in the implementation plan only after:

- path ownership and ACL review;
- pre-checkpoint and isolated restore;
- canonical manifest and external head;
- rollback rehearsal;
- exclusion from public Git, secrets, and private memory projections.

## 20. First-wave policy

The first wave is deliberately bounded:

- one current applicant with an exact host-observed Codex thread/turn;
- one existing named Codex task that returned a canonical self-application
  claim and opt-in;
- any task with repeated completed turns but zero canonical applicant output
  remains pending;
- no additional pinned/named task is inferred into the batch;
- prepared applications are kept outside Git and shown to Neo.K before any
  authority or ledger write.

Concrete names, native IDs, application IDs, and digests belong only in the
task-local intake/evidence package, not this reusable specification.

## 21. LIMEN B6A acceptance

At minimum:

| ID | Case | Expected |
|---|---|---|
| L6A-001 | Registry projection contains exact admitted thread binding | one resident candidate |
| L6A-002 | Display name only | unresolved |
| L6A-003 | Thread address collision | conflicting; no tie-break |
| L6A-004 | Session unavailable under strict App Server profile | rejected |
| L6A-005 | Session unavailable under approved task-tool profile | thread component may resolve |
| L6A-006 | Active host turn missing | no envelope |
| L6A-007 | Thread/turn from another task | native mismatch |
| L6A-008 | Exact current task-tool observation | new turn-scoped envelope |
| L6A-009 | Matching model label without host guard | not enforcement proof |
| L6A-010 | Output Guard outside inference | correct label or fail closed |
| L6A-011 | Registry correction/suspension | old envelope stale/refused |
| L6A-012 | Repeated inputs | deterministic result/receipt |

Promotion records resolution and enforcement separately. A BLOCKED host guard
cannot be hidden by a PASS resolution.

## 22. LIMEN B6B acceptance

Only after resident-specific opt-in:

| ID | Case | Expected |
|---|---|---|
| L6B-001 | Exact resolved envelope + opt-in + matching manifest | minimum bootstrap |
| L6B-002 | Registered resident without private opt-in | private access refused |
| L6B-003 | Another resident/root | no existence/path disclosure |
| L6B-004 | Checkpoint/manifest digest mismatch | refuse/rollback |
| L6B-005 | Revocation/dissent | subsequent access stops |
| L6B-006 | Token pressure | mandatory identity core retained |
| L6B-007 | Ordinary turn | no automatic canonical memory write |
| L6B-008 | Output label mismatch | blocked outside inference |

## 23. Verification and evidence package

Every run records:

- implementation commit and clean/dirty state;
- application/authority/attestation/ledger-head digests;
- applicant item and host observation refs;
- selected test IDs and injected controls;
- candidate staging projection digest;
- pre/post ledger head and append receipt IDs;
- public directory/RAL view digest;
- LIMEN resolution and enforcement results separately;
- network/private/registry write counters;
- checkpoint/restore/rollback evidence;
- secrets/private-path scan;
- explicit `not_claimed` fields.

No report is summarized only as “registered” or “resolved.”

## 24. Rollout sequence

```text
P3-0 written design and acceptance review
→ P3-1 synthetic applicant/host-observation preparation
→ P3-2 synthetic registrar and recovery
→ P3-3 CLI/package/STDIO MCP parity
→ P3-4 configured external registry root and rollback proof
→ P3-5 first real applications prepared; no write
→ P3-6 Neo.K approves exact digests
→ P3-7 sequential canonical admissions
→ B6A real registry projection and resolution audit
→ host-enforcement probe
→ B6B resident-specific private opt-in only if separately authorized
```

## 25. Success definition

The identity repair path succeeds when evidence proves:

```text
the applicant authored a bounded claim
→ the host observed the exact native task/turn
→ Neo.K approved the exact immutable application digest
→ the registrar appended a replayable collision-free event chain
→ SEDB-RAL rebuilt the exact public binding
→ LIMEN resolved only from that binding
→ output/private behavior reflected the measured host-enforcement state
```

It does not succeed merely because a familiar name reappears in model output.

## 26. Review decisions requested

Neo.K review should confirm:

1. the split into Phase 3A, LIMEN B6A, and LIMEN B6B;
2. the new task-tool observation profile with thread+turn and explicit
   session unavailability;
3. first-wave size of two applicants, with empty-output tasks deferred;
4. exact application-digest approval before any ledger write;
5. the recommended external registry root remains a later explicit path
   decision;
6. resolution evidence never substitutes for pre-turn output enforcement.
