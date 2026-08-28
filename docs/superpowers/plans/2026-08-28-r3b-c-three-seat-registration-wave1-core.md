# R3B-C Three-Seat Registration Wave 1 Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`
> with Inline FCAO. Neo.K has limited this work to one implementer plus at most
> one Twin reviewer at Slice/final gates; do not dispatch per-task reviewers.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and synthetically verify the SEDB-RAL contracts, policy
control, staging, sequential slot engine, recovery and public readback bundle
needed for the three-seat Wave 1, while stopping before any real application,
production policy activation or canonical ledger write.

**Architecture:** RAL owns a closed Wave 1 state machine layered on the existing
`prepare_registration()`, registrar plan/commit Core, production dormant
extension and public projections. Applicant evidence, principal approval,
Wave policy, slot ordering and recovery remain distinct digest-bound objects.
The engine executes at most one slot per call and derives the next slot from
verified history rather than a mutable counter.

**Tech Stack:** Python 3.11+, JSON Schema Draft 2020-12, strict canonical JSON/
NFC digest profile, pytest, existing SEDB-RAL file ledger/projection/operations
modules, Windows ACL/link guards, PowerShell wrappers only at later operational
gates.

**Spec:** `docs/superpowers/specs/2026-08-28-r3b-c-three-seat-registration-wave1-design.md`

## Global Constraints

- Exact accepted spec: commit `2d42940cce0b5876d45e6e07170d23688871dc67`,
  tree `befa9561669bb9e60028d1a32fe86f203e2cd79f`, SHA-256
  `E5AFF0DDEE55E547F0DBFA881DD186717F6431CA22D7D480690232F9833820C2`.
- Three applicant slots are equal standing; sequence is never rank, seniority,
  authority, ownership, continuity or resource priority.
- Claims may exist as candidate bytes, but preparation requires a completed
  assistant `agentMessage` exact-bound to parent task/turn and content.
- Wave 1 accepts `existing_resident_claim=null` and continuity `new|uncertain`
  only.
- Private B6B, memory body access, network, Fabric emission, provider calls,
  MCP, cloud, broadcast, deletion, identity/continuity merge and auto-resume
  are disabled.
- Existing production dormant policy, activation receipt, registry base,
  ledger and control head are immutable.
- All implementation/tests use synthetic storage roots. No task in this plan
  may read or write the exact production root.
- No real task IDs, labels, turn IDs, application IDs, resident IDs, paths or
  approval digests enter Git fixtures; use deterministic synthetic values.
- The initial ledger state is `{expected_ledger_head: null, cli_token:
  "GENESIS", ledger_event_count: 0}` with a separately pinned non-null control
  digest.
- One slot per execution call. There is no automatic three-slot loop.
- Helper names shown only inside test snippets (`valid_wave_plan`, `plan`,
  `request`, `approval`, `policy`, `checkpoint`, `status`, `h1` and mutation
  builders) are deterministic local fixture builders defined in that task's
  test file; they are not production interfaces or cross-task dependencies.
- Applicant preparation, production operational execution and LIMEN B6A live
  integration remain separately gated after this code candidate is accepted.

## Scope split

This plan modifies SEDB-RAL only. It produces a signed/digested public readback
bundle that a later LIMEN B6A plan consumes. It does not modify LIMEN, SOACR,
Fabric, MSP, ARCP, AI Residence or native provider memory.

---

### Task 1: Closed Wave Contract Assets and Models

**Files:**
- Create: `src/sedb_ral/registration_wave_models.py`
- Create: `src/sedb_ral/schemas/registration-applicant-item-evidence.schema.json`
- Create: `src/sedb_ral/schemas/registration-host-observation-v0.2.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-plan.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-policy.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-active-policy-record.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-policy-activation-request.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-policy-activation-authority.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-policy-activation-receipt.schema.json`
- Create: `src/sedb_ral/schemas/principal-application-approval.schema.json`
- Create: `src/sedb_ral/schemas/registration-slot-execution-authorization.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-slot-request.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-slot-receipt.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-slot-recovery-receipt.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-terminal-event.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-readback-bundle.schema.json`
- Test: `tests/test_registration_wave_contracts.py`

**Interfaces:**
- Consumes: `canonical_bytes`, `loads_strict`, `sha256_ref`, `validate_contract`.
- Produces: strict `_WaveContract` canonical base plus frozen
  `ApplicantItemEvidence`, `WaveHostObservation`, `WaveSlot`,
  `RegistrationWavePlan`, `RegistrationWavePolicy`, `ActiveWavePolicyRecord`,
  `WavePolicyActivationRequest`, `WavePolicyActivationAuthority`,
  `WavePolicyActivationReceipt`,
  `PrincipalApplicationApproval`, `SlotExecutionAuthorization`,
  `WaveSlotRequest`, `WaveSlotReceipt`, `WaveSlotRecoveryReceipt`,
  `WaveTerminalEvent`, `WaveReadbackBundle`; each exposes `from_dict()`,
  `to_dict()`, `sealed()` and `verify()`.

- [ ] **Step 1: Write schema/model RED tests**

```python
def test_wave_plan_requires_three_contiguous_equal_standing_slots():
    plan = valid_wave_plan()
    RegistrationWavePlan.from_dict(plan)
    for mutation in (duplicate_slot(plan), reorder_slot(plan), rank_field(plan)):
        with pytest.raises((RALValidationError, ValueError)):
            RegistrationWavePlan.from_dict(mutation)

def test_host_observation_v02_rejects_non_assistant_item_roles():
    for role, kind in (("user", "userMessage"), ("assistant", "toolCall")):
        with pytest.raises(RALValidationError, match="applicant_item_role_invalid"):
            WaveHostObservation.from_dict(valid_host_v02(role=role, kind=kind))
```

- [ ] **Step 2: Run contract tests and confirm RED**

Run: `python -m pytest -q tests/test_registration_wave_contracts.py`

Expected: collection errors because the schemas/models do not exist.

- [ ] **Step 3: Implement strict canonical models and schemas**

```python
@dataclass(frozen=True)
class WaveSlot:
    slot_id: str
    slot_index: int
    application_ref: str
    application_digest: str
    host_observation_ref: str
    host_observation_digest: str

@dataclass(frozen=True)
class RegistrationWavePlan(_WaveContract):
    wave_id: str
    ordered_slots: tuple[WaveSlot, WaveSlot, WaveSlot]
    initial_ledger_state: dict[str, object]
    registry_control_digest: str
    registry_generation_digest: str
    policy_ref: str
    policy_digest: str
    checkpoint_ref: str
    checkpoint_digest: str
    terminal_boundary: str
    not_claimed: tuple[str, ...]
    wave_plan_digest: str
```

Use `additionalProperties:false`, exact enum sets, lower-case UUID locator
regex and domain-separated `sha256:sedb-ral-json-nfc-codepoint-v1:` digests.
Do not change v0.1 host-observation semantics.

- [ ] **Step 4: Run contract/schema parity tests**

Run: `python -m pytest -q tests/test_registration_wave_contracts.py tests/test_phase3_schema_assets.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```text
git add src/sedb_ral/registration_wave_models.py src/sedb_ral/schemas tests/test_registration_wave_contracts.py
git commit -m "feat: define R3B-C wave contracts"
```

---

### Task 2: Applicant Item Evidence and Wave Preparation Gate

**Files:**
- Create: `src/sedb_ral/registration_wave_intake.py`
- Modify: `src/sedb_ral/registration.py` only to expose reusable canonical
  claim digest helper; do not relax `prepare_registration()` v0.1.
- Test: `tests/test_registration_wave_intake.py`

**Interfaces:**
- Consumes: `PreparedRegistration`, `RegistrationIds`,
  `prepare_registration()` and Task 1 models.
- Produces:
  `canonical_claim_digest(claim: Mapping[str, object]) -> str`,
  `verify_applicant_item_evidence(claim, item, host) -> None`,
  `prepare_wave_candidate(claim, item, host, ids) -> PreparedRegistration` and
  `validate_exact_three_candidates(candidates) -> tuple[PreparedRegistration, ...]`.

- [ ] **Step 1: Write applicant-authorship and continuity REDs**

```python
@pytest.mark.parametrize("kind", ["userMessage", "codexDelegation", "reasoning", "toolCall", "commandExecution"])
def test_non_agent_items_cannot_prepare_even_with_same_claim_bytes(kind):
    with pytest.raises(RALValidationError, match="applicant_item_role_invalid"):
        prepare_wave_candidate(valid_claim(), item(kind=kind), host_v02(kind=kind), ids())

def test_continue_and_missing_agent_message_stop_before_id_assignment():
    with pytest.raises(RALValidationError, match="continuity_evidence_required"):
        prepare_wave_candidate(valid_claim(continuity="continue"), item(), host_v02(), ids())
    with pytest.raises(RALValidationError, match="applicant_output_unavailable"):
        verify_applicant_item_evidence(valid_claim(), unavailable_item(), host_v02())
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_intake.py`

Expected: import/function failures.

- [ ] **Step 3: Implement exact item/claim/host binding**

```python
def verify_applicant_item_evidence(claim, item, host) -> None:
    if (item.source_item_role, item.source_item_kind, item.source_item_status) != ("assistant", "agentMessage", "completed"):
        raise RALValidationError("applicant_item_role_invalid", "applicant item is not completed assistant output")
    if item.parent_thread_id != host.native_thread_id or item.parent_turn_id != host.native_turn_id:
        raise RALValidationError("applicant_item_parent_mismatch", "applicant item parent differs")
    if item.canonical_claim_digest != canonical_claim_digest(claim):
        raise RALValidationError("applicant_item_claim_digest_mismatch", "claim differs from host item")
```

Require three distinct canonical locators and exactly three eligible candidates
before returning a wave candidate tuple. An opt-out or unavailable slot raises
`wave_exact_three_required` and produces no prepared Wave plan.

- [ ] **Step 4: Run preparation regressions**

Run: `python -m pytest -q tests/test_registration_wave_intake.py tests/test_phase3_registration_prepare.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```text
git add src/sedb_ral/registration.py src/sedb_ral/registration_wave_intake.py tests/test_registration_wave_intake.py
git commit -m "feat: bind applicants to host-observed output items"
```

---

### Task 3: Wave Plan, Slot Ordering and Typed GENESIS

**Files:**
- Create: `src/sedb_ral/registration_wave_plan.py`
- Test: `tests/test_registration_wave_plan.py`

**Interfaces:**
- Produces:
  `build_wave_plan(candidates, policy, registry_status, checkpoint) -> RegistrationWavePlan`,
  `derive_next_slot(plan, slot_receipts, events) -> WaveSlot | None`, and
  `build_slot_request(plan, slot_index, predecessor, ledger_state) -> WaveSlotRequest`.

- [ ] **Step 1: Write order and H0 REDs**

```python
def test_slot_three_cannot_use_current_h1_without_slot_two_receipt():
    with pytest.raises(RALValidationError, match="wave_predecessor_missing"):
        build_slot_request(plan(), 3, predecessor=slot1_receipt(), ledger_state=h1())

def test_control_digest_is_not_genesis_ledger_head():
    with pytest.raises(RALValidationError, match="wave_ledger_state_invalid"):
        build_slot_request(plan(), 1, predecessor=None, ledger_state={"expected_ledger_head": control_digest()})
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_plan.py`

Expected: missing module/functions.

- [ ] **Step 3: Implement history-derived next-slot logic**

```python
def derive_next_slot(plan, slot_receipts, events):
    verified = verify_receipt_prefix(plan, slot_receipts, events)
    index = len(verified) + 1
    return None if index == 4 else plan.ordered_slots[index - 1]
```

Slot 1 requires null ledger head, `GENESIS`, event count 0 and separately
matching control digest. Slots 2/3 require exact predecessor slot receipt and
post-head.

- [ ] **Step 4: Run order controls**

Run: `python -m pytest -q tests/test_registration_wave_plan.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```text
git add src/sedb_ral/registration_wave_plan.py tests/test_registration_wave_plan.py
git commit -m "feat: enforce registration wave slot order"
```

---

### Task 4: Principal Approval and JIT Execution Authorization

**Files:**
- Create: `src/sedb_ral/registration_wave_authority.py`
- Test: `tests/test_registration_wave_authority.py`

**Interfaces:**
- Produces:
  `verify_application_approval(approval, application, principal_item, host_observation) -> None` and
  `verify_slot_execution_authorization(auth, plan, slot_request, approval, policy, checkpoint, current_status) -> None`.

- [ ] **Step 1: Write principal-role and separation REDs**

```python
def test_application_approval_does_not_authorize_execution():
    verify_application_approval(approval(), application(), user_item(), principal_host())
    with pytest.raises(RALValidationError, match="slot_execution_authorization_missing"):
        verify_slot_execution_authorization(None, plan(), request(), approval(), policy(), checkpoint(), status())

@pytest.mark.parametrize("role", ["assistant", "tool", "relay"])
def test_non_user_principal_evidence_is_unverified(role):
    with pytest.raises(RALValidationError, match="principal_authorship_unverified"):
        verify_application_approval(approval(), application(), principal_item(role=role), principal_host())
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_authority.py`

Expected: missing module/functions.

- [ ] **Step 3: Implement exact digest/time/status binding**

Check application digest, role=user item metadata/content digest, host parent
thread/turn, scope, expiry/revocation, wave/slot/request/policy/checkpoint and
current pre-head. Registrar/applicant output never enters principal evidence.

- [ ] **Step 4: Run authority controls**

Run: `python -m pytest -q tests/test_registration_wave_authority.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```text
git add src/sedb_ral/registration_wave_authority.py tests/test_registration_wave_authority.py
git commit -m "feat: separate application and slot authority"
```

---

### Task 5: Append-Only Production Wave Policy Control

**Files:**
- Create: `src/sedb_ral/registration_wave_policy.py`
- Modify: `src/sedb_ral/production_operations_layout.py` to include Wave policy
  fields in status without changing dormant bytes.
- Test: `tests/test_registration_wave_policy.py`

**Interfaces:**
- Produces:
  `plan_wave_policy_activation(storage, plan, authority, checkpoint) -> dict`,
  `activate_wave_policy(storage, request, authority, acl_observation) -> ActiveWavePolicyRecord`,
  `terminate_wave_policy(storage, terminal_event, authority) -> ActiveWavePolicyRecord`, and
  `registration_wave_status(storage) -> dict[str, object]`.

- [ ] **Step 1: Write dormant-preservation/status REDs**

```python
def test_wave_policy_appends_sequence_one_without_rewriting_dormant(tmp_path):
    storage = dormant_production_fixture(tmp_path)
    before = dormant_bytes(storage)
    active = activate_wave_policy(storage, request(), authority(), protected_acl())
    assert active.sequence == 1
    assert dormant_bytes(storage) == before

def test_expired_policy_refuses_execute_but_status_and_recovery_remain():
    status = registration_wave_status(expired_policy_storage())
    assert status["wave_status"] == "expired"
    with pytest.raises(RALValidationError, match="wave_policy_inactive"):
        require_wave_execution(status)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_policy.py`

Expected: missing Wave policy implementation.

- [ ] **Step 3: Implement create-only policy/control chain**

Use `policies/wave1-policy-{64hex}.json` and fixed-width
`active-policy/{sequence:020d}.json`. Bind predecessor, dormant policy, registry
generation, extension index, checkpoint, authority and status. Reuse existing
ACL/reparse/hard-link/ADS guards.

- [ ] **Step 4: Run policy and production-layout regressions**

Run: `python -m pytest -q tests/test_registration_wave_policy.py tests/test_production_operations_layout.py tests/test_production_operations_recovery.py`

Expected: PASS with dormant fixture bytes unchanged.

- [ ] **Step 5: Commit Task 5**

```text
git add src/sedb_ral/registration_wave_policy.py src/sedb_ral/production_operations_layout.py tests/test_registration_wave_policy.py
git commit -m "feat: add append-only Wave 1 policy control"
```

---

### Task 6: Explicit External Staging Store

**Files:**
- Create: `src/sedb_ral/registration_wave_store.py`
- Test: `tests/test_registration_wave_store.py`

**Interfaces:**
- Produces `RegistrationWaveStore(root: Path, expected_wave_digest: str)` with
  `put_claim`, `put_item_evidence`, `put_host_observation`, `put_prepared`,
  `put_approval`, `put_slot_request`, `put_slot_receipt`, `read_manifest`, and
  `verify()` create-only methods.

- [ ] **Step 1: Write path/idempotency/tamper REDs**

```python
def test_store_rejects_git_private_temp_reparse_hardlink_and_ads_roots(tmp_path):
    for root in forbidden_roots(tmp_path):
        with pytest.raises(RALValidationError, match="wave_staging_root_refused"):
            RegistrationWaveStore(root, expected_wave_digest=digest("wave"))

def test_same_id_changed_bytes_quarantines_without_overwrite(store):
    store.put_claim("slot:1", claim_a())
    with pytest.raises(RALValidationError, match="wave_staging_digest_conflict"):
        store.put_claim("slot:1", claim_b())
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_store.py`

Expected: missing store module.

- [ ] **Step 3: Implement explicit root and create-only storage**

Require an existing caller-supplied ACL-reviewed parent and a new absent Wave
directory. Reject repo roots, AI_HOME/private markers, temp fallback, links,
ADS and path escapes. Manifest binds every object ref/digest and has no raw
principal/task/turn values in public export.

- [ ] **Step 4: Run store controls**

Run: `python -m pytest -q tests/test_registration_wave_store.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

```text
git add src/sedb_ral/registration_wave_store.py tests/test_registration_wave_store.py
git commit -m "feat: stage registration wave evidence safely"
```

---

### Task 7: One-Slot Registrar Engine

**Files:**
- Create: `src/sedb_ral/registration_wave_engine.py`
- Test: `tests/test_registration_wave_engine.py`

**Interfaces:**
- Consumes: Tasks 1-6, `evaluate_prepared_registration()`,
  `build_admission_plan()` and `commit_admission_plan()`.
- Produces:
  `plan_wave_slot(...) -> PlannedWaveSlot` and
  `execute_wave_slot(...) -> WaveSlotReceipt`.

- [ ] **Step 1: Write one-slot/no-auto-loop REDs**

```python
def test_execute_slot_one_does_not_attempt_slot_two(tmp_path):
    result = execute_wave_slot(engine(tmp_path), slot_request(1), execution_auth(1))
    assert result.slot_index == 1
    assert result.post_head == h1()
    assert engine_calls(tmp_path) == [1]

def test_slot_three_with_h1_and_no_slot_two_receipt_refuses(tmp_path):
    with pytest.raises(RALValidationError, match="wave_predecessor_missing"):
        plan_wave_slot(engine(tmp_path), slot_request(3, expected_head=h1()), execution_auth(3))
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_engine.py`

Expected: missing engine.

- [ ] **Step 3: Implement preflight/restage/commit/readback**

Validate Wave policy/status, plan/order, principal approval, JIT authorization,
checkpoint and expected head before using the existing registrar Core. Build
and restage the complete candidate chain. Execute exactly one slot, then
produce a receipt only after canonical projection readback. If B6A is pending,
record `canonical_committed_readback_failed` and stop later slots.

- [ ] **Step 4: Run engine plus registrar regressions**

Run: `python -m pytest -q tests/test_registration_wave_engine.py tests/test_phase3_registration_admission.py tests/test_phase3_registrar_plan.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 7**

```text
git add src/sedb_ral/registration_wave_engine.py tests/test_registration_wave_engine.py
git commit -m "feat: execute one registration wave slot safely"
```

---

### Task 8: Crash Prefix and Outer-Receipt Recovery

**Files:**
- Create: `src/sedb_ral/registration_wave_recovery.py`
- Test: `tests/test_registration_wave_recovery.py`

**Interfaces:**
- Produces:
  `inspect_wave_slot_prefix(...) -> durable_receipt | recovery_required | registrar_partial_transaction`,
  `recover_wave_slot_receipt(...) -> WaveSlotRecoveryReceipt`, and
  `plan_wave_continuation(...) -> dict[str, object]`.

- [ ] **Step 1: Write three crash-point REDs**

```python
def test_durable_core_receipt_retry_is_idempotent():
    assert inspect_wave_slot_prefix(complete_with_receipt()).status == "durable_receipt"

def test_complete_events_without_outer_receipt_require_recovery():
    assert inspect_wave_slot_prefix(complete_without_outer()).status == "recovery_required"

def test_mid_chain_prefix_is_not_recovery_required_or_accepted():
    assert inspect_wave_slot_prefix(partial_prefix()).status == "registrar_partial_transaction"
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_recovery.py`

Expected: missing recovery module.

- [ ] **Step 3: Implement exact prefix and continuation gates**

Reconstruct event IDs/digests/pre/post heads from canonical files. Recover only
a complete exact prefix under separate principal authorization. A stopped,
expired or revoked Wave needs a new continuation policy, checkpoint, current
head and execution authorization; unchanged application approval remains valid
only when active/unexpired/unrevoked.

- [ ] **Step 4: Run recovery regressions**

Run: `python -m pytest -q tests/test_registration_wave_recovery.py tests/test_phase3_registrar_recovery.py tests/test_production_operations_recovery.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 8**

```text
git add src/sedb_ral/registration_wave_recovery.py tests/test_registration_wave_recovery.py
git commit -m "feat: recover Wave 1 receipts without blind replay"
```

---

### Task 9: Public RAL Readback Bundle for LIMEN B6A

**Files:**
- Create: `src/sedb_ral/registration_wave_readback.py`
- Test: `tests/test_registration_wave_readback.py`

**Interfaces:**
- Produces:
  `build_wave_readback_bundle(ledger_root, expected_head, plan, receipts) -> dict[str, object]` and
  `verify_fresh_limen_observation(bundle, observation) -> dict[str, object]`.

- [ ] **Step 1: Write fresh-vs-claim-time observation REDs**

```python
def test_claim_time_item_cannot_be_reused_for_b6a():
    with pytest.raises(RALValidationError, match="stale_readback_observation"):
        verify_fresh_limen_observation(bundle(h1()), claim_time_observation())

def test_each_post_slot_bundle_resolves_only_admitted_locators():
    assert resolved_slots(bundle(h1())) == (1,)
    assert resolved_slots(bundle(h2())) == (1, 2)
    assert resolved_slots(bundle(h3())) == (1, 2, 3)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_readback.py`

Expected: missing module.

- [ ] **Step 3: Implement sanitized digest-bound bundle**

Bind exact RAL view schema/raw/public digests, ledger/authority/binding heads,
source events and per-slot application/resident/address/binding projection
digests. Require a fresh task/turn observation; record resolution separately
from pre-turn enforcement. Do not implement LIMEN code in this repo.

- [ ] **Step 4: Run RAL/LIMEN exporter regressions**

Run: `python -m pytest -q tests/test_registration_wave_readback.py tests/test_limen_public_view_contract.py tests/test_limen_public_view_export.py tests/test_limen_public_view_gate.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 9**

```text
git add src/sedb_ral/registration_wave_readback.py tests/test_registration_wave_readback.py
git commit -m "feat: export Wave 1 public readback evidence"
```

---

### Task 10: Typed CLI Surface

**Files:**
- Create: `src/sedb_ral/registration_wave_cli.py`
- Modify: `src/sedb_ral/cli.py` to register only the new subcommands.
- Test: `tests/test_registration_wave_cli.py`

**Interfaces:**
- Adds:
  `registration-wave validate-intake`,
  `prepare-slot`, `build-plan`, `policy-plan`, `policy-status`, `slot-plan`,
  `slot-admit`, `slot-recover`, `wave-status`, and `export-readback`.

- [ ] **Step 1: Write CLI no-write/exit-code REDs**

```python
def test_validate_and_plan_commands_write_only_explicit_output(tmp_path):
    result = run_cli("registration-wave", "build-plan", *inputs(tmp_path))
    assert result.exit_code == 0
    assert production_root_digest() == production_before()

def test_slot_admit_requires_explicit_synthetic_root_until_live_gate():
    result = run_cli("registration-wave", "slot-admit", *without_synthetic_root())
    assert result.exit_code == 1
    assert result.json["reason_code"] == "production_wave_execution_not_authorized"
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_cli.py`

Expected: parser command missing.

- [ ] **Step 3: Implement canonical JSON CLI handlers**

Use strict UTF-8/duplicate-key parsing, canonical stdout, typed exit codes and
explicit output roots. The code candidate hard-refuses exact production
execution unless a later operational plan replaces the candidate guard under
Neo.K authority.

- [ ] **Step 4: Run CLI/package regressions**

Run: `python -m pytest -q tests/test_registration_wave_cli.py tests/test_phase3a_operations_cli.py tests/test_production_operations_cli.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 10**

```text
git add src/sedb_ral/registration_wave_cli.py src/sedb_ral/cli.py tests/test_registration_wave_cli.py
git commit -m "feat: expose typed Wave 1 CLI"
```

---

### Task 11: Deterministic Wave Acceptance Matrix

**Files:**
- Create: `src/sedb_ral/registration_wave_acceptance.py`
- Create: `scripts/validate_registration_wave.py`
- Create: `tests/test_registration_wave_acceptance.py`

**Interfaces:**
- Produces `validate_registration_wave(root: Path) -> RegistrationWaveAcceptanceReport`
  covering exact W1-001 through W1-053.

- [ ] **Step 1: Write matrix completeness and mutation REDs**

```python
def test_acceptance_has_every_unique_case_and_executed_control(tmp_path):
    report = validate_registration_wave(tmp_path)
    assert tuple(case.case_id for case in report.cases) == tuple(f"W1-{i:03d}" for i in range(1, 54))
    assert all(case.executed and case.passed for case in report.cases)
    assert report.effects == {"real_applicants": 0, "production_events": 0, "private_reads": 0, "network_calls": 0}
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_acceptance.py`

Expected: missing report/module.

- [ ] **Step 3: Implement two-run deterministic synthetic acceptance**

Execute all 53 negative/positive populations in disposable storage. Compare
canonical report/execution digests across two runs with supplied opaque fixture
IDs. Include active policy, three slots, crash/recovery, locator, authorship,
authority, B6A bundle and private/no-network controls.

- [ ] **Step 4: Run acceptance and generate temp report**

Run:

```powershell
python -m pytest -q tests/test_registration_wave_acceptance.py
$out = Join-Path $env:TEMP 'r3b-c-wave1-synthetic.json'
python scripts/validate_registration_wave.py --output $out
```

Expected: 53 pass, zero fail/blocked, repeated digest match, zero real effects.

- [ ] **Step 5: Commit Task 11**

```text
git add src/sedb_ral/registration_wave_acceptance.py scripts/validate_registration_wave.py tests/test_registration_wave_acceptance.py
git commit -m "test: validate the three-seat registration wave"
```

---

### Task 12: Packaging, CI, Documentation and Final Candidate Gate

**Files:**
- Modify: `pyproject.toml` version from `0.5.0b1` to `0.5.0c1`; retain the
  existing `schemas/*.json` package-data rule.
- Modify: `.github/workflows/phase3a.yml` to add Wave focused commands on
  Windows/Ubuntu without changing existing gates.
- Create: `docs/runtime/R3B_C_THREE_SEAT_WAVE1.md`.
- Test: `tests/test_registration_wave_packaging.py`.

**Interfaces:**
- Produces an installed local candidate containing Wave modules/schemas, a
  public runbook, wheel evidence and exact source/test manifests.

- [ ] **Step 1: Write installed-wheel/resource REDs**

```python
def test_clean_wheel_contains_all_wave_schemas_and_cli(tmp_path):
    wheel = build_clean_wheel(tmp_path)
    install = install_wheel(wheel, tmp_path / "install")
    assert expected_wave_schema_names() <= installed_schema_names(install)
    assert installed_cli_help(install, "registration-wave").exit_code == 0
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_packaging.py`

Expected: missing installed Wave resources.

- [ ] **Step 3: Add package resources, CI focus and runbook**

The runbook states that current applicant claims are candidate-only until exact
assistant item evidence is host-visible. It contains no real task IDs, labels,
digests, staging paths or production authority.

- [ ] **Step 4: Run final code-candidate gates**

Run:

```powershell
python -m pytest -q -rs
python -m compileall -q src tests
python scripts/validate_registry_root.py --verify-production-receipt evidence/production-registry-root/2026-08-25-production.json
$r3b = Join-Path $env:TEMP 'r3b-b-regression.json'
$wave = Join-Path $env:TEMP 'r3b-c-wave1.json'
python scripts/validate_production_operations.py --output $r3b
python scripts/validate_registration_wave.py --output $wave
git diff --check 580b647d2ce567ece16d5e07f9b9aa8dfa5b79a2..HEAD
```

Expected: zero failures; every skip listed; P3-4/R3B-B unchanged; W1 53/53;
production root remains active_dormant with 0 applications/residents/events;
worktree clean after commit.

- [ ] **Step 5: Build retained wheel and record exact hashes**

Use a new explicit temporary root. Record wheel bytes/SHA, installed module
source, schema bytes/SHA, dependency metadata, no-vendoring/runtime-boundary
scans and reproducibility status. Do not publish.

- [ ] **Step 6: Commit Task 12**

```text
git add pyproject.toml .github/workflows/phase3a.yml docs/runtime/R3B_C_THREE_SEAT_WAVE1.md tests/test_registration_wave_packaging.py
git commit -m "docs: record R3B-C Wave 1 candidate evidence"
```

- [ ] **Step 7: Stop for one Twin final review**

Review exact code head/tree, full tests, W1 acceptance, wheel, production
read-only status and zero effects. Do not collect new host evidence, prepare
real applications, activate Wave policy or append production events.

## Spec coverage map

- Equal standing, public-only scope and no hierarchy: Global Constraints plus
  Tasks 1, 3, 9 and 11.
- Applicant claim/item/host binding, exact-three gate and continuity refusal:
  Tasks 1 and 2.
- Canonical locator grammar and collision separation: Tasks 1, 2 and 11.
- Principal application approval and separate JIT execution authorization:
  Tasks 1 and 4.
- Append-only Wave policy/control/status and dormant preservation: Tasks 1 and
  5.
- Explicit external staging and no private/Git/temp fallback: Task 6.
- Typed H0, Wave plan, slot order, predecessor receipts and one-slot execution:
  Tasks 1, 3 and 7.
- Durable receipt retry, outer-receipt recovery, partial prefix and continuation
  policy: Tasks 1 and 8.
- Fresh post-append public RAL bundle and claim-time/B6A separation: Tasks 1 and
  9; LIMEN consumption remains the later B6A plan.
- Typed CLI and production hard-stop: Task 10.
- W1-001 through W1-053, deterministic controls and zero real effects: Task 11.
- Wheel/CI/runbook/final evidence and one Twin gate: Task 12.

## Post-plan gates not authorized here

After this plan's candidate is accepted, create two separately reviewed
artifacts:

1. a LIMEN B6A plan consuming the RAL readback bundle and testing three fresh
   post-append observations; and
2. an operational Wave 1 plan binding the real applicant items, staging root,
   three application digests, three Neo.K application approvals, policy
   activation, three separate JIT execution authorizations and three manual
   slot admissions.

Neither follow-up may infer authority from this implementation plan.
