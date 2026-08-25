import copy
import hashlib
import json
from pathlib import Path

import pytest

from sedb_ral.canonical import canonical_bytes
from sedb_ral.errors import RALValidationError
from sedb_ral.limen_public_view import (
    build_limen_public_view,
    limen_contract_digest,
)
from sedb_ral.projection import RegistryProjection

ROOT = Path(__file__).parents[1]
HEAD = "sha256:sedb-ral-chain-v1:" + "a" * 64


def instance(resident_id, suffix="001"):
    return {
        "schema_version": "0.1",
        "instance_id": f"instance:{resident_id}:{suffix}",
        "resident_ref": resident_id,
        "runtime_tag": "runtime:codex-app",
        "started_time_ref": "ctcl:instant:test",
        "ended_time_ref": None,
    }


def line_claim(resident_id, instance_id, line_id, suffix="1"):
    return {
        "schema_version": "0.1",
        "claim_id": f"claim:{resident_id}:line:{suffix}",
        "claimant_ref": resident_id,
        "subject_ref": resident_id,
        "predicate": "continuity_line_id",
        "object": line_id,
        "claimed_time": "ctcl:instant:test",
        "claimed_authored_by_instance": instance_id,
        "claimed_on_behalf_of_line": None,
    }


def address(
    resident_id,
    *,
    suffix="thread",
    locator=None,
    adapter_kind="codex_app_task_tool",
    status="active",
):
    return {
        "schema_version": "0.1",
        "address_id": f"address:{resident_id}:{suffix}",
        "namespace": "codex_thread",
        "adapter_kind": adapter_kind,
        "locator": locator or f"thread:{resident_id}",
        "target_ref": resident_id,
        "status": status,
    }


def resident(
    resident_id="resident:test-alpha",
    *,
    label="Test Alpha",
    locator="thread:test-alpha",
    resident_status="active",
    address_status="active",
    adapter_kind="codex_app_task_tool",
    instance_count=1,
    line_ids=("line:test-alpha",),
    address_id_suffix="thread",
):
    instances = [
        instance(resident_id, f"{index + 1:03d}")
        for index in range(instance_count)
    ]
    claims = (
        []
        if not instances
        else [
            line_claim(
                resident_id,
                instances[0]["instance_id"],
                line_id,
                str(index + 1),
            )
            for index, line_id in enumerate(line_ids)
        ]
    )
    return {
        "schema_version": "0.1",
        "resident_id": resident_id,
        "display_label": label,
        "status": resident_status,
        "application_ref": f"application:{resident_id}",
        "identifier_refs": [],
        "instances": instances,
        "addresses": [
            address(
                resident_id,
                suffix=address_id_suffix,
                locator=locator,
                adapter_kind=adapter_kind,
                status=address_status,
            )
        ],
        "claims": claims,
    }


def projection(*residents, unapplied=()):
    residents = tuple(sorted(residents, key=lambda item: item["resident_id"]))
    resident_map = {item["resident_id"]: item for item in residents}
    event_ids = tuple(
        f"evt_resident_registered_{index + 1:03d}"
        for index in range(len(residents))
    )
    resident_sources = {
        item["resident_id"]: event_ids[index]
        for index, item in enumerate(residents)
    }
    claims = {
        claim["claim_id"]: claim
        for item in residents
        for claim in item["claims"]
    }
    applications = {
        item["application_ref"]: {
            "application_id": item["application_ref"],
            "claimed_resident_id": item["resident_id"],
            "status": "accepted",
            "authority_ref": f"authority:{item['resident_id']}",
            "authority_digest": (
                "sha256:sedb-ral-json-nfc-codepoint-v1:" + "b" * 64
            ),
            "authority_grant_event_id": f"evt_authority:{item['resident_id']}",
        }
        for item in residents
    }
    return RegistryProjection(
        applications=applications,
        residents=resident_map,
        directory={
            item["resident_id"]: {
                "display_label": item["display_label"],
                "status": item["status"],
                "addresses": copy.deepcopy(item["addresses"]),
                "instance_refs": [
                    value["instance_id"] for value in item["instances"]
                ],
            }
            for item in residents
        },
        claims=claims,
        resident_source_event_ids=resident_sources,
        applied_corrections=(),
        unapplied_event_ids=tuple(unapplied),
        unapplied_reasons={item: "synthetic_unapplied" for item in unapplied},
        source_event_ids=event_ids,
    )


def export(*residents):
    return build_limen_public_view(
        projection(*residents),
        ledger_head=HEAD,
        sequence=max(1, len(residents)),
    )


def conflict_codes(view):
    return [item["error_code"] for item in view["projection_conflicts"]]


def nested_keys(value):
    if isinstance(value, dict):
        return set(value).union(
            *(nested_keys(item) for item in value.values())
        )
    if isinstance(value, list):
        return set().union(*(nested_keys(item) for item in value))
    return set()


def test_L6A_001_exact_registered_thread_exports_one_public_binding():
    view = export(resident()).to_dict()

    assert len(view["bindings"]) == 1
    binding = view["bindings"][0]
    assert binding["native_thread_id"] == "thread:test-alpha"
    assert binding["resident_id"] == "resident:test-alpha"
    assert binding["instance_id"] == "instance:resident:test-alpha:001"
    assert binding["continuity_line_id"] == "line:test-alpha"
    assert binding["identifier_components"] == ["native_thread_id"]
    assert binding["native_session_id"] is None
    assert binding["source_refs"] == [
        "address:resident:test-alpha:thread",
        "application:resident:test-alpha",
        "evt_resident_registered_001",
    ]


def test_L6A_003_active_thread_collision_emits_conflict_and_no_binding():
    first = resident(locator="thread:test-shared")
    second = resident(
        "resident:test-beta",
        label="Test Beta",
        locator="thread:test-shared",
        line_ids=("line:test-beta",),
    )

    view = export(first, second).to_dict()

    assert view["bindings"] == []
    assert conflict_codes(view) == ["address_binding_conflict"]
    conflict = view["projection_conflicts"][0]
    assert conflict["binding_refs"] == [
        "address:resident:test-alpha:thread",
        "address:resident:test-beta:thread",
    ]
    assert "resident_id" not in conflict


def test_homonymous_labels_do_not_collide_when_threads_are_distinct():
    first = resident(label="Same Label")
    second = resident(
        "resident:test-beta",
        label="Same Label",
        locator="thread:test-beta",
        line_ids=("line:test-beta",),
    )

    view = export(first, second).to_dict()

    assert conflict_codes(view) == []
    assert [item["resident_id"] for item in view["bindings"]] == [
        "resident:test-alpha",
        "resident:test-beta",
    ]


def test_exporter_never_selects_one_instance_from_an_ambiguous_resident():
    view = export(resident(instance_count=2)).to_dict()

    assert view["bindings"] == []
    assert conflict_codes(view) == ["instance_binding_ambiguous"]


def test_missing_or_ambiguous_continuity_line_is_a_public_conflict():
    missing = export(resident(line_ids=())).to_dict()
    ambiguous = export(
        resident(line_ids=("line:test-alpha", "line:test-other"))
    ).to_dict()

    assert conflict_codes(missing) == ["continuity_line_missing"]
    assert conflict_codes(ambiguous) == ["continuity_line_ambiguous"]
    assert missing["bindings"] == []
    assert ambiguous["bindings"] == []


@pytest.mark.parametrize(
    ("source_status", "exported_status"),
    [("suspended", "suspended"), ("revoked", "tombstoned")],
)
def test_inactive_address_is_exported_only_as_nonactive_status(
    source_status, exported_status
):
    view = export(resident(address_status=source_status)).to_dict()

    assert view["bindings"][0]["status"] == exported_status


@pytest.mark.parametrize(
    ("resident_status", "exported_status"),
    [("suspended", "suspended"), ("withdrawn", "withdrawn"),
     ("tombstoned", "tombstoned")],
)
def test_inactive_resident_status_overrides_active_address(
    resident_status, exported_status
):
    view = export(resident(resident_status=resident_status)).to_dict()

    assert view["bindings"][0]["status"] == exported_status


def test_app_server_address_without_canonical_session_is_not_exported():
    view = export(resident(adapter_kind="codex_app_server")).to_dict()

    assert view["bindings"] == []
    assert conflict_codes(view) == ["adapter_profile_unsupported"]


def test_duplicate_address_id_with_different_locator_is_source_conflict():
    first = resident(locator="thread:test-alpha")
    second = resident(
        "resident:test-beta",
        locator="thread:test-beta",
        line_ids=("line:test-beta",),
    )
    second["addresses"][0]["address_id"] = first["addresses"][0][
        "address_id"
    ]

    view = export(first, second).to_dict()

    assert view["bindings"] == []
    assert conflict_codes(view) == ["binding_source_invalid"]


def test_repeated_export_is_byte_identical_and_order_independent():
    first = resident()
    second = resident(
        "resident:test-beta",
        label="Test Beta",
        locator="thread:test-beta",
        line_ids=("line:test-beta",),
    )

    left = export(first, second)
    right = export(second, first)

    assert canonical_bytes(left.to_dict()) == canonical_bytes(right.to_dict())
    assert left.digest == right.digest
    assert left.to_dict()["view_id"] == right.to_dict()["view_id"]


def test_view_contains_no_applicant_host_private_or_model_fields():
    value = export(resident()).to_dict()
    keys = nested_keys(value)

    for forbidden in (
        "applicant_claim",
        "host_observation",
        "native_turn_id",
        "private_root",
        "principal_ref",
        "model_id",
        "role_description",
    ):
        assert forbidden not in keys
    assert "private-root:" not in json.dumps(value, sort_keys=True)


def test_unapplied_projection_is_refused_instead_of_partially_exported():
    dirty = projection(resident(), unapplied=("evt_future_test",))

    with pytest.raises(RALValidationError, match="projection_unapplied_events"):
        build_limen_public_view(dirty, ledger_head=HEAD, sequence=1)


def test_packaged_contract_digest_is_raw_schema_sha256():
    expected = hashlib.sha256(
        (ROOT / "src/sedb_ral/schemas/limen-ral-view-v0.2.schema.json")
        .read_bytes()
    ).hexdigest()

    assert limen_contract_digest() == expected
