# SEDB-RAL Phase 3A Registration Core and CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. Multi-agent/subagent execution is not
> authorized for this run.

**Goal:** Implement a synthetic/local applicant-self registration Core and CLI
that prepares immutable applications, evaluates exact principal authority and
address collisions, stages a replayable candidate commit, and appends through
the existing SEDB-RAL file ledger without network, private Residence, or real
applicant data.

**Architecture:** New Phase 3 contracts and a focused `registration` module
wrap the existing v0.1 application/authority/event contracts rather than
creating a second registry model. A `registrar` module adds projection-aware
admission, isolated staging, expected-head commit, idempotent accepted-result
lookup, and partial-prefix detection. CLI commands call the same Core; real
ledger root, MCP, LIMEN B6, and real applications remain later gates.

**Tech Stack:** Python 3.11+, standard library only, existing SEDB-RAL strict
canonical JSON and append-only ledger, pytest, setuptools.

**Spec:** `docs/superpowers/specs/2026-08-25-phase3-self-registration-and-limen-b6-design.md`

## Global Constraints

- Phase 3A uses synthetic `resident:test-*`, `thread:test-*`, and pytest
  temporary roots only.
- Applicant content is a claim. Display label, role, model, title, provider,
  and memory have zero identity weight.
- Host observation and applicant claim remain separate objects with separate
  digests.
- Native session absence is retained as `null` plus an exact unavailable
  reason; no value is synthesized.
- Prepared applications use existing `application.schema.json` v0.1 and encode
  the prepared continuity-line ID as a claim; no silent schema mutation.
- Every prepared ID is opaque and supplied through `RegistrationIds`; tests
  never depend on random UUID output.
- Application evaluation performs zero writes.
- Registrar staging and canonical commit require exact expected ledger head.
- Validation/refusal before canonical commit writes nothing. A process crash
  that leaves a valid event prefix is detected as
  `registrar_partial_transaction`; it is not guessed complete.
- CLI and direct Core outputs are canonical-byte equivalent.
- No MCP, HTTP, socket, subprocess execution capability, Bridge, Board, Wake,
  private Residence access, public discovery, release, publication, or
  deployment is added.
- No real names, native task IDs, applicant replies, authority artifacts,
  credentials, private paths, or production ledger roots enter source,
  fixtures, docs, logs, or evidence.
- Existing Basic Phase 2 behavior remains compatible at package version 0.2.1
  until the final Phase 3A packaging task promotes the candidate to 0.3.0.

---

### Task 1: Applicant, host-observation, and prepared-registration contracts

**Files:**
- Create: `src/sedb_ral/schemas/self-application-claim.schema.json`
- Create: `src/sedb_ral/schemas/registration-host-observation.schema.json`
- Create: `src/sedb_ral/schemas/prepared-registration.schema.json`
- Create: `src/sedb_ral/registration.py`
- Create: `tests/test_phase3_registration_prepare.py`
- Create: `tests/test_phase3_schema_assets.py`

**Interfaces:**
- Produces: immutable `RegistrationIds` dataclass.
- Produces: immutable `PreparedRegistration` dataclass with `to_dict()` and
  `digest`.
- Produces: `prepare_registration(claim, host_observation, ids) -> PreparedRegistration`.
- Reuses: existing application, instance, address, and claim v0.1 contracts.

- [ ] **Step 1: Write failing contract and preparation tests**

```python
from sedb_ral.registration import RegistrationIds, prepare_registration


IDS = RegistrationIds(
    prepared_id="prepared:test-alpha",
    application_id="application:test-alpha",
    resident_id="resident:test-alpha",
    instance_id="instance:test-alpha-001",
    continuity_line_id="line:test-alpha",
    address_ids=("address:test-alpha-thread",),
    claim_ids=(
        "claim:test-alpha-display",
        "claim:test-alpha-role",
        "claim:test-alpha-line",
    ),
)


def test_P3_001_opted_in_claim_and_exact_host_thread_prepare_application():
    prepared = prepare_registration(valid_claim(), valid_host_observation(), IDS)
    assert prepared.application["claimed_resident_id"] == "resident:test-alpha"
    assert prepared.application["instance_claims"][0]["instance_id"] == (
        "instance:test-alpha-001"
    )
    assert prepared.application["addresses"][0]["locator"] == "thread:test-alpha"
    assert prepared.host_observation["native_session_id"] is None
    assert prepared.host_observation["unavailable_fields"] == [
        {
            "field": "native_session_id",
            "reason": "structurally_unavailable_from_codex_app_task_tool",
        }
    ]
    assert prepared.application["claims"][2]["object"] == "line:test-alpha"


def test_P3_002_opt_out_refuses_before_ids_are_used():
    with pytest.raises(RALValidationError, match="applicant_opt_out"):
        prepare_registration(valid_claim(opt_in=False), valid_host_observation(), IDS)


def test_P3_003_claimed_address_must_equal_host_observed_thread():
    with pytest.raises(RALValidationError, match="applicant_address_host_mismatch"):
        prepare_registration(
            valid_claim(address="thread:other"), valid_host_observation(), IDS
        )
```

Additional tests cover wrong schema, `applicant_claim_only=false`, missing
canonical applicant item, foreign/non-host origin, duplicate IDs, wrong claim
ID count, non-opaque IDs containing the display label, and unexpected
available session data under the task-tool profile.

The production mutations caught are adopting a model-supplied native ID,
dropping the unavailable reason, deriving IDs from names, or preparing an
opted-out applicant.

- [ ] **Step 2: Run RED**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_phase3_registration_prepare.py tests/test_phase3_schema_assets.py -q
```

Expected: collection fails because `sedb_ral.registration` and the three
schemas do not exist.

- [ ] **Step 3: Implement strict schemas**

`self-application-claim.schema.json` requires exactly:

```text
schema
applicant_claim_only
desired_display_label
existing_resident_claim
continuity_claim
desired_addresses
role_description_claim
dissent_or_limits
opt_in
relay_is_authorship
not_claimed
```

`continuity_claim` is `new | continue | uncertain`. Initial desired addresses
use exact `{namespace, identifier_kind, locator}` objects.

`registration-host-observation.schema.json` requires exact provider, adapter,
identifier, thread/session/turn, unavailable fields, host origin/time, and
applicant item ref. Only the `codex_app_task_tool` profile may have null
`native_session_id`, and it requires the declared reason.

`prepared-registration.schema.json` wraps canonical copies plus
`application_digest`, `preparation_digest`, and `not_claimed`.

- [ ] **Step 4: Implement minimal preparation**

`RegistrationIds`:

```python
@dataclass(frozen=True)
class RegistrationIds:
    prepared_id: str
    application_id: str
    resident_id: str
    instance_id: str
    continuity_line_id: str
    address_ids: tuple[str, ...]
    claim_ids: tuple[str, str, str]
```

`prepare_registration` validates both inputs, exact address/thread equality,
all ID uniqueness/opacity, and creates an application v0.1 with three claims:

```text
display_label
role_description
continuity_line_id
```

The instance `runtime_tag` is metadata `runtime:codex-app`; it is never used as
an address or identifier. `submitted_time_ref` and `started_time_ref` use the
host observation time ref.

- [ ] **Step 5: Run GREEN**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_phase3_registration_prepare.py tests/test_phase3_schema_assets.py -q
```

Expected: all selected tests pass with no warnings.

- [ ] **Step 6: Commit**

```powershell
git add src/sedb_ral/schemas src/sedb_ral/registration.py tests/test_phase3_registration_prepare.py tests/test_phase3_schema_assets.py
git commit -m "feat: prepare bounded self-registration applications"
```

### Task 2: Projection-aware admission and collision gates

**Files:**
- Create: `src/sedb_ral/registration_admission.py`
- Create: `tests/test_phase3_registration_admission.py`
- Modify: `src/sedb_ral/projection.py`

**Interfaces:**
- Consumes: `PreparedRegistration`, existing `evaluate_application`, and
  `RegistryProjection`.
- Produces: immutable `RegistrationDecision` with `to_dict()` and `digest`.
- Produces: `evaluate_prepared_registration(prepared, authorities,
  verified_attestation_refs, projection) -> RegistrationDecision`.
- Produces: `continuity_line_for(resident_id, projection) -> str | None`.

- [ ] **Step 1: Write failing admission tests**

```python
def test_P3_009_exact_digest_authority_and_empty_projection_accept():
    prepared = prepared_registration()
    decision = evaluate_prepared_registration(
        prepared,
        [authority_for(prepared.application_digest)],
        verified_attestation_refs={"attestation:test-principal"},
        projection=empty_projection(),
    )
    assert decision.decision == "accept"
    assert decision.reason_codes == ("authority_sufficient",)


def test_P3_010_missing_authority_defers_without_write(tmp_path):
    decision = evaluate_prepared_registration(
        prepared_registration(), [], frozenset(), empty_projection()
    )
    assert decision.reason_codes == ("authority_missing",)
    assert not list(tmp_path.rglob("*.json"))


def test_P3_012_active_thread_address_collision_rejects():
    decision = evaluate_prepared_registration(
        prepared_registration(),
        [valid_authority()],
        {"attestation:test-principal"},
        projection_with_address(
            locator="thread:test-alpha", resident_id="resident:test-other"
        ),
    )
    assert decision.reason_codes == ("address_binding_conflict",)


def test_P3_013_homonymous_display_label_is_not_a_collision():
    decision = evaluate_prepared_registration(
        prepared_registration(label="Same Label"),
        [valid_authority()],
        {"attestation:test-principal"},
        projection_with_resident(label="Same Label"),
    )
    assert decision.decision == "accept"
```

Additional tests cover unverified principal attestation, applicant/host digest
mutation, continue/uncertain claims without an existing canonical resident,
active same-resident duplicate address, suspended/revoked addresses,
continuity-line claim ambiguity, and claim/instance/address cross-reference
failure.

The production mutations caught are name-based collision, address stealing,
self-granted authority, or accepting `continue` without lineage evidence.

- [ ] **Step 2: Run RED**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_phase3_registration_admission.py -q
```

Expected: import fails because `registration_admission` does not exist.

- [ ] **Step 3: Implement the immutable decision**

`RegistrationDecision` contains:

```text
decision: accept | defer | reject
reason_codes
prepared_digest
application_digest
authority_ref
resident_id
address_refs
mutated: false
not_claimed: canonical_commit, private_access, identity_merge
digest
```

First validate `PreparedRegistration.digest`, then delegate application
authority evaluation to the existing Core. Projection checks occur before an
accepted decision is returned.

- [ ] **Step 4: Add continuity-line projection helper**

`continuity_line_for` selects exactly one registered claim with predicate
`continuity_line_id`, matching claimant/subject resident and an instance owned
by that resident. Zero returns `None`; more than one distinct line raises
`continuity_line_ambiguous`.

- [ ] **Step 5: Run GREEN and existing application/projection regression**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_phase3_registration_admission.py tests/test_application_decision.py tests/test_projection.py tests/test_sqlite_projection.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add src/sedb_ral/registration_admission.py src/sedb_ral/projection.py tests/test_phase3_registration_admission.py
git commit -m "feat: gate registration authority and address collisions"
```

### Task 3: Isolated staging and registrar admission plan

**Files:**
- Create: `src/sedb_ral/registrar.py`
- Create: `tests/test_phase3_registrar_plan.py`

**Interfaces:**
- Consumes: accepted `RegistrationDecision`, prepared application, authority,
  CTCL receipt, verified attestation refs, and expected head.
- Produces: immutable `RegistrarAdmissionPlan` with canonical input digests,
  candidate event IDs/head, projection digest, and source expected head.
- Produces: `build_admission_plan(...) -> RegistrarAdmissionPlan`.
- Produces: `commit_admission_plan(...) -> RegistrarCommitReceipt`.

- [ ] **Step 1: Write failing staging tests**

```python
def test_P3_016_staging_builds_candidate_without_canonical_write(tmp_path):
    canonical = tmp_path / "canonical"
    plan = build_admission_plan(
        canonical,
        prepared_registration(),
        accepted_decision(),
        valid_authority(),
        valid_ctcl(),
        expected_head=None,
        verified_attestation_refs={"attestation:test-principal"},
        staging_parent=tmp_path / "staging",
    )
    assert plan.candidate_event_ids[-1].startswith("evt_resident_registered_")
    assert plan.candidate_head.startswith("sha256:sedb-ral-chain-v1:")
    assert not canonical.exists()


def test_P3_017_wrong_expected_head_refuses_before_staging(tmp_path):
    with pytest.raises(RALValidationError, match="external_anchor_mismatch"):
        build_admission_plan(
            existing_ledger(tmp_path),
            prepared_registration(),
            accepted_decision(),
            valid_authority(),
            valid_ctcl(),
            expected_head="sha256:sedb-ral-chain-v1:" + "0" * 64,
            verified_attestation_refs={"attestation:test-principal"},
            staging_parent=tmp_path / "staging",
        )
```

Additional tests mutate application, authority, decision, CTCL receipt, staging
projection, and candidate event order. Each mutation must fail before the
canonical root changes.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_phase3_registrar_plan.py -q`

Expected: import fails because `sedb_ral.registrar` does not exist.

- [ ] **Step 3: Implement isolated staging**

`build_admission_plan`:

1. verifies the canonical ledger at `expected_head` or confirms an absent new
   root for `expected_head=None`;
2. copies only verified canonical event files into a new temporary directory;
3. runs existing `commit_application` against the temporary ledger;
4. rebuilds `RegistryProjection` and SQLite there;
5. verifies zero unapplied events and exact resident/address/line content;
6. emits plan digests and removes the temporary tree after capturing the plan.

The plan stores no private path or applicant display text in diagnostics.

- [ ] **Step 4: Implement expected-head canonical commit**

`commit_admission_plan` revalidates every plan/input digest and current head,
then calls `commit_application` on the canonical root. It verifies returned
event IDs/head and rebuilt projection against the plan before returning:

```python
@dataclass(frozen=True)
class RegistrarCommitReceipt:
    application_digest: str
    prepared_digest: str
    source_head: str | None
    final_head: str
    event_ids: tuple[str, ...]
    projection_digest: str
    committed: bool
    idempotent: bool
```

- [ ] **Step 5: Run GREEN**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_phase3_registrar_plan.py tests/test_application_commit.py tests/test_ledger.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add src/sedb_ral/registrar.py tests/test_phase3_registrar_plan.py
git commit -m "feat: stage and commit registrar admissions"
```

### Task 4: Idempotency, partial-prefix detection, and recovery boundary

**Files:**
- Modify: `src/sedb_ral/registrar.py`
- Create: `tests/test_phase3_registrar_recovery.py`

**Interfaces:**
- Produces: `find_committed_registration(events, application_digest) -> RegistrarCommitReceipt | None`.
- Produces: `inspect_registration_prefix(events, application_digest) -> complete | absent | partial | conflicting`.
- Extends: `commit_admission_plan` with idempotent accepted-result return.

- [ ] **Step 1: Write failing recovery tests**

```python
def test_P3_020_identical_retry_returns_existing_receipt(tmp_path):
    first = admitted_registration(tmp_path)
    second = commit_admission_plan(
        tmp_path,
        same_plan(first.source_head),
        prepared_registration(),
        accepted_decision(),
        valid_authority(),
        valid_ctcl(),
        verified_attestation_refs={"attestation:test-principal"},
    )
    assert second.final_head == first.final_head
    assert second.committed is False
    assert second.idempotent is True


def test_P3_021_valid_partial_prefix_is_detected_not_resumed_implicitly(tmp_path):
    inject_valid_application_submitted_prefix(tmp_path)
    with pytest.raises(RALValidationError, match="registrar_partial_transaction"):
        commit_admission_plan(...)
```

Additional tests cover same application ID/different digest, same address ID
with different locator, accepted application missing registered resident,
registered resident with mismatched authority grant, and prefix after authority
revocation.

The production mutation caught is duplicating residents after an uncertain
process outcome.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_phase3_registrar_recovery.py -q`

Expected: recovery helpers are absent or retries conflict.

- [ ] **Step 3: Implement deterministic prefix inspection**

The expected logical sequence is:

```text
optional matching authority.granted
application.submitted
application.accepted
resident.registered
```

Only a complete, projection-valid sequence returns idempotent success. Partial
or conflicting evidence raises a typed code and requires checkpoint restore or
an explicit future recovery procedure; Phase 3A never guesses/resumes it.

- [ ] **Step 4: Run GREEN and mutation checks**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_phase3_registrar_recovery.py tests/test_phase3_registrar_plan.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/registrar.py tests/test_phase3_registrar_recovery.py
git commit -m "fix: make registrar retries and partial outcomes explicit"
```

### Task 5: Phase 3A CLI and Core parity

**Files:**
- Modify: `src/sedb_ral/cli.py`
- Create: `tests/test_phase3_cli.py`
- Modify: `pyproject.toml`
- Modify: `src/sedb_ral/__init__.py`

**Interfaces:**
- Adds: `application prepare`, `application digest`, `application explain`.
- Adds: `registrar plan`, `registrar admit`, `registrar status`.
- Reuses: `application check` and all new Core functions.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_P3_022_prepare_cli_matches_direct_core_bytes(tmp_path, capsys):
    code = main(
        [
            "application",
            "prepare",
            str(CLAIM),
            str(HOST_OBSERVATION),
            "--ids",
            str(IDS),
        ]
    )
    assert code == 0
    assert canonical_bytes(json.loads(capsys.readouterr().out)) == canonical_bytes(
        prepare_registration(CLAIM_VALUE, OBS_VALUE, IDS_VALUE).to_dict()
    )


def test_registrar_admit_requires_expected_head_and_exact_files(capsys):
    assert main(["registrar", "admit"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason_codes"] == ["cli_usage_error"]
```

Additional tests cover `--output` refusal on existing target, generated UUID
IDs with no display-name substring, malformed JSON, missing authority,
unverified attestation, wrong head, human view non-canonical marker, and zero
path/stack leakage.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_phase3_cli.py -q`

Expected: new subcommands are absent.

- [ ] **Step 3: Implement commands using shared Core**

`application prepare` accepts an optional deterministic IDs JSON for tests;
without it, UUID4 IDs are generated once and emitted. It never overwrites an
output path.

`registrar plan` emits a plan only. `registrar admit` requires prepared,
decision, authority, CTCL, attestation refs, configured ledger root, and exact
expected head. Empty-ledger initialization uses the explicit string `GENESIS`,
which the CLI converts to `None`; omission is a usage error.

- [ ] **Step 4: Promote package version to 0.3.0 candidate**

Update both `pyproject.toml` and `src/sedb_ral/__init__.py` to `0.3.0` only
after CLI/Core parity tests pass. Update version tests without changing Basic
Phase 2 profile identifiers.

- [ ] **Step 5: Run GREEN and CLI/package regression**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_phase3_cli.py tests/test_cli_smoke.py tests/test_packaging.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add src/sedb_ral/cli.py src/sedb_ral/__init__.py pyproject.toml tests/test_phase3_cli.py tests/test_cli_smoke.py
git commit -m "feat: expose Phase 3A registration CLI"
```

### Task 6: Acceptance runner, evidence, docs, and CI

**Files:**
- Create: `scripts/validate_phase3a.py`
- Create: `tests/test_phase3a_gate.py`
- Create: `.github/workflows/phase3a.yml`
- Create: `docs/runtime/PHASE3A_REGISTRAR_CORE.md`
- Create: `evidence/phase3a/2026-08-25-local.json`
- Modify: `README.md`

**Interfaces:**
- Produces: deterministic `sedb-ral.phase3a-acceptance/0.1` evidence.
- Produces: CI Windows/Ubuntu Python 3.11 Phase 3A synthetic jobs.

- [ ] **Step 1: Define exact acceptance inventory**

`validate_phase3a.py` runs twice and requires:

```python
EXPECTED_CASE_IDS = tuple(f"P3-{index:03d}" for index in range(1, 25))
EXPECTED_CONTROLS = (
    "applicant-opt-out",
    "applicant-host-address-mismatch",
    "host-origin-unverified",
    "opaque-id-name-leak",
    "authority-missing",
    "authority-authorship-unverified",
    "address-binding-conflict",
    "prepared-digest-mutation",
    "expected-head-mismatch",
    "staging-projection-mutation",
    "partial-transaction",
    "package-no-send",
)
```

- [ ] **Step 2: Write the integrated gate test RED**

```python
def test_phase3a_gate_reports_exact_inventory(tmp_path):
    report = validate_phase3a(ROOT, output_root=tmp_path)
    assert report.passed is True
    assert report.case_ids == EXPECTED_CASE_IDS
    assert report.network_calls == 0
    assert report.private_reads == 0
    assert report.real_applicant_count == 0
```

Expected RED: `validate_phase3a` does not exist.

- [ ] **Step 3: Implement the acceptance runner**

The report records implementation commit/candidate digest, source invocation,
schema/fixture digests, test IDs, controls, staging/canonical head digests,
repeated-run digest, package scan, and explicit `not_claimed` fields.

The source scan fails on real Codex UUIDs, `D:\AI_RESIDENCE`, private root
content, credential patterns, HTTP/socket/subprocess send capability, or a
production ledger directory.

- [ ] **Step 4: Add CI and runtime documentation**

CI installs from source with `PYTHONPATH=src`, runs the Phase 3A marker/runner
on Windows and Ubuntu Python 3.11, uploads evidence, and uses `contents: read`.
It does not require the external SEDB v0.4B archive because Phase 3A has its own
synthetic gate; existing Phase 2 CI remains unchanged.

- [ ] **Step 5: Run the full local completion gate**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q `
  --ignore=tests/test_phase2_gate.py `
  --ignore=tests/test_sedb_adoption.py `
  --ignore=tests/test_sedb_v04b_integration.py
python scripts/validate_phase2.py --sedb-archive "D:\Ai\work together\SEDB\releases\SEDB-v0.4B-local.zip"
python scripts/validate_phase3a.py --output "<new-temp-path>"
git diff --check
git status --short --branch
```

Expected: all source/Core tests pass except the preserved platform symlink skip;
Phase 2 reports `passed: true`; Phase 3A reports 24 PASS, zero blocked/fail,
zero real applicants/network/private reads.

- [ ] **Step 6: Commit and push synthetic Phase 3A**

```powershell
git add .github README.md docs evidence pyproject.toml scripts src tests
git commit -m "feat: complete SEDB-RAL Phase 3A registrar core"
git push origin main
```

Do not create a production registry root, prepare real applications, request
principal digest approval, append real ledger events, implement Registrar MCP,
modify LIMEN, access AI Residence, create a release, or deploy in this plan.

## Plan self-review

- **Spec coverage:** Tasks 1–6 cover synthetic claim/host contracts,
  application preparation, exact authority, collision gates, staging,
  expected-head commit, partial detection, idempotency, CLI, package, CI, and
  evidence. Registrar MCP, LIMEN B6A/B6B, production root, and real applicants
  are intentionally separate follow-up plans.
- **Placeholder scan:** Every step names concrete files, commands, contracts,
  expected failures, and neighboring interfaces.
- **Type consistency:** `RegistrationIds`, `PreparedRegistration`,
  `RegistrationDecision`, `RegistrarAdmissionPlan`, and
  `RegistrarCommitReceipt` names and fields are consistent across tasks.
- **Canonicality:** Existing application/ledger contracts remain canonical;
  staging, CLI views, SQLite, and evidence reports are derived or candidate
  state.
- **Authority:** Connection, applicant claim, familiar name, and prepared
  digest never self-grant registrar scope.
