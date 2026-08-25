# LIMEN Public View v0.2

SEDB-RAL `0.3.1` can derive a public-only `limen.ral-view/0.2` from an
exact-head verified synthetic registry ledger.

## Command

```text
sedb-ral registry limen-view \
  --ledger-root ROOT \
  --expected-head sha256:sedb-ral-chain-v1:... \
  [--output VIEW.json]
```

The command refuses an absent, empty, invalid, or wrong-head ledger. Optional
output uses create-new semantics and is never overwritten. The command does
not create a registry, staging directory, SQLite file, or ledger event.

## Exported facts

The view contains only:

- exact SEDB-RAL ledger, authority-projection, and binding-projection heads;
- current public resident ID, display label, instance ID, continuity line;
- public `codex_thread` address and its source event/address/application refs;
- binding validity/status and typed public conflicts.

For `codex_app_task_tool`, the declared identifier components are exactly
`native_thread_id`. `native_session_id` remains null and
`session_match_policy` is `not_applicable_for_profile`.

The compatibility schema can describe a future App Server binding, but this
exporter does not emit one: current canonical SEDB-RAL address records do not
retain a native session component. Supplying a synthetic session would be
false evidence.

## Fail-closed rules

- Active thread collisions emit `address_binding_conflict`; no resident wins.
- Multiple instances emit `instance_binding_ambiguous`; none is selected.
- Missing or multiple continuity lines emit a conflict and no binding.
- Suspended, revoked, withdrawn, and tombstoned records remain nonactive.
- A dirty projection with unapplied events is not exported.
- Names, models, roles, projects, prompts, and memory never choose a binding.

## Acceptance and boundary

```powershell
$env:PYTHONPATH = "src"
python scripts/validate_limen_public_view.py --output REPORT.json
```

The runner executes `S6A-001..S6A-008` twice, exercises a real temporary
ledger through CLI/Core parity, and requires six injected controls. Production
network, private-read, and registry-write counters remain zero; one temporary
synthetic registry is created and removed inside the runner.

This phase proves SEDB-RAL export only. It does not claim LIMEN consumption,
real identity resolution, host enforcement, private access, a production
registry, registration of a real resident, publication, release, or
deployment.
