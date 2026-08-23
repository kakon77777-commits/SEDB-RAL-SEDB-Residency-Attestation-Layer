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
    encodings = value["encodings"]
    if int(encodings["unix_ns"]) != int(encodings["unix_ms"]) * 1_000_000:
        raise RALValidationError(
            "encoding_mismatch", "unix_ms and unix_ns disagree"
        )
