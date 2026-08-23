# SEDB-RAL Basic Phase 2 SEDB Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt one immutable SEDB v0.4B package, map the Basic Phase 1B registry projection into SEDB entities/fields/cells, and prove compatibility through field-level differential tests and an auditable receipt.

**Architecture:** The RAL adapter is profile-driven and pure until an integration test injects services from a safely extracted SEDB package. RAL never vendors or mutates the live `D:\Ai\work together\SEDB` checkout; archive verification, mapping, SEDB application, differential classification, and compatibility receipts remain separate stages.

**Tech Stack:** Python 3.11+, standard library (`zipfile`, `hashlib`, `tomllib`, `sqlite3`, `importlib`), SEDB v0.4B (`sedb-local==0.4.0b1`) extracted from an immutable local ZIP, `pytest` 8.x.

**Spec:** `docs/superpowers/specs/2026-08-23-sedb-ral-core-design.md`

## Global Constraints

- Work locally on `feat/basic-phase2`; do not push GitHub until this plan and final review are complete.
- Target archive: `C:\Users\kakon\Downloads\SEDB\SEDB-v0.4B-local.zip`.
- Target archive SHA-256: `159F0928415811A434E885D50E94846266474725723D25DAC426170874B844D8`.
- Target size: `8980052` bytes.
- Target package: `sedb-local==0.4.0b1`.
- Target source commit: `139b9952bb283b2e95f7690d76e3c5fbcdc680aa`.
- Internal `MANIFEST.sha256` has 114 entries and must verify before extraction is adopted.
- Extraction is to a newly created temporary directory only; never read executable source from the live SEDB checkout.
- Missing fields remain absent/null according to mapping; they never become false.
- Decision != Commit; Capability != Authority; Consensus != Authority.
- No autonomous SEDB canonical commit, authority-envelope installation, registrar, federation, or network send.
- Differential classes are exactly `expected_by_mapping`, `unmapped`, and `contradiction`; only contradiction fails the compatibility gate.
- Every gate has an executed positive control and an executed corrupted-input result.

---

### Task 1: Pin the SEDB adoption and mapping contracts

**Files:**

- Create: `src/sedb_ral/schemas/sedb-adoption.schema.json`
- Create: `src/sedb_ral/schemas/sedb-compatibility-receipt.schema.json`
- Create: `profiles/sedb-v0.4b-adoption.json`
- Create: `profiles/sedb-v0.4b-mapping.json`
- Create: `fixtures/sedb/wrong-archive-hash.json`
- Create: `fixtures/sedb/wrong-source-commit.json`
- Create: `tests/test_sedb_profiles.py`

**Interfaces:**

- Produces two JSON contracts and two immutable profiles consumed by every later task.

- [ ] **Step 1: Write failing profile tests**

```python
def test_adoption_profile_pins_exact_package():
    profile = load("profiles/sedb-v0.4b-adoption.json")
    assert profile["archive_sha256"] == "159F0928415811A434E885D50E94846266474725723D25DAC426170874B844D8"
    assert profile["package_version"] == "0.4.0b1"
    assert profile["source_commit"] == "139b9952bb283b2e95f7690d76e3c5fbcdc680aa"


def test_mapping_has_one_rule_per_projected_value():
    mapping = load("profiles/sedb-v0.4b-mapping.json")
    assert {rule["classification"] for rule in mapping["rules"]} == {
        "mapped", "intentionally_unmapped"
    }
```

- [ ] **Step 2: Run and confirm missing-profile RED**

Run: `python -m pytest tests/test_sedb_profiles.py -q`

- [ ] **Step 3: Define adoption fields**

```text
profile_id, profile_version, archive_filename, archive_size, archive_sha256,
package_name, package_version, source_commit, manifest_path,
manifest_entry_count, validation_claim_source, adoption_status
```

`adoption_status` is `candidate|adopted|rejected`; the checked-in profile starts `candidate` and only the compatibility receipt records adoption.

- [ ] **Step 4: Define mapping rules**

Each rule declares `rule_id`, `ral_path`, `sedb_target`, `value_transform`, `null_policy`, `classification`, and `reason`. Initial SEDB field namespace is `sedb_ral` with keys:

```text
ral.resident_id
ral.application_id
ral.application_status
ral.instance_refs
ral.addresses
ral.claims
ral.attestations
ral.ledger_head
```

- [ ] **Step 5: Run profile tests and corrupted hash/source fixtures**

- [ ] **Step 6: Commit**

```powershell
git add src/sedb_ral/schemas/sedb-*.schema.json profiles fixtures/sedb tests/test_sedb_profiles.py
git commit -m "feat: pin the SEDB v0.4B compatibility profile"
```

---

### Task 2: Verify and safely extract the immutable SEDB archive

**Files:**

- Create: `src/sedb_ral/sedb_adoption.py`
- Create: `tests/test_sedb_adoption.py`

**Interfaces:**

- Produces `inspect_sedb_archive(archive, profile) -> SEDBAdoptionInspection` and
  `extract_verified_sedb(archive, profile, target) -> Path`.

- [ ] **Step 1: Write archive, traversal, manifest, and wrong-hash tests**

```python
def test_exact_archive_is_adoption_candidate():
    result = inspect_sedb_archive(ARCHIVE, PROFILE)
    assert result.compatible is True
    assert result.manifest_verified is True


def test_wrong_hash_fails_before_extraction(tmp_path):
    result = inspect_sedb_archive(ARCHIVE, WRONG_HASH)
    assert result.error_codes == ("archive_hash_mismatch",)
    assert not list(tmp_path.iterdir())
```

Build a synthetic ZIP containing `../escape.py`; it must return `archive_path_unsafe` and create no outside path.

- [ ] **Step 2: Run missing-module RED**

- [ ] **Step 3: Implement inspection without extraction**

```python
@dataclass(frozen=True)
class SEDBAdoptionInspection:
    compatible: bool
    archive_sha256: str
    package_version: str | None
    source_commit: str | None
    manifest_entry_count: int
    manifest_verified: bool
    error_codes: tuple[str, ...]
```

Read `pyproject.toml` with `tomllib`, `SOURCE_COMMIT.txt`, and `MANIFEST.sha256` directly from ZIP members. Reject absolute paths, drive prefixes, `..`, duplicate member names, and symlink entries before extraction.

- [ ] **Step 4: Implement verified temp extraction**

Create the target only after inspection is compatible. Extract each member by opening and copying bytes after containment checks; do not call `ZipFile.extractall()`.

- [ ] **Step 5: Prove one-byte archive and internal-manifest mutations turn red**

- [ ] **Step 6: Commit**

```powershell
git add src/sedb_ral/sedb_adoption.py tests/test_sedb_adoption.py
git commit -m "feat: verify immutable SEDB adoption archives"
```

---

### Task 3: Produce a pure SEDB exchange projection

**Files:**

- Create: `src/sedb_ral/sedb_mapping.py`
- Create: `tests/test_sedb_mapping.py`
- Create: `fixtures/sedb/expected-resident.jsonl`

**Interfaces:**

- Consumes: `RegistryProjection` and mapping profile.
- Produces `project_to_sedb_records(projection, mapping) -> tuple[dict[str, object], ...]`.

- [ ] **Step 1: Write exact JSONL-record tests**

```python
def test_resident_projection_matches_expected_record():
    records = project_to_sedb_records(PROJECTION, MAPPING)
    assert canonical_bytes(records[0]) == EXPECTED.read_bytes().rstrip(b"\n")


def test_missing_address_remains_absent_not_false():
    record = project_to_sedb_records(ZERO_ADDRESS, MAPPING)[0]
    assert "ral.addresses" not in record["values"]
```

- [ ] **Step 2: Run missing-mapper RED**

- [ ] **Step 3: Implement deterministic records**

Use SEDB exchange shape `id`, `kind`, `label`, `values`. Set `kind="ai_resident"`; use canonical resident ID as entity ID; apply only declared rules and sort records by ID.

- [ ] **Step 4: Add unknown rule, null-policy, and order corruptions**

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/sedb_mapping.py tests/test_sedb_mapping.py fixtures/sedb/expected-resident.jsonl
git commit -m "feat: project RAL residents into SEDB exchange records"
```

---

### Task 4: Apply exchange records to an injected SEDB service boundary

**Files:**

- Create: `src/sedb_ral/sedb_apply.py`
- Create: `tests/test_sedb_apply.py`

**Interfaces:**

- Produces `apply_sedb_records(records, fields, entities) -> SEDBApplyResult` without importing `sedb` inside package code.

- [ ] **Step 1: Write fake-service unit tests**

```python
def test_apply_creates_declared_fields_then_entities():
    result = apply_sedb_records(RECORDS, FakeFields(), FakeEntities())
    assert result.field_count == 8
    assert result.entity_count == 1
```

Reject pre-existing fields whose namespace/type conflicts with the profile. Existing compatible fields are reused.

- [ ] **Step 2: Run missing-module RED**

- [ ] **Step 3: Define structural protocols and apply result**

```python
class FieldServiceLike(Protocol):
    def get_field(self, field_id_or_key: str) -> dict[str, object]:
        raise NotImplementedError

    def create_field(self, **kwargs: object) -> dict[str, object]:
        raise NotImplementedError


@dataclass(frozen=True)
class SEDBApplyResult:
    field_count: int
    entity_count: int
    cell_count: int
    reused_field_count: int
```

- [ ] **Step 4: Run conflict and missing/null tests**

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/sedb_apply.py tests/test_sedb_apply.py
git commit -m "feat: apply SEDB projections through injected services"
```

---

### Task 5: Run the real extracted SEDB v0.4B integration in temp storage

**Files:**

- Create: `scripts/validate_sedb_v04b.py`
- Create: `tests/test_sedb_v04b_integration.py`

**Interfaces:**

- Consumes: verified extracted root and one RAL projection fixture.
- Produces `run_integration(archive, adoption_profile, projection, mapping, output) -> SEDBIntegrationResult`, a temp `sedb.sqlite`, exported JSONL, and a structured own-execution result; no files are committed.

- [ ] **Step 1: Write integration tests guarded by exact archive availability**

```python
def test_real_sedb_v04b_round_trip(tmp_path):
    expected_records = project_to_sedb_records(PROJECTION, MAPPING)
    result = run_integration(ARCHIVE, PROFILE, PROJECTION, tmp_path)
    assert result.database_integrity == "ok"
    assert result.exported_record_count == len(expected_records)
    assert result.exported_records == expected_records
```

`expected_records` is derived exclusively from the RAL projection fixture and
the checked-in mapping profile before SEDB is invoked. It must never be read
from, counted from, or regenerated from the SEDB export under test.

If the exact archive is absent, skip with `archive_unavailable`; a wrong archive present is a failure, not a skip.

- [ ] **Step 2: Run missing-runner RED**

- [ ] **Step 3: Implement isolated import and service use**

The script creates `Path(tempfile.mkdtemp(prefix="sedb-ral-v04b-"))`, extracts `SEDB-v0.4B-local` beneath it, adds only that extracted `src` directory to its process-local `sys.path`, imports `Database`, `FieldService`, `EntityService`, and `ExchangeService`, creates `sedb.sqlite`, applies records, runs `PRAGMA integrity_check`, and exports JSONL.

- [ ] **Step 4: Run the inherited SEDB v0.4B test suite**

Execute `python -m pytest -q` with cwd at the extracted package root and record exact pass/fail/skip counts. Until this is run, release-note validation remains `package_claim`; after a green run it becomes `own_execution` for this environment only.

- [ ] **Step 5: Commit**

```powershell
git add scripts/validate_sedb_v04b.py tests/test_sedb_v04b_integration.py
git commit -m "test: exercise the real SEDB v0.4B package"
```

---

### Task 6: Implement field-level differential classification

**Files:**

- Create: `src/sedb_ral/sedb_diff.py`
- Create: `tests/test_sedb_diff.py`

**Interfaces:**

- Produces `compare_sedb_projection(expected, actual, mapping) -> SEDBDiffReport`.

- [ ] **Step 1: Write the three-class tests**

```python
def test_declared_transform_is_expected_difference():
    report = compare_sedb_projection(EXPECTED, TRANSFORMED, MAPPING)
    assert report.counts == {"expected_by_mapping": 1, "unmapped": 0, "contradiction": 0}


def test_unmapped_extra_does_not_fail_but_is_visible():
    assert compare_sedb_projection(EXPECTED, EXTRA, MAPPING).passed is True


def test_mapped_value_change_is_contradiction():
    report = compare_sedb_projection(EXPECTED, WRONG, MAPPING)
    assert report.passed is False
    assert report.counts["contradiction"] == 1
```

- [ ] **Step 2: Run missing-comparator RED**

- [ ] **Step 3: Implement exact-path comparison**

```python
@dataclass(frozen=True)
class SEDBDifference:
    path: str
    classification: str
    expected: object
    actual: object
    rule_id: str | None
```

Do not use fuzzy or semantic-language-model comparison. Paths and transforms come only from the profile.

- [ ] **Step 4: Add null-vs-false and ordering mutations**

- [ ] **Step 5: Commit**

```powershell
git add src/sedb_ral/sedb_diff.py tests/test_sedb_diff.py
git commit -m "feat: classify SEDB projection differences"
```

---

### Task 7: Create the compatibility receipt and Basic Phase 2 gate

**Files:**

- Create: `src/sedb_ral/phase2.py`
- Modify: `src/sedb_ral/cli.py`
- Create: `scripts/validate_phase2.py`
- Create: `tests/test_phase2_gate.py`
- Create: `VALIDATION_BASIC_PHASE2.json`

**Interfaces:**

- Produces `validate_basic_phase2(root, archive) -> Phase2Report` and CLI `phase2 verify ROOT --sedb-archive PATH`.

- [ ] **Step 1: Write integrated positive and wrong-hash tests**

```python
def test_basic_phase2_gate_passes_exact_archive():
    report = validate_basic_phase2(ROOT, ARCHIVE)
    assert report.passed is True
    assert report.diff_counts["contradiction"] == 0


def test_wrong_hash_fixture_proves_adoption_gate_red():
    report = validate_basic_phase2(ROOT, ARCHIVE, profile=WRONG_HASH)
    assert "archive_hash_mismatch" in report.error_codes
```

- [ ] **Step 2: Run missing-gate RED**

- [ ] **Step 3: Implement report and compatibility receipt**

The receipt records archive name/size/hash, internal manifest result, package version, source commit, mapping-profile digest, Phase 1B projection head, SEDB export digest, differential counts, SEDB test source (`package_claim|own_execution`), exact executed-fault records, and CTCL registered/retrieved responses. Signature presence remains `not_performed` unless independently verified.

- [ ] **Step 4: Run complete clean vertical flow**

```powershell
python -m pytest -q
python scripts/validate_phase1a.py
python scripts/validate_phase1bc.py
python scripts/validate_phase2.py --sedb-archive "C:\Users\kakon\Downloads\SEDB\SEDB-v0.4B-local.zip"
sedb-ral phase2 verify . --sedb-archive "C:\Users\kakon\Downloads\SEDB\SEDB-v0.4B-local.zip"
```

- [ ] **Step 5: Register and retrieve the final validation instant**

Use `ctcl_register_instant`, immediately call `ctcl_get_instant`, and write exact results to `VALIDATION_BASIC_PHASE2.json`. Do not use `ctcl_now`.

- [ ] **Step 6: Prove every gate has an executed failure record**

The final JSON must list the test name, injected change, expected code, observed code, and `executed=true` for archive hash, manifest member, mapping contradiction, null-vs-false, and no-send gates.

- [ ] **Step 7: Commit locally and stop for complete review**

```powershell
git add src/sedb_ral/phase2.py src/sedb_ral/cli.py scripts/validate_phase2.py tests/test_phase2_gate.py VALIDATION_BASIC_PHASE2.json
git commit -m "feat: complete the Basic Phase 2 compatibility gate"
```

Do not push yet. Request Plumb plus an independent code review, run a clean reinstall/rebuild, then perform Neo.K's single final GitHub update. Do not merge main without separate approval.

---

## Plan self-review checklist

- [ ] Archive hash, size, package version, source commit, and internal manifest are exact.
- [ ] Extraction never trusts or modifies the live SEDB checkout.
- [ ] The SEDB package's release claim and our own test execution are labeled separately.
- [ ] Every RAL value is mapped or intentionally unmapped.
- [ ] Null/missing never becomes false.
- [ ] Package code imports no SEDB implementation and sends no network request.
- [ ] Differential comparison is field/path-driven with exactly three classes.
- [ ] Wrong hash and mapped-value contradiction are executed red controls.
- [ ] Compatibility receipts preserve Decision/Commit and Capability/Authority separation.
- [ ] Phase 3 registrar/federation work is absent.
- [ ] No GitHub push occurs before final complete review.
