# SEDB-RAL LIMEN Public View Exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Multi-agent/subagent execution is
> not authorized for this run.

**Goal:** Export a deterministic, public-only `limen.ral-view/0.2` from an
exact-head SEDB-RAL ledger so LIMEN can resolve a task-tool observation by its
host-observed thread component without reading private Residence data.

**Architecture:** A new focused exporter consumes only `RegistryProjection`
and the verified ledger head. It maps registered `codex_thread` addresses into
versioned LIMEN bindings, emits explicit projection conflicts instead of
tie-breaking, and validates its output against a packaged compatibility copy
of the LIMEN v0.2 schema. A read-only CLI wraps the same Core; it never opens a
private root or appends registry events.

**Tech Stack:** Python 3.11+, standard library, existing strict canonical JSON,
JSON Schema, pytest, existing file-ledger verifier and CLI.

**Spec:**
`docs/superpowers/specs/2026-08-25-phase3-self-registration-and-limen-b6-design.md`
sections 7, 8, 10, 21, and 23.

## Global Constraints

- The canonical input is an exact-head verified SEDB-RAL event ledger.
- LIMEN view generation is pure and performs zero registry, private, network,
  external, deployment, publication, or Residence writes.
- Output contains public resident/binding facts only; no applicant claim,
  authority body, principal evidence, host turn, private path, credential, or
  Residence manifest enters the view.
- `display_label`, model, role, title, project, and memory never select a
  resident or break a collision.
- `codex_app_task_tool` bindings discriminate only on `native_thread_id` and
  preserve `native_session_id: null` with
  `session_match_policy: not_applicable_for_profile`.
- An address does not prove an instance. Exactly one active instance and one
  unambiguous continuity line are required before the exporter emits a
  binding; otherwise it emits a public conflict and omits that binding.
- Active namespace+locator collisions across residents emit conflicts and no
  winner. Suspended/revoked/tombstoned records never resolve as active.
- The shared `limen.ral-view/0.2` schema bytes and SHA-256 are pinned in a
  mapping profile and must match the LIMEN checkout during the final local
  cross-repository gate.
- Fixtures use only `resident:test-*`, `thread:test-*`, and temporary ledgers.
- No production registry root or real native identifier is configured.

---

### Task 1: Shared public-view contract and mapping profile

**Files:**
- Create: `src/sedb_ral/schemas/limen-ral-view-v0.2.schema.json`
- Create: `profiles/limen-ral-view-v0.2-mapping.json`
- Create: `tests/test_limen_public_view_contract.py`

**Interfaces:**
- Produces schema ID `limen.ral-view/0.2`.
- Produces profile ID `limen-ral-view-v0.2-mapping`, version `1`.
- The profile pins the exact schema SHA-256 and the only source mapping that
  current canonical address records can prove:
  `codex_app_task_tool -> openai/codex_thread/native_thread_id`.
- The shared schema can describe an App Server binding, but this exporter does
  not emit one because canonical SEDB-RAL address records do not yet retain a
  native session component.

- [ ] **Step 1: Write the failing contract tests**

The test file defines `valid_public_view()` as a complete literal v0.2 object
and `load_profile()` as a strict UTF-8 JSON loader for the exact profile path.

```python
def test_public_view_v02_accepts_task_tool_thread_only_binding():
    value = valid_public_view()
    binding = value["bindings"][0]
    assert binding["identifier_components"] == ["native_thread_id"]
    assert binding["native_session_id"] is None
    assert binding["session_match_policy"] == "not_applicable_for_profile"
    validate_contract("limen-ral-view-v0.2.schema.json", value)


def test_task_tool_binding_cannot_invent_a_session():
    value = valid_public_view()
    value["bindings"][0]["native_session_id"] = "session:invented"
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("limen-ral-view-v0.2.schema.json", value)


def test_mapping_profile_pins_actual_schema_bytes():
    profile = load_profile()
    assert profile["contract_sha256"] == hashlib.sha256(
        SCHEMA.read_bytes()
    ).hexdigest()
```

The production changes caught are relaxing v0.1 in place, synthesizing a
session, or allowing the profile to drift from the packaged schema.

- [ ] **Step 2: Run RED**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_limen_public_view_contract.py -q
```

Expected: schema/profile files are missing.

- [ ] **Step 3: Add the strict v0.2 schema and profile**

The top-level object requires exactly:

```text
schema, profile, view_id, sequence, authority_head, binding_head,
ledger_head, bindings, projection_conflicts, source_refs, not_claimed
```

Each binding requires exactly:

```text
binding_id, provider, adapter_kind, identifier_kind,
identifier_components, native_thread_id, native_session_id,
session_match_policy, resident_id, instance_id, continuity_line_id,
speaker_label, status, valid_from_sequence, valid_until_sequence,
lineage_from_thread_ids, supersedes_binding_id, source_refs
```

Task-tool conditional validation requires the exact thread-only component,
null session, and not-applicable session policy. App Server requires both
thread and session components and a non-empty session.

- [ ] **Step 4: Run GREEN and packaged-schema regression**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_limen_public_view_contract.py tests/test_phase3_schema_assets.py tests/test_packaging.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/schemas/limen-ral-view-v0.2.schema.json profiles/limen-ral-view-v0.2-mapping.json tests/test_limen_public_view_contract.py
git commit -m "feat: define LIMEN public view contract"
```

### Task 2: Deterministic projection exporter and collision gates

**Files:**
- Create: `src/sedb_ral/limen_public_view.py`
- Create: `tests/test_limen_public_view_export.py`

**Interfaces:**
- Produces immutable `LimenPublicView(value: dict[str, object], digest: str)`
  with `to_dict()`.
- Produces
  `build_limen_public_view(projection, *, ledger_head, sequence) -> LimenPublicView`.
- Produces `limen_contract_digest() -> str` from packaged schema bytes.
- Consumes `RegistryProjection`, `continuity_line_for`, and
  `resident_source_event_ids` only.

- [ ] **Step 1: Write failing exporter tests**

The test file defines literal `RegistryProjection` constructors named
`projection_with_registered_task_tool_resident`,
`projection_with_colliding_active_threads`, and
`projection_with_same_labels_and_distinct_threads`; they do not call exporter
helpers to derive expected values.

```python
def test_L6A_001_exact_registered_thread_exports_one_public_binding():
    view = build_limen_public_view(
        projection_with_registered_task_tool_resident(),
        ledger_head=HEAD,
        sequence=4,
    )
    assert len(view.to_dict()["bindings"]) == 1
    binding = view.to_dict()["bindings"][0]
    assert binding["native_thread_id"] == "thread:test-alpha"
    assert binding["resident_id"] == "resident:test-alpha"
    assert binding["identifier_components"] == ["native_thread_id"]
    assert binding["native_session_id"] is None


def test_L6A_003_active_thread_collision_emits_conflict_and_no_binding():
    view = build_limen_public_view(
        projection_with_colliding_active_threads(),
        ledger_head=HEAD,
        sequence=8,
    ).to_dict()
    assert view["bindings"] == []
    assert [item["error_code"] for item in view["projection_conflicts"]] == [
        "address_binding_conflict"
    ]


def test_homonymous_labels_export_as_distinct_noncolliding_bindings():
    view = build_limen_public_view(
        projection_with_same_labels_and_distinct_threads(),
        ledger_head=HEAD,
        sequence=8,
    ).to_dict()
    assert len(view["bindings"]) == 2
```

Additional tests cover zero/multiple instances, missing/ambiguous continuity
line, suspended/revoked addresses, withdrawn/tombstoned residents, unknown
adapter kinds, duplicate address IDs, stable source refs, stable ordering, and
two byte-identical builds.

The production changes caught are name-based selection, arbitrary instance
selection, last-writer collision tie-breaks, and private/applicant field leaks.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_limen_public_view_export.py -q`

Expected: `sedb_ral.limen_public_view` is missing.

- [ ] **Step 3: Implement the pure exporter**

Binding IDs use `binding:address:{address_id}`. `authority_head` is a digest of
the accepted authority references in the projection; `binding_head` is a
digest of the emitted binding/conflict material; `ledger_head` remains the
exact external checkpoint. `source_refs` include the resident registration
event and address/application references, never filesystem paths.

The exporter validates its finished value through
`limen-ral-view-v0.2.schema.json` before returning it.

- [ ] **Step 4: Run GREEN plus projection regression**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_limen_public_view_export.py tests/test_projection.py tests/test_sqlite_projection.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/limen_public_view.py tests/test_limen_public_view_export.py
git commit -m "feat: export deterministic LIMEN public bindings"
```

### Task 3: Exact-head read-only CLI and Core parity

**Files:**
- Modify: `src/sedb_ral/cli.py`
- Create: `tests/test_limen_public_view_cli.py`

**Interfaces:**
- Adds command:
  `sedb-ral registry limen-view --ledger-root ROOT --expected-head DIGEST [--output FILE]`.
- Reuses `read_verified_events`, `project_events`, and
  `build_limen_public_view`.
- `--expected-head` has no `GENESIS` spelling because an empty registry has no
  admitted public binding to export.

- [ ] **Step 1: Write failing CLI parity and refusal tests**

The test file defines `committed_ledger` by using the existing synthetic
registrar Core and defines `tree_fingerprint(path)` as a sorted mapping of
relative file paths to SHA-256 values.

```python
def test_limen_view_cli_matches_direct_core_bytes(committed_ledger, capfd):
    root, head, events = committed_ledger
    expected = build_limen_public_view(
        project_events(events), ledger_head=head, sequence=len(events)
    )
    assert main([
        "registry", "limen-view", "--ledger-root", str(root),
        "--expected-head", head,
    ]) == 0
    assert canonical_bytes(json.loads(capfd.readouterr().out)) == canonical_bytes(
        expected.to_dict()
    )


def test_wrong_head_refuses_without_output_or_registry_write(tmp_path, capfd):
    before = tree_fingerprint(tmp_path)
    assert main([
        "registry", "limen-view", "--ledger-root", str(tmp_path / "ledger"),
        "--expected-head", ZERO_HEAD,
    ]) == 2
    assert json.loads(capfd.readouterr().out)["reason_codes"] == [
        "external_anchor_mismatch"
    ]
    assert tree_fingerprint(tmp_path) == before
```

Also test output create-new semantics, CLI import/help zero writes, no path/stack
leakage, and deterministic output across two invocations.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_limen_public_view_cli.py -q`

Expected: `registry` is not a declared command.

- [ ] **Step 3: Implement the CLI wrapper**

The CLI verifies the external head before projection, passes the final event
sequence explicitly, emits strict canonical JSON plus LF, and uses `xb` for an
optional output file. It does not create a ledger, staging tree, SQLite file,
or registry event.

- [ ] **Step 4: Run GREEN and existing CLI regression**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_limen_public_view_cli.py tests/test_phase3_cli.py tests/test_cli_smoke.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/cli.py tests/test_limen_public_view_cli.py
git commit -m "feat: expose exact-head LIMEN public view CLI"
```

### Task 4: Exporter acceptance, evidence, docs, and CI

**Files:**
- Create: `src/sedb_ral/limen_export_acceptance.py`
- Create: `scripts/validate_limen_public_view.py`
- Create: `tests/test_limen_public_view_gate.py`
- Create: `docs/runtime/LIMEN_PUBLIC_VIEW_V02.md`
- Create: `evidence/limen-public-view/2026-08-25-local.json`
- Modify: `.github/workflows/phase3a.yml`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `src/sedb_ral/__init__.py`

**Interfaces:**
- Produces deterministic `sedb-ral.limen-public-view-acceptance/0.1` evidence.
- Requires exact cases `S6A-001..S6A-008`:

```text
S6A-001 exact task-tool public binding
S6A-002 homonymous labels remain separate
S6A-003 active thread collision
S6A-004 ambiguous instance
S6A-005 ambiguous continuity line
S6A-006 inactive address omitted/refused
S6A-007 exact-head CLI/Core parity
S6A-008 repeated byte-identical export and no-send boundary
```

- Promotes package version to `0.3.1`; the emitted registry profile remains
  `sedb-ral/0.3.0` because no canonical ledger contract changes.

- [ ] **Step 1: Write the integrated gate RED**

```python
def test_export_gate_has_exact_inventory_and_zero_side_effects(tmp_path):
    report = validate_limen_public_view(ROOT, output_root=tmp_path)
    assert report.passed is True
    assert report.case_ids == tuple(f"S6A-{i:03d}" for i in range(1, 9))
    assert report.network_calls == 0
    assert report.private_reads == 0
    assert report.registry_writes == 0
    assert report.real_resident_count == 0
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_limen_public_view_gate.py -q`

Expected: acceptance module is missing.

- [ ] **Step 3: Implement repeated synthetic acceptance and evidence**

Run the eight cases twice under independent temporary roots; require identical
execution digests. Scan exporter source/evidence for real task IDs, private
markers, credentials, network/process imports, and production ledger paths.
The report records the shared schema SHA-256 and explicitly does not claim
LIMEN consumption, real resolution, host enforcement, private access, or
production registry configuration.

- [ ] **Step 4: Add CI, docs, and version**

Extend the existing Windows/Ubuntu Python 3.11 workflow with a public-view job,
using the already pinned action SHAs and `contents: read`. Update README and
runtime docs only after local evidence exists.

- [ ] **Step 5: Run the completion gate**

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q --ignore=tests/test_phase2_gate.py --ignore=tests/test_sedb_adoption.py --ignore=tests/test_sedb_v04b_integration.py
python scripts/validate_phase2.py --sedb-archive "D:\Ai\work together\SEDB\releases\SEDB-v0.4B-local.zip"
$phase3aEvidence = Join-Path $env:TEMP ("sedb-ral-phase3a-" + [guid]::NewGuid().ToString("N") + ".json")
$limenViewEvidence = Join-Path $env:TEMP ("sedb-ral-limen-view-" + [guid]::NewGuid().ToString("N") + ".json")
python scripts/validate_phase3a.py --output $phase3aEvidence
python scripts/validate_limen_public_view.py --output $limenViewEvidence
git diff --check
```

Expected: source regression passes with the preserved platform skip; Phase 2,
Phase 3A, and exporter reports pass; no external/private/registry mutation
counter is nonzero.

- [ ] **Step 6: Commit and push exporter**

```powershell
git add .github README.md docs evidence profiles pyproject.toml scripts src tests
git commit -m "feat: complete LIMEN public view exporter"
git push origin main
```

Do not create or configure a production registry root, prepare a real
application, append a real resident, access Residence, install LIMEN, publish,
release, or deploy in this plan.

## Plan self-review

- **Spec coverage:** Tasks 1–4 cover versioned v0.2 view/binding contracts,
  thread-only task-tool discrimination, collision/no-tie-break behavior,
  exact-head public projection, determinism, source refs, and evidence.
- **Placeholder scan:** clean; every helper, command, expected error, and
  neighboring interface is defined in the task that first uses it.
- **Type consistency:** `LimenPublicView`, `build_limen_public_view`, and
  `limen_contract_digest` are defined once and reused unchanged.
- **Boundary check:** this exporter proves only public synthetic projection;
  LIMEN consumption, host enforcement, B6B, and real registration remain in
  their owning gates.
