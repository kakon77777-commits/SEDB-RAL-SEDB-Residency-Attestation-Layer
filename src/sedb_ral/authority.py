from __future__ import annotations

from collections.abc import Mapping

from .contracts import validate_contract


def validate_authority(value: Mapping[str, object]) -> None:
    validate_contract("authority-envelope.schema.json", value)


def authority_matches_subject(
    authority: Mapping[str, object],
    *,
    application_digest: str,
    resident_id: str,
) -> bool:
    kind = authority["subject_kind"]
    subject = authority["subject_ref"]
    return (
        kind == "application_digest" and subject == application_digest
    ) or (kind == "resident_id" and subject == resident_id)
