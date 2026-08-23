# Basic Phase 2 final whole-branch fix report

## Scope and authority

- Worktree: D:\Ai\work together\SEDB-RAL\.worktrees\basic-phase2-sedb-profile
- Branch: feat/basic-phase2-sedb-profile
- Fix base: a08787c917818940d6163244c37bc02ba33125cf
- Binding brief: .superpowers/sdd/2026-08-23-basic-phase-2-sedb-profile/final-review-fix-brief.md
- The live D:\Ai\work together\SEDB checkout was neither inspected nor executed.
- VALIDATION_BASIC_PHASE2.json was not modified.
- No network message, registrar/federation action, authority installation,
  subagent, or reviewer was used.

## Untouched baseline

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest -q
~~~

Output (exit 0):

~~~text
419 passed, 1 skipped in 42.77s
~~~

The skip was the pre-existing Windows directory-symlink privilege control
(WinError 1314).

## 1. Three-class differential authority

### 1A. Comparison-only authority projection

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_sedb_mapping.py::test_comparison_projection_adds_authority_without_changing_write_records -q
~~~

RED output (exit 1):

~~~text
AssertionError: Phase 2 needs a comparison-only projection distinct from SEDB writes
1 failed in 0.32s
~~~

GREEN output after the minimal comparison projector (exit 0):

~~~text
1 passed in 0.16s
~~~

The original write projection remained unchanged and contained no
ral.authority value. The comparison projection added only authority_ref and
authority_digest from the canonical Phase 1 application.

### 1B. Unknown Task 5 export fields

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_sedb_v04b_integration.py::test_v04b_export_adapter_preserves_unknown_field_for_comparison -q
~~~

RED output (exit 1):

~~~text
ValueError: sedb_export_field_unmapped:authority
1 failed in 0.37s
~~~

GREEN regression command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_sedb_v04b_integration.py::test_v04b_export_adapter_preserves_unknown_field_for_comparison tests/test_sedb_v04b_integration.py::test_v04b_export_adapter_rejects_duplicate_local_key_before_adaptation tests/test_sedb_v04b_integration.py::test_v04b_export_adapter_rejects_duplicate_ral_path_before_adaptation -q
~~~

GREEN output (exit 0):

~~~text
3 passed in 0.20s
~~~

Unknown local keys now survive under sedb_unmapped.<local_key>. Duplicate
local and duplicate destination mappings still fail closed.

### 1C. Real authority omission is expected_by_mapping

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_phase2_gate.py::test_basic_phase2_gate_passes_exact_archive -q
~~~

RED output (exit 1):

~~~text
assert 0 >= 1
1 failed in 4.16s
~~~

GREEN output (exit 0):

~~~text
1 passed in 3.92s
~~~

The real integrated run now reports one comparison-only authority omission as
expected_by_mapping and passes with zero contradictions.

### 1D. Nonexact diagnostics are nonfatal when contradiction-free

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_phase2_gate.py::test_unknown_actual_field_is_unmapped_and_overall_passes -q
~~~

RED output (exit 1):

~~~text
Phase2Report(... passed=False, error_codes=('sedb_integration_failed',))
1 failed in 4.16s
~~~

GREEN output after removing records_match as an independent fatal condition
(exit 0):

~~~text
1 passed in 3.87s
~~~

Observed GREEN report: records_match=false, expected_by_mapping=1, unmapped=1,
contradiction=0, passed=true. Database integrity remained mandatory.

### 1E. Mapped contradiction negative control

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_phase2_gate.py::test_mapped_actual_field_contradiction_fails_overall -q
~~~

Output (exit 0; the asserted Phase 2 report itself is RED):

~~~text
1 passed in 3.95s
~~~

Observed report: passed=false, records_match=false, expected_by_mapping=1,
unmapped=0, contradiction=1, sole error sedb_mapping_contradiction.

### 1F. Final writer follows the differential

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_phase2_gate.py::test_writer_accepts_nonexact_diagnostics_when_allowed_differences_agree -q
~~~

RED output (exit 1):

~~~text
RALValidationError: sedb_records_mismatch: SEDB records do not match
1 failed in 4.17s
~~~

GREEN output after removing exact equality/count diagnostics as writer
vetoes (exit 0):

~~~text
1 passed in 4.05s
~~~

### 1G. Differential count/list consistency

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_phase2_gate.py::test_writer_rejects_differential_count_list_mismatch -q
~~~

RED output (exit 1):

~~~text
Failed: DID NOT RAISE RALValidationError
1 failed in 4.17s
~~~

GREEN regression command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_phase2_gate.py::test_writer_rejects_differential_count_list_mismatch tests/test_phase2_gate.py::test_writer_accepts_nonexact_diagnostics_when_allowed_differences_agree tests/test_phase2_gate.py::test_writer_rejects_contradiction_even_when_report_says_passed -q
~~~

GREEN output (exit 0):

~~~text
3 passed in 4.10s
~~~

Semantic validation now recomputes all three counts from the list, rejects
unknown or malformed classifications, requires passed=true, and requires zero
contradictions.

Section 1 full focused regression:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_sedb_mapping.py tests/test_sedb_diff.py tests/test_sedb_v04b_integration.py tests/test_phase2_gate.py -q
~~~

~~~text
75 passed in 13.23s
~~~

## 2. Exact adopted-profile facts

### 2A. JSON Schema

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_phase2_gate.py::test_v02_receipt_schema_binds_exact_adopted_profile_facts -q
~~~

RED output (exit 1):

~~~text
.FFF
package-version: DID NOT RAISE
source-commit: DID NOT RAISE
mapping-digest: DID NOT RAISE
3 failed, 1 passed in 4.22s
~~~

The package-name case was already exact. GREEN after scoping all four exact
facts to v0.2 receipts:

~~~text
4 passed in 3.99s
~~~

### 2B. Semantic writer and coherent tampering

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_phase2_gate.py::test_writer_rejects_coherently_reidentified_profile_tampering -q
~~~

RED output (exit 1):

~~~text
All four mutations reached only schema_invalid instead of the independent
semantic code sedb_profile_identity_mismatch.
4 failed in 4.37s
~~~

Each mutated report had its compatibility subject and final receipt ID
recomputed first. GREEN output:

~~~text
4 passed in 4.48s
~~~

Existing archive, manifest, adoption-profile, and mapping-profile constants:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_phase2_gate.py::test_writer_retains_existing_exact_profile_constants -q
~~~

~~~text
9 passed in 4.06s
~~~

Section 2 full focused regression:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_sedb_profiles.py tests/test_phase2_gate.py -q
~~~

~~~text
58 passed in 11.67s
~~~

## 3. Task 5 no-send boundary

### 3A. Positive executable scan

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_no_send.py::test_task5_script_allows_only_its_isolated_sedb_imports -q
~~~

RED output (exit 1):

~~~text
AssertionError: Task 5 executable boundary is not scanned
1 failed in 0.17s
~~~

Initial GREEN output after adding the exact four-import allowance:

~~~text
1 passed in 0.04s
~~~

### 3B. Package-gate separation investigation

The first implementation shared Task 5's broad urllib denylist with package
code. The existing package positive control caught the mistake:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_no_send.py::test_source_tree_contains_no_send_capability -q
~~~

~~~text
NoSendFinding(code='forbidden_import:urllib.parse', path='projection.py', line=7)
1 failed in 0.27s
~~~

Root cause: package code legitimately uses non-network urllib.parse; Task 5
must reject broad urllib/http imports. Separate denylists restored the package
contract:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_no_send.py::test_source_tree_contains_no_send_capability tests/test_no_send.py::test_task5_script_allows_only_its_isolated_sedb_imports -q
~~~

~~~text
2 passed in 0.15s
~~~

### 3C. Phase 2 consumes script findings

An initial run of the injected-network test returned 1 passed in 4.04s for the
wrong reason: the temporary global denylist had already made the package scan
red. After correcting that confounder, the same command produced the intended
RED:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_phase2_gate.py::test_phase2_gate_rejects_injected_task5_network_call -q
~~~

~~~text
Phase2Report(... passed=True, error_codes=())
1 failed in 4.21s
~~~

The injected script scanner had already observed
forbidden_call:socket.create_connection; Phase 2 had ignored it. GREEN after
combining package and Task 5 findings:

~~~text
1 passed in 3.93s
~~~

Section 3 full focused regression:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_no_send.py tests/test_phase2_gate.py::test_phase2_gate_rejects_injected_task5_network_call tests/test_phase2_gate.py::test_basic_phase2_gate_passes_exact_archive -q
~~~

~~~text
16 passed in 8.02s
~~~

Additional AST controls cover requests, broad urllib, broad http, subprocess,
and an unapproved SEDB import.

## 4. README and packaging boundary

### 4A. Real wheel-content behavior

The first clean copied-source build failed during setup because the active
interpreter lacked the separately declared wheel package:

~~~text
ERROR Missing dependencies:
    wheel
1 failed in 1.56s
~~~

No network installation was attempted. The build frontend used
--no-isolation --skip-dependency-check; the installed setuptools backend then
successfully produced the real wheel:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_packaging.py::test_phase2_repository_gate_is_not_claimed_as_self_contained_in_wheel -q
~~~

~~~text
1 passed in 2.00s
~~~

The wheel contains the Phase 2 receipt schema and excludes repository-only
profiles, scripts, and VALIDATION_BASIC_PHASE2.json.

### 4B. README contract

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_packaging.py::test_readme_names_basic_phase2_commands_pins_and_boundaries -q
~~~

RED output (exit 1):

~~~text
assert '$env:PYTHONPATH = "src"' in the Basic Phase 1 README
1 failed in 0.20s
~~~

GREEN output:

~~~text
1 passed in 0.05s
~~~

Combined section output:

~~~text
2 passed in 1.97s
~~~

README now states every exact archive/package/source/manifest fact, isolated
integration and differential semantics, Windows ENOTSUP behavior, source
checkout packaging scope, no-live-checkout/Phase-3/send boundaries, validation
and real-integration commands, reproducible build, clean install, and manual
staging cleanup.

## 5. Canonical malformed diagnostics

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_sedb_diff.py::test_malformed_record_collections_have_stable_canonical_diagnostics -q
~~~

RED output (exit 1):

~~~text
AssertionError: raw frozenset did not equal the explicit diagnostic envelope
1 failed in 0.35s
~~~

GREEN output:

~~~text
1 passed in 0.16s
~~~

Full differential output:

~~~text
25 passed in 0.19s
~~~

Set, frozenset, and tuple diagnostics now use explicit typed envelopes.
Set-like items sort by canonical bytes. Lists and mappings recurse; arbitrary
objects are not silently stringified.

## 6. Traversal regression and preservation-first debt

The assertion was corrected to watch tmp_path / "escape.py". That exact path
was deliberately created for the traversal case before running:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_sedb_adoption.py::test_unsafe_member_path_is_rejected_without_writing_outside -q
~~~

Mutation RED output (exit 1):

~~~text
AssertionError: escape.py exists
1 failed, 2 passed in 0.28s
~~~

After removing only the deliberate file-creation mutation:

~~~text
3 passed in 0.13s
~~~

Full adoption output:

~~~text
36 passed in 0.53s
~~~

No cleanup implementation was added. README documents exact staging-prefix
identification, manual identity/content checks, no automated path-only
recursive cleanup, retained-handle publication, Windows-only operation, and
non-Windows ENOTSUP.

## 7. Basic Phase 2 package identity

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_packaging.py::test_clean_installed_wheel_cli_reports_phase2_version -q
~~~

RED output (exit 1):

~~~text
AssertionError: assert '0.1.0' == '0.2.0'
1 failed in 25.18s
~~~

The wheel came from a clean copied source without egg-info/bytecode, was
force-installed with --no-deps into a fresh venv, and its generated
sedb-ral.exe ran outside the checkout with PYTHONPATH removed.

GREEN output:

~~~text
1 passed in 25.58s
~~~

Direct CLI output:

~~~text
4 passed in 0.22s
~~~

Full packaging/CLI output:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_packaging.py tests/test_cli_smoke.py -q
~~~

~~~text
13 passed in 29.23s
~~~

SEDB-RAL project metadata, package version, and CLI now report 0.2.0.
External sedb-local==0.4.0b1 remains unchanged.

## Consolidated focused verification

Command:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_sedb_mapping.py tests/test_sedb_diff.py tests/test_sedb_v04b_integration.py tests/test_phase2_gate.py tests/test_sedb_profiles.py tests/test_no_send.py tests/test_packaging.py tests/test_sedb_adoption.py tests/test_cli_smoke.py -q
~~~

Output (exit 0):

~~~text
166 passed in 47.09s
~~~

## Final verification

Full suite:

~~~powershell
$env:PYTHONPATH='src'
python -m pytest -q
~~~

Output (exit 0):

~~~text
449 passed, 1 skipped in 79.69s (0:01:19)
~~~

The sole skip is the pre-existing Windows directory-symlink privilege control
(WinError 1314).

Additional gates:

~~~powershell
python -m compileall -q src scripts
git diff --check
git diff --exit-code -- VALIDATION_BASIC_PHASE2.json
~~~

Output (all exit 0):

~~~text
compileall: PASS
git diff --check: PASS
VALIDATION_BASIC_PHASE2.json unchanged: PASS
~~~

## Commit and concerns

- Implementation/docs/tests commit:
  b6e7c8ea5089c98d0497d5ed0b1d6c616292c253
- This report is committed in the immediate follow-on evidence commit; that
  commit SHA is assigned after this file is fixed and is returned in the final
  handoff.
- No implementation or verification concern remains.
- The old finalized receipt is intentionally stale. The controller must
  register/retrieve the replacement CTCL anchor and supersede the receipt.

CTCL_REFINALIZATION_PENDING
