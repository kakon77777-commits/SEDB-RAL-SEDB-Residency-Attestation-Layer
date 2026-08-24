# SEDB-RAL

**SEDB Residency Attestation Layer**<br>
**SEDB AI 居籍存證層**

SEDB-RAL is a federated, file-first profile for recording AI residents, runtime
instances, continuity lines, identifiers, addresses, claims, observations,
attestations, authority, and delivery state without collapsing those concepts
into one overloaded identity field.

The project now contains the executable **Basic Phase 2** checkpoint. It keeps
the Phase 1A deterministic foundations, Phase 1B admission and explanation,
and Phase 1C read-only delivery evidence, then adds a pinned SEDB v0.4B
adoption profile, isolated real-package integration, a three-class
differential, and a guarded compatibility receipt. It does not add
message-send, registrar, federation, or SEDB canonical-mutation authority.

## Validate Basic Phase 2 from a source checkout

Python 3.11 or newer and Windows are required for the complete real archive
flow. From the repository root:

```powershell
python -m pip install -e ".[test]"
$env:PYTHONPATH = "src"
python -m pytest -q
python scripts/validate_phase1a.py
python scripts/validate_phase1bc.py
python -m pytest tests/test_sedb_v04b_integration.py -q
$sedbArchive = "C:\Users\kakon\Downloads\SEDB\SEDB-v0.4B-local.zip"
python scripts/validate_phase2.py --sedb-archive $sedbArchive
sedb-ral phase1a verify .
sedb-ral phase1bc verify .
sedb-ral phase2 verify . --sedb-archive $sedbArchive
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

For a clean local artifact/CLI check without resolving dependencies from the
network:

```powershell
python -m build --wheel --no-isolation --outdir dist/clean
$cleanVenv = Join-Path $env:TEMP "sedb-ral-0.2.1-clean"
python -m venv $cleanVenv
& "$cleanVenv\Scripts\python.exe" -m pip install --no-deps `
  (Get-ChildItem dist\clean\*.whl | Select-Object -First 1).FullName
& "$cleanVenv\Scripts\sedb-ral.exe" --version
```

After activation, the equivalent command is `sedb-ral --version`; the Basic
Phase 2 artifact reports `0.2.1`.

The public contracts ship once under `src/sedb_ral/schemas/`. The repository
gate requires positive, negative, and indeterminate identifier populations and
builds a temporary ledger from checked-in drafts. A deliberately corrupted
copy must make each gate report red.

## Adopted SEDB profile

Basic Phase 2 accepts exactly this external package profile:

- Archive: `SEDB-v0.4B-local.zip`, exactly `8980052` bytes.
- Archive SHA-256:
  `159F0928415811A434E885D50E94846266474725723D25DAC426170874B844D8`.
- Package: `sedb-local==0.4.0b1`.
- Source commit: `139b9952bb283b2e95f7690d76e3c5fbcdc680aa`.
- Internal manifest: `MANIFEST.sha256`, exactly `114 entries`, with every
  listed member digest verified before extraction is adopted.

The archive is read into one bounded same-handle snapshot, verified, and
extracted beneath newly created temporary storage. The extracted `src`
directory is inserted only into the integration process's local import path;
SEDB-RAL package code does not import `sedb`.

The SEDB write projection remains pure and contains only declared mapped
fields. Comparison uses exactly `expected_by_mapping`, `unmapped`, and
`contradiction`; only `contradiction` fails compatibility. Exact export equality
and record counts remain diagnostics, while SQLite database integrity remains
mandatory.

## Extraction and packaging boundary

Verified extraction publication is Windows-only and uses a retained directory
handle with no-replace publication. On non-Windows systems it fails closed with
`ENOTSUP`; there is no path-only fallback.

If extraction fails after staging begins, a directory beside the requested
target with prefix `.<target-name>.sedb-` may be intentionally abandoned. To
clean one manually, identify it in that exact parent, confirm the integration
process has ended and the retained handle is released, verify it is not the
published target or an unrelated replacement, inspect its contents, and then
remove only that confirmed directory with a trusted file manager. Do not
automate recursive cleanup based only on a pathname or prefix.

Phase 2 is a repository/source-checkout gate. The checked-in profiles,
integration scripts, and final receipt are not self-contained wheel/sdist resources.
The wheel still ships the package schemas and CLI, but an installed artifact
alone is not a complete Phase 2 archive validator.

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
sedb-ral phase2 verify ROOT --sedb-archive ARCHIVE
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

## Basic Phase 2 capabilities

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
  SEDB imports from `src/sedb_ral`, plus transport/process capability in the
  dynamically executed Task 5 integration script.
- Verified, isolated SEDB v0.4B extraction/application/export with a
  contradiction-authoritative three-class differential.

## Basic Phase 2 exclusions

- No transport send.
- No registrar or federation.
- No Phase 3.
- No automatic resident, instance, or continuity merge.
- No live-provider read as a prerequisite for core validation.
- No live SEDB checkout input or mutation.
- No SEDB canonical mutation.

Generated JSON and SQLite views are rebuildable outputs, never canonical
authority. Transport execution, registrar/federation behavior, identity merge,
and Phase 3 remain unauthorized.

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
- Only the exact SEDB v0.4B archive profile above is adopted for the local
  Basic Phase 2 compatibility gate; other external artifacts remain evidence.
- CTCL receipts are stored as temporal evidence; a timestamp string by itself
  is not treated as a verified clock observation.
- No license has been selected yet. Repository visibility does not imply a
  reuse license.
