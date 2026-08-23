from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .canonical import loads_strict
from .contracts import load_schema
from .ctcl import validate_ctcl_receipt
from .errors import RALValidationError
from .identifier import evaluate_identifier_fixture
from .ledger import append_event, verify_ledger

_SCHEMAS = (
    "ctcl-receipt.schema.json",
    "identifier-discrimination.schema.json",
    "identifier-field.schema.json",
    "ledger-event.schema.json",
)
_IDENTIFIER_FIXTURES = (
    "positive/resident-address.json",
    "negative/shared-runtime-tag.json",
    "mixed_population/one-resident.json",
)
_REQUIRED_DECISIONS = ("admit", "reject", "indeterminate")
_NEGATIVE_FIXTURE = "negative/shared-runtime-tag.json"
_POSITIVE_FIXTURE = "positive/resident-address.json"
_INDETERMINATE_FIXTURE = "mixed_population/one-resident.json"


@dataclass(frozen=True)
class Phase1AReport:
    passed: bool
    checked_schemas: tuple[str, ...]
    checked_fixtures: tuple[str, ...]
    observed_decisions: tuple[str, ...]
    ledger_status: str
    error_codes: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "checked_schemas": list(self.checked_schemas),
            "checked_fixtures": list(self.checked_fixtures),
            "observed_decisions": list(self.observed_decisions),
            "ledger_status": self.ledger_status,
            "error_codes": list(self.error_codes),
        }


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _load_object(path: Path) -> Mapping[str, object]:
    value = loads_strict(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RALValidationError("fixture_not_object", str(path))
    return value


def _error_code(error: Exception) -> str:
    if isinstance(error, RALValidationError):
        return error.code
    if isinstance(error, json.JSONDecodeError):
        return "input_invalid_json"
    if isinstance(error, UnicodeError):
        return "input_not_utf8"
    if isinstance(error, OSError):
        return "input_unreadable"
    if isinstance(error, SchemaError):
        return "schema_invalid"
    return "phase1a_gate_error"


def validate_phase1a(root: Path) -> Phase1AReport:
    root = Path(root)
    schema_root = root / "src" / "sedb_ral" / "schemas"
    fixture_root = root / "fixtures"
    checked_schemas: list[str] = []
    checked_fixtures: list[str] = []
    observed_decisions: list[str] = []
    errors: list[str] = []
    ledger_status = "unmeasured"

    actual_schemas = tuple(
        path.name for path in sorted(schema_root.glob("*.json"))
    )
    if actual_schemas != tuple(sorted(_SCHEMAS)):
        errors.append("schema_set_mismatch")
    for name in _SCHEMAS:
        try:
            schema = load_schema(name, schema_root)
            Draft202012Validator.check_schema(schema)
            checked_schemas.append(name)
        except Exception as error:
            errors.append(_error_code(error))

    ctcl_values: dict[str, Mapping[str, object]] = {}
    for relative in ("ctcl/reading.json", "ctcl/registered-anchor.json"):
        path = fixture_root / relative
        try:
            value = _load_object(path)
            validate_ctcl_receipt(value, schema_root)
            ctcl_values[relative] = value
            checked_fixtures.append(_relative(root, path))
        except Exception as error:
            errors.append(_error_code(error))

    manifest_path = fixture_root / "identifier" / "mixed_population" / "manifest.json"
    try:
        manifest = _load_object(manifest_path)
        checked_fixtures.append(_relative(root, manifest_path))
        if (
            tuple(manifest.get("fixture_paths", ())) != _IDENTIFIER_FIXTURES
            or tuple(manifest.get("required_decisions", ()))
            != _REQUIRED_DECISIONS
        ):
            errors.append("fixture_manifest_mismatch")
    except Exception as error:
        errors.append(_error_code(error))

    for relative in _IDENTIFIER_FIXTURES:
        path = fixture_root / "identifier" / relative
        if not path.exists():
            if relative == _NEGATIVE_FIXTURE:
                errors.append("negative_fixture_missing")
            elif relative == _POSITIVE_FIXTURE:
                errors.append("positive_fixture_missing")
            elif relative == _INDETERMINATE_FIXTURE:
                errors.append("indeterminate_fixture_missing")
            continue
        try:
            fixture = _load_object(path)
            result = evaluate_identifier_fixture(fixture, schema_root)
            checked_fixtures.append(_relative(root, path))
            observed_decisions.append(result.decision.value)
            if (
                fixture.get("expected_decision") != result.decision.value
                or set(fixture.get("expected_reason_codes", ()))
                != set(result.reason_codes)
            ):
                errors.append("fixture_expectation_mismatch")
        except Exception as error:
            errors.append(_error_code(error))

    if set(observed_decisions) != set(_REQUIRED_DECISIONS):
        errors.append("decision_population_incomplete")

    ledger_paths = tuple(
        sorted((fixture_root / "ledger").glob("event-*.json"))
    )
    if len(ledger_paths) != 2:
        errors.append("ledger_fixture_set_mismatch")
    anchor_receipt = ctcl_values.get("ctcl/registered-anchor.json")
    if anchor_receipt is not None and ledger_paths:
        try:
            with tempfile.TemporaryDirectory(prefix="sedb-ral-phase1a-") as temporary:
                ledger_root = Path(temporary)
                previous = None
                last_receipt = None
                for path in ledger_paths:
                    draft = _load_object(path)
                    checked_fixtures.append(_relative(root, path))
                    last_receipt = append_event(
                        ledger_root,
                        draft,
                        anchor_receipt,
                        expected_previous_chain_digest=previous,
                    )
                    previous = last_receipt.chain_digest
                if last_receipt is None:
                    raise RALValidationError(
                        "ledger_fixture_set_mismatch", "no event drafts"
                    )
                verification = verify_ledger(
                    ledger_root,
                    expected_final_chain_digest=last_receipt.chain_digest,
                )
                ledger_status = verification.status.value
                errors.extend(verification.error_codes)
        except Exception as error:
            errors.append(_error_code(error))

    unique_errors = tuple(sorted(set(errors)))
    return Phase1AReport(
        passed=(
            not unique_errors
            and set(observed_decisions) == set(_REQUIRED_DECISIONS)
            and ledger_status == "checkpoint_verified"
        ),
        checked_schemas=tuple(sorted(checked_schemas)),
        checked_fixtures=tuple(sorted(set(checked_fixtures))),
        observed_decisions=tuple(sorted(set(observed_decisions))),
        ledger_status=ledger_status,
        error_codes=unique_errors,
    )
