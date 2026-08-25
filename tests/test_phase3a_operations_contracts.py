from __future__ import annotations

import copy

import pytest
from phase3a_operations_helpers import (
    digest,
    valid_foreign_pin,
    valid_intake,
    valid_manifest,
    valid_operation_receipt,
    valid_operation_request,
    valid_operator_observation,
    valid_policy,
)

from sedb_ral.contracts import load_schema, validate_contract
from sedb_ral.errors import RALValidationError
from sedb_ral.operations.models import (
    ForeignSchemaPin,
    OperationReceipt,
    OperationRequest,
    OperationsManifest,
    OperationsPolicy,
    OperatorObservation,
    RegistrarIntake,
)

MODEL_CASES = (
    (ForeignSchemaPin, valid_foreign_pin, "pin_digest"),
    (OperationsPolicy, valid_policy, "policy_digest"),
    (RegistrarIntake, valid_intake, "intake_digest"),
    (OperatorObservation, valid_operator_observation, "observation_digest"),
    (OperationRequest, valid_operation_request, "operation_digest"),
    (OperationReceipt, valid_operation_receipt, "receipt_digest"),
    (OperationsManifest, valid_manifest, "manifest_digest"),
)


@pytest.mark.parametrize(("model", "factory", "digest_field"), MODEL_CASES)
def test_contract_models_round_trip_strict_canonical_values(
    model, factory, digest_field
):
    value = factory()
    parsed = model.from_dict(value)

    assert parsed.to_dict() == value
    assert parsed.digest == value[digest_field]


@pytest.mark.parametrize(("model", "factory", "digest_field"), MODEL_CASES)
def test_bound_document_byte_mutation_is_typed_before_semantic_use(
    model, factory, digest_field
):
    value = factory()
    value[digest_field] = digest("f")

    with pytest.raises(RALValidationError) as caught:
        model.from_dict(value)

    assert caught.value.code.endswith("_digest_mismatch")


def test_operation_digest_binds_every_authority_and_concurrency_gate():
    original = OperationRequest.from_dict(valid_operation_request())
    for field, changed in (
        ("policy_digest", digest("1")),
        ("operations_generation", "operations-generation:other"),
        ("registry_manifest_digest", digest("2")),
        ("expected_ledger_head", digest("3")),
        ("operator_observation_digest", digest("4")),
        ("authority_artifact_digest", digest("e")),
        ("checkpoint_evidence_digest", digest("6")),
    ):
        mutated = OperationRequest.from_dict(
            valid_operation_request(**{field: changed})
        )
        assert mutated.digest != original.digest


def test_applicant_cannot_supply_operational_evidence():
    for forbidden in (
        "canonical_root",
        "expected_head",
        "operator_ref",
        "policy_digest",
        "authority",
        "checkpoint_ref",
        "private_path",
    ):
        value = valid_intake()
        value.pop("intake_digest")
        value[forbidden] = "attacker-value"
        with pytest.raises(RALValidationError) as caught:
            RegistrarIntake.from_dict(value)
        assert caught.value.code == "registrar_intake_forbidden_field"


def test_foreign_pin_rejects_copied_schema_body():
    value = valid_foreign_pin()
    value.pop("pin_digest")
    value["schema_body"] = {"type": "object"}

    with pytest.raises(RALValidationError) as caught:
        ForeignSchemaPin.from_dict(value)

    assert caught.value.code == "schema_invalid"


def test_policy_cannot_enable_forbidden_capabilities():
    value = valid_policy()
    capabilities = copy.deepcopy(value["capabilities"])
    capabilities["production_mutation"] = True
    value = valid_policy(capabilities=capabilities)

    with pytest.raises(RALValidationError) as caught:
        OperationsPolicy.from_dict(value)

    assert caught.value.code == "operations_policy_forbidden_capability"


def test_read_only_request_may_omit_authority_and_checkpoint():
    value = valid_operation_request(
        operation_kind="inspect",
        application_digest=None,
        target_ref=None,
        authority_artifact_ref=None,
        authority_artifact_digest=None,
        expected_ledger_head=None,
        checkpoint_evidence_ref=None,
        checkpoint_evidence_digest=None,
        foreign_evidence_pins=[],
    )

    parsed = OperationRequest.from_dict(value)

    assert parsed.to_dict()["operation_kind"] == "inspect"


SCHEMAS = (
    "registrar-operations-manifest.schema.json",
    "registrar-operations-policy.schema.json",
    "registrar-intake.schema.json",
    "registrar-operator-observation.schema.json",
    "registrar-operation-request.schema.json",
    "registrar-operation-receipt.schema.json",
    "foreign-schema-pin.schema.json",
)


@pytest.mark.parametrize("name", SCHEMAS)
def test_operations_schema_assets_are_strict_and_stably_identified(name):
    schema = load_schema(name)
    assert schema["$id"] == ("https://evemisslab.com/schemas/sedb-ral/" + name)
    assert schema["additionalProperties"] is False


def test_schema_validation_rejects_unknown_receipt_field():
    value = valid_operation_receipt()
    value["transport_delivery_state"] = "acknowledged"

    with pytest.raises(RALValidationError) as caught:
        validate_contract("registrar-operation-receipt.schema.json", value)

    assert caught.value.code == "schema_invalid"
