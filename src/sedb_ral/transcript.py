from __future__ import annotations

import html
from collections.abc import Mapping
from dataclasses import dataclass

from .canonical import canonical_bytes, loads_strict
from .contracts import validate_contract
from .errors import RALValidationError


@dataclass(frozen=True)
class SpeakerResolution:
    status: str
    label: str
    bound_identifier: str | None
    identifier_kind: str | None


def _canonical_object(value: Mapping[str, object]) -> dict[str, object]:
    normalized = loads_strict(canonical_bytes(value).decode("utf-8"))
    if not isinstance(normalized, dict):
        raise RALValidationError(
            "transcript_not_object", "transcript must remain an object"
        )
    return normalized


def validate_transcript_bindings(value: Mapping[str, object]) -> None:
    value = _canonical_object(value)
    validate_contract("transcript-binding.schema.json", value)
    bindings = value["bindings"]
    labels = [item["label"] for item in bindings]
    identifiers = [item["bound_identifier"] for item in bindings]
    tokens = [
        item["visual_token"]
        for item in bindings
        if item["visual_token"] is not None
    ]
    if len(labels) != len(set(labels)):
        raise RALValidationError("speaker_label_collision", "duplicate label")
    if len(identifiers) != len(set(identifiers)):
        raise RALValidationError(
            "bound_identifier_collision", "identifier has two active labels"
        )
    if len(tokens) != len(set(tokens)):
        raise RALValidationError(
            "visual_token_collision", "visual token collides in transcript"
        )
    label_set = set(labels)
    if any(
        item["rebinds"] is not None and item["rebinds"] not in label_set
        for item in bindings
    ):
        raise RALValidationError(
            "rebind_target_missing", "rebind target is not declared"
        )
    turns = value["turns"]
    turn_ids = [item["turn_id"] for item in turns]
    if len(turn_ids) != len(set(turn_ids)):
        raise RALValidationError("turn_id_duplicate", "duplicate turn ID")
    binding_by_label = {item["label"]: item for item in bindings}
    for turn in turns:
        binding = binding_by_label.get(turn["speaker_label"])
        if binding is None:
            raise RALValidationError(
                "speaker_resolution_indeterminate",
                "turn speaker is not bound in this transcript",
            )
        relay = turn["relay"]
        if relay is not None and relay["relayed_by"] != binding["bound_identifier"]:
            raise RALValidationError(
                "relay_speaker_mismatch",
                "relay provenance does not identify the actual speaker binding",
            )


def resolve_speaker_label(
    transcript: Mapping[str, object] | None,
    label: str,
) -> SpeakerResolution:
    if transcript is None:
        return SpeakerResolution("indeterminate", label, None, None)
    validate_transcript_bindings(transcript)
    for binding in transcript["bindings"]:
        if binding["label"] == label:
            return SpeakerResolution(
                "resolved",
                label,
                binding["bound_identifier"],
                binding["identifier_kind"],
            )
    return SpeakerResolution("indeterminate", label, None, None)


def render_turn(
    transcript: Mapping[str, object],
    turn_id: str,
    *,
    rich: bool,
) -> str:
    transcript = _canonical_object(transcript)
    validate_transcript_bindings(transcript)
    turn = next(
        (item for item in transcript["turns"] if item["turn_id"] == turn_id),
        None,
    )
    if turn is None:
        raise RALValidationError("turn_not_found", str(turn_id))
    binding = next(
        item
        for item in transcript["bindings"]
        if item["label"] == turn["speaker_label"]
    )
    label = str(binding["label"])
    body = str(turn["body"])
    if not rich:
        return f"{label}: {body}"
    escaped_label = html.escape(label, quote=True)
    escaped_body = html.escape(body, quote=True)
    token = binding.get("visual_token")
    swatch = ""
    if token is not None:
        swatch = (
            '<span class="speaker-swatch" data-token="'
            + html.escape(str(token), quote=True)
            + '"></span>'
        )
    return (
        swatch
        + f'<span class="speaker-label">{escaped_label}:</span> '
        + escaped_body
    )
