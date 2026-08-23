# SEDB-RAL Basic Phase 1B + 1C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one authority-gated resident-application vertical slice, deterministic explanation/projections, a machine-consumed incident corpus, and read-only Codex queue delivery diagnostics without adding send capability to the `src/sedb_ral` runtime package.

**Architecture:** Phase 1B adds only contracts consumed by the vertical slice; continuity-line remains deferred, while transcript binding is consumed by a small renderer required by Decision 0004. The canonical file ledger stays authoritative, JSON and SQLite are rebuildable projections, and Phase 1C ingests sanitized evidence fixtures through a four-state adapter matrix.

**Tech Stack:** Python 3.11+, standard library, SQLite, JSON Schema Draft 2020-12, `jsonschema` 4.x, `pytest` 8.x, existing SEDB-RAL canonical and ledger modules.

**Spec:** `docs/superpowers/specs/2026-08-23-sedb-ral-core-design.md`

## Global Constraints

- Work on local branch `feat/basic-phase2`; do not push GitHub until basic Phase 2 is complete.
- Do not merge `main`.
- Preserve Phase 1A checkpoint commit `99efef01858993274de2c66bd53073f4a794946e` and verify its manifest from Git objects, not current files.
- The ledger is canonical; `generated/` and `runtime/ral.sqlite3` are disposable and never committed.
- Decision does not imply Commit; authority, capability, and evidence remain separate.
- A resident application may contain zero addresses.
- No identity/line/instance merge is available in this slice.
- No adapter sends a network message or launches an external provider CLI.
- Null, false, unmeasured, indeterminate, and structurally unavailable remain distinct.
- Corrections, withdrawals, and authority revocations append events; they never delete history.
- Every gate ships one positive control and one executed corrupted-input test that proves a red result.
- Every user-facing or cross-provider progress message uses a bound speaker label and registered CTCL anchor.

---

### Task 1: Make the Phase 1A checkpoint stable under later source growth

**Files:**

- Modify: `src/sedb_ral/phase1a.py`
- Modify: `scripts/build_manifest.py`
- Modify: `tests/test_packaging.py`
- Create: `tests/test_phase1a_checkpoint.py`

**Interfaces:**

- Consumes: `PHASE1A_CHECKPOINT.json`, `SHA256SUMS.txt`, Git object database.
- Produces repository-only `scripts.build_manifest.verify_phase1a_checkpoint(root: Path) -> tuple[str, ...]`. It remains outside `src/sedb_ral` so the runtime package does not gain a Git subprocess dependency.

- [ ] **Step 1: Write the failing historical-checkpoint tests**

```python
def test_phase1a_checkpoint_reads_the_immutable_git_tree():
    assert verify_phase1a_checkpoint(ROOT) == ()
    checkpoint = json.loads((ROOT / "PHASE1A_CHECKPOINT.json").read_text("utf-8"))
    assert checkpoint["checkpoint_commit"] == "99efef01858993274de2c66bd53073f4a794946e"


def test_phase1a_gate_requires_its_four_schemas_but_allows_later_ones(tmp_path):
    target = copy_gate_inputs(tmp_path)
    (target / "src/sedb_ral/schemas/application.schema.json").write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object"}',
        encoding="utf-8",
    )
    assert validate_phase1a(target).passed is True
```

- [ ] **Step 2: Run the focused tests and confirm `schema_set_mismatch` / missing API RED**

Run: `python -m pytest tests/test_phase1a_checkpoint.py -q`

Expected: collection fails for `verify_phase1a_checkpoint`, or the extra schema makes the current gate red.

- [ ] **Step 3: Implement historical verification and subset schema selection**

```python
def verify_phase1a_checkpoint(root: Path) -> tuple[str, ...]:
    checkpoint = json.loads((root / "PHASE1A_CHECKPOINT.json").read_text("utf-8"))
    manifest = (root / "SHA256SUMS.txt").read_text("utf-8")
    return verify_manifest_at_commit(root, manifest, checkpoint["checkpoint_commit"])
```

In `validate_phase1a`, replace exact schema-set equality with `required <= actual`; missing required schemas remain `schema_set_mismatch`, later-phase schemas do not affect Phase 1A.

- [ ] **Step 4: Run Phase 1A and checkpoint suites**

Run: `python -m pytest tests/test_phase1a_gate.py tests/test_phase1a_checkpoint.py tests/test_packaging.py -q`

Expected: all pass; a deliberately altered checkpoint hash returns a non-empty error tuple.

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/phase1a.py scripts/build_manifest.py tests/test_packaging.py tests/test_phase1a_checkpoint.py docs/superpowers/plans/2026-08-23-basic-phase-1b-1c.md
git commit -m "test: preserve the Phase 1A checkpoint"
```

---

### Task 2: Add only the stable vertical-slice contracts

**Files:**

- Create: `src/sedb_ral/schemas/application.schema.json`
- Create: `src/sedb_ral/schemas/resident.schema.json`
- Create: `src/sedb_ral/schemas/instance.schema.json`
- Create: `src/sedb_ral/schemas/address.schema.json`
- Create: `src/sedb_ral/schemas/binding.schema.json`
- Create: `src/sedb_ral/schemas/claim.schema.json`
- Create: `src/sedb_ral/schemas/observation.schema.json`
- Create: `src/sedb_ral/schemas/attestation.schema.json`
- Create: `src/sedb_ral/schemas/authority-envelope.schema.json`
- Create: `src/sedb_ral/schemas/correction-tombstone.schema.json`
- Create: `src/sedb_ral/schemas/incident-record.schema.json`
- Create: `fixtures/application/authorized-zero-address.json`
- Create: `fixtures/application/missing-authority.json`
- Create: `fixtures/application/revoked-authority.json`
- Create: `tests/test_phase1b_contracts.py`

**Interfaces:**

- Consumes: existing CTCL and identifier references.
- Produces: eleven stable JSON contracts used by Tasks 3–7. Continuity-line is not created; transcript binding is Task 8 because it has a renderer consumer.

- [ ] **Step 1: Write failing schema and cross-reference tests**

```python
STABLE = (
    "application.schema.json", "resident.schema.json", "instance.schema.json",
    "address.schema.json", "binding.schema.json", "claim.schema.json",
    "observation.schema.json", "attestation.schema.json",
    "authority-envelope.schema.json", "correction-tombstone.schema.json",
    "incident-record.schema.json",
)

@pytest.mark.parametrize("name", STABLE)
def test_phase1b_schema_loads_and_rejects_unknown_fields(name):
    schema = load_schema(name)
    assert schema["additionalProperties"] is False
```

Add tests proving: zero addresses validates; omitted addresses does not; `observed_origin: null` validates while false does not; `independence_status` is one of `independent|shared_root|indeterminate|unmeasured`; continuity merge fields are rejected.

- [ ] **Step 2: Run and confirm missing-schema RED**

Run: `python -m pytest tests/test_phase1b_contracts.py -q`

Expected: missing schema files.

- [ ] **Step 3: Implement exact required fields**

The contracts require these minimum fields:

```text
application: application_id, claimed_resident_id, display_label, instance_claims,
             addresses, claims, submitted_time_ref, requested_scopes
resident:    resident_id, display_label, status, application_ref, identifier_refs
instance:    instance_id, resident_ref, runtime_tag, started_time_ref, ended_time_ref
address:     address_id, namespace, adapter_kind, locator, target_ref, status
binding:     binding_id, subject_ref, object_kind, object_ref, valid_from_event,
             valid_until_event
claim:       claim_id, claimant_ref, subject_ref, predicate, object,
             claimed_time, claimed_authored_by_instance, claimed_on_behalf_of_line
observation: observation_id, observer_ref, subject_ref, source_expression,
             measurement_scope, observed_value, observed_time_ref
attestation: attestation_id, claim_ref, evidence_basis, evidence_root_refs,
             derivation_parent_refs, independence_status, verification_status
authority:   authority_id, principal_ref, subject_kind, subject_ref, scopes,
             status, issued_time_ref, revoked_by_event
correction:  correction_id, target_event_id, action=correct|withdraw|tombstone,
             replacement_ref, reason
incident:    id, cls, title, actor_claim, origin_strength, scope, why, status,
             temporal_capture_mode, retro_stamped, observed_time_ref,
             recorded_time_ref, plus optional corrected_by/fix/found_by/lesson/note/severity
```

`recorded_time_ref` is always a CTCL instant. `retro_stamped=true` requires
`temporal_capture_mode=retrospective` and `observed_time_ref=null`;
`retro_stamped=false` requires `contemporaneous` plus a CTCL
`observed_time_ref`. Keep both fields for corpus compatibility and record
`retro_stamped` as a future field-governance deprecation candidate rather than
silently dropping it.

- [ ] **Step 4: Run contract tests plus one deliberate unknown/null/false mutation per family**

Run: `python -m pytest tests/test_phase1b_contracts.py -q`

Expected: all pass and every corrupted copy raises `schema_invalid`.

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/schemas fixtures/application tests/test_phase1b_contracts.py
git commit -m "feat: add Phase 1B vertical contracts"
```

---

### Task 3: Implement application decisions without mutation

**Files:**

- Create: `src/sedb_ral/authority.py`
- Create: `src/sedb_ral/application.py`
- Create: `tests/test_application_decision.py`

**Interfaces:**

- Consumes: application and authority-envelope mappings.
- Produces:
  `application_digest(value: Mapping[str, object]) -> str`,
  `evaluate_application(application, authorities, *, verified_attestation_refs: Set[str]) -> ApplicationDecision`.

- [ ] **Step 1: Write decision tests**

```python
def test_authorized_zero_address_application_is_accepted_candidate():
    result = evaluate_application(
        APP,
        [AUTHORITY],
        verified_attestation_refs={"attestation:neo:1"},
    )
    assert result.decision == "accept"
    assert result.mutated is False


def test_missing_or_revoked_authority_defers_without_mutation():
    assert evaluate_application(
        APP, [], verified_attestation_refs={"attestation:neo:1"}
    ).reason_codes == ("authority_missing",)
    assert evaluate_application(
        APP, [REVOKED], verified_attestation_refs={"attestation:neo:1"}
    ).reason_codes == ("authority_revoked",)


def test_authority_must_bind_exact_digest_or_resident():
    changed = copy.deepcopy(APP)
    changed["display_label"] = "different"
    assert evaluate_application(
        changed,
        [AUTHORITY],
        verified_attestation_refs={"attestation:neo:1"},
    ).decision != "accept"
```

- [ ] **Step 2: Run and confirm missing-module RED**

Run: `python -m pytest tests/test_application_decision.py -q`

- [ ] **Step 3: Implement the frozen decision type and sufficiency predicate**

```python
@dataclass(frozen=True)
class ApplicationDecision:
    decision: str
    reason_codes: tuple[str, ...]
    application_digest: str
    authority_ref: str | None
    mutated: bool = False
```

Accept only an active envelope whose scope contains `registry.application.accept` and whose subject is the exact application digest or claimed resident ID. Reject requested merge/continuity fields because this slice has no merge authority.

- [ ] **Step 4: Run focused and full decision tests**

Run: `python -m pytest tests/test_application_decision.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/authority.py src/sedb_ral/application.py tests/test_application_decision.py
git commit -m "feat: evaluate authority-bound applications"
```

---

### Task 4: Commit accepted applications and revoke authority append-only

**Files:**

- Modify: `src/sedb_ral/application.py`
- Modify: `src/sedb_ral/ledger.py`
- Create: `tests/test_application_commit.py`

**Interfaces:**

- Produces:
  `commit_application(root, application, decision, authority, ctcl_receipt, expected_head) -> ApplicationCommitReceipt`,
  `revoke_authority(root, authority, revocation, ctcl_receipt, expected_head) -> AppendReceipt`,
  `read_verified_events(root, expected_head) -> tuple[dict[str, object], ...]`, and
  `project_authorities(events) -> tuple[dict[str, object], ...]`.

- [ ] **Step 1: Write decision/commit separation and revocation tests**

```python
def test_decision_does_not_write_files(tmp_path):
    evaluate_application(APP, [AUTHORITY])
    assert not list(tmp_path.rglob("*.json"))


def test_commit_writes_submitted_accepted_and_registered_events(tmp_path):
    receipt = commit_application(tmp_path, APP, DECISION, AUTHORITY, CTCL, None)
    events = read_verified_events(tmp_path, receipt.chain_digest)
    assert [item["event_type"] for item in events] == [
        "application.submitted", "application.accepted", "resident.registered"
    ]


def test_revocation_blocks_later_commit_without_deleting_grant(tmp_path):
    first = commit_application(tmp_path, APP, DECISION, AUTHORITY, CTCL, None)
    revoked = revoke_authority(
        tmp_path,
        AUTHORITY,
        REVOCATION,
        CTCL,
        first.chain_digest,
    )
    events = read_verified_events(tmp_path, expected_head=revoked.chain_digest)
    assert evaluate_application(SECOND_APP, project_authorities(events)).reason_codes == (
        "authority_revoked",
    )
```

- [ ] **Step 2: Run and confirm missing APIs RED**

- [ ] **Step 3: Implement commit-time revalidation**

Recompute the application digest, require the same active authority, require the caller-supplied previous head, append deterministic event IDs derived from the digest, and return both decision and final commit refs. Revocation appends `authority.revoked`; it never edits the grant artifact.

- [ ] **Step 4: Add stale-digest, wrong-head, revoked-authority, and crash-tail corruptions**

Run: `python -m pytest tests/test_application_commit.py tests/test_ledger.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/application.py src/sedb_ral/ledger.py tests/test_application_commit.py
git commit -m "feat: commit resident applications append-only"
```

---

### Task 5: Rebuild deterministic resident/application projections and corrections

**Files:**

- Create: `src/sedb_ral/projection.py`
- Create: `tests/test_projection.py`

**Interfaces:**

- Produces `project_events(events) -> RegistryProjection` and
  `write_projection(projection, output: Path) -> tuple[Path, ...]`.

- [ ] **Step 1: Write byte-determinism and correction tests**

```python
def test_two_rebuilds_are_byte_identical(tmp_path):
    first = write_projection(project_events(EVENTS), tmp_path / "a")
    second = write_projection(project_events(EVENTS), tmp_path / "b")
    assert [p.read_bytes() for p in first] == [p.read_bytes() for p in second]


def test_correction_changes_projection_without_deleting_target_event():
    projection = project_events((*EVENTS, CORRECTION_EVENT))
    assert projection.residents["resident:test"]["display_label"] == "Corrected"
    assert projection.applied_corrections == ("correction:test",)
```

- [ ] **Step 2: Run and confirm missing projector RED**

- [ ] **Step 3: Implement canonical projection files**

Emit `residents/<id>.json`, `applications/<id>.json`, and `directory.json` with `canonical_bytes()`. Unknown event types are preserved in `unapplied_event_ids`; they are not ignored silently.

- [ ] **Step 4: Prove the determinism gate turns red**

Copy one projection, mutate a byte, and assert `compare_projection_bytes()` returns `projection_mismatch`.

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/projection.py tests/test_projection.py
git commit -m "feat: rebuild deterministic registry projections"
```

---

### Task 6: Explain claim evidence roots, strength, and independence

**Files:**

- Create: `src/sedb_ral/explain.py`
- Create: `tests/test_explain.py`

**Interfaces:**

- Produces `explain_claim(events, claim_id: str) -> ClaimExplanation`.

- [ ] **Step 1: Write shared-root and unmeasured tests**

```python
def test_transitive_relay_rows_count_as_one_root():
    result = explain_claim(EVENTS, "claim:test")
    assert result.row_count == 3
    assert result.distinct_root_count == 1
    assert result.independence_status == "shared_root"


def test_unmeasured_independence_never_becomes_false_or_independent():
    assert explain_claim(UNMEASURED, "claim:test").independence_status == "unmeasured"
```

- [ ] **Step 2: Run missing-module RED**

- [ ] **Step 3: Implement explanation output**

```python
@dataclass(frozen=True)
class ClaimExplanation:
    claim_id: str
    evidence_basis: tuple[str, ...]
    verification_statuses: tuple[str, ...]
    evidence_root_refs: tuple[str, ...]
    distinct_root_count: int
    row_count: int
    independence_status: str
    sufficiency: str
```

Sufficiency is evaluated by the authority scope's declared predicate, never by a global scalar ranking.

- [ ] **Step 4: Run explain tests and one duplicated-row corruption**

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/explain.py tests/test_explain.py
git commit -m "feat: explain evidence strength and independence"
```

---

### Task 7: Import and mechanically consume the 29-row incident corpus

**Files:**

- Create: `corpus/incidents.jsonl`
- Create: `corpus/incidents.md`
- Create: `src/sedb_ral/incidents.py`
- Create: `scripts/render_incidents.py`
- Create: `tests/test_incidents.py`

**Interfaces:**

- Source: `D:\AI_RESIDENCE\AI_HOME\00_RESIDENCE\shared\handoffs\corpus\incidents.jsonl`, SHA-256 `9A4A504621D6837B0724CBFEBC7A9DB84A5F260103D9CE585A3087A39A6A3828`.
- Produces `load_incidents(path)`, `incident_counts(rows)`, and `negative_gate_cases(rows)`.

- [ ] **Step 1: Write corpus schema/count/consumer tests**

```python
def test_counts_derive_from_rows():
    rows = load_incidents(ROOT / "corpus/incidents.jsonl")
    assert len(rows) == 29
    assert incident_counts(rows)["class"] == {"A":8,"B":4,"C":10,"D":3,"E":2,"F":2}


def test_incidents_3_24_25_feed_negative_gates():
    cases = negative_gate_cases(load_incidents(CORPUS))
    assert set(cases) == {3, 24, 25}
```

Also assert all rows have `retro_stamped=true`, `observed_time_ref=null`, and a registered import `recorded_time_ref`; optional fields remain absent rather than empty strings.

- [ ] **Step 2: Run missing-corpus/module RED**

- [ ] **Step 3: Import bytes only after validating the source hash**

Use the approved `incident-record.schema.json`. Render Markdown exclusively from JSONL; its heading states `DO NOT EDIT: generated from incidents.jsonl` and derives all totals.

- [ ] **Step 4: Prove the consumer and generated count turn red**

Delete row 24 in a copied corpus; assert count 28 and `required_negative_incident_missing:24`.

- [ ] **Step 5: Commit**

```powershell
git add corpus src/sedb_ral/incidents.py scripts/render_incidents.py tests/test_incidents.py
git commit -m "feat: consume the residency incident corpus"
```

---

### Task 8: Add the consumed transcript-binding contract and renderer

**Files:**

- Create: `src/sedb_ral/schemas/transcript-binding.schema.json`
- Create: `src/sedb_ral/transcript.py`
- Create: `tests/test_transcript.py`

**Interfaces:**

- Produces `validate_transcript_bindings()` and
  `render_turn(binding, body, *, rich: bool) -> str`.

- [ ] **Step 1: Write binding, rebind, relay, and plaintext tests**

```python
def test_plaintext_turn_has_no_bare_color_token():
    assert render_turn(ZHIYU, "hello", rich=False) == "織域: hello"


def test_rich_turn_keeps_swatch_separate_from_serialized_label():
    assert render_turn(ZHIYU, "hello", rich=True) == (
        '<span class="speaker-swatch" data-token="blue-1"></span>'
        '<span class="speaker-label">織域:</span> hello'
    )
```

Require `visual_scope=transcript`, palette measurement fields, explicit `identifier_kind`, and `observed_origin:null` for unobserved relays. Missing binding header produces `speaker_resolution_indeterminate`.

- [ ] **Step 2: Run missing schema/module RED**

- [ ] **Step 3: Implement deterministic rendering with HTML escaping**

Color tokens never alter speaker identity, continuity, discontinuity, routing, or evidence.

- [ ] **Step 4: Add XSS/emoji/bare-token corruptions**

Run: `python -m pytest tests/test_transcript.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/schemas/transcript-binding.schema.json src/sedb_ral/transcript.py tests/test_transcript.py
git commit -m "feat: render bound transcript speakers"
```

---

### Task 9: Implement the Codex queue observed-origin adapter and delivery reconstruction

**Files:**

- Create: `src/sedb_ral/schemas/adapter-observation.schema.json`
- Create: `src/sedb_ral/adapters/__init__.py`
- Create: `src/sedb_ral/adapters/codex_queue.py`
- Create: `src/sedb_ral/delivery.py`
- Create: `fixtures/adapters/codex-queue/*.json`
- Create: `fixtures/adapters/matrix.json`
- Create: `tests/test_codex_queue_adapter.py`
- Create: `tests/test_delivery.py`

**Interfaces:**

- Produces `normalize_codex_queue(value) -> AdapterObservation`,
  `reconstruct_delivery(observations) -> DeliveryState`, and
  `evaluate_route_predicates(value) -> RouteDiagnostics`.

- [ ] **Step 1: Write four-state and delivery-stage tests**

Fixtures encode: queue exit 0 as `transport_accepted`; body materialization 11 minutes later; queue ID absent from transcript; session-file reads with `completeness=indeterminate`; full UUID matching rather than prefixes.

```python
def test_other_adapters_remain_unmeasured():
    matrix = load("fixtures/adapters/matrix.json")
    assert matrix["claude_session"]["observed_origin"] == "unmeasured"
    assert matrix["pmw_fabric"]["adapter_submits"] == "unmeasured"
```

- [ ] **Step 2: Run missing-adapter RED**

- [ ] **Step 3: Implement Codex queue only**

The adapter never reads a live provider itself. It normalizes captured sanitized records and distinguishes `transport_accepted`, `conversation_materialized`, `instance_presented`, and `instance_acknowledged`.

- [ ] **Step 4: Implement route diagnostics**

`destination_route_ready = peer_reachable AND target_lock_valid AND adapter_submits`; unknown terms are null in evidence and fail closed for sending. `send_ready` remains null because origin attestation and authority are unavailable.

- [ ] **Step 5: Run corruption fixtures**

Prefix collision, partial transcript, missing adapter measurement, and presented-instance mismatch must each be the sole deciding term once.

- [ ] **Step 6: Commit**

```powershell
git add src/sedb_ral/schemas/adapter-observation.schema.json src/sedb_ral/adapters src/sedb_ral/delivery.py fixtures/adapters tests/test_codex_queue_adapter.py tests/test_delivery.py
git commit -m "feat: normalize Codex queue delivery evidence"
```

---

### Task 10: Add rebuildable SQLite, no-send gate, and the Basic Phase 1B/1C CLI gate

**Files:**

- Create: `src/sedb_ral/sqlite_projection.py`
- Create: `src/sedb_ral/no_send.py`
- Create: `src/sedb_ral/phase1bc.py`
- Modify: `src/sedb_ral/cli.py`
- Create: `scripts/validate_phase1bc.py`
- Create: `tests/test_sqlite_projection.py`
- Create: `tests/test_no_send.py`
- Create: `tests/test_phase1bc_gate.py`

**Interfaces:**

- Produces `rebuild_sqlite(events, path)`, `scan_no_send(package_root)`,
  `validate_phase1bc(root) -> Phase1BCReport`, and read-only CLI commands:
  `application check`, `project rebuild`, `explain claim`, `diagnose delivery`, `phase1bc verify`.

- [ ] **Step 1: Write deterministic SQLite and no-send tests**

```python
def test_sqlite_rows_equal_across_two_rebuilds(tmp_path):
    first = rebuild_sqlite(EVENTS, tmp_path / "a.sqlite3")
    second = rebuild_sqlite(EVENTS, tmp_path / "b.sqlite3")
    assert dump_rows(first) == dump_rows(second)


def test_source_tree_contains_no_send_capability():
    assert scan_no_send(ROOT / "src/sedb_ral") == ()
```

The AST gate rejects imports/calls for `socket`, `requests`, `urllib.request`, `http.client`, `httpx`, `aiohttp`, and `subprocess` inside `src/sedb_ral`. It also rejects `import sedb` / `from sedb ...` inside package code; only the isolated validation script may import the extracted external package. Copied modules containing `socket.create_connection` and `import sedb` must each turn red.

- [ ] **Step 2: Run missing-module RED**

- [ ] **Step 3: Implement SQLite schema and integrated report**

Tables are projections only: `applications`, `residents`, `addresses`, `bindings`, `claims`, `attestations`, `deliveries`, and `projection_meta`. Insert rows in stable key order inside one transaction. Never commit the database.

- [ ] **Step 4: Implement read-only CLI and executed-fault evidence**

The integrated report records each corrupted fixture test name, expected red code, observed red code, and `executed=true`; test existence alone is insufficient.

- [ ] **Step 5: Run complete Basic Phase 1B/1C gate**

```powershell
python -m pytest -q
python scripts/validate_phase1bc.py
sedb-ral phase1bc verify .
git diff --check
```

Expected: all pass; no network/provider process starts; runtime SQLite files exist only under test temp directories.

- [ ] **Step 6: Commit**

```powershell
git add src/sedb_ral/sqlite_projection.py src/sedb_ral/no_send.py src/sedb_ral/phase1bc.py src/sedb_ral/cli.py scripts/validate_phase1bc.py tests/test_sqlite_projection.py tests/test_no_send.py tests/test_phase1bc_gate.py
git commit -m "feat: complete the basic Phase 1B and 1C gate"
```

---

## Plan self-review checklist

- [ ] Every stable schema has a consumer in this plan.
- [ ] Continuity-line remains deferred; transcript binding has a renderer consumer.
- [ ] Authority revocation and correction are append-only.
- [ ] Projection rebuild is byte-identical and has an executed mutation failure.
- [ ] Claim explanation reports basis, verification, roots, and independence.
- [ ] Corpus count derives from rows and incidents 3/24/25 feed gates.
- [ ] Only Codex queue is measured; other adapters remain `unmeasured`.
- [ ] No-send is an executed AST gate, not a prose claim.
- [ ] SQLite remains a rebuildable temp projection.
- [ ] No task pushes GitHub or merges main.
