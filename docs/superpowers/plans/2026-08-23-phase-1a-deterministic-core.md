# SEDB-RAL Phase 1A Deterministic Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest executable SEDB-RAL core that canonicalizes bytes,
validates CTCL receipts and identifier contracts, rejects non-discriminating
resident identifiers, and verifies an append-only hash-chain ledger.

**Architecture:** Python modules expose pure validation and canonicalization
functions; JSON Schema files remain the public contracts. The first admissible
identifier integration unit always contains its schema, executable gate, and
positive/negative/mixed fixtures. The file ledger is canonical; Phase 1A has no
SQLite projection, message sending, registrar, UI, daemon, or full incident
corpus.

**Tech Stack:** Python 3.11+, standard library, `jsonschema` 4.x, `pytest` 8.x,
setuptools build backend, UTF-8/LF files.

**Spec:**
`docs/superpowers/specs/2026-08-23-sedb-ral-core-design.md`

**Plan anchor:** `ctcl:instant:17111e98-6e52-4850-98c4-0e1df5b1f85a`

## Global Constraints

- Execute on an isolated task branch/worktree created from `main` at or after
  commit `c152f66`.
- Require Python `>=3.11`; support Windows and POSIX path semantics.
- Runtime dependency is only `jsonschema>=4.23,<5`.
- Test dependencies are `pytest>=8.3,<9` and `build>=1.2,<2`.
- Canonical JSON accepts null, booleans, integers, strings, arrays, and objects;
  floats are rejected and decimals travel as strings.
- Canonical bytes are UTF-8, NFC-normalized, sorted-key, compact JSON with no
  BOM, CR, or trailing newline.
- Repository JSON Schemas under `src/sedb_ral/schemas/` are the source of
  truth and package data. No second checked-in schema tree is allowed.
- `ctcl_now` is a non-persisted `reading`; only `ctcl_register_instant` creates
  a `registered_anchor` expected to support third-party retrieval.
- A CTCL signature being present is not signature verification.
- Unknown, unmeasured, and indeterminate remain distinct from false.
- A shared evidence root may produce many rows but counts once for sufficiency.
- No Phase 1A command sends a message or grants authority.
- No public mutation command is exposed until authority envelopes exist in
  Phase 1B. Ledger append is a library interface used by tests and controlled
  import code only.
- Every validation gate has at least one deliberately corrupted input that
  proves the gate turns red.
- Every user-facing or cross-agent progress message uses a registered CTCL
  anchor. A reading ID must not be presented as retrievable.
- Do not add a license or rename the repository without Neo's separate choice.

---

## Planned file map

```text
pyproject.toml                              package, dependencies, CLI entry point
src/sedb_ral/schemas/ctcl-receipt.schema.json temporal evidence contract
src/sedb_ral/schemas/identifier-field.schema.json identifier declaration contract
src/sedb_ral/schemas/identifier-discrimination.schema.json executable-fixture contract
src/sedb_ral/schemas/ledger-event.schema.json canonical ledger event envelope
src/sedb_ral/__init__.py                    package version
src/sedb_ral/errors.py                      typed validation failures
src/sedb_ral/canonical.py                   strict parse, NFC, canonical bytes, digest
src/sedb_ral/contracts.py                   schema registry and validator lookup
src/sedb_ral/ctcl.py                        reading/anchor semantic validation
src/sedb_ral/identifier.py                  discrimination decision engine
src/sedb_ral/ledger.py                      append-only files, chain and anchor verification
src/sedb_ral/cli.py                         read-only Phase 1A CLI
src/sedb_ral/phase1a.py                     integrated artifact/fixture gate
fixtures/identifier/positive/*.json         admissible resident discriminator
fixtures/identifier/negative/*.json         measured shared runtime-tag counterexample
fixtures/identifier/mixed_population/*.json manifest proving discrimination
fixtures/ctcl/*.json                        reading and registered-anchor examples
fixtures/ledger/*.json                      deterministic valid ledger draft inputs
tests/test_cli_smoke.py                      install and command smoke tests
tests/test_canonical.py                      byte and digest behavior
tests/test_ctcl_contract.py                  CTCL semantic conditions
tests/test_identifier_contract.py            JSON Schema contract tests
tests/test_identifier_gate.py                executable discrimination tests
tests/test_ledger.py                         mutation/deletion/reorder detection
tests/test_phase1a_gate.py                    mixed artifact and corruption gate
scripts/validate_phase1a.py                   release-facing validation entry point
```

---

### Task 1: Bootstrap the installable package and read-only CLI

**Files:**

- Create: `pyproject.toml`
- Create: `src/sedb_ral/__init__.py`
- Create: `src/sedb_ral/cli.py`
- Create: `tests/test_cli_smoke.py`

**Interfaces:**

- Consumes: no project code.
- Produces: `sedb_ral.__version__ == "0.1.0"`,
  `sedb_ral.cli.build_parser() -> argparse.ArgumentParser`, and
  `sedb_ral.cli.main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing package and CLI smoke tests**

```python
# tests/test_cli_smoke.py
import pytest

from sedb_ral import __version__
from sedb_ral.cli import main


def test_version_is_phase_1a_version():
    assert __version__ == "0.1.0"


def test_help_exits_zero_and_names_phase_1a(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "SEDB-RAL Phase 1A" in capsys.readouterr().out


def test_version_flag(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"
```

- [ ] **Step 2: Run the focused test and confirm the missing-package failure**

Run:

```powershell
python -m pytest tests/test_cli_smoke.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named
'sedb_ral'`.

- [ ] **Step 3: Create package metadata and the minimal CLI**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "sedb-ral"
version = "0.1.0"
description = "SEDB Residency Attestation Layer deterministic core"
requires-python = ">=3.11"
dependencies = ["jsonschema>=4.23,<5"]

[project.optional-dependencies]
test = ["pytest>=8.3,<9", "build>=1.2,<2"]

[project.scripts]
sedb-ral = "sedb_ral.cli:entrypoint"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
sedb_ral = ["schemas/*.json"]

[tool.pytest.ini_options]
addopts = "-ra"
testpaths = ["tests"]
```

```python
# src/sedb_ral/__init__.py
__version__ = "0.1.0"
```

```python
# src/sedb_ral/cli.py
from __future__ import annotations

import argparse
from collections.abc import Sequence

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sedb-ral",
        description="SEDB-RAL Phase 1A deterministic core",
    )
    parser.add_argument("--version", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(__version__)
    return 0


def entrypoint() -> None:
    raise SystemExit(main())
```

- [ ] **Step 4: Install editable test dependencies and run the smoke tests**

Run:

```powershell
python -m pip install -e ".[test]"
python -m pytest tests/test_cli_smoke.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit the bootstrap**

```powershell
git add pyproject.toml src/sedb_ral/__init__.py src/sedb_ral/cli.py tests/test_cli_smoke.py
git commit -m "build: bootstrap Phase 1A package"
```

---

### Task 2: Implement strict canonical JSON and digest rules

**Files:**

- Create: `src/sedb_ral/errors.py`
- Create: `src/sedb_ral/canonical.py`
- Create: `tests/test_canonical.py`

**Interfaces:**

- Consumes: Python JSON values.
- Produces:
  `loads_strict(text: str) -> JsonValue`,
  `canonical_bytes(value: JsonValue) -> bytes`, and
  `sha256_ref(value: JsonValue) -> str`.

- [ ] **Step 1: Write failing canonical-byte tests**

```python
# tests/test_canonical.py
import pytest

from sedb_ral.canonical import canonical_bytes, loads_strict, sha256_ref
from sedb_ral.errors import RALValidationError


def test_canonicalizes_key_order_and_unicode_nfc():
    value = {"b": "e\u0301", "a": 1}
    assert canonical_bytes(value) == '{"a":1,"b":"é"}'.encode("utf-8")
    assert sha256_ref(value) == (
        "sha256:09ad9fd2fb648cb2f62141215828ea00"
        "a62c299db05d20aa9ade2f527a301cc6"
    )


def test_rejects_duplicate_keys_before_dict_collapse():
    with pytest.raises(RALValidationError, match="duplicate_key"):
        loads_strict('{"a":1,"a":2}')


def test_rejects_floats():
    with pytest.raises(RALValidationError, match="unsupported_number"):
        loads_strict('{"a":1.5}')


def test_rejects_keys_that_collide_after_nfc():
    with pytest.raises(RALValidationError, match="normalized_key_collision"):
        canonical_bytes({"é": 1, "e\u0301": 2})


def test_emits_no_bom_cr_or_trailing_newline():
    result = canonical_bytes({"a": [True, None, "x"]})
    assert not result.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in result
    assert not result.endswith(b"\n")
```

- [ ] **Step 2: Run the focused tests and confirm missing-module failures**

Run:

```powershell
python -m pytest tests/test_canonical.py -q
```

Expected: collection fails because `sedb_ral.canonical` and
`sedb_ral.errors` do not exist.

- [ ] **Step 3: Implement typed errors and canonicalization**

```python
# src/sedb_ral/errors.py
from __future__ import annotations


class RALValidationError(ValueError):
    def __init__(self, code: str, message: str, path: tuple[str, ...] = ()):
        self.code = code
        self.path = path
        super().__init__(f"{code}: {message}")
```

```python
# src/sedb_ral/canonical.py
from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import TypeAlias

from .errors import RALValidationError

JsonScalar: TypeAlias = None | bool | int | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _pairs(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise RALValidationError("duplicate_key", key)
        result[key] = value
    return result


def _float(token: str):
    raise RALValidationError("unsupported_number", token)


def loads_strict(text: str) -> JsonValue:
    return json.loads(
        text,
        object_pairs_hook=_pairs,
        parse_float=_float,
        parse_constant=_float,
    )


def _normalize(value: JsonValue, path: tuple[str, ...] = ()) -> JsonValue:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        raise RALValidationError("unsupported_number", repr(value), path)
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(item, path + (str(index),)) for index, item in enumerate(value)]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RALValidationError("non_string_key", repr(key), path)
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in result:
                raise RALValidationError(
                    "normalized_key_collision", normalized_key, path
                )
            result[normalized_key] = _normalize(item, path + (normalized_key,))
        return result
    raise RALValidationError("unsupported_type", type(value).__name__, path)


def canonical_bytes(value: JsonValue) -> bytes:
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_ref(value: JsonValue) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()
```

- [ ] **Step 4: Run focused tests and verify exact-byte success**

Run:

```powershell
python -m pytest tests/test_canonical.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Commit canonicalization**

```powershell
git add src/sedb_ral/errors.py src/sedb_ral/canonical.py tests/test_canonical.py
git commit -m "feat: add strict canonical JSON"
```

---

### Task 3: Add schema loading and the CTCL reading/anchor contract

**Files:**

- Create: `src/sedb_ral/schemas/ctcl-receipt.schema.json`
- Create: `src/sedb_ral/contracts.py`
- Create: `src/sedb_ral/ctcl.py`
- Create: `tests/test_ctcl_contract.py`
- Create: `fixtures/ctcl/reading.json`
- Create: `fixtures/ctcl/registered-anchor.json`

**Interfaces:**

- Consumes: dictionaries matching `ctcl-receipt.schema.json`.
- Produces:
  `load_schema(name: str, schema_root: Path | None = None) -> dict[str, object]`,
  `validate_contract(name: str, value: object, schema_root: Path | None = None) -> None`, and
  `validate_ctcl_receipt(value: Mapping[str, object]) -> None`.

- [ ] **Step 1: Write failing CTCL semantic tests**

```python
# tests/test_ctcl_contract.py
import copy
import json
from pathlib import Path

import pytest

from sedb_ral.ctcl import validate_ctcl_receipt
from sedb_ral.errors import RALValidationError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ctcl"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_reading_is_valid_local_evidence_but_not_retrievable():
    value = load("reading.json")
    validate_ctcl_receipt(value)
    assert value["ctcl_call_kind"] == "reading"
    assert value["retrievability"]["expected"] is False


def test_reading_cannot_claim_verified_retrieval():
    value = copy.deepcopy(load("reading.json"))
    value["retrievability"] = {"expected": True, "status": "verified"}
    with pytest.raises(RALValidationError, match="reading_not_retrievable"):
        validate_ctcl_receipt(value)


def test_registered_anchor_can_be_verified_retrievable():
    validate_ctcl_receipt(load("registered-anchor.json"))


def test_reading_cannot_carry_a_service_returned_share_url():
    value = copy.deepcopy(load("reading.json"))
    value["service_returned_share_url"] = "https://commoninstant.org/i/fabricated"
    with pytest.raises(RALValidationError, match="reading_share_url_invalid"):
        validate_ctcl_receipt(value)


def test_verified_retrieval_requires_evidence_ref():
    value = copy.deepcopy(load("registered-anchor.json"))
    value["retrievability"]["retrieval_evidence_ref"] = None
    with pytest.raises(RALValidationError, match="retrieval_evidence_missing"):
        validate_ctcl_receipt(value)


def test_unix_ms_and_ns_must_agree():
    value = copy.deepcopy(load("registered-anchor.json"))
    value["encodings"]["unix_ns"] = "1"
    with pytest.raises(RALValidationError, match="encoding_mismatch"):
        validate_ctcl_receipt(value)


def test_signature_presence_remains_unverified():
    value = load("registered-anchor.json")
    assert value["signature"]["verification_status"] == "not_performed"
```

- [ ] **Step 2: Run the tests and confirm missing contract modules**

Run:

```powershell
python -m pytest tests/test_ctcl_contract.py -q
```

Expected: collection fails because `sedb_ral.ctcl` does not exist.

- [ ] **Step 3: Write the CTCL JSON Schema and exact fixtures**

The schema requires these top-level fields and forbids unknown properties:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://evemisslab.com/schemas/sedb-ral/ctcl-receipt-v0.1.json",
  "title": "SEDB-RAL CTCL Receipt v0.1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "ctcl_instant_id", "ctcl_call_kind", "reference",
    "encodings", "source", "quality", "signature", "retrievability",
    "service_returned_share_url"
  ],
  "properties": {
    "schema_version": {"const": "0.1"},
    "ctcl_instant_id": {"type": "string", "pattern": "^ctcl:instant:[0-9a-f-]{36}$"},
    "ctcl_call_kind": {"enum": ["reading", "registered_anchor"]},
    "reference": {
      "type": "object",
      "additionalProperties": false,
      "required": ["timescale", "value"],
      "properties": {
        "timescale": {"const": "utc"},
        "value": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*Z$"}
      }
    },
    "encodings": {
      "type": "object",
      "additionalProperties": false,
      "required": ["unix_ms", "unix_ns", "rfc3339"],
      "properties": {
        "unix_ms": {"type": "string", "pattern": "^[0-9]+$"},
        "unix_ns": {"type": "string", "pattern": "^[0-9]+$"},
        "rfc3339": {"type": "string"}
      }
    },
    "source": {
      "type": "object",
      "additionalProperties": false,
      "required": ["class", "protocol", "provider", "sync_status"],
      "properties": {
        "class": {"type": "string", "minLength": 1},
        "protocol": {"type": "string", "minLength": 1},
        "provider": {"type": "string", "minLength": 1},
        "sync_status": {"type": "string", "minLength": 1}
      }
    },
    "quality": {
      "type": "object",
      "additionalProperties": false,
      "required": ["precision", "estimated_uncertainty_ns", "synchronized"],
      "properties": {
        "precision": {"type": "string", "minLength": 1},
        "estimated_uncertainty_ns": {"type": "integer", "minimum": 0},
        "synchronized": {"type": "boolean"}
      }
    },
    "signature": {
      "type": "object",
      "additionalProperties": false,
      "required": ["alg", "key_id", "signed_fields", "value", "verification_status"],
      "properties": {
        "alg": {"const": "Ed25519"},
        "key_id": {"type": "string", "minLength": 1},
        "signed_fields": {"const": "instant_id|unix_ns|timescale"},
        "value": {"type": "string", "minLength": 1},
        "verification_status": {"enum": ["not_performed", "verified", "failed"]}
      }
    },
    "retrievability": {
      "type": "object",
      "additionalProperties": false,
      "required": ["expected", "status", "checked_at_ref", "retrieval_evidence_ref"],
      "properties": {
        "expected": {"type": "boolean"},
        "status": {"enum": ["not_applicable", "unverified", "verified", "unknown_instant", "unavailable"]},
        "checked_at_ref": {"type": ["string", "null"]},
        "retrieval_evidence_ref": {"type": ["string", "null"]}
      }
    },
    "service_returned_share_url": {"type": ["string", "null"]}
  }
}
```

The JSON Schema validates structure. Cross-field reading/anchor semantics are
enforced by `validate_ctcl_receipt()` so failures retain specific reason codes
instead of collapsing into a generic schema error.

`fixtures/ctcl/reading.json` uses a real historical `ctcl_now` reading from
`evidence/ctcl/2026-08-23-project-inception.json`, sets
`ctcl_call_kind: "reading"`, `retrievability.expected: false`,
`retrievability.status: "not_applicable"`, null check/evidence refs, and a null
share URL.

`fixtures/ctcl/registered-anchor.json` uses registered instant
`ctcl:instant:5a76bd1b-2db2-463b-b2ad-0b1307102710`, sets
`ctcl_call_kind: "registered_anchor"`, `retrievability.expected: true`,
`retrievability.status: "verified"`, a registered check instant plus retrieval
evidence ref, and preserves the service-returned share URL. Both fixtures keep
`signature.verification_status: "not_performed"`.

- [ ] **Step 4: Implement schema loading and semantic checks**

```python
# src/sedb_ral/contracts.py
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .errors import RALValidationError


def default_schema_root() -> Path:
    return Path(__file__).with_name("schemas")


def load_schema(name: str, schema_root: Path | None = None) -> dict[str, object]:
    source = (schema_root or default_schema_root()) / name
    return json.loads(source.read_text(encoding="utf-8"))


def _registry(schema_root: Path) -> Registry:
    registry = Registry()
    for path in sorted(schema_root.glob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


def validate_contract(
    name: str,
    value: object,
    schema_root: Path | None = None,
) -> None:
    root = schema_root or default_schema_root()
    errors = sorted(
        Draft202012Validator(
            load_schema(name, root),
            registry=_registry(root),
        ).iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.path),
    )
    if errors:
        error = errors[0]
        raise RALValidationError(
            "schema_invalid",
            error.message,
            tuple(str(part) for part in error.path),
        )
```

```python
# src/sedb_ral/ctcl.py
from __future__ import annotations

from collections.abc import Mapping

from .contracts import validate_contract
from .errors import RALValidationError


def validate_ctcl_receipt(value: Mapping[str, object]) -> None:
    validate_contract("ctcl-receipt.schema.json", value)
    kind = value["ctcl_call_kind"]
    retrieval = value["retrievability"]
    if kind == "reading" and (
        retrieval["expected"] is not False
        or retrieval["status"] not in {"not_applicable", "unknown_instant"}
    ):
        raise RALValidationError(
            "reading_not_retrievable", "ctcl_now readings are not anchors"
        )
    if kind == "reading" and value["service_returned_share_url"] is not None:
        raise RALValidationError(
            "reading_share_url_invalid", "ctcl_now did not return a share URL"
        )
    if kind == "registered_anchor":
        if retrieval["expected"] is not True or retrieval["status"] not in {
            "unverified", "verified", "unknown_instant", "unavailable"
        }:
            raise RALValidationError(
                "anchor_retrievability_invalid",
                "registered anchor has invalid retrieval semantics",
            )
        if (
            retrieval["status"] == "verified"
            and not retrieval["retrieval_evidence_ref"]
        ):
            raise RALValidationError(
                "retrieval_evidence_missing",
                "verified retrieval requires an evidence reference",
            )
    encodings = value["encodings"]
    if int(encodings["unix_ns"]) != int(encodings["unix_ms"]) * 1_000_000:
        raise RALValidationError("encoding_mismatch", "unix_ms and unix_ns disagree")
```

- [ ] **Step 5: Run focused tests and a deliberately corrupted fixture**

Run:

```powershell
python -m pytest tests/test_ctcl_contract.py -q
```

Expected: `7 passed`; the test that promotes a reading to verified retrieval
must fail before the implementation and pass only because the implementation
rejects it.

- [ ] **Step 6: Commit CTCL contracts**

```powershell
git add src/sedb_ral/schemas/ctcl-receipt.schema.json src/sedb_ral/contracts.py src/sedb_ral/ctcl.py tests/test_ctcl_contract.py fixtures/ctcl
git commit -m "feat: distinguish CTCL readings from anchors"
```

---

### Task 4: Define identifier and discrimination contracts

**Files:**

- Create: `src/sedb_ral/schemas/identifier-field.schema.json`
- Create: `src/sedb_ral/schemas/identifier-discrimination.schema.json`
- Create: `tests/test_identifier_contract.py`

**Interfaces:**

- Consumes: JSON identifier declarations and discrimination fixtures.
- Produces contracts named `identifier-field.schema.json` and
  `identifier-discrimination.schema.json` loadable through
  `validate_contract()`.

- [ ] **Step 1: Write failing schema tests**

```python
# tests/test_identifier_contract.py
import json
from pathlib import Path

import pytest

from sedb_ral.contracts import validate_contract
from sedb_ral.errors import RALValidationError

ROOT = Path(__file__).parents[1]


def load_fixture(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_positive_fixture_matches_contract():
    validate_contract(
        "identifier-discrimination.schema.json",
        load_fixture("fixtures/identifier/positive/resident-address.json"),
    )


def test_unknown_identifier_field_is_rejected():
    fixture = load_fixture("fixtures/identifier/positive/resident-address.json")
    fixture["identifier"]["seat"] = "overloaded"
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("identifier-discrimination.schema.json", fixture)


def test_fixture_requires_retro_stamp_status_when_retrospective():
    fixture = load_fixture("fixtures/identifier/negative/shared-runtime-tag.json")
    del fixture["temporal_evidence"]["retro_stamped"]
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_contract("identifier-discrimination.schema.json", fixture)
```

- [ ] **Step 2: Run tests and confirm missing schemas/fixtures**

Run:

```powershell
python -m pytest tests/test_identifier_contract.py -q
```

Expected: failures report missing fixture files or missing schema files.

- [ ] **Step 3: Write the identifier field contract**

The schema is Draft 2020-12, uses `additionalProperties: false`, and requires:

```json
{
  "schema_version": "0.1",
  "identifier_id": "id:resident-address:v1",
  "namespace": "agent",
  "value": "agent://example/resident/alice",
  "subject_kind": "resident",
  "identifier_kind": "resident_address",
  "uniqueness_scope": "namespace",
  "changes_when": ["resident_address_rotated"],
  "is_routable_address": true,
  "attestation_refs": ["attestation:example"]
}
```

`subject_kind` is one of `resident`, `instance`, `line`, `runtime`, `binding`,
or `address`. The contract does not infer identity from `identifier_kind`.

- [ ] **Step 4: Write the fixture contract and three fixture populations**

The fixture contract requires:

```text
schema_version
fixture_id
identifier
discrimination_target = resident
required_instances_per_resident >= 2
observations[]
expected_decision = admit | reject | indeterminate
expected_reason_codes[]
temporal_evidence.temporal_capture_mode
temporal_evidence.retro_stamped
temporal_evidence.basis_refs[]
```

Its `identifier` property uses the relative JSON Schema reference
`"$ref": "identifier-field.schema.json"`. Both schemas have absolute `$id`
values under `https://evemisslab.com/schemas/sedb-ral/`; Task 3's
`referencing.Registry` resolves the reference from the same canonical schema
directory.

Each observation requires `observation_id`, `resident_ref`, `instance_ref`,
`runtime_ref`, and `observed_value`.

Create exact cases:

- Positive: two residents, two instances each; each resident's value is stable
  and values differ between residents.
- Negative: two residents in the same runtime, each with two instances; all
  values equal `agent://evemisslab/residence/claude-code`; expected reject code
  `does_not_distinguish_residents`; mark retrospective and cite the incident
  handoff as a basis ref.
- Indeterminate: only one resident; expected
  `population_too_small`.
- Mixed manifest: list the three relative fixture paths and require one
  `admit`, one `reject`, and one `indeterminate` result.

- [ ] **Step 5: Run schema tests and confirm all three populations validate**

Run:

```powershell
python -m pytest tests/test_identifier_contract.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit identifier contracts and fixtures together**

Do not commit only the schema. This task is not admissible until Task 5's gate
is also implemented; keep Tasks 4 and 5 on the same isolated branch and do not
merge between them.

```powershell
git add src/sedb_ral/schemas/identifier-field.schema.json src/sedb_ral/schemas/identifier-discrimination.schema.json tests/test_identifier_contract.py fixtures/identifier
git commit -m "test: define identifier discrimination contracts"
```

---

### Task 5: Implement the executable identifier admission gate

**Files:**

- Create: `src/sedb_ral/identifier.py`
- Create: `tests/test_identifier_gate.py`
- Modify: `src/sedb_ral/cli.py`

**Interfaces:**

- Consumes: one validated discrimination fixture.
- Produces:
  `DiscriminationDecision`,
  `DiscriminationResult`, and
  `evaluate_identifier_fixture(value: Mapping[str, object]) -> DiscriminationResult`.

- [ ] **Step 1: Write failing decision tests over all fixture classes**

```python
# tests/test_identifier_gate.py
import json
from pathlib import Path

import pytest

from sedb_ral.identifier import (
    DiscriminationDecision,
    evaluate_identifier_fixture,
)

ROOT = Path(__file__).parents[1] / "fixtures" / "identifier"


@pytest.mark.parametrize(
    ("relative", "decision", "reason"),
    [
        ("positive/resident-address.json", DiscriminationDecision.ADMIT, "admissible_resident_discriminator"),
        ("negative/shared-runtime-tag.json", DiscriminationDecision.REJECT, "does_not_distinguish_residents"),
        ("mixed_population/one-resident.json", DiscriminationDecision.INDETERMINATE, "population_too_small"),
    ],
)
def test_expected_fixture_decisions(relative, decision, reason):
    fixture = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is decision
    assert reason in result.reason_codes
    assert result.decision.value == fixture["expected_decision"]
    assert set(result.reason_codes) == set(fixture["expected_reason_codes"])


def test_mixed_population_has_discriminating_power():
    decisions = set()
    for path in ROOT.rglob("*.json"):
        if path.name == "manifest.json":
            continue
        fixture = json.loads(path.read_text(encoding="utf-8"))
        decisions.add(evaluate_identifier_fixture(fixture).decision)
    assert decisions == {
        DiscriminationDecision.ADMIT,
        DiscriminationDecision.REJECT,
        DiscriminationDecision.INDETERMINATE,
    }


def test_subject_kind_must_match_discrimination_target():
    fixture = json.loads(
        (ROOT / "positive/resident-address.json").read_text(encoding="utf-8")
    )
    fixture["identifier"]["subject_kind"] = "runtime"
    result = evaluate_identifier_fixture(fixture)
    assert result.decision is DiscriminationDecision.REJECT
    assert result.reason_codes == ("identifier_subject_mismatch",)
```

- [ ] **Step 2: Run the focused tests and verify the missing-gate failure**

Run:

```powershell
python -m pytest tests/test_identifier_gate.py -q
```

Expected: collection fails because `sedb_ral.identifier` does not exist.

- [ ] **Step 3: Implement the gate without naming an unobserved cause**

```python
# src/sedb_ral/identifier.py
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from .contracts import validate_contract


class DiscriminationDecision(str, Enum):
    ADMIT = "admit"
    REJECT = "reject"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class DiscriminationResult:
    decision: DiscriminationDecision
    reason_codes: tuple[str, ...]
    distinct_residents: int
    distinct_values: int


def evaluate_identifier_fixture(value: Mapping[str, object]) -> DiscriminationResult:
    validate_contract("identifier-discrimination.schema.json", value)
    if value["identifier"]["subject_kind"] != value["discrimination_target"]:
        return DiscriminationResult(
            DiscriminationDecision.REJECT,
            ("identifier_subject_mismatch",),
            0,
            0,
        )
    observations = value["observations"]
    by_resident: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    value_to_residents: dict[str, set[str]] = defaultdict(set)
    for observation in observations:
        resident = observation["resident_ref"]
        by_resident[resident].append(observation)
        value_to_residents[observation["observed_value"]].add(resident)

    distinct_residents = len(by_resident)
    distinct_values = len(value_to_residents)
    required_instances = value["required_instances_per_resident"]
    if distinct_residents < 2:
        return DiscriminationResult(
            DiscriminationDecision.INDETERMINATE,
            ("population_too_small",),
            distinct_residents,
            distinct_values,
        )
    if any(
        len({item["instance_ref"] for item in items}) < required_instances
        for items in by_resident.values()
    ):
        return DiscriminationResult(
            DiscriminationDecision.INDETERMINATE,
            ("instances_per_resident_unmeasured",),
            distinct_residents,
            distinct_values,
        )
    if any(len({item["observed_value"] for item in items}) > 1 for items in by_resident.values()):
        return DiscriminationResult(
            DiscriminationDecision.REJECT,
            ("unstable_within_resident",),
            distinct_residents,
            distinct_values,
        )
    if any(len(residents) > 1 for residents in value_to_residents.values()):
        return DiscriminationResult(
            DiscriminationDecision.REJECT,
            ("does_not_distinguish_residents",),
            distinct_residents,
            distinct_values,
        )
    return DiscriminationResult(
        DiscriminationDecision.ADMIT,
        ("admissible_resident_discriminator",),
        distinct_residents,
        distinct_values,
    )
```

The rejection intentionally says only that the value did not distinguish
residents in the measured scope. It does not relabel the value as runtime tag,
role, or pane without another contract.

- [ ] **Step 4: Add the `identifier check` CLI subcommand**

The subcommand reads strict JSON, evaluates it, prints compact JSON with
`decision`, `reason_codes`, `distinct_residents`, and `distinct_values`, and
returns:

```text
0 admit
2 reject or schema invalid
3 indeterminate
```

Add CLI tests that assert all three exit codes and parse the emitted JSON.

- [ ] **Step 5: Run contract and gate tests together**

Run:

```powershell
python -m pytest tests/test_identifier_contract.py tests/test_identifier_gate.py -q
```

Expected: all tests pass, including the measured shared runtime-tag rejection
and mixed population.

- [ ] **Step 6: Commit the executable gate in the same integration unit**

```powershell
git add src/sedb_ral/identifier.py src/sedb_ral/cli.py tests/test_identifier_gate.py
git commit -m "feat: reject non-discriminating identifiers"
```

Before any merge, review Tasks 4 and 5 together. Neither commit alone is an
admissible Phase 1A result.

---

### Task 6: Implement the append-only file ledger and hash chain

**Files:**

- Create: `src/sedb_ral/schemas/ledger-event.schema.json`
- Create: `src/sedb_ral/ledger.py`
- Create: `tests/test_ledger.py`
- Create: `fixtures/ledger/event-001.json`
- Create: `fixtures/ledger/event-002.json`

**Interfaces:**

- Consumes: event drafts with `event_id`, `ledger_id`, `event_type`,
  `causal_parent_ids`, `recorded_time_ref`, `recorded_time`, and `payload`, plus
  the referenced registered CTCL receipt.
- Produces:
  `append_event(root: Path, draft: Mapping[str, object], ctcl_receipt: Mapping[str, object]) -> AppendReceipt` and
  `verify_ledger(root: Path) -> LedgerVerification`.

- [ ] **Step 1: Write failing ledger tests**

```python
# tests/test_ledger.py
import json
from pathlib import Path

import pytest

from sedb_ral.errors import RALValidationError
from sedb_ral.ledger import append_event, verify_ledger

CTCL = json.loads(
    (Path(__file__).parents[1] / "fixtures/ctcl/registered-anchor.json").read_text(
        encoding="utf-8"
    )
)


def draft(event_id: str, parent_ids=()):
    return {
        "schema_version": "0.1",
        "event_id": event_id,
        "ledger_id": "ledger:test",
        "event_type": "identifier.observed",
        "causal_parent_ids": list(parent_ids),
        "recorded_time_ref": "ctcl:instant:5a76bd1b-2db2-463b-b2ad-0b1307102710",
        "recorded_time": "2026-08-23T08:09:39.165Z",
        "payload": {"identifier_id": "id:test"},
    }


def test_append_and_verify_two_events(tmp_path):
    first = append_event(tmp_path, draft("evt_001"), CTCL)
    second = append_event(tmp_path, draft("evt_002", ("evt_001",)), CTCL)
    result = verify_ledger(tmp_path)
    assert result.valid is True
    assert result.event_count == 2
    assert result.final_chain_digest == second.chain_digest
    assert first.ledger_seq == 1


def test_mutation_turns_verification_red(tmp_path):
    receipt = append_event(tmp_path, draft("evt_001"), CTCL)
    path = receipt.event_path
    value = json.loads(path.read_text(encoding="utf-8"))
    value["payload"]["identifier_id"] = "id:mutated"
    path.write_text(json.dumps(value), encoding="utf-8")
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "record_digest_mismatch" in result.error_codes


def test_deletion_turns_anchor_red(tmp_path):
    first = append_event(tmp_path, draft("evt_001"), CTCL)
    append_event(tmp_path, draft("evt_002", ("evt_001",)), CTCL)
    first.event_path.unlink()
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "sequence_gap" in result.error_codes


def test_duplicate_event_id_is_refused(tmp_path):
    append_event(tmp_path, draft("evt_001"), CTCL)
    with pytest.raises(RALValidationError, match="duplicate_event_id"):
        append_event(tmp_path, draft("evt_001"), CTCL)


def test_reading_cannot_anchor_recorded_time(tmp_path):
    reading = json.loads(
        (Path(__file__).parents[1] / "fixtures/ctcl/reading.json").read_text(
            encoding="utf-8"
        )
    )
    with pytest.raises(RALValidationError, match="registered_anchor_required"):
        append_event(tmp_path, draft("evt_001"), reading)
```

- [ ] **Step 2: Run tests and confirm the ledger module is absent**

Run:

```powershell
python -m pytest tests/test_ledger.py -q
```

Expected: collection fails because `sedb_ral.ledger` does not exist.

- [ ] **Step 3: Define the event schema and chain algorithm**

The schema forbids unknown properties and requires the draft fields above plus
ledger-assigned `ledger_seq` and `integrity`.

Use these exact digest rules:

```text
record_digest = SHA256(canonical bytes of the event without `integrity`)
previous raw digest = 32 zero bytes for genesis, otherwise decoded prior chain digest
chain_digest = SHA256(
  b"SEDB-RAL-CHAIN-v1\x00" + previous_raw_digest + record_raw_digest
)
```

Event files are named `{ledger_seq:020d}-{event_id}.json` under
`events/YYYY/MM/`, derived from the explicit UTC `recorded_time`. Each append
also writes an immutable `anchors/{ledger_seq:020d}.json` containing event
count, last event ID, and final chain digest. Canonical files contain no
trailing newline.

- [ ] **Step 4: Implement append and verification**

Use frozen result dataclasses:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppendReceipt:
    ledger_seq: int
    event_id: str
    record_digest: str
    chain_digest: str
    event_path: Path
    anchor_path: Path


@dataclass(frozen=True)
class LedgerVerification:
    valid: bool
    event_count: int
    final_chain_digest: str | None
    error_codes: tuple[str, ...]
```

Write temporary files in the target directory with exclusive creation, call
`flush()` and `os.fsync()`, then publish with `os.link(temp, final)` and unlink
the temp file. The hard-link publish is same-filesystem, exposes only complete
bytes, and fails if the immutable final path already exists; do not use
`os.replace()` because it can overwrite history. A crash between event and
anchor publication leaves a detectable `anchor_missing` state and is not
silently repaired. Refuse an existing event ID. Before writing, call `validate_ctcl_receipt()`, require
`ctcl_call_kind == "registered_anchor"`, and require receipt ID/reference time
to equal the event's `recorded_time_ref`/`recorded_time`. Verification sorts by embedded `ledger_seq`, checks filename
agreement, contiguous sequence, record digest, previous digest, chain digest,
causal parent existence, and latest immutable anchor.

- [ ] **Step 5: Add reorder and truncated-tail corruption tests**

Add tests for a missing anchor, a renamed event whose filename disagrees with
its embedded sequence, and a deleted final event whose anchor remains. Each
returns `valid=False` with a specific reason code rather than raising an
untyped exception.

```python
def test_event_without_anchor_is_detected(tmp_path):
    receipt = append_event(tmp_path, draft("evt_001"), CTCL)
    receipt.anchor_path.unlink()
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "anchor_missing" in result.error_codes


def test_filename_sequence_disagreement_is_detected(tmp_path):
    receipt = append_event(tmp_path, draft("evt_001"), CTCL)
    wrong = receipt.event_path.with_name("00000000000000000002-evt_001.json")
    receipt.event_path.rename(wrong)
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "filename_sequence_mismatch" in result.error_codes


def test_deleted_tail_with_anchor_is_detected(tmp_path):
    receipt = append_event(tmp_path, draft("evt_001"), CTCL)
    receipt.event_path.unlink()
    result = verify_ledger(tmp_path)
    assert result.valid is False
    assert "anchored_event_missing" in result.error_codes
```

- [ ] **Step 6: Run ledger and canonical tests together**

Run:

```powershell
python -m pytest tests/test_canonical.py tests/test_ledger.py -q
```

Expected: all tests pass; each corruption test proves a red path.

- [ ] **Step 7: Commit the file ledger**

```powershell
git add src/sedb_ral/schemas/ledger-event.schema.json src/sedb_ral/ledger.py tests/test_ledger.py fixtures/ledger
git commit -m "feat: add append-only hash-chain ledger"
```

---

### Task 7: Integrate the read-only CLI and Phase 1A artifact gate

**Files:**

- Create: `src/sedb_ral/phase1a.py`
- Create: `tests/test_phase1a_gate.py`
- Modify: `src/sedb_ral/cli.py`
- Create: `scripts/validate_phase1a.py`

**Interfaces:**

- Consumes: repository schemas, fixtures, and a ledger directory.
- Produces:
  `validate_phase1a(root: Path) -> Phase1AReport` and CLI commands:
  `canonicalize`, `contract validate`, `identifier check`, `ledger verify`, and
  `phase1a verify`.

- [ ] **Step 1: Write failing integrated-gate tests**

```python
# tests/test_phase1a_gate.py
import json
import shutil
from pathlib import Path

from sedb_ral.phase1a import validate_phase1a


def test_repository_phase1a_gate_is_green():
    root = Path(__file__).parents[1]
    report = validate_phase1a(root)
    assert report.passed is True
    assert set(report.observed_decisions) == {"admit", "reject", "indeterminate"}


def test_missing_negative_fixture_turns_gate_red(tmp_path):
    source = Path(__file__).parents[1]
    target = tmp_path / "repo"
    shutil.copytree(
        source / "src/sedb_ral/schemas",
        target / "src/sedb_ral/schemas",
    )
    shutil.copytree(source / "fixtures", target / "fixtures")
    (target / "fixtures/identifier/negative/shared-runtime-tag.json").unlink()
    report = validate_phase1a(target)
    assert report.passed is False
    assert "negative_fixture_missing" in report.error_codes


def test_promoted_ctcl_reading_turns_gate_red(tmp_path):
    source = Path(__file__).parents[1]
    target = tmp_path / "repo"
    shutil.copytree(
        source / "src/sedb_ral/schemas",
        target / "src/sedb_ral/schemas",
    )
    shutil.copytree(source / "fixtures", target / "fixtures")
    path = target / "fixtures/ctcl/reading.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["retrievability"] = {
        "expected": True,
        "status": "verified",
        "checked_at_ref": "ctcl:instant:invalid-promotion",
        "retrieval_evidence_ref": "evidence:invalid-promotion",
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    report = validate_phase1a(target)
    assert report.passed is False
    assert "reading_not_retrievable" in report.error_codes
```

- [ ] **Step 2: Run the integrated tests and confirm missing gate failure**

Run:

```powershell
python -m pytest tests/test_phase1a_gate.py -q
```

Expected: collection fails because `sedb_ral.phase1a` does not exist.

- [ ] **Step 3: Implement the integrated gate**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Phase1AReport:
    passed: bool
    checked_schemas: tuple[str, ...]
    checked_fixtures: tuple[str, ...]
    observed_decisions: tuple[str, ...]
    error_codes: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "checked_schemas": list(self.checked_schemas),
            "checked_fixtures": list(self.checked_fixtures),
            "observed_decisions": list(self.observed_decisions),
            "error_codes": list(self.error_codes),
        }
```

`validate_phase1a()` must:

1. load all four Phase 1A schemas from
   `root / "src/sedb_ral/schemas"` by passing that path to
   `validate_contract()`;
2. validate every CTCL and identifier fixture;
3. evaluate every identifier fixture;
4. require at least one admit, reject, and indeterminate result;
5. require the exact measured negative fixture path;
6. build a temporary ledger from the sorted checked-in event drafts and the
   registered-anchor CTCL fixture, then verify that ledger;
7. sort report paths and error codes for deterministic output.

- [ ] **Step 4: Implement read-only CLI commands and deterministic JSON output**

`canonicalize FILE` writes canonical bytes to stdout.

`contract validate CONTRACT FILE` prints:

```json
{"contract":"identifier-field.schema.json","valid":true}
```

`identifier check FILE` uses the exit codes from Task 5.

`ledger verify ROOT` and `phase1a verify ROOT` return zero only when `passed` or
`valid` is true. All JSON output uses `canonical_bytes()` and appends one LF at
the terminal boundary only; the underlying canonical value remains newline-free.

- [ ] **Step 5: Implement the standalone validator wrapper**

```python
# scripts/validate_phase1a.py
from pathlib import Path

from sedb_ral.canonical import canonical_bytes
from sedb_ral.phase1a import validate_phase1a


def main() -> int:
    report = validate_phase1a(Path(__file__).resolve().parents[1])
    print(canonical_bytes(report.as_json()).decode("utf-8"))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run CLI, gate, and corruption tests**

Run:

```powershell
python -m pytest tests/test_cli_smoke.py tests/test_phase1a_gate.py -q
python scripts/validate_phase1a.py
sedb-ral phase1a verify .
```

Expected: tests pass; both validator commands exit zero and report one admit,
one reject, and one indeterminate class. Corrupted-copy tests remain green only
because their copied gates correctly report red.

- [ ] **Step 7: Commit the integrated gate**

```powershell
git add src/sedb_ral/phase1a.py src/sedb_ral/cli.py tests/test_phase1a_gate.py scripts/validate_phase1a.py
git commit -m "feat: add integrated Phase 1A gate"
```

---

### Task 8: Package, independently reinstall, and publish validation evidence

**Files:**

- Modify: `README.md`
- Create: `VALIDATION_PHASE_1A.json`
- Create: `SHA256SUMS.txt`
- Create: `scripts/build_manifest.py`
- Test: `tests/test_packaging.py`

**Interfaces:**

- Consumes: complete Phase 1A source tree.
- Produces: reproducible sdist/wheel, installed `sedb-ral` CLI, static SHA-256
  manifest, and a validation record with a registered CTCL anchor.

- [ ] **Step 1: Write failing packaging tests**

```python
# tests/test_packaging.py
from pathlib import Path


def test_public_contracts_exist_once():
    root = Path(__file__).parents[1]
    schema_root = root / "src/sedb_ral/schemas"
    schemas = sorted(path.name for path in schema_root.glob("*.json"))
    assert schemas == [
        "ctcl-receipt.schema.json",
        "identifier-discrimination.schema.json",
        "identifier-field.schema.json",
        "ledger-event.schema.json",
    ]
    assert not (root / "schemas").exists()


def test_no_phase_1a_sqlite_or_send_adapter():
    root = Path(__file__).parents[1]
    assert not list(root.rglob("*.sqlite3"))
    assert not (root / "src/sedb_ral/adapters").exists()
```

- [ ] **Step 2: Run the full test suite before packaging**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 3: Build artifacts and reinstall into a clean temporary venv**

Run:

```powershell
python -m build
$phase1aVenv = Join-Path $env:TEMP ("sedb-ral-phase1a-" + [guid]::NewGuid().ToString("N"))
python -m venv $phase1aVenv
& "$phase1aVenv\Scripts\python.exe" -m pip install --upgrade pip
& "$phase1aVenv\Scripts\python.exe" -m pip install (Get-ChildItem dist\*.whl | Select-Object -First 1).FullName
& "$phase1aVenv\Scripts\sedb-ral.exe" --version
& "$phase1aVenv\Scripts\sedb-ral.exe" phase1a verify .
$ctclFixture = (Resolve-Path 'fixtures\ctcl\registered-anchor.json').Path
Push-Location $env:TEMP
try {
  & "$phase1aVenv\Scripts\sedb-ral.exe" contract validate ctcl-receipt.schema.json $ctclFixture
} finally {
  Pop-Location
}
```

Expected: installed version `0.1.0`; installed CLI gate exits zero; contract
validation succeeds outside the checkout, proving wheel schema data is
present. Use a newly created temp directory and do not delete it with a broad
or unresolved path.

- [ ] **Step 4: Register the validation instant and write exact evidence**

After all tests, build, clean-install, manifest, and CLI checks pass, call
`ctcl_register_instant` with label `sedb-ral-phase-1a-validation` and meta that
contains:

```text
project = SEDB-RAL
git_commit = current HEAD
test_count = exact pytest passed count
wheel_filename = exact wheel basename
validation = passed
signature_scope_note = CTCL signature does not cover meta or Git authorship
```

Immediately call `ctcl_get_instant` on the returned ID. Write
`VALIDATION_PHASE_1A.json` with the exact test/build outputs, registered CTCL
response, retrieval result, and `signature_verification_status:
"not_performed"`. Do not substitute `ctcl_now`.

- [ ] **Step 5: Update README with exact Phase 1A commands and boundaries**

Document installation, the four read-only CLI groups, exit codes, canonical
byte rules, CTCL reading-versus-anchor distinction, fixture locations, and the
explicit absence of SQLite, transports, registrar, and full incident corpus.

- [ ] **Step 6: Generate and test the SHA-256 manifest**

Implement `scripts/build_manifest.py` with:

```python
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def release_paths(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        text=True,
    )
    return [
        root / relative
        for relative in sorted(line for line in output.splitlines() if line)
        if relative != "SHA256SUMS.txt"
    ]


def build_manifest(root: Path, paths: list[Path] | None = None) -> str:
    lines = []
    selected = release_paths(root) if paths is None else sorted(paths)
    for path in selected:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        relative = path.relative_to(root).as_posix()
        lines.append(f"{digest}  {relative}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[1]
    (repo / "SHA256SUMS.txt").write_text(build_manifest(repo), encoding="utf-8", newline="\n")
```

Add this exact packaging test:

```python
from scripts.build_manifest import build_manifest


def test_manifest_matches_release_files():
    root = Path(__file__).parents[1]
    assert (root / "SHA256SUMS.txt").read_text(encoding="utf-8") == build_manifest(root)


def test_manifest_changes_on_mutation_omission_and_extra(tmp_path):
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    original = build_manifest(tmp_path, [first, second])
    first.write_text("changed", encoding="utf-8")
    assert build_manifest(tmp_path, [first, second]) != original
    assert build_manifest(tmp_path, [first]) != original
    third = tmp_path / "c.txt"
    third.write_text("c", encoding="utf-8")
    assert build_manifest(tmp_path, [first, second, third]) != original
```

This covers `VALIDATION_PHASE_1A.json` and excludes only the manifest itself.
Mutation, omission, and extra-file variants must turn the comparison red.

After the script, tests, README, and validation evidence all contain their
final bytes, generate the manifest:

```powershell
python scripts/build_manifest.py
```

- [ ] **Step 7: Run the final verification gate from a clean Git state**

Run:

```powershell
python -m pytest -q
python scripts/validate_phase1a.py
python -m build
git diff --check
git status --short
```

Expected: zero test failures; validator exits zero; build exits zero; diff
check has no output; status lists only the intended Task 8 files before commit.

- [ ] **Step 8: Commit Phase 1A validation evidence**

```powershell
git add README.md VALIDATION_PHASE_1A.json SHA256SUMS.txt tests/test_packaging.py scripts/build_manifest.py
git commit -m "docs: publish Phase 1A validation evidence"
```

- [ ] **Step 9: Review the complete task branch before integration**

Review all commits from the task branch base through HEAD. Confirm Tasks 4 and
5 are integrated together; no commit is presented as an admissible schema-only
release. Re-run the full verification commands after any review fix.

---

## Plan self-review checklist

- [ ] Every Phase 1A spec requirement maps to a task.
- [ ] Identifier schema, gate, and positive/negative/mixed fixtures are one
  reviewed integration unit.
- [ ] Every gate includes a corrupted input that proves it can fail.
- [ ] CTCL readings and registered anchors have different machine states.
- [ ] No test counts rows with a shared evidence root as independent evidence.
- [ ] No SQLite, transport send, registrar, automatic merge, or full incident
  corpus appears in Phase 1A.
- [ ] Function names and result types are consistent across tasks.
- [ ] No unresolved markers or incomplete test bodies remain in committed
  implementation.
- [ ] Final evidence uses `ctcl_register_instant` and verifies retrievability.
