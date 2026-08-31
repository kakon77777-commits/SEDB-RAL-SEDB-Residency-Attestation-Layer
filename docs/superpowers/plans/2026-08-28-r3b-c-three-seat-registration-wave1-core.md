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

This plan modifies SEDB-RAL only. It produces a sealed, digest-bound public readback
bundle that a later LIMEN B6A plan consumes. It does not modify LIMEN, SOACR,
Fabric, MSP, ARCP, AI Residence or native provider memory.

## Inline FCAO slice boundaries

No per-task reviewer is dispatched. One implementer executes tasks inline and
one necessary Twin performs read-only review at each boundary:

```text
Slice A  Tasks 1-4   contracts, synthetic context, intake wrapper, Wave plan
         Twin: applicant/context-memory boundary reviewer

Slice B  Tasks 5-9   authority, policy, staging, one-slot engine, recovery
         Twin: RAL/Registrar domain reviewer

Slice C  Tasks 10-13 RAL bundle, CLI, acceptance, packaging/evidence
         Twin: one final RAL/portability reviewer
```

A Slice finding returns to the same inline implementer. Do not spawn a fresh
reviewer per task and do not infer operational approval from code review.

---

### Task 1: Closed Wave Contract Assets and Models

**Files:**
- Create: `src/sedb_ral/registration_wave_models.py`
- Create: `src/sedb_ral/schemas/registration-applicant-item-evidence.schema.json`
- Create: `src/sedb_ral/schemas/registration-host-observation-v0.2.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-prepared-candidate.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-plan.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-policy.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-active-policy-record.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-policy-activation-request.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-policy-activation-authority.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-policy-activation-receipt.schema.json`
- Create: `src/sedb_ral/schemas/principal-application-approval.schema.json`
- Create: `src/sedb_ral/schemas/registration-slot-execution-authorization.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-slot-request.schema.json`
- Create: `src/sedb_ral/schemas/synthetic-wave-slot-execution-result.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-slot-receipt.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-slot-recovery-authorization.schema.json`
- Create: `src/sedb_ral/schemas/synthetic-wave-slot-recovery-result.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-slot-recovery-receipt.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-terminal-event.schema.json`
- Create: `src/sedb_ral/schemas/registration-wave-readback-bundle.schema.json`
- Test: `tests/test_registration_wave_contracts.py`

**Interfaces:**
- Consumes: `canonical_bytes`, `loads_strict`, `sha256_ref`, `validate_contract`.
- Produces: strict `_WaveContract` canonical base plus frozen
  `ApplicantItemEvidence`, `WaveHostObservation`, `WaveSlot`,
  `RegistrationWavePreparedCandidate`,
  `RegistrationWavePlan`, `RegistrationWavePolicy`, `ActiveWavePolicyRecord`,
  `WavePolicyActivationRequest`, `WavePolicyActivationAuthority`,
  `WavePolicyActivationReceipt`,
  `PrincipalApplicationApproval`, `SlotExecutionAuthorization`,
  `WaveSlotRequest`, `SyntheticWaveSlotExecutionResult`, `WaveSlotReceipt`,
  `WaveSlotRecoveryAuthorization`,
  `SyntheticWaveSlotRecoveryResult`,
  `WaveSlotRecoveryReceipt`,
  `WaveTerminalEvent`, `WaveReadbackBundle`; each exposes `from_dict()`,
  `to_dict()`, `sealed()` and `verify()`.

`WaveSlotReceipt` and `WaveSlotRecoveryReceipt` are production-contract models
and fixtures only in this implementation plan. Synthetic runtime APIs must
return the two `Synthetic*Result` types and must never publish either production
receipt type.

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
            ApplicantItemEvidence.from_dict(valid_item_evidence(role=role, kind=kind))

def test_host_v02_requires_exact_item_evidence_ref_and_digest():
    with pytest.raises(RALValidationError, match="host_item_evidence_mismatch"):
        WaveHostObservation.from_dict(swapped_item_binding_host_v02())
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
    candidate_ref: str
    candidate_digest: str
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

### Task 2: Non-Bypassable Synthetic Execution Context and Effect Journal

**Files:**
- Create: `src/sedb_ral/registration_wave_context.py`
- Test: `tests/test_registration_wave_context.py`

**Interfaces:**
- Produces `WaveExecutionMode = synthetic_test | real_staging_candidate`,
  sealed `SyntheticWaveExecutionContext`, and `WaveEffectJournal`.
- `SyntheticWaveExecutionContext.verify_before_io(operation, target) -> None`
  is required by every Task 3-12 API before any filesystem/capability read or
  write.
- No production execution context is implemented in this plan.

- [ ] **Step 1: Write direct-API root and live-capability REDs**

```python
@pytest.mark.parametrize("target", [exact_production_root(), production_descendant(), private_root(), repo_root(), junction_alias(), ads_path()])
def test_synthetic_context_rejects_forbidden_roots_before_io(target, spies):
    context = synthetic_context(target_root=target, spies=spies)
    with pytest.raises(RALValidationError, match="synthetic_wave_boundary_refused"):
        context.verify_before_io("prepare", target)
    assert spies.reads == 0
    assert spies.writes == 0

def test_callers_cannot_label_production_as_synthetic(spies):
    forged = synthetic_context(target_root=exact_production_root(), marker="synthetic")
    with pytest.raises(RALValidationError, match="synthetic_wave_boundary_refused"):
        forged.verify_before_io("policy_activate", exact_production_root())
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_context.py`

Expected: missing context/effect-journal module.

- [ ] **Step 3: Implement context modes and measured effect journal**

```python
@dataclass(frozen=True)
class SyntheticWaveExecutionContext:
    mode: WaveExecutionMode
    fixture_root: Path
    target_root: Path
    fixture_marker_ref: str
    fixture_marker_digest: str
    forbidden_roots: tuple[Path, ...]
    context_digest: str

@dataclass
class WaveEffectJournal:
    fixture_reads: int = 0
    staging_writes: int = 0
    synthetic_ledger_writes: int = 0
    synthetic_receipt_writes: int = 0
    production_reads: int = 0
    production_writes: int = 0
    private_reads: int = 0
    private_writes: int = 0
    network_calls: int = 0
    provider_calls: int = 0
    fabric_calls: int = 0
    mcp_calls: int = 0
    external_cli_calls: int = 0
```

`synthetic_test` permits only an explicit disposable root under its sealed test
sandbox marker. `real_staging_candidate` permits only an explicit ACL-reviewed,
non-temp, non-Git, non-private staging candidate root and still rejects the
production registry. Both modes resolve paths and verify containment, links,
hard links and ADS before the first read/write. Production support requires a
future separately reviewed adapter, not a boolean or CLI flag.

- [ ] **Step 4: Run context/effect controls**

Run: `python -m pytest -q tests/test_registration_wave_context.py`

Expected: PASS, including injected network/provider/Fabric/private/production
effects turning the journal nonzero and the gate red.

- [ ] **Step 5: Commit Task 2**

```text
git add src/sedb_ral/registration_wave_context.py tests/test_registration_wave_context.py
git commit -m "feat: enforce synthetic Wave execution boundaries"
```

---

### Task 3: Applicant Item Evidence and Durable Prepared Candidate

**Files:**
- Create: `src/sedb_ral/registration_wave_intake.py`
- Modify: `src/sedb_ral/registration.py` only to expose reusable canonical
  claim digest helper; do not relax `prepare_registration()` v0.1.
- Test: `tests/test_registration_wave_intake.py`

**Interfaces:**
- Consumes: `PreparedRegistration`, `RegistrationIds`,
  `prepare_registration()`, Task 1 models and a verified Task 2
  `SyntheticWaveExecutionContext`.
- Produces:
  `canonical_claim_digest(claim: Mapping[str, object]) -> str`,
  `verify_applicant_item_evidence(claim, item, host) -> None`,
  `prepare_wave_candidate(context, claim, item, host_v02, ids_factory) -> RegistrationWavePreparedCandidate` and
  `validate_exact_three_candidates(candidates) -> tuple[RegistrationWavePreparedCandidate, ...]`.

- [ ] **Step 1: Write applicant-authorship and continuity REDs**

```python
@pytest.mark.parametrize("kind", ["userMessage", "codexDelegation", "reasoning", "toolCall", "commandExecution"])
def test_non_agent_items_cannot_prepare_or_allocate_ids(kind, counting_ids_factory):
    with pytest.raises(RALValidationError, match="applicant_item_role_invalid"):
        prepare_wave_candidate(context(), valid_claim(), item(kind=kind), host_v02(), counting_ids_factory)
    assert counting_ids_factory.calls == 0

def test_continue_and_missing_agent_message_stop_before_id_assignment(counting_ids_factory):
    with pytest.raises(RALValidationError, match="continuity_evidence_required"):
        prepare_wave_candidate(context(), valid_claim(continuity="continue"), item(), host_v02(), counting_ids_factory)
    with pytest.raises(RALValidationError, match="applicant_output_unavailable"):
        verify_applicant_item_evidence(valid_claim(), unavailable_item(), host_v02())
    assert counting_ids_factory.calls == 0

def test_prepared_candidate_replays_and_rejects_swapped_item_evidence(tmp_path):
    candidate = prepare_wave_candidate(context(tmp_path), valid_claim(), item(), host_v02(), ids_factory())
    assert RegistrationWavePreparedCandidate.from_dict(candidate.to_dict()) == candidate
    with pytest.raises(RALValidationError, match="wave_candidate_evidence_mismatch"):
        RegistrationWavePreparedCandidate.from_dict(swap_item_evidence(candidate.to_dict()))
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

After all evidence gates pass, call `ids_factory()` exactly once. Derive a
closed v0.1 compatibility host observation from v0.2, call the unchanged
`prepare_registration()`, and return a sealed wrapper containing:

```text
candidate_id
claim_ref + canonical_claim_digest
item_evidence_ref + item_evidence_digest
host_v02_ref + host_v02_digest
compatibility_host_v01_ref + compatibility_host_v01_digest
prepared_registration_ref + prepared_registration_digest
application_ref + application_digest
canonical_locator
not_claimed
candidate_digest
```

The wrapper—not bare `PreparedRegistration`—is stored, restarted, placed in a
Wave slot and bound by the Wave plan. Item/host/compatibility/prepared evidence
cannot become ephemeral after preparation.

Require three distinct canonical locators and exactly three eligible candidates
before returning a wave candidate tuple. An opt-out or unavailable slot raises
`wave_exact_three_required` and produces no prepared Wave plan.

- [ ] **Step 4: Run preparation regressions**

Run: `python -m pytest -q tests/test_registration_wave_intake.py tests/test_phase3_registration_prepare.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```text
git add src/sedb_ral/registration.py src/sedb_ral/registration_wave_intake.py tests/test_registration_wave_intake.py
git commit -m "feat: bind applicants to host-observed output items"
```

---

### Task 4: Wave Plan, Slot Ordering and Typed GENESIS

**Files:**
- Create: `src/sedb_ral/registration_wave_plan.py`
- Test: `tests/test_registration_wave_plan.py`

**Interfaces:**
- Produces:
  `build_wave_plan(candidates: tuple[RegistrationWavePreparedCandidate, ...], policy, registry_status, checkpoint) -> RegistrationWavePlan`,
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

def test_changed_or_swapped_candidate_digest_changes_or_refuses_plan():
    original = build_wave_plan(candidates(), policy(), status(), checkpoint())
    with pytest.raises(RALValidationError, match="wave_candidate_binding_mismatch"):
        build_wave_plan(swap_candidate_evidence(candidates()), policy(), status(), checkpoint())
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

- [ ] **Step 5: Commit Task 4**

```text
git add src/sedb_ral/registration_wave_plan.py tests/test_registration_wave_plan.py
git commit -m "feat: enforce registration wave slot order"
```

---

### Task 5: Principal Approval and JIT Execution Authorization

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

- [ ] **Step 5: Commit Task 5**

```text
git add src/sedb_ral/registration_wave_authority.py tests/test_registration_wave_authority.py
git commit -m "feat: separate application and slot authority"
```

---

### Task 6: Append-Only Production Wave Policy Control

**Files:**
- Create: `src/sedb_ral/registration_wave_policy.py`
- Modify: `src/sedb_ral/production_operations_layout.py` to include Wave policy
  fields in status without changing dormant bytes.
- Test: `tests/test_registration_wave_policy.py`

**Interfaces:**
- Produces:
  `WavePolicyActivationResult(record: ActiveWavePolicyRecord, receipt: WavePolicyActivationReceipt)`,
  `plan_wave_policy_activation(context, storage, plan, approvals, authority, checkpoint) -> dict`,
  `activate_wave_policy(context, storage, request, approvals, authority, acl_observation) -> WavePolicyActivationResult`,
  `terminate_wave_policy(context, storage, terminal_event, authority) -> ActiveWavePolicyRecord`, and
  `registration_wave_status(context, storage) -> dict[str, object]`.

- [ ] **Step 1: Write dormant-preservation/status REDs**

```python
def test_wave_policy_appends_sequence_one_without_rewriting_dormant(tmp_path):
    storage = dormant_production_fixture(tmp_path)
    before = dormant_bytes(storage)
    journal = WaveEffectJournal()
    activated = activate_wave_policy(context(tmp_path, journal=journal), storage, request(), three_approvals(), authority(), protected_acl())
    assert activated.record.sequence == 1
    assert activated.receipt.active_policy_digest == activated.record.digest
    assert registration_wave_status(context(tmp_path), storage)["activation_receipt_status"] == "verified"
    assert activation_receipt_path(storage, 1).relative_to(storage.root) == Path(
        "evidence/registration-wave-policy-activation-00000000000000000001.json"
    )
    assert journal.synthetic_receipt_writes == 1
    assert journal.refs("synthetic_receipt_writes") == (activated.receipt.ref,)
    assert dormant_bytes(storage) == before

def test_policy_requires_three_exact_application_approvals_before_io(tmp_path, io_spies):
    with pytest.raises(RALValidationError, match="wave_exact_three_approvals_required"):
        activate_wave_policy(context(tmp_path, spies=io_spies), storage(tmp_path), request(), two_approvals(), authority(), protected_acl())
    assert io_spies.reads == 0
    assert io_spies.writes == 0

def test_expired_policy_refuses_execute_but_status_and_recovery_remain():
    status = registration_wave_status(context(), expired_policy_storage())
    assert status["wave_status"] == "expired"
    with pytest.raises(RALValidationError, match="wave_policy_inactive"):
        require_wave_execution(status)

def test_crash_after_active_record_before_receipt_is_unreceipted(tmp_path):
    storage = dormant_production_fixture(tmp_path)
    journal = WaveEffectJournal()
    with pytest.raises(InjectedCrash, match="after_active_record_before_receipt"):
        activate_wave_policy(
            context(tmp_path, journal=journal, crash_at="after_active_record_before_receipt"),
            storage, request(), three_approvals(), authority(), protected_acl(),
        )
    status = registration_wave_status(context(tmp_path), storage)
    assert status["wave_status"] == "active_unreceipted"
    assert status["activation_receipt_status"] == "missing"
    assert journal.synthetic_receipt_writes == 0
    with pytest.raises(RALValidationError, match="wave_policy_unreceipted"):
        require_wave_execution(status)

def test_exact_retry_finalizes_missing_receipt_without_second_active_record(tmp_path):
    storage = crashed_after_active_record_fixture(tmp_path)
    before = active_policy_files(storage)
    activated = activate_wave_policy(
        context(tmp_path), storage, request(), three_approvals(), authority(), protected_acl()
    )
    assert active_policy_files(storage) == before
    assert len(before) == 1
    assert activated.receipt.active_policy_digest == activated.record.digest
    assert registration_wave_status(context(tmp_path), storage)["activation_receipt_status"] == "verified"

def test_tampered_or_cross_bound_activation_receipt_refuses_execution(tmp_path):
    storage = activated_fixture(tmp_path)
    mutate_activation_receipt(storage, active_policy_digest=digest("other"))
    with pytest.raises(RALValidationError, match="wave_policy_activation_receipt_mismatch"):
        registration_wave_status(context(tmp_path), storage)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_policy.py`

Expected: missing Wave policy implementation.

- [ ] **Step 3: Implement create-only policy/control chain**

Use create-only `policies/wave1-policy-{64hex}.json`, fixed-width
`active-policy/{sequence:020d}.json`, and the existing evidence convention
`evidence/registration-wave-policy-activation-{sequence:020d}.json`. Bind the
receipt to the exact policy and active-policy record refs/digests, predecessor,
dormant policy, registry generation, extension index, checkpoint, authority,
request, all three approvals, ACL observation and post-write readback. Before any IO,
require exactly three active `PrincipalApplicationApproval` objects whose
application digests equal the ordered candidate/application digests in the Wave
plan; duplicate, missing, changed, expired or revoked approval refuses. Reuse
existing ACL/reparse/hard-link/ADS guards after the context pre-IO gate.

Publish the active-policy record first and its activation receipt second, both
with no-replace semantics, then read back and verify both before returning the
composite `WavePolicyActivationResult`. A crash in that gap is a durable
`active_unreceipted` state: status/diagnosis work, but intake/planning/execution
fail closed. An exact retry may create the missing receipt after verifying every
bound input and the unchanged record; changed inputs, changed bytes, a second
receipt, or a mismatched digest fail closed without overwrite.

- [ ] **Step 4: Run policy and production-layout regressions**

Run: `python -m pytest -q tests/test_registration_wave_policy.py tests/test_production_operations_layout.py tests/test_production_operations_recovery.py`

Expected: PASS with dormant fixture bytes unchanged.

- [ ] **Step 5: Commit Task 6**

```text
git add src/sedb_ral/registration_wave_policy.py src/sedb_ral/production_operations_layout.py tests/test_registration_wave_policy.py
git commit -m "feat: add append-only Wave 1 policy control"
```

---

### Task 7: Explicit External Staging Store

**Files:**
- Create: `src/sedb_ral/registration_wave_store.py`
- Test: `tests/test_registration_wave_store.py`

**Interfaces:**
- Produces `RegistrationWaveStore(context: SyntheticWaveExecutionContext, root: Path, expected_wave_digest: str)` with
  `put_claim`, `put_item_evidence`, `put_host_observation`, `put_candidate`,
  `put_approval`, `put_slot_request`, `put_slot_result`,
  `put_recovery_result`,
  `read_manifest`, and
  `verify()` create-only methods.

- [ ] **Step 1: Write path/idempotency/tamper REDs**

```python
def test_synthetic_test_mode_accepts_only_its_sealed_tmp_sandbox(tmp_path):
    store = RegistrationWaveStore(synthetic_test_context(tmp_path), tmp_path / "wave", digest("wave"))
    assert store.verify()["mode"] == "synthetic_test"

def test_real_staging_mode_rejects_temp_git_private_reparse_hardlink_and_ads(tmp_path):
    for root in forbidden_real_staging_roots(tmp_path):
        with pytest.raises(RALValidationError, match="wave_staging_root_refused"):
            RegistrationWaveStore(real_staging_context(root), root, digest("wave"))

def test_same_id_changed_bytes_quarantines_without_overwrite(store):
    store.put_claim("slot:1", claim_a())
    with pytest.raises(RALValidationError, match="wave_staging_digest_conflict"):
        store.put_claim("slot:1", claim_b())

def test_synthetic_result_paths_reject_production_receipt_types(store):
    with pytest.raises(RALValidationError, match="synthetic_result_type_required"):
        store.put_slot_result("slot:1", production_slot_receipt())
    with pytest.raises(RALValidationError, match="synthetic_result_type_required"):
        store.put_recovery_result("slot:1", production_recovery_receipt())
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_store.py`

Expected: missing store module.

- [ ] **Step 3: Implement explicit root and create-only storage**

Call `context.verify_before_io()` before every read or write. In
`synthetic_test`, require the target under the exact sealed pytest sandbox. In
`real_staging_candidate`, require an existing caller-supplied ACL-reviewed,
non-temp parent and a new absent Wave directory. Both modes reject production,
repo, AI_HOME/private, links, hard links, ADS and path escapes. Manifest binds
the full `RegistrationWavePreparedCandidate` ref/digest plus every evidence
object; no raw principal/task/turn values enter public export.

- [ ] **Step 4: Run store controls**

Run: `python -m pytest -q tests/test_registration_wave_store.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 7**

```text
git add src/sedb_ral/registration_wave_store.py tests/test_registration_wave_store.py
git commit -m "feat: stage registration wave evidence safely"
```

---

### Task 8: One-Slot Registrar Engine

**Files:**
- Create: `src/sedb_ral/registration_wave_engine.py`
- Test: `tests/test_registration_wave_engine.py`

**Interfaces:**
- Consumes: Tasks 1-7, `RegistrationWavePreparedCandidate`,
  `evaluate_prepared_registration()`,
  `build_admission_plan()` and `commit_admission_plan()`.
- Produces:
  `plan_wave_slot(context, candidate, ...) -> PlannedWaveSlot` and
  `simulate_wave_slot(context, candidate, ...) -> SyntheticWaveSlotExecutionResult`.

- [ ] **Step 1: Write one-slot/no-auto-loop REDs**

```python
def test_simulate_slot_one_does_not_attempt_slot_two(tmp_path):
    result = simulate_wave_slot(context(tmp_path), candidate(1), engine(tmp_path), slot_request(1), execution_auth(1))
    assert result.slot_index == 1
    assert result.post_head == h1()
    assert result.execution_scope == "synthetic"
    assert result.production_wave_run == "NOT_RUN"
    assert result.live_limen_b6a == "NOT_RUN"
    assert engine_calls(tmp_path) == [1]

def test_slot_three_with_h1_and_no_slot_two_receipt_refuses(tmp_path):
    with pytest.raises(RALValidationError, match="wave_predecessor_missing"):
        plan_wave_slot(context(tmp_path), candidate(3), engine(tmp_path), slot_request(3, expected_head=h1()), execution_auth(3))
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_engine.py`

Expected: missing engine.

- [ ] **Step 3: Implement preflight/restage/commit/readback**

Call `context.verify_before_io()` first. Validate candidate wrapper/item/host
evidence, Wave policy/status, plan/order, three approval eligibility, JIT
authorization, checkpoint and expected head before using the existing registrar
Core against synthetic storage only. Build and restage the complete candidate
chain. Execute exactly one synthetic slot and produce a sealed
`SyntheticWaveSlotExecutionResult` with
`live_limen_b6a=NOT_RUN` and `production_wave_run=NOT_RUN`. Never emit a
production `WaveSlotReceipt`, `accepted`, or
`canonical_committed_readback_failed` object in this plan. The later operational
adapter alone may construct the real receipt after production append/readback.

- [ ] **Step 4: Run engine plus registrar regressions**

Run: `python -m pytest -q tests/test_registration_wave_engine.py tests/test_phase3_registration_admission.py tests/test_phase3_registrar_plan.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 8**

```text
git add src/sedb_ral/registration_wave_engine.py tests/test_registration_wave_engine.py
git commit -m "feat: simulate one registration wave slot safely"
```

---

### Task 9: Crash Prefix and Outer-Receipt Recovery

**Files:**
- Create: `src/sedb_ral/registration_wave_recovery.py`
- Test: `tests/test_registration_wave_recovery.py`

**Interfaces:**
- Produces:
  `inspect_wave_slot_prefix(context, ...) -> durable_receipt | recovery_required | registrar_partial_transaction`,
  `recover_synthetic_wave_slot_result(context, recovery_authorization, ...) -> SyntheticWaveSlotRecoveryResult`, and
  `plan_wave_continuation(context, ...) -> dict[str, object]`.

- [ ] **Step 1: Write three crash-point REDs**

```python
def test_durable_core_receipt_retry_is_idempotent():
    assert inspect_wave_slot_prefix(complete_with_receipt()).status == "durable_receipt"

def test_complete_events_without_outer_receipt_require_recovery():
    assert inspect_wave_slot_prefix(complete_without_outer()).status == "recovery_required"

def test_mid_chain_prefix_is_not_recovery_required_or_accepted():
    assert inspect_wave_slot_prefix(partial_prefix()).status == "registrar_partial_transaction"

def test_recovery_without_exact_recovery_authorization_fails_before_io(io_spies):
    with pytest.raises(RALValidationError, match="wave_recovery_authorization_missing"):
        recover_synthetic_wave_slot_result(context(spies=io_spies), None, complete_without_outer())
    assert io_spies.reads == 0
    assert io_spies.writes == 0

def test_synthetic_recovery_never_emits_a_production_receipt(tmp_path):
    recovered = recover_synthetic_wave_slot_result(
        context(tmp_path), recovery_authorization(), complete_without_outer()
    )
    assert isinstance(recovered, SyntheticWaveSlotRecoveryResult)
    assert recovered.execution_scope == "synthetic"
    assert recovered.production_wave_run == "NOT_RUN"
    assert recovered.live_limen_b6a == "NOT_RUN"
    assert not isinstance(recovered, (WaveSlotReceipt, WaveSlotRecoveryReceipt))
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_recovery.py`

Expected: missing recovery module.

- [ ] **Step 3: Implement exact prefix and continuation gates**

Call `context.verify_before_io()` before prefix reads. Reconstruct event
IDs/digests/pre/post heads from synthetic canonical files. Recover only a
complete exact prefix under a sealed `WaveSlotRecoveryAuthorization` bound to
wave/slot/request/original execution authorization/application approval,
pre/post heads, checkpoint and current prefix. A stopped,
expired or revoked Wave needs a new continuation policy, checkpoint, current
head and execution authorization; unchanged application approval remains valid
only when active/unexpired/unrevoked. The existing registrar Core commit receipt
is verified input evidence; this synthetic path writes only a sealed
`SyntheticWaveSlotRecoveryResult`. It never emits `WaveSlotReceipt` or
`WaveSlotRecoveryReceipt`. The positive three-slot effect manifest excludes the
recovery-only result; recovery tests use a separate scoped journal expecting one
synthetic recovery-result write and zero production receipt writes. Persist the
outcome only through `RegistrationWaveStore.put_recovery_result()`.

- [ ] **Step 4: Run recovery regressions**

Run: `python -m pytest -q tests/test_registration_wave_recovery.py tests/test_phase3_registrar_recovery.py tests/test_production_operations_recovery.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 9**

```text
git add src/sedb_ral/registration_wave_recovery.py tests/test_registration_wave_recovery.py
git commit -m "feat: recover synthetic Wave 1 results without blind replay"
```

---

### Task 10: Public RAL Readback Bundle for Later LIMEN B6A

**Files:**
- Create: `src/sedb_ral/registration_wave_readback.py`
- Test: `tests/test_registration_wave_readback.py`

**Interfaces:**
- Produces:
  `build_wave_readback_bundle(context, ledger_root, expected_head, plan, slot_results: tuple[VerifiedSyntheticWaveSlotResult, ...]) -> WaveReadbackBundle`.

- [ ] **Step 1: Write RAL-bundle and non-promotion REDs**

```python
def test_bundle_reports_synthetic_ral_state_without_claiming_live_b6a():
    result = build_wave_readback_bundle(context(), ledger(), h1(), plan(), verified_slot_results(1))
    assert result.admitted_slot_indexes == (1,)
    assert result.production_wave_run == "NOT_RUN"
    assert result.live_limen_b6a == "NOT_RUN"

def test_plain_self_sealed_result_is_not_readback_evidence():
    with pytest.raises(RALValidationError, match="verified_synthetic_result_required"):
        build_wave_readback_bundle(context(), ledger(), h1(), plan(), (plain_slot_result(),))

def test_ral_bundle_api_and_schema_have_no_limen_observation_input():
    assert tuple(inspect.signature(build_wave_readback_bundle).parameters) == (
        "context", "ledger_root", "expected_head", "plan", "slot_results"
    )
    value = valid_readback_bundle().to_dict()
    value["limen_observation"] = claim_time_observation().to_dict()
    with pytest.raises(RALValidationError, match="schema_invalid"):
        WaveReadbackBundle.from_dict(value)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_readback.py`

Expected: missing module.

- [ ] **Step 3: Implement sanitized digest-bound bundle**

Require verifier-issued `VerifiedSyntheticWaveSlotResult` values, call each
capability verifier, compare capability i to the actual ledger prefix through
slot i, and require only the final capability to bind `expected_head` and the
complete current prefix. Rebuild exact synthetic RAL view schema/raw/public
digests, ledger/authority/binding heads, source events and per-slot
application/resident/instance/address/binding projection digests from the
actual verified ledger; never copy plain caller fields. Set
`production_wave_run=NOT_RUN` and
`live_limen_b6a=NOT_RUN`. Do not accept a LIMEN observation or claim resolution/
enforcement success in this repo; the later LIMEN-owner plan supplies those
objects and tests W1-019/W1-020/W1-021/W1-022/W1-047/W1-048.

Restart and CLI paths obtain capabilities through
`RegistrationWaveStore.get_verified_slot_result()`. They never parse a plain
result mapping and promote it into Task 10. Projection digest, result ID, event
pair, plan, prefix or actual-ledger substitutions must turn red. The bundle
wire schema and Task 12 physical effect counts remain unchanged.

- [ ] **Step 4: Run RAL/LIMEN exporter regressions**

Run: `python -m pytest -q tests/test_registration_wave_readback.py tests/test_limen_public_view_contract.py tests/test_limen_public_view_export.py tests/test_limen_public_view_gate.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 10**

```text
git add src/sedb_ral/registration_wave_readback.py tests/test_registration_wave_readback.py
git commit -m "feat: export Wave 1 public readback evidence"
```

---

### Task 11: Typed CLI Surface

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
    context, journal, sentinel = synthetic_cli_fixture(tmp_path)
    before = sentinel.digest()
    result = run_cli("registration-wave", "build-plan", *inputs(tmp_path, context))
    assert result.exit_code == 0
    assert sentinel.digest() == before
    assert journal.production_reads == 0
    assert journal.production_writes == 0

def test_slot_admit_requires_explicit_synthetic_root_until_live_gate():
    result = run_cli("registration-wave", "slot-admit", *without_synthetic_root())
    assert result.exit_code == 2
    assert result.json["reason_codes"] == ["production_wave_execution_not_authorized"]
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_cli.py`

Expected: parser command missing.

- [ ] **Step 3: Implement canonical JSON CLI handlers**

Use strict UTF-8/duplicate-key parsing, canonical stdout, typed exit codes and
explicit output roots. Input/unreadable/malformed transport errors use exit 1;
readable substantive policy/authority/boundary refusals use exit 2. Construct
and verify `SyntheticWaveExecutionContext` in every mutating handler; direct
library calls retain the same guard. The code candidate hard-refuses exact production
execution unless a later operational plan replaces the candidate guard under
Neo.K authority.

`export-readback` loads verifier-issued slot capabilities through
`RegistrationWaveStore.get_verified_slot_result()` and passes only those
capabilities to Task 10. No CLI command accepts a plain self-sealed slot result
as readback evidence.

- [ ] **Step 4: Run CLI/package regressions**

Run: `python -m pytest -q tests/test_registration_wave_cli.py tests/test_phase3a_operations_cli.py tests/test_production_operations_cli.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 11**

```text
git add src/sedb_ral/registration_wave_cli.py src/sedb_ral/cli.py tests/test_registration_wave_cli.py
git commit -m "feat: expose typed Wave 1 CLI"
```

---

### Task 12: Deterministic Wave Acceptance Matrix

**Files:**
- Create: `src/sedb_ral/registration_wave_acceptance.py`
- Create: `scripts/validate_registration_wave.py`
- Create: `tests/test_registration_wave_acceptance.py`
- Create: `tests/fixtures/registration_wave/expected-positive-effects.json`

**Interfaces:**
- Produces `validate_registration_wave(root: Path) -> RegistrationWaveAcceptanceReport`
  covering exact W1-001 through W1-053.

- [ ] **Step 1: Write matrix completeness and mutation REDs**

```python
def test_acceptance_has_every_unique_case_and_executed_control(tmp_path):
    report = validate_registration_wave(tmp_path)
    assert tuple(case.case_id for case in report.cases) == tuple(f"W1-{i:03d}" for i in range(1, 54))
    owner_plan_cases = {
        "W1-019", "W1-020", "W1-021", "W1-022", "W1-047", "W1-048"
    }
    assert all(
        case.executed and case.passed
        for case in report.cases
        if case.case_id not in owner_plan_cases
    )
    assert {case.case_id: case.status for case in report.cases if not case.executed} == {
        "W1-019": "NOT_RUN_OWNER_PLAN_REQUIRED",
        "W1-020": "NOT_RUN_OWNER_PLAN_REQUIRED",
        "W1-021": "NOT_RUN_OWNER_PLAN_REQUIRED",
        "W1-022": "NOT_RUN_OWNER_PLAN_REQUIRED",
        "W1-047": "NOT_RUN_OWNER_PLAN_REQUIRED",
        "W1-048": "NOT_RUN_OWNER_PLAN_REQUIRED",
    }
    assert report.production_wave_run == "NOT_RUN"
    assert report.live_limen_b6a == "NOT_RUN"
    assert report.production_root_status == "NOT_READ"
    assert report.effects.allowed_refs() == expected_positive_effect_manifest()
    assert report.effects.forbidden_nonzero_dimensions() == ()
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest -q tests/test_registration_wave_acceptance.py`

Expected: missing report/module.

- [ ] **Step 3: Implement two-run deterministic synthetic acceptance**

Execute 47 RAL-owned negative/positive populations in disposable storage.
Retain W1-019/W1-020/W1-021/W1-022/W1-047/W1-048 as explicit LIMEN-owner
`NOT_RUN_OWNER_PLAN_REQUIRED` entries: a synthetic RAL bundle cannot prove slot
resolution, cross-task conflict, freshness or enforcement. Compare
canonical report/execution digests across two runs with supplied opaque fixture
IDs. Include active policy, three slots, crash/recovery, locator, authorship,
authority, RAL readback bundle and private/no-network controls. Use a scoped
`WaveEffectJournal` and injected capability adapters to attempt production/
private reads and writes, network, provider, Fabric, MCP and external CLI calls;
every injected attempt must increment a dimension and turn the gate red.

Readback positives use exact store-rebuilt
`VerifiedSyntheticWaveSlotResult` capabilities. Mutations to projection
digests, deterministic result IDs, appended event pairs, plan/prefix bindings or
actual ledger bytes must turn the Task 10 consumer red even when a plain wire
object is canonically re-sealed.

The independent expected-positive-effects fixture contains exact synthetic
refs/counts:

```text
fixture_reads                 9  (claim/item/host for slots 1-3)
staging_writes               28  (per slot: claim/item/host/candidate/approval/request/result;
                                  plus plan/policy/active-policy/activation-receipt and 3 readback bundles)
synthetic_ledger_writes      12  (4 staged events per slot)
synthetic_receipt_writes      4  (one exact policy activation receipt plus
                                  one sealed SyntheticWaveSlotExecutionResult per slot)
```

The journal records exact refs, not only integers; observed sorted refs must
equal the fixture manifest byte-for-byte. `synthetic_receipt_writes` is a typed
subset of the 28 staging writes. It includes the policy activation receipt in
the synthetic fixture and the three synthetic slot results; it never denotes a
production `WaveSlotReceipt` or `WaveSlotRecoveryReceipt` and is not added again when
computing physical write totals. Forbidden dimensions are production
read/write, private read/write, network, provider, Fabric, MCP and external CLI.
Every acceptance case receives its own scoped journal. The manifest above is
only the canonical three-slot positive path; crash/recovery controls compare
their separate expected journals and cannot inflate or hide this baseline.

- [ ] **Step 4: Run acceptance and generate temp report**

Run:

```powershell
python -m pytest -q tests/test_registration_wave_acceptance.py
$out = Join-Path $env:TEMP 'r3b-c-wave1-synthetic.json'
python scripts/validate_registration_wave.py --output $out
```

Expected: 47 executed pass; W1-019/W1-020/W1-021/W1-022/W1-047/W1-048 explicit
owner-plan NOT_RUN; zero fail/blocked; repeated digest match; every injected
effect control red; exact allowed synthetic dimensions match the fixture; and
all forbidden dimensions remain zero in the positive.

- [ ] **Step 5: Commit Task 12**

```text
git add src/sedb_ral/registration_wave_acceptance.py scripts/validate_registration_wave.py tests/test_registration_wave_acceptance.py tests/fixtures/registration_wave/expected-positive-effects.json
git commit -m "test: validate the three-seat registration wave"
```

---

### Task 13: Packaging, CI, Documentation and Final Candidate Gate

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
digests, staging paths or production authority. It states exactly:

```text
production_wave_run = NOT_RUN
live_limen_b6a = NOT_RUN
production_root_status = NOT_READ
pinned_p3_4_receipt = VERIFIED
r3b_b_regression = PASS
```

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

Expected: zero failures; every skip listed; pinned P3-4 receipt verification and
R3B-B synthetic regression pass; 47 RAL-owned W1 cases executed PASS;
W1-019/W1-020/W1-021/W1-022/W1-047/W1-048 explicit
`NOT_RUN_OWNER_PLAN_REQUIRED`; `production_root_status=NOT_READ`;
`production_wave_run=NOT_RUN`; journal production/private/network/provider/
Fabric/MCP/external-CLI effects zero; exact allowed synthetic effect refs/counts
match the independent fixture; worktree clean after commit.

- [ ] **Step 5: Build retained wheel and record exact hashes**

Use a new explicit temporary root. Record wheel bytes/SHA, installed module
source, schema bytes/SHA, dependency metadata, no-vendoring/runtime-boundary
scans and reproducibility status. Do not publish.

- [ ] **Step 6: Commit Task 13**

```text
git add pyproject.toml .github/workflows/phase3a.yml docs/runtime/R3B_C_THREE_SEAT_WAVE1.md tests/test_registration_wave_packaging.py
git commit -m "docs: record R3B-C Wave 1 candidate evidence"
```

- [ ] **Step 7: Stop for one Twin final review**

Review exact code head/tree, full tests, W1 acceptance, wheel, pinned production
receipt evidence, R3B-B synthetic regression, explicit
`production_root_status=NOT_READ` and
exact allowed synthetic effects with zero forbidden effects. Do not collect new host evidence, prepare
real applications, activate Wave policy or append production events.

## Spec coverage map

- Equal standing, public-only scope and no hierarchy: Global Constraints plus
  Tasks 1, 4, 10 and 12.
- Applicant claim/item/host binding, exact-three gate and continuity refusal:
  Tasks 1 and 3.
- Canonical locator grammar and collision separation: Tasks 1, 3 and 12.
- Non-bypassable synthetic/real-staging modes and measured effects: Task 2 and
  every guarded API in Tasks 3-12.
- Principal application approval and separate JIT execution authorization:
  Tasks 1 and 5.
- Append-only Wave policy/control/status and dormant preservation: Tasks 1 and
  6.
- Explicit mode-aware staging and no production/private/Git/path escape: Tasks
  2 and 7.
- Typed H0, Wave plan, slot order, predecessor receipts and one-slot execution:
  Tasks 1, 4 and 8.
- Durable receipt retry, outer-receipt recovery, partial prefix and continuation
  policy: Tasks 1 and 9.
- Synthetic RAL readback bundle without live-B6A promotion: Tasks 1 and 10;
  LIMEN consumption remains the later B6A plan.
- Typed CLI and core production hard-stop: Tasks 2 and 11.
- W1-001 through W1-053 with six explicit LIMEN-owner NOT_RUN cases
  (W1-019/W1-020/W1-021/W1-022/W1-047/W1-048), measured effects and zero real
  side effects: Task 12.
- Wheel/CI/runbook/final evidence and one Twin gate: Task 13.

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
