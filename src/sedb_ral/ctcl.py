from __future__ import annotations

import calendar
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .contracts import validate_contract
from .errors import RALValidationError

_RFC3339_UTC = re.compile(
    r"^(?P<base>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.(?P<fraction>[0-9]{1,9}))?Z$"
)


def _rfc3339_to_ns(value: str) -> int:
    match = _RFC3339_UTC.fullmatch(value)
    if match is None:
        raise RALValidationError("encoding_mismatch", "invalid UTC rfc3339")
    try:
        base = datetime.strptime(match.group("base"), "%Y-%m-%dT%H:%M:%S")
    except ValueError as error:
        raise RALValidationError(
            "encoding_mismatch", "invalid UTC rfc3339"
        ) from error
    fraction = (match.group("fraction") or "").ljust(9, "0")
    return calendar.timegm(base.timetuple()) * 1_000_000_000 + int(
        fraction or "0"
    )


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
            "unverified",
            "verified",
            "unknown_instant",
            "unavailable",
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
        if value["service_returned_share_url"] is None:
            raise RALValidationError(
                "anchor_share_url_missing",
                "registered anchor must carry the service-returned locator",
            )
    encodings = value["encodings"]
    ns = int(encodings["unix_ns"])
    try:
        seconds_ns = Decimal(encodings["unix_s"]) * Decimal(1_000_000_000)
    except InvalidOperation as error:
        raise RALValidationError(
            "encoding_mismatch", "unix_s is not a decimal"
        ) from error
    consistent = (
        int(encodings["unix_ms"]) * 1_000_000 == ns
        and int(encodings["unix_us"]) * 1_000 == ns
        and seconds_ns == Decimal(ns)
        and _rfc3339_to_ns(encodings["rfc3339"]) == ns
        and _rfc3339_to_ns(value["reference"]["value"]) == ns
    )
    if not consistent:
        raise RALValidationError(
            "encoding_mismatch", "CTCL time encodings disagree"
        )
