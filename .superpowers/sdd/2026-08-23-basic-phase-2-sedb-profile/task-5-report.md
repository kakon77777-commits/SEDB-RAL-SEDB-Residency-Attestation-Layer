# Basic Phase 2 — Task 5 report

Status: completed and committed locally.

Commit: `d6203b9 test: exercise the real SEDB v0.4B package`

## Delivered

- Added
  `run_integration(archive, adoption_profile, projection, mapping, output) -> SEDBIntegrationResult`
  in `scripts/validate_sedb_v04b.py`.
- The runner derives `expected_records` from the supplied `RegistryProjection`
  and checked-in mapping before creating a temp tree, extracting the archive,
  importing SEDB, or constructing any SEDB service.
- Every run creates a fresh `sedb-ral-v04b-*` directory beneath the caller's
  temporary output directory, calls `extract_verified_sedb` into its
  `extracted` child, and loads SEDB only from the verified package's `src`.
- The import context temporarily removes any preloaded `sedb` modules, adds
  only the verified extracted `src` to process-local `sys.path`, checks the
  origin of `Database`, `FieldService`, `EntityService`, and
  `ExchangeService`, then restores both `sys.path` and the prior module cache.
- The real v0.4B services are passed directly to Task 4's
  `apply_sedb_records`; no `src/sedb_ral` module imports SEDB and no service API
  adapter was needed.
- The runner creates `sedb.sqlite`, executes `PRAGMA integrity_check`, exports
  JSONL through the real `ExchangeService`, reads the raw export, applies the
  explicit script-local export-shape adapter described below, and compares the
  normalized records exactly with the independently derived expected tuple.
- The structured result preserves temp/package/database/export paths, Task 4
  apply counts, integrity, expected/export counts, raw and normalized records,
  exact-match status, adapter identity, and `execution_claim="own_execution"`.

## Script-local export-shape adapter

The pinned v0.4B `ExchangeService.export_jsonl` emits each field's local key
but not its separately stored namespace. Task 4 correctly creates field
`key="resident_id"` with `namespace="sedb_ral"`, so raw JSONL contains
`resident_id` while the independent RAL record contains `ral.resident_id`.

Task 5 therefore includes the explicit, fail-closed script-local adapter
`v04b_local_field_keys_to_ral_paths`. It reconstructs each RAL path solely
from the checked-in mapping's one-to-one `sedb_target` rules, rejects unknown
or duplicate local keys, preserves the raw on-disk records separately, and
does not modify `src/sedb_ral` or infer authority. Focused tests cover the
normal mapping and an unmapped `authority` field rejection.

## TDD and focused integration evidence

- Missing-runner RED:
  `python -m pytest tests/test_sedb_v04b_integration.py -q` failed during
  collection with
  `ModuleNotFoundError: No module named 'scripts.validate_sedb_v04b'`.
- First real-service run: `1 failed, 2 passed`; the failure exposed the raw
  local-key export shape (`resident_id`) against the independently expected
  RAL path (`ral.resident_id`).
- Adapter RED: collection failed with
  `ImportError: cannot import name '_adapt_sedb_export'`.
- Focused GREEN: `5 passed in 0.95s`.
- The focused suite covers the exact pinned archive round trip, mapping
  preflight before temp/runtime creation, present-wrong-archive failure,
  explicit export normalization, unmapped-export rejection, temp-only paths,
  import-cache restoration, and exact expected/export equality.

## Real integration result

- Archive: `C:\Users\kakon\Downloads\SEDB\SEDB-v0.4B-local.zip`
- Size: `8980052` bytes
- SHA-256:
  `159F0928415811A434E885D50E94846266474725723D25DAC426170874B844D8`
- Package/source/manifest verification: enforced by the checked-in adoption
  profile and `extract_verified_sedb` before extraction is adopted.
- SQLite integrity: `ok`
- Applied: 8 fields, 1 entity, 7 cells
- Expected/exported: 1 / 1 record
- Exact mapped record equality: `true`
- Integration claim source: `own_execution`

## Inherited SEDB v0.4B suite

Command: `python -m pytest -q`, with cwd at the verified extracted
`SEDB-v0.4B-local` package root.

Result: **189 passed, 0 failed, 0 skipped in 40.12s**.

This is an `own_execution` result for this environment only. It does not
replace or merge with any package release claim.

## Full RAL suite

Command: process-local `PYTHONPATH=<this worktree>\src`, then
`python -m pytest -q`.

Result: **362 passed, 0 failed, 1 skipped in 35.00s**.

The sole skip is the established Windows directory-symlink privilege control
at `tests/test_ledger.py:323` (`WinError 1314`).

## Boundaries and concerns

- No live `D:\Ai\work together\SEDB` executable source was read or used.
- No database, extracted package, sidecar, authority installation, canonical
  SEDB commit, send, registrar, federation, push, merge, or release was added
  to the repository or performed.
- The machine's global editable `sedb-ral` install points to the separate
  `phase-1a-deterministic-core` worktree. All RAL verification therefore used
  this worktree's `src` through process-local `PYTHONPATH`; the global install
  was not changed.
- Cleanup of the two explicit development verification trees was refused by
  the shell safety layer before command launch. They remain outside the repo
  at
  `C:\Users\kakon\AppData\Local\Temp\sedb-ral-api-inspection-20260824-task5`
  and
  `C:\Users\kakon\AppData\Local\Temp\sedb-ral-task5-verification-20260824`.
  They contain only verified extracted/temp integration artifacts and are not
  tracked. No bypass was attempted.
- Branch/worktree are preserved locally at
  `feat/basic-phase2-sedb-profile` / the supplied linked worktree. No push,
  merge, release, reviewer, or subagent action occurred.

## Fix Round 1/5

Status: completed and committed locally.

Commit: `3fee29f fix: harden isolated SEDB integration`

### Review findings reproduced

- On baseline `d6203b9`, `_adapt_sedb_export((), ambiguous_mapping)` accepted
  an empty export when two distinct local keys mapped to the same
  `ral.resident_id`; record adaptation could therefore overwrite one value.
- On baseline `d6203b9`, a real pinned-archive integration returned integrity
  `ok` and exact records, but immediate `TemporaryDirectory` cleanup raised
  `PermissionError: [WinError 32]` on the returned `sedb.sqlite`. Diagnostic
  cleanup succeeded only after `gc.collect`, confirming retained upstream
  SQLite connections as the cause.

### Corrections

- Export mapping construction now tracks both local SEDB keys and destination
  RAL paths. Duplicate local keys retain the existing fail-closed control;
  duplicate destination paths raise
  `sedb_export_mapping_duplicate_destination:<ral_path>` before any record is
  adapted, including for an empty export.
- The validator creates a script-local subclass of the verified real SEDB
  `Database` for each run. Its `connect()` records every connection returned
  to the real services.
- The `PRAGMA integrity_check` connection is explicitly closed and removed
  from the tracker. After all apply/integrity/export operations, field,
  entity, exchange, and database references are dropped in `finally`; every
  remaining tracked connection is closed before the isolated import context
  restores `sys.path` and `sys.modules`.
- `SEDBIntegrationResult` remains path/data-only and continues to preserve raw
  exported records separately from normalized comparison records.

### TDD and verification evidence

- Adapter RED: the two focused controls produced `1 failed, 1 passed`; the
  duplicate-destination test failed because no exception was raised, while
  the duplicate-local control remained green.
- Adapter GREEN: all normal, unknown-local, duplicate-local, and
  duplicate-destination controls passed: `4 passed, 3 deselected in 0.18s`.
- Cleanup RED: the real pinned integration failed at immediate
  `shutil.rmtree(result.temp_root)` and again at `TemporaryDirectory.__exit__`
  with `WinError 32` on `sedb.sqlite`.
- Cleanup GREEN: the exact real integration cleanup test passed without
  importing or calling `gc`: `1 passed in 0.94s`.
- Focused Task 5 suite: **8 passed, 0 failed, 0 skipped in 1.71s**.
- Full RAL suite, run once after both fixes: **365 passed, 0 failed, 1 skipped
  in 36.51s**. The sole skip remains `tests/test_ledger.py:323`, where Windows
  directory-symlink privilege is unavailable (`WinError 1314`).
- The inherited SEDB suite was not rerun because neither the immutable package
  nor its source changed. The earlier report's `189 passed, 0 failed,
  0 skipped` remains the last inherited own-execution result and is not
  represented as a new execution for this fix round.

### Boundaries and remaining debt

- No Task 6, live SEDB checkout access, source-package mutation, send,
  authority installation, registrar, federation, push, merge, release,
  reviewer, or subagent action occurred.
- The deferred Minor module-cache identity test remains final-review debt;
  runtime identity restoration behavior was not changed in this round.
- The cleanup RED process left one now-unlocked temporary diagnostic tree at
  `C:\Users\kakon\AppData\Local\Temp\sedb-ral-v04b-cleanup-2c2c6xdg`.
  It is outside the repository and untracked. Recursive deletion was not
  bypassed.
