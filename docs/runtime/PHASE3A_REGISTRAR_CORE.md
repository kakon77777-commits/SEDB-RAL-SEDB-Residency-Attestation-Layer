# Phase 3A Registrar Core

SEDB-RAL `0.3.0` is a synthetic/local candidate for applicant-self
registration. It can prepare an immutable application, evaluate exact
principal authority and registry collisions, stage the resulting ledger
events, commit only against an exact retained head, and identify complete,
partial, absent, or conflicting retry evidence.

## What is implemented

- Strict applicant-claim and host-observation contracts. Applicant text stays
  a claim; native thread and turn facts stay in a separate host record.
- The `codex_app_task_tool` profile preserves `native_session_id: null` plus
  its structural-unavailability reason. It does not invent a session ID.
- Opaque caller-supplied or UUID-generated resident, instance, line,
  application, address, and claim IDs.
- Exact application-digest authority with independently verified authorship
  reference input. Resident-wide authority cannot substitute for this gate.
- Name-independent collision checks over canonical resident, instance,
  address, claim, and continuity-line projections.
- Isolated candidate ledger and SQLite rebuild, followed by a fresh pre-commit
  restaging check and exact expected-head append.
- Idempotent complete retries and fail-closed partial/conflicting prefix
  detection. Phase 3A never guesses or resumes a partial transaction.
- Canonical machine CLI for preparation, digest, plan, admission, and status;
  the human explanation view marks itself non-authoritative.

## Acceptance matrix

`python scripts/validate_phase3a.py --output REPORT.json` runs the complete
synthetic scenario twice. It requires exactly 24 passing cases and these 12
executed controls:

```text
applicant-opt-out
applicant-host-address-mismatch
host-origin-unverified
opaque-id-name-leak
authority-missing
authority-authorship-unverified
address-binding-conflict
prepared-digest-mutation
expected-head-mismatch
staging-projection-mutation
partial-transaction
package-no-send
```

The report also requires byte-stable execution digests, zero network calls,
zero private reads, zero real applicants, two synthetic applicants, a clean
package no-send scan, and an injected no-send control that turns red.

## CLI

```text
sedb-ral application prepare CLAIM HOST [--ids IDS] [--output PREPARED]
sedb-ral application digest PREPARED
sedb-ral application explain PREPARED
sedb-ral registrar plan PREPARED DECISION AUTHORITY \
  --ctcl-receipt RECEIPT --verified-attestation-refs REFS \
  --ledger-root ROOT --expected-head GENESIS|DIGEST \
  --staging-parent STAGING
sedb-ral registrar admit PLAN PREPARED DECISION AUTHORITY \
  --ctcl-receipt RECEIPT --verified-attestation-refs REFS \
  --ledger-root ROOT --expected-head GENESIS|DIGEST
sedb-ral registrar status APPLICATION_DIGEST \
  --ledger-root ROOT --expected-head DIGEST
```

`GENESIS` is an explicit request for a new empty ledger. Omitting
`--expected-head` is a usage error. Output paths use create-new semantics and
are never overwritten.

## Boundary

All acceptance ledger writes occur under disposable test directories. This
candidate does not create a production registry, register a real applicant,
implement Registrar MCP, perform LIMEN B6 resolution or pre-turn enforcement,
open private AI Residence data, send network messages, release, or deploy.

The next separately authorized gates are Registrar MCP, production-root
checkpoint/restore rehearsal, real applicant approval artifacts, LIMEN B6A
public resolution, and resident-specific LIMEN B6B private opt-in.
