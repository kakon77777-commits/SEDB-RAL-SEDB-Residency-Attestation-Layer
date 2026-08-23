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
    binding: Mapping[str, object],
    body: str,
    *,
    rich: bool,
) -> str:
    label = str(binding["label"])
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
