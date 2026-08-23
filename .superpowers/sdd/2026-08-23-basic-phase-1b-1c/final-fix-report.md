# Final fix report — Basic Phase 1B/1C whole-branch review

## Status

PASS. All eleven required fix clusters are implemented on `feat/basic-phase2`.
The implementation commit is `383f793` (`fix: close Phase 1BC authority
boundaries`). The report is carried by the immediately following local
documentation commit, identified as `HEAD` at handoff; its exact hash is also
returned in the final handoff. The final review range is `be27c3f..HEAD`.

No Phase 2 implementation, push, merge, provider send, provider CLI launch,
nudge/status protocol, or package-level SEDB import occurred.

## RED/GREEN evidence by required cluster

### 1. Application cross-reference boundary — Critical

RED:

```powershell
python -m pytest tests/test_application_decision.py tests/test_application_commit.py -q
```

```text
17 failed, 11 passed in 2.53s
```

The failures included the missing pure reference validator and independently
reproduced acceptance of each sole corruption: instance resident, address
target, claim subject, claim claimant, undeclared authored-by instance,
unsupported on-behalf line, and duplicate instance/address/claim IDs.

GREEN:

```powershell
python -m pytest tests/test_application_decision.py tests/test_application_commit.py -q
```

```text
28 passed in 2.96s
```

`validate_application_references()` is named, pure, deterministic, and called
by `evaluate_application()`. `commit_application()` calls the same evaluation
path before any append.

### 2. Exact acceptance scope — Critical

RED and GREEN used the same application command above. The RED run accepted an
application and authority that substituted
`registry.application.inspect`; the GREEN run returned exactly
`authority_scope_missing`. The exact `registry.application.accept` action is
checked in requested scopes and authority scopes before the additional-scope
subset check.

### 3. Canonical authority grant — Critical

RED and GREEN used the same application command above. RED lacked
`authority.granted`, grant reuse/conflict behavior, digest validation, and
verified grant projection. GREEN proved:

- the first committed event is a canonical `authority.granted` snapshot;
- the grant records its canonical digest, attestation ref, and verified status;
- `application.accepted` binds authority ID, digest, and grant event ID;
- identical active grants are reused and conflicting same-ID content fails
  with `authority_grant_conflict`;
- changed snapshot/digest, unverified authorship, and revocation without a
  prior grant fail closed;
- `project_authorities()` reconstructs principal, subject, scopes, active or
  revoked status, and authorship attestation from grant/revocation events.

### 4. Exact Phase 1B/1C census and representative gate — Important

RED:

```powershell
python -m pytest tests/test_phase1bc_gate.py -q
```

```text
3 failed, 3 passed in 8.07s
```

RED showed no exact required-artifact API, no pinned incident digest in the
report, and no transcript-schema census failure.

GREEN:

```powershell
python -m pytest tests/test_phase1bc_gate.py -q
```

```text
6 passed in 11.73s
```

The final census contains 66 required schemas, runtime modules, fixtures,
corpus artifacts, and validation inputs. It uses required-subset semantics.
Deleting `src/sedb_ral/schemas/transcript-binding.schema.json` produces
`required_artifact_missing:src/sedb_ral/schemas/transcript-binding.schema.json`.
The corpus is pinned to 29 rows and SHA-256
`9a4a504621d6837b0724cbfebc7a9db84a5f260103d9ce585a3087a39a6a3828`.

The integrated report records seven executed positive controls and eleven
executed corrupted controls covering admission, JSON projection/correction,
claim explanation, transcript binding, adapter matrix/delivery, SQLite,
no-send, the Phase 1A negative fixture, and the required transcript schema.

### 5. Attestation and machine-evaluable sufficiency — Important

RED:

```powershell
python -m pytest tests/test_phase1b_contracts.py tests/test_explain.py -q
```

```text
14 failed, 39 passed in 0.76s
```

GREEN:

```powershell
python -m pytest tests/test_phase1b_contracts.py tests/test_explain.py -q
```

```text
53 passed in 0.59s
```

The canonical schema now has only the four spec evidence bases, the four
verification statuses, record status, separate observer/evidence independence,
independence scope, root/derivation/evidence refs, scope, temporal validity,
and `not_claimed`. `shared_root` requires a root. Legacy
`peer_assertion_verified` is rejected canonically and remains only in corpus
mapping.

The final unknown-preservation control was separately proved RED/GREEN:

```powershell
python -m pytest tests/test_explain.py::test_unmeasured_required_policy_term_stays_indeterminate_not_false -q
```

```text
RED:   1 failed in 0.43s
GREEN: included in 19 passed in 13.22s for tests/test_explain.py plus tests/test_phase1bc_gate.py
```

Sufficiency is now `sufficient | insufficient | indeterminate`, requires an
explicit scope policy and comparability relation, counts distinct roots, and
keeps unmeasured/indeterminate terms unknown. Mixed-population tests make basis,
verification, scope overlap, observer independence, and evidence-root
independence each the sole deciding term once.

### 6. Correction target/action/provenance — Important

RED:

```powershell
python -m pytest tests/test_projection.py tests/test_sqlite_projection.py -q
```

```text
15 failed in 5.06s
```

GREEN:

```powershell
python -m pytest tests/test_projection.py tests/test_sqlite_projection.py -q
```

```text
15 passed in 5.12s
```

Projection indexes source events and exact event/entity ownership. `correct`
requires a resolvable replacement claim whose subject, predicate, and object
match the declared display-label change. `withdraw` and `tombstone` use a
separate status branch. Wrong event, wrong entity, unsupported payload, invalid
contract, missing replacement, and mismatched replacement remain append-only
and unapplied with stable reason codes.

### 7. Transcript binding and relay boundary — Important

RED:

```powershell
python -m pytest tests/test_transcript.py -q
```

```text
10 failed, 1 passed in 0.48s
```

GREEN:

```powershell
python -m pytest tests/test_transcript.py -q
```

```text
11 passed in 0.25s
```

`render_turn()` now accepts a complete validated transcript and a stored
`turn_id`; a standalone binding cannot prove membership. Stored turns bind
speaker label, body, and explicit relay metadata. Relays require `relayed_by`,
`relay_is_authorship=false`, `original_claimed_author`, and explicit
`observed_origin` including null. The actual speaker binding owns the rendered
label/swatch. Unbound, newline-label, copied-header-missing, and unobserved
relay controls are executed.

### 8. SQLite provenance — Important

RED/GREEN used the projection command in cluster 6. GREEN proves every derived
instance and address binding has `schema_version: "0.1"`, validates against
`binding.schema.json`, and carries the exact source `resident.registered`
event ID in `valid_from_event`. Every such ref resolves in the canonical input
event set. The synthetic `projection:resident.registered` value is gone.

### 9. Route-scoped adapter matrix — Important

RED:

```powershell
python -m pytest tests/test_delivery.py tests/test_no_send.py -q
```

```text
10 failed, 13 passed in 0.61s
```

GREEN:

```powershell
python -m pytest tests/test_delivery.py tests/test_no_send.py -q
```

```text
23 passed in 0.44s
```

The route matrix now uses route IDs plus source adapter and destination
surface. Every capability has a measurement object separating
`measurement_status` from strict `observed_value: true | false | null`.
Arbitrary strings, bare booleans, numbers, null, and wrong nested objects turn
schema validation red. The measured routes are:

- Codex queue to Codex conversation: `observable`, `true`, fixture evidence;
- PMW Fabric/Herdr to Codex TUI: `observable`, `false`, incident 24 and
  own-execution evidence;
- Claude session to Claude conversation: genuinely `unmeasured`, null.

Route diagnostics receive only extracted `bool | null`.

### 10. No-send structural availability — Important

RED/GREEN used the delivery/no-send command in cluster 9. GREEN distinguishes
a clean scanned package from `package_root_missing`,
`package_root_not_directory`, and `python_source_missing`. The integrated gate
executes a missing-root control as well as forbidden socket-call and forbidden
SEDB-import controls.

### 11. Stale JSON projection output — Minor

RED/GREEN used the projection command in cluster 6. A non-empty output
directory now fails with `projection_output_not_empty`. The
second-rebuild-with-fewer-entities control proves the prior files remain
detectable and cannot be silently mistaken for the new projection.

## Combined focused regression

```powershell
python -m pytest tests/test_application_decision.py tests/test_application_commit.py tests/test_phase1b_contracts.py tests/test_explain.py tests/test_projection.py tests/test_sqlite_projection.py tests/test_transcript.py tests/test_delivery.py tests/test_no_send.py tests/test_phase1bc_gate.py tests/test_cli_smoke.py tests/test_packaging.py tests/test_incidents.py tests/test_codex_queue_adapter.py -q
```

```text
162 passed in 24.49s
```

## Full gates

### Full suite — executed exactly once

```powershell
python -m pytest -q
```

Captured progress:

```text
........................................................................ [ 27%]
........................................................................ [ 54%]
...........s............................................................ [ 81%]
.......................
```

The process completed after the initial 30-second capture window. Fresh pytest
completion evidence was:

```text
.pytest_cache/v/cache/lastfailed = {}
nodeids=268
```

The progress stream contained exactly one `s` and no `F`/`E`, giving the
observed full result `267 passed, 1 skipped`. The skipped control was then
identified without rerunning the full suite:

```powershell
python -m pytest -q tests/test_ledger.py -rs
```

```text
31 passed, 1 skipped in 1.56s
SKIPPED tests/test_ledger.py:323: directory symlink unavailable: [WinError 1314]
```

### Phase 1A integrated gate

```powershell
python scripts/validate_phase1a.py
```

Exit `0`:

```json
{"checked_fixtures":["fixtures/ctcl/reading.json","fixtures/ctcl/registered-anchor.json","fixtures/identifier/mixed_population/manifest.json","fixtures/identifier/mixed_population/one-resident.json","fixtures/identifier/negative/shared-runtime-tag.json","fixtures/identifier/positive/resident-address.json","fixtures/ledger/event-001.json","fixtures/ledger/event-002.json"],"checked_schemas":["ctcl-receipt.schema.json","identifier-discrimination.schema.json","identifier-field.schema.json","ledger-event.schema.json"],"error_codes":[],"ledger_status":"checkpoint_verified","observed_decisions":["admit","indeterminate","reject"],"passed":true}
```

### Basic Phase 1B/1C integrated gate

```powershell
python scripts/validate_phase1bc.py
```

Exit `0`; canonical result:

```json
{"delivery_stage":"instance_acknowledged","error_codes":[],"executed_faults":[{"executed":true,"expected_red_code":"negative_fixture_missing","observed_red_code":"negative_fixture_missing","test_name":"phase1a_missing_negative_fixture"},{"executed":true,"expected_red_code":"required_artifact_missing:src/sedb_ral/schemas/transcript-binding.schema.json","observed_red_code":"required_artifact_missing:src/sedb_ral/schemas/transcript-binding.schema.json","test_name":"required_transcript_schema_missing"},{"executed":true,"expected_red_code":"application_claim_subject_mismatch","observed_red_code":"application_claim_subject_mismatch","test_name":"admission_cross_resident"},{"executed":true,"expected_red_code":"correction_target_event_mismatch","observed_red_code":"correction_target_event_mismatch","test_name":"projection_wrong_correction_target"},{"executed":true,"expected_red_code":"scope_overlap_missing","observed_red_code":"scope_overlap_missing","test_name":"claim_explanation_scope_mismatch"},{"executed":true,"expected_red_code":"speaker_resolution_indeterminate","observed_red_code":"speaker_resolution_indeterminate","test_name":"transcript_unbound_turn"},{"executed":true,"expected_red_code":"schema_invalid","observed_red_code":"schema_invalid","test_name":"adapter_matrix_invalid_submit"},{"executed":true,"expected_red_code":"sqlite_projection_mismatch","observed_red_code":"sqlite_projection_mismatch","test_name":"sqlite_projection_mutation"},{"executed":true,"expected_red_code":"package_root_missing","observed_red_code":"package_root_missing","test_name":"no_send_package_missing"},{"executed":true,"expected_red_code":"forbidden_call:socket.create_connection","observed_red_code":"forbidden_call:socket.create_connection","test_name":"no_send_socket_call"},{"executed":true,"expected_red_code":"forbidden_import:sedb","observed_red_code":"forbidden_import:sedb","test_name":"no_send_sedb_import"}],"executed_positive_controls":[{"executed":true,"expected_red_code":"positive","observed_red_code":"positive","test_name":"admission_positive"},{"executed":true,"expected_red_code":"positive","observed_red_code":"positive","test_name":"projection_correction_positive"},{"executed":true,"expected_red_code":"positive","observed_red_code":"positive","test_name":"claim_explanation_positive"},{"executed":true,"expected_red_code":"positive","observed_red_code":"positive","test_name":"transcript_binding_positive"},{"executed":true,"expected_red_code":"positive","observed_red_code":"positive","test_name":"adapter_matrix_delivery_positive"},{"executed":true,"expected_red_code":"positive","observed_red_code":"positive","test_name":"sqlite_projection_positive"},{"executed":true,"expected_red_code":"positive","observed_red_code":"positive","test_name":"no_send_positive"}],"incident_count":29,"incident_sha256":"9a4a504621d6837b0724cbfebc7a9db84a5f260103d9ce585a3087a39a6a3828","no_send_findings":[],"passed":true,"phase1a_passed":true,"required_artifact_count":66,"sqlite_bytes_identical":true,"sqlite_row_counts":{"addresses":0,"applications":1,"attestations":0,"bindings":1,"claims":1,"deliveries":0,"projection_meta":4,"residents":1}}
```

### Installed CLI gate

The executable was installed at
`C:/Users/kakon/AppData/Local/Python/pythoncore-3.14-64/Scripts/sedb-ral.exe`
but was not on PATH. It was run with a process-local PATH only:

```powershell
$env:PATH = 'C:\Users\kakon\AppData\Local\Python\pythoncore-3.14-64\Scripts;' + $env:PATH
sedb-ral phase1bc verify .
```

Exit `0`; output was byte-for-byte the same canonical Phase 1B/1C report shown
above.

### Diff, SQLite artifact, and historical checkpoint gates

```powershell
git diff --check
```

Exit `0`; no output.

```powershell
rg --files -g '*.sqlite3' -g '!*.sqlite3-journal' .
```

Exit `1`; no matches, which is the expected clean repository result.

```powershell
python -m pytest -q tests/test_phase1a_checkpoint.py
```

```text
3 passed in 3.00s
```

## Files changed in implementation commit `383f793`

- `fixtures/adapters/matrix.json`
- `src/sedb_ral/application.py`
- `src/sedb_ral/delivery.py`
- `src/sedb_ral/explain.py`
- `src/sedb_ral/no_send.py`
- `src/sedb_ral/phase1bc.py`
- `src/sedb_ral/projection.py`
- `src/sedb_ral/schemas/adapter-matrix.schema.json`
- `src/sedb_ral/schemas/attestation.schema.json`
- `src/sedb_ral/schemas/transcript-binding.schema.json`
- `src/sedb_ral/sqlite_projection.py`
- `src/sedb_ral/transcript.py`
- `tests/test_application_commit.py`
- `tests/test_application_decision.py`
- `tests/test_delivery.py`
- `tests/test_explain.py`
- `tests/test_no_send.py`
- `tests/test_phase1b_contracts.py`
- `tests/test_phase1bc_gate.py`
- `tests/test_projection.py`
- `tests/test_sqlite_projection.py`
- `tests/test_transcript.py`

## Self-review

- Re-read all eleven brief findings against the final source and tests.
- Confirmed the binding spec wins over the older plan in attestation shape,
  categorical evidence semantics, explicit relay provenance, exact authority,
  and unknown preservation.
- Confirmed application authority is checked before writes and is reconstructed
  from canonical grant/revocation events rather than applicant payload claims.
- Confirmed every new gate has a positive control and an independently derived
  corruption control.
- Confirmed projection source events remain append-only and every correction
  failure is retained with a reason.
- Confirmed no generated JSON output is rebuilt in place over stale files.
- Confirmed SQLite remains disposable and no SQLite artifact is committed.
- Confirmed route measurements and route diagnostic truth values remain
  separate.
- Confirmed `git diff --check` is clean and no unrelated pre-existing worktree
  changes were present or modified.

## Unresolved concerns

- Windows directory-symlink coverage remains explicitly unverified because this
  process lacks symlink privilege (`WinError 1314`). The junction/reparse-point
  coverage and all other ledger controls passed. No other unresolved concern is
  known.

## Boundary confirmations

- Phase 2 was not started.
- No SEDB adapter or SEDB import was added under `src/sedb_ral`.
- No network or provider-send capability was added or invoked.
- No Claude, Herdr, PMW Fabric, Codex queue, or other provider message was sent.
- No provider CLI was launched; only the local installed `sedb-ral` verifier was
  run.
- The proposed nudge/status protocol was not implemented.
- No push, merge, release, deployment, publication, or protected-branch action
  occurred.

## Residual Fix Cycle

### Status and scope

PASS. The controller-authorized residual cycle changed only the three
load-bearing findings from the final re-review. The implementation commit is
`cd3ee44da807a6012f7fc52abaadf727b315db16` (`fix: close residual
Phase 1BC review gaps`). This appended report section is carried by the
immediately following local documentation commit, identified as `HEAD` at
handoff and returned with its exact hash in the final response.

No Phase 2 work, push, merge, send, provider CLI, nudge implementation, or
package-level SEDB import occurred.

### Residual 1 — post-revocation projection authority

RED:

```powershell
python -m pytest tests/test_projection.py::test_revoked_grant_cannot_authorize_later_acceptance_or_registration -q
```

```text
1 failed in 0.74s
AssertionError: expected application status 'submitted', observed 'accepted'
```

GREEN:

```powershell
python -m pytest tests/test_projection.py::test_revoked_grant_cannot_authorize_later_acceptance_or_registration -q
```

```text
1 passed in 0.51s
```

Root cause: `project_events()` indexed `authority.granted` but the
`authority.revoked` branch only indexed an event/entity relationship; it never
invalidated the grant for later acceptance.

Minimal fix: projection now records exactly matched revoked grant event IDs.
A later `application.accepted` bound to one of those IDs remains unapplied with
`application_authority_grant_revoked`; its following `resident.registered`
remains unapplied with `resident_registration_not_authorized`. Grant,
revocation, acceptance, and registration event IDs all remain in
`source_event_ids`.

### Residual 2 — plan-required test evidence census

RED:

```powershell
python -m pytest tests/test_phase1bc_gate.py -q -k "task_test_artifact or missing_required_test_artifact"
```

```text
17 failed, 7 deselected in 4.32s
```

All sixteen Task 1–10 test deletions escaped `_required_artifact_errors()`, and
deleting `tests/test_explain.py` left `validate_phase1bc()` green.

GREEN:

```powershell
python -m pytest tests/test_phase1bc_gate.py -q -k "task_test_artifact or missing_required_test_artifact"
```

```text
17 passed, 7 deselected in 3.95s
```

`REQUIRED_PHASE1BC_ARTIFACTS` now includes these plan-named test evidence
files:

- `tests/test_application_commit.py`
- `tests/test_application_decision.py`
- `tests/test_codex_queue_adapter.py`
- `tests/test_delivery.py`
- `tests/test_explain.py`
- `tests/test_incidents.py`
- `tests/test_ledger.py`
- `tests/test_no_send.py`
- `tests/test_packaging.py`
- `tests/test_phase1a_checkpoint.py`
- `tests/test_phase1a_gate.py`
- `tests/test_phase1b_contracts.py`
- `tests/test_phase1bc_gate.py`
- `tests/test_projection.py`
- `tests/test_sqlite_projection.py`
- `tests/test_transcript.py`

Every listed deletion produces its exact
`required_artifact_missing:tests/...` census error. The full repository gate is
also executed against a missing `tests/test_explain.py` control. Later Phase 2
artifacts remain allowed through required-subset semantics. The required
artifact count increased from 66 to 82.

### Residual 3 — derived shared-root sufficiency

RED:

```powershell
python -m pytest tests/test_explain.py::test_derived_shared_root_population_cannot_satisfy_independent_root_policy -q
```

```text
1 failed in 0.40s
AssertionError: expected sufficiency 'insufficient', observed 'sufficient'
```

GREEN:

```powershell
python -m pytest tests/test_explain.py::test_derived_shared_root_population_cannot_satisfy_independent_root_policy -q
```

```text
1 passed in 0.17s
```

Root cause: sufficiency inspected only each row's declared
`evidence_independence_status`. Two rows could each declare `independent` while
sharing one root; the explanation correctly derived population status
`shared_root`, but that derived result was not an input to policy evaluation.

Minimal fix: `_evaluate_sufficiency()` now consumes the derived population
evidence-independence status. A policy requiring `independent` roots fails
closed with `evidence_independence_insufficient` when the population derives
`shared_root`; derived `unmeasured` or `indeterminate` remains indeterminate.

### Focused residual regression

```powershell
python -m pytest tests/test_projection.py tests/test_explain.py tests/test_phase1bc_gate.py -q
```

```text
51 passed in 19.59s
```

### Residual full gates

Full suite, executed once for this residual cycle:

```powershell
python -m pytest -q
```

```text
283 passed, 1 skipped in 33.15s
SKIPPED tests/test_ledger.py:323: directory symlink unavailable: [WinError 1314]
```

Phase 1A:

```powershell
python scripts/validate_phase1a.py
```

Exit `0`:

```json
{"checked_fixtures":["fixtures/ctcl/reading.json","fixtures/ctcl/registered-anchor.json","fixtures/identifier/mixed_population/manifest.json","fixtures/identifier/mixed_population/one-resident.json","fixtures/identifier/negative/shared-runtime-tag.json","fixtures/identifier/positive/resident-address.json","fixtures/ledger/event-001.json","fixtures/ledger/event-002.json"],"checked_schemas":["ctcl-receipt.schema.json","identifier-discrimination.schema.json","identifier-field.schema.json","ledger-event.schema.json"],"error_codes":[],"ledger_status":"checkpoint_verified","observed_decisions":["admit","indeterminate","reject"],"passed":true}
```

Basic Phase 1B/1C:

```powershell
python scripts/validate_phase1bc.py
```

Exit `0`; the canonical report had `passed:true`, `phase1a_passed:true`,
`error_codes:[]`, `required_artifact_count:82`, incident count `29`, incident
SHA-256
`9a4a504621d6837b0724cbfebc7a9db84a5f260103d9ce585a3087a39a6a3828`,
`sqlite_bytes_identical:true`, no no-send findings, all seven positive controls
observed as positive, and all eleven corrupted controls observed with their
expected red codes.

Installed CLI:

```powershell
$env:PATH = 'C:\Users\kakon\AppData\Local\Python\pythoncore-3.14-64\Scripts;' + $env:PATH
sedb-ral phase1bc verify .
```

Exit `0`; output matched the script gate, including
`required_artifact_count:82` and `error_codes:[]`.

Remaining gates:

```powershell
git diff --check
# exit 0; no output

rg --files -g '*.sqlite3' -g '!*.sqlite3-journal' .
# exit 1; no matches, expected clean result

python -m pytest -q tests/test_phase1a_checkpoint.py
# 3 passed in 2.94s
```

### Residual files changed

- `src/sedb_ral/explain.py`
- `src/sedb_ral/phase1bc.py`
- `src/sedb_ral/projection.py`
- `tests/test_explain.py`
- `tests/test_phase1bc_gate.py`
- `tests/test_projection.py`
- `.superpowers/sdd/2026-08-23-basic-phase-1b-1c/final-fix-report.md`

### Residual concerns and boundary confirmations

- The only unresolved verification limitation remains the Windows
  directory-symlink privilege skip (`WinError 1314`); no test failed.
- Canonical source events remain append-only and retained in projection source
  IDs even when their effect is unapplied.
- No Phase 2 file or SEDB adapter/import was added under `src/sedb_ral`.
- No network/provider send, provider CLI, nudge protocol, push, merge, release,
  deployment, or publication action occurred.

## Second Residual Fix

### Status and scope

PASS. This cycle changes only the final event-order Critical: an accepted
application whose bound authority is revoked before `resident.registered` may
retain accepted/source history but may not create a resident.

The implementation commit is
`19cf79f2e89d3ac0747b7077218625293e1924a3` (`fix: recheck authority at
resident projection`). This section is carried by the immediately following
local documentation commit, identified as `HEAD` at handoff and returned with
its exact hash in the final response.

### Focused RED

```powershell
python -m pytest tests/test_projection.py::test_intervening_revocation_blocks_registration_without_erasing_acceptance -q
```

```text
1 failed in 0.72s
AssertionError: projection.residents contained resident:test instead of {}
```

The failing sequence was:

```text
authority.granted
application.submitted
application.accepted
authority.revoked
resident.registered
```

The application correctly remained accepted, but registration trusted that
prior status without rechecking the application-bound grant at the current
ledger sequence.

### Minimal GREEN

At `resident.registered`, projection now resolves the accepted application's
stored `authority_grant_event_id`, `authority_ref`, and `authority_digest`
against the canonical grant index and checks the matched grant against the
revocation set. An intervening revocation leaves registration unapplied with
`resident_registration_authority_revoked`.

Accepted application fields and all grant/submit/accept/revoke/register source
event IDs remain present. No accepted history is erased.

The new control and the normal accept→register positive control were run
together:

```powershell
python -m pytest tests/test_projection.py::test_intervening_revocation_blocks_registration_without_erasing_acceptance tests/test_projection.py::test_projection_rebuilds_application_resident_and_directory -q
```

```text
2 passed in 1.12s
```

### Focused regression

```powershell
python -m pytest tests/test_projection.py tests/test_phase1bc_gate.py -q
```

```text
38 passed in 19.24s
```

### Full gates

Full suite, executed once for this second residual cycle:

```powershell
python -m pytest -q
```

```text
284 passed, 1 skipped in 35.12s
SKIPPED tests/test_ledger.py:323: directory symlink unavailable: [WinError 1314]
```

Phase 1A:

```powershell
python scripts/validate_phase1a.py
```

Exit `0`; `passed:true`, `error_codes:[]`, ledger status
`checkpoint_verified`, and observed decisions `admit`, `indeterminate`, and
`reject`.

Basic Phase 1B/1C:

```powershell
python scripts/validate_phase1bc.py
```

Exit `0`; `passed:true`, `phase1a_passed:true`, `error_codes:[]`,
`required_artifact_count:82`, incident count `29`, pinned incident SHA-256
`9a4a504621d6837b0724cbfebc7a9db84a5f260103d9ce585a3087a39a6a3828`,
`sqlite_bytes_identical:true`, no no-send findings, and every recorded positive
and corrupted control matched its expected outcome.

Installed CLI:

```powershell
$env:PATH = 'C:\Users\kakon\AppData\Local\Python\pythoncore-3.14-64\Scripts;' + $env:PATH
sedb-ral phase1bc verify .
```

Exit `0`; output matched the script gate, including
`required_artifact_count:82` and `error_codes:[]`.

Remaining gates:

```powershell
git diff --check
# exit 0; no output

rg --files -g '*.sqlite3' -g '!*.sqlite3-journal' .
# exit 1; no matches, expected clean result

python -m pytest -q tests/test_phase1a_checkpoint.py
# 3 passed in 3.00s
```

### Files changed

- `src/sedb_ral/projection.py`
- `tests/test_projection.py`
- `.superpowers/sdd/2026-08-23-basic-phase-1b-1c/final-fix-report.md`

### Concerns and boundary confirmations

- The only unresolved verification limitation remains the Windows
  directory-symlink privilege skip (`WinError 1314`); no test failed.
- No other cluster, Phase 2 file, SEDB adapter/import, provider send or CLI,
  nudge protocol, push, merge, release, deployment, or publication was touched
  or performed.
