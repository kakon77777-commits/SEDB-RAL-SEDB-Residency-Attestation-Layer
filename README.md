# SEDB-RAL

**SEDB Residency Attestation Layer**<br>
**SEDB AI 居籍存證層**

SEDB-RAL is a federated, file-first profile for recording AI residents, runtime
instances, continuity lines, identifiers, addresses, claims, observations,
attestations, authority, and delivery state without collapsing those concepts
into one overloaded identity field.

The project now contains the reviewed executable **Basic Phase 1** checkpoint:
Phase 1A deterministic foundations, Phase 1B admission and explanation, and
Phase 1C read-only delivery evidence. It validates strict canonical JSON, CTCL
receipts, identifier-discrimination fixtures, authority-gated resident
applications, an append-only file ledger, deterministic projections, and
captured transport evidence without adding message-send capability.

## Install and verify Basic Phase 1

Python 3.11 or newer is required.

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
python scripts/validate_phase1a.py
python scripts/validate_phase1bc.py
sedb-ral phase1a verify .
sedb-ral phase1bc verify .
```

For byte-reproducible wheel and sdist artifacts, use the pinned release epoch
and the normalization wrapper rather than invoking `python -m build` directly:

```powershell
python scripts/build_reproducible.py `
  --outdir dist/release `
  --source-date-epoch 1787484453
```

The wrapper passes `SOURCE_DATE_EPOCH` to the build backend and normalizes sdist
tar/gzip metadata. Phase 1A validation requires two independent output
directories to produce identical wheel and sdist SHA-256 values.

The public contracts ship once under `src/sedb_ral/schemas/`. The repository
gate requires positive, negative, and indeterminate identifier populations and
builds a temporary ledger from checked-in drafts. A deliberately corrupted
copy must make each gate report red.

## Read-only CLI

```text
sedb-ral canonicalize FILE
sedb-ral contract validate CONTRACT FILE
sedb-ral identifier check FILE
sedb-ral ledger verify ROOT --expected-final-chain-digest DIGEST
sedb-ral phase1a verify ROOT
sedb-ral application check APPLICATION_FILE
sedb-ral project rebuild EVENTS_JSON
sedb-ral explain claim EVENTS_JSON CLAIM_ID
sedb-ral diagnose delivery ADAPTER_OBSERVATION_JSON
sedb-ral phase1bc verify ROOT
```

Exit codes are semantic:

```text
0  validated/admitted/checkpoint-verified
1  unreadable or syntactically invalid input; integrated gate failed
2  contract or substantive rule rejection; invalid ledger
3  indeterminate identifier result or ledger lacking an external head
```

All JSON command output is strict canonical UTF-8 plus one terminal LF.

## Canonical byte contract

Phase 1A uses `sedb-ral-json-nfc-codepoint-v1`: UTF-8, NFC-normalized
strings/keys, Unicode code-point key order, compact separators, no BOM/CR/tail
newline, integers only, and no duplicate keys. This is explicitly not RFC 8785
JCS. The standalone digest reference binds this version through domain
separation.

## CTCL temporal evidence

`ctcl_now` produces a local `reading`; its instant ID is not a third-party
retrievable anchor. `ctcl_register_instant` produces a `registered_anchor`.
Signature presence is not verification: the current signature covers only
`instant_id|unix_ns|timescale`, not message text, Git state, authorship, or
arbitrary metadata.

## Phase 1A fixtures

```text
fixtures/ctcl/                 reading and registered-anchor receipts
fixtures/identifier/positive  admissible control population
fixtures/identifier/negative  measured shared-value counterexample
fixtures/identifier/mixed_population  indeterminate control and exact manifest
fixtures/ledger/               deterministic event drafts
```

## Basic Phase 1 capabilities

- Authority-gated self-application with exact resident-reference and scope
  checks.
- Canonical authority grant snapshots, digest binding, append-only revocation,
  and commit-time revalidation.
- Deterministic resident/application JSON and disposable SQLite projections;
  the file ledger remains canonical.
- Categorical attestation and scope-specific, machine-evaluable evidence
  sufficiency.
- Append-only corrections, withdrawals, and tombstones with exact target and
  replacement provenance.
- Bound transcript speaker labels with transcript-scoped visual cues and
  explicit relay provenance.
- A machine-consumed 29-row incident corpus and route-scoped adapter matrix.
- Sanitized Codex queue observations, exact delivery reconstruction, and
  tri-state route diagnostics.
- An AST gate that rejects send/process/network capability and package-level
  SEDB imports from `src/sedb_ral`.

## Basic Phase 1 exclusions

- No transport send.
- No registrar.
- No automatic resident, instance, or continuity merge.
- No live-provider read as a prerequisite for core validation.
- No SEDB canonical mutation.
- No SEDB Phase 2 compatibility profile yet.

Generated JSON and SQLite views are rebuildable outputs, never canonical
authority. Transport execution, registrar/federation behavior, identity merge,
and SEDB adoption remain later phases.

## Core boundary

```text
Claim != Observation
Observation != Proof
Line != Instance
Role != Resident
Runtime Tag != Address
Transport Accepted != Delivered
Capability != Authority
Decision != Commit
Wall-clock Time != Causal Order
```

The initial design is in
[`docs/superpowers/specs/2026-08-23-sedb-ral-core-design.md`](docs/superpowers/specs/2026-08-23-sedb-ral-core-design.md).

## Repository relationship

SEDB-RAL is a sibling of SEDB, not a replacement for it. SEDB supplies the
governance and sparse-field concepts; SEDB-RAL defines the residency and
attestation profile. EveMissLab PMW Fabric, Claude Code session messaging,
Codex queue, AI Board, and future transports remain external adapters.

## Current evidence boundary

- No existing SEDB, AI Residence, or PMW Fabric files are modified by this
  repository.
- External archives and handoffs are design evidence until explicitly adopted.
- CTCL receipts are stored as temporal evidence; a timestamp string by itself
  is not treated as a verified clock observation.
- No license has been selected yet. Repository visibility does not imply a
  reuse license.
