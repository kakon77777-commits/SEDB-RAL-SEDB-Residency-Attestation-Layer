from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .contracts import default_schema_root, validate_contract
from .errors import RALValidationError
from .projection import RegistryProjection, continuity_line_for

_SCHEMA_NAME = "limen-ral-view-v0.2.schema.json"
_NOT_CLAIMED = (
    "private_access",
    "host_observation",
    "host_enforcement",
    "registry_authority",
    "identity_merge",
)
_ADDRESS_STATUS = {
    "active": "active",
    "suspended": "suspended",
    "revoked": "tombstoned",
    "unknown": "suspended",
}
_RESIDENT_STATUS = {
    "active": None,
    "suspended": "suspended",
    "withdrawn": "withdrawn",
    "tombstoned": "tombstoned",
}


def _canonical_object(value: object) -> dict[str, object]:
    normalized = loads_strict(canonical_bytes(value).decode("utf-8"))
    if not isinstance(normalized, dict):
        raise TypeError("public view must remain a JSON object")
    return normalized


def limen_contract_digest() -> str:
    return hashlib.sha256(
        (default_schema_root() / _SCHEMA_NAME).read_bytes()
    ).hexdigest()


@dataclass(frozen=True)
class LimenPublicView:
    value: dict[str, object]
    digest: str

    def to_dict(self) -> dict[str, object]:
        return _canonical_object(self.value)


def _conflict(
    *,
    error_code: str,
    namespace: str,
    locator: str,
    binding_refs: list[str] | tuple[str, ...],
    source_refs: list[str] | tuple[str, ...],
) -> dict[str, object]:
    body = {
        "error_code": error_code,
        "namespace": namespace,
        "locator": locator,
        "binding_refs": sorted(set(binding_refs)),
        "source_refs": sorted(set(source_refs)),
    }
    suffix = sha256_ref(body).rsplit(":", 1)[-1][:24]
    return {"conflict_id": f"conflict:{suffix}", **body}


def _authority_head(projection: RegistryProjection) -> str:
    authorities = []
    for application_id, application in sorted(
        projection.applications.items()
    ):
        if application.get("status") != "accepted":
            continue
        authorities.append(
            {
                "application_id": application_id,
                "authority_ref": application.get("authority_ref"),
                "authority_digest": application.get("authority_digest"),
                "authority_grant_event_id": application.get(
                    "authority_grant_event_id"
                ),
            }
        )
    return sha256_ref(
        {
            "kind": "sedb-ral-public-authority-projection",
            "authorities": authorities,
        }
    )


def _binding_status(
    resident: Mapping[str, object], address: Mapping[str, object]
) -> str:
    resident_status = _RESIDENT_STATUS.get(str(resident.get("status")))
    if resident_status is not None:
        return resident_status
    return _ADDRESS_STATUS.get(str(address.get("status")), "suspended")


def _source_sequence(
    projection: RegistryProjection, event_id: str | None
) -> int | None:
    if event_id is None:
        return None
    try:
        return projection.source_event_ids.index(event_id) + 1
    except ValueError:
        return None


def build_limen_public_view(
    projection: RegistryProjection,
    *,
    ledger_head: str,
    sequence: int,
) -> LimenPublicView:
    if projection.unapplied_event_ids:
        raise RALValidationError(
            "projection_unapplied_events",
            "public export requires a fully applied registry projection",
        )
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise RALValidationError(
            "public_view_sequence_invalid", "sequence must be positive"
        )

    entries: list[dict[str, object]] = []
    for resident_id, resident in sorted(projection.residents.items()):
        event_id = projection.resident_source_event_ids.get(resident_id)
        valid_from = _source_sequence(projection, event_id)
        for address in sorted(
            resident.get("addresses", ()),
            key=lambda item: str(item.get("address_id", "")),
        ):
            if address.get("namespace") != "codex_thread":
                continue
            entries.append(
                {
                    "resident_id": resident_id,
                    "resident": resident,
                    "address": address,
                    "event_id": event_id,
                    "valid_from": valid_from,
                    "status": _binding_status(resident, address),
                }
            )

    conflicts: list[dict[str, object]] = []
    blocked_address_ids: set[str] = set()
    by_address_id: dict[str, list[dict[str, object]]] = defaultdict(list)
    for entry in entries:
        address_id = str(entry["address"].get("address_id", ""))
        by_address_id[address_id].append(entry)
    for address_id, values in sorted(by_address_id.items()):
        if not address_id or len(values) == 1:
            continue
        blocked_address_ids.add(address_id)
        conflicts.append(
            _conflict(
                error_code="binding_source_invalid",
                namespace="codex_thread",
                locator=str(values[0]["address"].get("locator", "unknown")),
                binding_refs=[address_id],
                source_refs=[
                    str(item["event_id"] or f"missing-event:{item['resident_id']}")
                    for item in values
                ],
            )
        )

    active_by_locator: dict[tuple[str, str], list[dict[str, object]]] = (
        defaultdict(list)
    )
    for entry in entries:
        address = entry["address"]
        address_id = str(address.get("address_id", ""))
        if address_id in blocked_address_ids or entry["status"] != "active":
            continue
        active_by_locator[("codex_thread", str(address.get("locator", "")))].append(
            entry
        )
    for (namespace, locator), values in sorted(active_by_locator.items()):
        if len(values) < 2:
            continue
        address_ids = sorted(
            str(item["address"].get("address_id", "")) for item in values
        )
        blocked_address_ids.update(address_ids)
        conflicts.append(
            _conflict(
                error_code="address_binding_conflict",
                namespace=namespace,
                locator=locator,
                binding_refs=address_ids,
                source_refs=[str(item["event_id"]) for item in values],
            )
        )

    bindings: list[dict[str, object]] = []
    for entry in entries:
        resident = entry["resident"]
        address = entry["address"]
        resident_id = str(entry["resident_id"])
        address_id = str(address.get("address_id", ""))
        if address_id in blocked_address_ids:
            continue
        locator = str(address.get("locator", ""))
        event_id = entry["event_id"]
        conflict_sources = [
            address_id or f"missing-address:{resident_id}",
            str(event_id or f"missing-event:{resident_id}"),
        ]
        if address.get("adapter_kind") != "codex_app_task_tool":
            conflicts.append(
                _conflict(
                    error_code="adapter_profile_unsupported",
                    namespace="codex_thread",
                    locator=locator,
                    binding_refs=[address_id],
                    source_refs=conflict_sources,
                )
            )
            continue
        instances = resident.get("instances", ())
        if not isinstance(instances, list) or len(instances) != 1:
            conflicts.append(
                _conflict(
                    error_code="instance_binding_ambiguous",
                    namespace="codex_thread",
                    locator=locator,
                    binding_refs=[address_id],
                    source_refs=conflict_sources,
                )
            )
            continue
        try:
            line_id = continuity_line_for(resident_id, projection)
        except RALValidationError as error:
            if error.code != "continuity_line_ambiguous":
                raise
            conflicts.append(
                _conflict(
                    error_code="continuity_line_ambiguous",
                    namespace="codex_thread",
                    locator=locator,
                    binding_refs=[address_id],
                    source_refs=conflict_sources,
                )
            )
            continue
        if line_id is None:
            conflicts.append(
                _conflict(
                    error_code="continuity_line_missing",
                    namespace="codex_thread",
                    locator=locator,
                    binding_refs=[address_id],
                    source_refs=conflict_sources,
                )
            )
            continue
        valid_from = entry["valid_from"]
        if (
            not address_id
            or not locator
            or event_id is None
            or valid_from is None
        ):
            conflicts.append(
                _conflict(
                    error_code="binding_source_invalid",
                    namespace="codex_thread",
                    locator=locator or "unknown",
                    binding_refs=[address_id or f"missing-address:{resident_id}"],
                    source_refs=conflict_sources,
                )
            )
            continue
        instance_id = str(instances[0].get("instance_id", ""))
        application_ref = str(resident.get("application_ref", ""))
        bindings.append(
            {
                "binding_id": f"binding:address:{address_id}",
                "provider": "openai",
                "adapter_kind": "codex_app_task_tool",
                "identifier_kind": "codex_thread",
                "identifier_components": ["native_thread_id"],
                "native_thread_id": locator,
                "native_session_id": None,
                "session_match_policy": "not_applicable_for_profile",
                "resident_id": resident_id,
                "instance_id": instance_id,
                "continuity_line_id": line_id,
                "speaker_label": str(resident.get("display_label", "")),
                "status": entry["status"],
                "valid_from_sequence": valid_from,
                "valid_until_sequence": None,
                "lineage_from_thread_ids": [],
                "supersedes_binding_id": None,
                "source_refs": sorted(
                    {address_id, application_ref, str(event_id)}
                ),
            }
        )

    bindings.sort(key=lambda item: str(item["binding_id"]))
    conflicts.sort(key=lambda item: str(item["conflict_id"]))
    binding_head = sha256_ref(
        {
            "kind": "limen-public-binding-projection",
            "ledger_head": ledger_head,
            "bindings": bindings,
            "projection_conflicts": conflicts,
        }
    )
    view_seed = sha256_ref(
        {
            "schema": "limen.ral-view/0.2",
            "ledger_head": ledger_head,
            "binding_head": binding_head,
        }
    )
    value = _canonical_object(
        {
            "schema": "limen.ral-view/0.2",
            "profile": "sedb-ral/0.3.0",
            "view_id": f"ral-view:{view_seed.rsplit(':', 1)[-1][:24]}",
            "sequence": sequence,
            "authority_head": _authority_head(projection),
            "binding_head": binding_head,
            "ledger_head": ledger_head,
            "bindings": bindings,
            "projection_conflicts": conflicts,
            "source_refs": [
                ledger_head,
                *sorted(set(projection.resident_source_event_ids.values())),
            ],
            "not_claimed": list(_NOT_CLAIMED),
        }
    )
    validate_contract(_SCHEMA_NAME, value)
    return LimenPublicView(value=value, digest=sha256_ref(value))
