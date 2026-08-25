# Phase 3B-B Production Operations Layout

SEDB-RAL `0.5.0b1` adds a versioned, dormant registrar-operations extension for
the exact production public registry:

```text
D:\AI_RESIDENCE\REGISTRY\SEDB-RAL\extensions\registrar-operations\v1
```

R3B-B is infrastructure activation only. It creates no applicant, resident,
address, authority grant, or ledger event. It never reads private `AI_HOME`,
sends network/provider/Fabric messages, starts MCP, or enables registrar
execution.

## Immutable base

Activation does not overwrite or regenerate:

- `registry-manifest.json`;
- `control/heads/00000000000000000000.json`;
- `ledger/`;
- existing checkpoints, rehearsals, or evidence receipts.

The existing base `tree_digest` retains its P3-4 meaning. A separate
`registry_generation_digest` binds the base and latest extension index.

## Dormant layout

The complete top-level `extensions` candidate contains an append-only index,
extension manifest, activation commit, canonical dormant policy, policy
activation receipt, and empty operational directories. The initial policy
permits only `inspect` and `status`; intake and execution are false.

The candidate is built at a same-volume sibling and the complete `extensions`
directory is published with a no-replace atomic move. A post-move receipt is
written separately, so a candidate artifact never claims the move already
happened.

## Local synthetic verification

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q `
  tests/test_production_operations_contracts.py `
  tests/test_production_operations_layout.py `
  tests/test_production_operations_recovery.py `
  tests/test_production_operations_cli.py `
  tests/test_production_operations_acl_script.py `
  tests/test_production_operations_acl_windows.py `
  tests/test_production_operations_acceptance.py `
  tests/test_production_operations_packaging.py
python scripts/validate_production_operations.py `
  --output r3b-b-synthetic.json
```

The acceptance report requires R3B-001 through R3B-021, deterministic repeated
digests, create-only receipts, and zero production resident/event, applicant,
private, network, provider, Fabric, or MCP effects.

## CLI

```text
sedb-ral registry operations-extension-plan
sedb-ral registry operations-extension-prepare
sedb-ral registry operations-extension-status
sedb-ral registry operations-extension-acceptance
```

Plan, prepare, status, and acceptance do not publish a live extension. The
Windows action wrapper is the only supported activation path:

```text
scripts/Initialize-ProductionOperationsExtension.ps1
```

It requires an exact plan, exact authority, verified pre-checkpoint, protected
candidate ACL, and exact production target. It retains failed candidates and
never performs automatic cleanup or rollback.

## Recovery

Versioned pre/post checkpoints coexist under `checkpoints/`. Their create-only
receipts use `evidence/checkpoints/`; restore and rollback evidence use
`evidence/restores/` and `evidence/rollbacks/`. Snapshots copy the base,
extension, activation receipt, and public evidence by value while excluding the
contents of checkpoints/rehearsals to prevent recursion.

Rollback testing mutates only a disposable rehearsal copy. No automatic action
deletes a published extension.

## Next gate

R3B-C may begin only after exact source/CI/production activation evidence agrees.
It requires one exact host-observed applicant, immutable application digest,
principal approval, canonical append, public projection, and LIMEN B6A readback.
Private B6B remains separate opt-in authority.
