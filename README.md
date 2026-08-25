# SEDB-RAL

**SEDB Residency Attestation Layer**<br>
**SEDB AI 居籍存證層**

SEDB-RAL is a federated, file-first profile for recording AI residents, runtime
instances, continuity lines, identifiers, addresses, claims, observations,
attestations, authority, and delivery state without collapsing those concepts
into one overloaded identity field.

The project now contains the executable **Phase 3A synthetic/local registrar,
LIMEN public-view exporter, and P3-4 public registry-root lifecycle candidate**
at version `0.4.0`. It retains the Basic Phase 2 compatibility checkpoint, then
adds applicant-self preparation, exact-digest authority, projection collision
gates, isolated staging, exact-head commit, idempotent retry, candidate-first
root publication, protected Windows ACLs, and isolated recovery rehearsals. It
does not register a real applicant, add network send/federation, implement
Registrar MCP or LIMEN B6B, access private Residence data, or mutate SEDB
canonically.

## Validate the P3-4 public registry-root lifecycle

The synthetic gate maps the exact logical public root into temporary storage;
it does not create or inspect the production Residence tree:

```powershell
$env:PYTHONPATH = "src"
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

The gate requires P4-001 through P4-016, eight injected controls, deterministic
repeat execution, and zero resident, private, network, or external effects. The
production initializer is separately action-gated and accepts only
`D:\AI_RESIDENCE\REGISTRY\SEDB-RAL`; it never reads `AI_HOME` or creates a
ledger event. See
[`docs/runtime/PRODUCTION_REGISTRY_ROOT.md`](docs/runtime/PRODUCTION_REGISTRY_ROOT.md).

## Validate Phase 3A from a source checkout

Phase 3A uses only synthetic applicants and temporary ledgers:

```powershell
python -m pip install -e ".[test]"
$env:PYTHONPATH = "src"
python -m pytest -q `
  tests/test_phase3_registration_prepare.py `
  tests/test_phase3_schema_assets.py `
  tests/test_phase3_registration_admission.py `
  tests/test_phase3_registrar_plan.py `
  tests/test_phase3_registrar_recovery.py `
  tests/test_phase3_cli.py `
  tests/test_phase3a_gate.py
python scripts/validate_phase3a.py --output phase3a-local.json
```

The integrated report requires 24 passing cases, 12 executed controls, two
byte-stable runs, zero real applicants, zero network calls, and zero private
reads. See
[`docs/runtime/PHASE3A_REGISTRAR_CORE.md`](docs/runtime/PHASE3A_REGISTRAR_CORE.md)
for the exact CLI and boundary.

## Validate the LIMEN public-view exporter

The exporter reads only an exact-head SEDB-RAL ledger and produces a public
`limen.ral-view/0.2` candidate:

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q `
  tests/test_limen_public_view_contract.py `
  tests/test_limen_public_view_export.py `
  tests/test_limen_public_view_cli.py `
  tests/test_limen_public_view_gate.py
python scripts/validate_limen_public_view.py --output limen-public-view-local.json
```

See
[`docs/runtime/LIMEN_PUBLIC_VIEW_V02.md`](docs/runtime/LIMEN_PUBLIC_VIEW_V02.md)
for the mapping, collision behavior, CLI, and non-claims.

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
$sedbArchive = "D:\Ai\work together\SEDB\releases\SEDB-v0.4B-local.zip"
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
$cleanVenv = Join-Path $env:TEMP "sedb-ral-0.4.0-clean"
python -m venv $cleanVenv
& "$cleanVenv\Scripts\python.exe" -m pip install --no-deps `
  (Get-ChildItem dist\clean\*.whl | Select-Object -First 1).FullName
& "$cleanVenv\Scripts\sedb-ral.exe" --version
```

After activation, the equivalent command is `sedb-ral --version`; the public
view/root candidate reports `0.4.0`.

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

## CLI

```text
sedb-ral canonicalize FILE
sedb-ral contract validate CONTRACT FILE
sedb-ral identifier check FILE
sedb-ral ledger verify ROOT --expected-final-chain-digest DIGEST
sedb-ral phase1a verify ROOT
sedb-ral application check APPLICATION_FILE
sedb-ral application prepare CLAIM HOST [--ids IDS] [--output PREPARED]
sedb-ral application digest PREPARED
sedb-ral application explain PREPARED
sedb-ral registrar plan PREPARED DECISION AUTHORITY ... --expected-head GENESIS|DIGEST
sedb-ral registrar admit PLAN PREPARED DECISION AUTHORITY ... --expected-head GENESIS|DIGEST
sedb-ral registrar status APPLICATION_DIGEST --ledger-root ROOT --expected-head DIGEST
sedb-ral registry root-plan ... --expected-owner-sid SID
sedb-ral registry prepare-root PLAN AUTHORITY PARENT_ACL CANDIDATE_ACL
sedb-ral registry verify-root PLAN AUTHORITY PARENT_ACL CANDIDATE_ACL
sedb-ral registry publish-root PLAN VERIFICATION
sedb-ral registry root-status --expected-plan-digest DIGEST
sedb-ral registry checkpoint-root --root ROOT --checkpoint-id UUID --authority AUTHORITY --time-ref REF
sedb-ral registry rehearse-restore --root ROOT --checkpoint-root CHECKPOINT --rehearsal-id UUID --authority AUTHORITY --time-ref REF
sedb-ral registry rehearse-rollback --root ROOT --checkpoint-root CHECKPOINT --rehearsal-id UUID --authority AUTHORITY --time-ref REF
sedb-ral registry limen-view --ledger-root ROOT --expected-head DIGEST [--output VIEW]
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
Registrar mutation requires an exact staged plan and retained head. The literal
`GENESIS` is the only CLI spelling for a new empty ledger; omission is an
error. Phase 3A and P3-4 synthetic acceptance exercise writes only in temporary
synthetic roots. Production-root mutation requires the separate Windows
initializer, exact plan/authority/time artifacts, and the action-time gate.

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

## Phase 3A capabilities

- Applicant claim and host observation remain separate canonical inputs.
- Host-unavailable session data remains null with a structured reason.
- Authority binds the exact immutable application digest; connection,
  familiarity, model, title, role, and display name grant no authority.
- Active native addresses cannot be stolen or silently duplicated; homonymous
  display labels remain valid.
- Commit reruns staging before canonical append and requires the exact source
  head, event sequence, candidate head, and projection digest.
- Complete retries are idempotent. Partial or conflicting prefixes require an
  explicit future recovery procedure.

## Phase 3A exclusions

- No transport send.
- No network federation.
- No production registry or real applicant admission.
- No Registrar MCP.
- No LIMEN B6 identity resolution, pre-turn enforcement, or private opt-in.
- No automatic resident, instance, or continuity merge.
- No live-provider read as a prerequisite for core validation.
- No live SEDB checkout input or mutation.
- No SEDB canonical mutation.

Generated JSON and SQLite views are rebuildable outputs, never canonical
authority. Transport execution, federation, production admission, identity
merge, private Residence access, release, and deployment remain unauthorized.

The inherited Basic Phase 2 profile itself still grants **No Phase 3** and
**No registrar or federation** authority; Phase 3A is a separate bounded
candidate with its own acceptance gate.

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

The approved design for applicant-self registration and LIMEN B6 is captured
in
[`docs/superpowers/specs/2026-08-25-phase3-self-registration-and-limen-b6-design.md`](docs/superpowers/specs/2026-08-25-phase3-self-registration-and-limen-b6-design.md).
Its Phase 3A synthetic/local Core is implemented and acceptance-tested here;
production registration, Registrar MCP, LIMEN B6, and private Residence access
remain separate future gates.

## Repository relationship

SEDB-RAL is a sibling of SEDB, not a replacement for it. SEDB supplies the
governance and sparse-field concepts; SEDB-RAL defines the residency and
attestation profile. EveMissLab PMW Fabric, Claude Code session messaging,
Codex queue, AI Board, and future transports remain external adapters.

## Current evidence boundary

- No existing SEDB, AI Residence, or PMW Fabric files are modified by this
  repository.
- Phase 3A evidence contains only two synthetic applicants and temporary-ledger
  heads; it contains no real native task ID or private root content.
- Only the exact SEDB v0.4B archive profile above is adopted for the local
  Basic Phase 2 compatibility gate; other external artifacts remain evidence.
- CTCL receipts are stored as temporal evidence; a timestamp string by itself
  is not treated as a verified clock observation.
- No license has been selected yet. Repository visibility does not imply a
  reuse license.
