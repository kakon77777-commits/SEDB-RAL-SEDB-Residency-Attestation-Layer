import copy

import pytest

from sedb_ral.canonical import sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.registration import RegistrationIds, prepare_registration

TIME = "ctcl:instant:test-registration"

IDS = RegistrationIds(
    prepared_id="prepared:7b5a4b15",
    application_id="application:42ce0eb1",
    resident_id="resident:75c9559e",
    instance_id="instance:bb68ace7",
    continuity_line_id="line:cb6d31e7",
    address_ids=("address:codex-thread:79b497c5",),
    claim_ids=(
        "claim:display:81f5895d",
        "claim:role:10757453",
        "claim:line:b2fc8d91",
    ),
)


def valid_claim(**changes):
    value = {
        "schema": "sedb-ral.self-application-claim/0.1",
        "applicant_claim_only": True,
        "desired_display_label": "Synthetic Resident",
        "existing_resident_claim": None,
        "continuity_claim": "new",
        "desired_addresses": [
            {
                "namespace": "codex_thread",
                "identifier_kind": "codex_thread",
                "locator": "thread:test-alpha",
            }
        ],
        "role_description_claim": "Synthetic registration tester",
        "dissent_or_limits": ["No private access"],
        "opt_in": True,
        "relay_is_authorship": False,
        "not_claimed": [
            "verified_identity",
            "registrar_authority",
            "private_access",
        ],
    }
    value.update(changes)
    return value


def valid_host_observation(**changes):
    value = {
        "schema": "sedb-ral.registration-host-observation/0.1",
        "observation_id": "observation:test-alpha",
        "provider": "openai",
        "adapter_kind": "codex_app_task_tool",
        "identifier_kind": "codex_thread",
        "native_thread_id": "thread:test-alpha",
        "native_session_id": None,
        "native_turn_id": "turn:test-alpha",
        "unavailable_fields": [
            {
                "field": "native_session_id",
                "reason": (
                    "structurally_unavailable_from_codex_app_task_tool"
                ),
            }
        ],
        "observed_origin": "host:codex-app-thread-tools",
        "observed_at_ref": TIME,
        "applicant_item_ref": "item:test-alpha",
        "not_claimed": ["pre_turn_output_enforcement"],
    }
    value.update(changes)
    return value


def test_P3_001_opted_in_claim_and_exact_host_thread_prepare_application():
    prepared = prepare_registration(
        valid_claim(), valid_host_observation(), IDS
    )

    assert prepared.application["claimed_resident_id"] == IDS.resident_id
    assert (
        prepared.application["instance_claims"][0]["instance_id"]
        == IDS.instance_id
    )
    assert (
        prepared.application["addresses"][0]["locator"]
        == "thread:test-alpha"
    )
    assert prepared.host_observation["native_session_id"] is None
    assert prepared.host_observation["unavailable_fields"] == [
        {
            "field": "native_session_id",
            "reason": "structurally_unavailable_from_codex_app_task_tool",
        }
    ]
    assert (
        prepared.application["claims"][2]["object"]
        == IDS.continuity_line_id
    )
    assert prepared.application_digest == sha256_ref(prepared.application)
    assert prepared.digest == prepared.preparation_digest
    assert prepared.to_dict()["preparation_digest"] == prepared.digest


def test_P3_002_opt_out_refuses_before_preparation():
    with pytest.raises(RALValidationError, match="applicant_opt_out"):
        prepare_registration(
            valid_claim(opt_in=False), valid_host_observation(), IDS
        )


def test_P3_003_claimed_address_must_equal_host_observed_thread():
    claim = valid_claim()
    claim["desired_addresses"][0]["locator"] = "thread:other"
    with pytest.raises(
        RALValidationError, match="applicant_address_host_mismatch"
    ):
        prepare_registration(claim, valid_host_observation(), IDS)


@pytest.mark.parametrize(
    "claim_change",
    [
        {"schema": "sedb-ral.self-application-claim/9.9"},
        {"applicant_claim_only": False},
        {"relay_is_authorship": True},
    ],
)
def test_P3_004_claim_contract_rejects_identity_or_authorship_promotion(
    claim_change,
):
    with pytest.raises(RALValidationError, match="schema_invalid"):
        prepare_registration(
            valid_claim(**claim_change), valid_host_observation(), IDS
        )


@pytest.mark.parametrize(
    ("host_change", "code"),
    [
        ({"applicant_item_ref": ""}, "schema_invalid"),
        ({"observed_origin": "model:self-report"}, "schema_invalid"),
        (
            {"schema": "sedb-ral.registration-host-observation/9.9"},
            "schema_invalid",
        ),
    ],
)
def test_P3_005_host_observation_requires_canonical_item_and_host_origin(
    host_change, code
):
    with pytest.raises(RALValidationError, match=code):
        prepare_registration(
            valid_claim(), valid_host_observation(**host_change), IDS
        )


@pytest.mark.parametrize(
    "ids",
    [
        RegistrationIds(
            prepared_id=IDS.prepared_id,
            application_id=IDS.prepared_id,
            resident_id=IDS.resident_id,
            instance_id=IDS.instance_id,
            continuity_line_id=IDS.continuity_line_id,
            address_ids=IDS.address_ids,
            claim_ids=IDS.claim_ids,
        ),
        RegistrationIds(
            prepared_id=IDS.prepared_id,
            application_id=IDS.application_id,
            resident_id=IDS.resident_id,
            instance_id=IDS.instance_id,
            continuity_line_id=IDS.continuity_line_id,
            address_ids=(),
            claim_ids=IDS.claim_ids,
        ),
        RegistrationIds(
            prepared_id=IDS.prepared_id,
            application_id=IDS.application_id,
            resident_id=IDS.resident_id,
            instance_id=IDS.instance_id,
            continuity_line_id=IDS.continuity_line_id,
            address_ids=IDS.address_ids,
            claim_ids=IDS.claim_ids[:2],
        ),
    ],
)
def test_P3_006_preparation_rejects_duplicate_or_wrong_id_counts(ids):
    with pytest.raises(RALValidationError, match="registration_ids_invalid"):
        prepare_registration(valid_claim(), valid_host_observation(), ids)


def test_P3_007_prepared_ids_must_not_embed_the_display_label():
    ids = RegistrationIds(
        prepared_id=IDS.prepared_id,
        application_id="application:synthetic-resident",
        resident_id=IDS.resident_id,
        instance_id=IDS.instance_id,
        continuity_line_id=IDS.continuity_line_id,
        address_ids=IDS.address_ids,
        claim_ids=IDS.claim_ids,
    )
    with pytest.raises(RALValidationError, match="registration_id_not_opaque"):
        prepare_registration(valid_claim(), valid_host_observation(), ids)


@pytest.mark.parametrize(
    "host_change",
    [
        {"native_session_id": "session:model-supplied"},
        {"unavailable_fields": []},
        {
            "unavailable_fields": [
                {
                    "field": "native_session_id",
                    "reason": "unknown",
                }
            ]
        },
    ],
)
def test_P3_008_task_tool_profile_preserves_session_unavailability(
    host_change,
):
    with pytest.raises(RALValidationError, match="schema_invalid"):
        prepare_registration(
            valid_claim(), valid_host_observation(**host_change), IDS
        )


def test_prepare_does_not_mutate_inputs():
    claim = valid_claim()
    host = valid_host_observation()
    claim_before = copy.deepcopy(claim)
    host_before = copy.deepcopy(host)

    prepare_registration(claim, host, IDS)

    assert claim == claim_before
    assert host == host_before
