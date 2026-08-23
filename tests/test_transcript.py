import copy

import pytest

from sedb_ral.errors import RALValidationError
from sedb_ral.transcript import (
    render_turn,
    resolve_speaker_label,
    validate_transcript_bindings,
)

TIME = "ctcl:instant:3a40eb8b-121f-4c6a-b66f-b28db4740fb4"


def binding(label, identifier, kind, token):
    return {
        "label": label,
        "bound_identifier": identifier,
        "identifier_kind": kind,
        "bound_at_ref": TIME,
        "scope": "transcript",
        "rebinds": None,
        "visual_token": token,
        "visual_scope": "transcript",
        "palette_version": "eml-palette-1",
        "contrast_standard": "WCAG-2.2-SC-1.4.11>=3:1",
        "verified_backgrounds": [],
        "deficiency_set": ["protanopia", "deuteranopia", "tritanopia"],
        "accessibility_verification_status": "unmeasured",
    }


TRANSCRIPT = {
    "schema_version": "0.1",
    "transcript_id": "transcript:test:1",
    "bindings": [
        binding("Neo.K", "principal:neo.k", "principal", "amber-1"),
        binding(
            "準繩",
            "session:6d613942-d7d1-47b8-b0f3-e485e15db60f",
            "session_uuid",
            "purple-1",
        ),
        binding(
            "織域",
            "codex-thread:019fe51e-9276-7f63-8c16-414624b7fa9d",
            "codex_thread",
            "blue-1",
        ),
    ],
    "turns": [
        {
            "turn_id": "turn:test:1",
            "speaker_label": "織域",
            "body": "hello",
            "relay": None,
        },
        {
            "turn_id": "turn:test:relay",
            "speaker_label": "織域",
            "body": "relayed body",
            "relay": {
                "relayed_by": "codex-thread:019fe51e-9276-7f63-8c16-414624b7fa9d",
                "relay_is_authorship": False,
                "original_claimed_author": "準繩",
                "observed_origin": None,
            },
        },
    ],
}


def test_transcript_binding_contract_and_unique_population():
    validate_transcript_bindings(TRANSCRIPT)


def test_plaintext_turn_has_no_bare_color_token():
    assert render_turn(TRANSCRIPT, "turn:test:1", rich=False) == "織域: hello"


def test_rich_turn_keeps_swatch_separate_from_serialized_label():
    assert render_turn(TRANSCRIPT, "turn:test:1", rich=True) == (
        '<span class="speaker-swatch" data-token="blue-1"></span>'
        '<span class="speaker-label">織域:</span> hello'
    )


def test_rich_renderer_escapes_label_token_and_body():
    unsafe = copy.deepcopy(TRANSCRIPT)
    unsafe["bindings"][2]["label"] = "<script>"
    unsafe["bindings"][2]["visual_token"] = "blue-unsafe"
    unsafe["turns"][0]["speaker_label"] = "<script>"
    unsafe["turns"][0]["body"] = "<b>body</b>"
    unsafe["turns"][1]["speaker_label"] = "<script>"
    output = render_turn(unsafe, "turn:test:1", rich=True)
    assert "<script>" not in output
    assert "<b>body</b>" not in output
    assert "&lt;b&gt;body&lt;/b&gt;" in output


def test_visual_token_must_be_unique_in_transcript():
    value = copy.deepcopy(TRANSCRIPT)
    value["bindings"][1]["visual_token"] = "blue-1"
    with pytest.raises(RALValidationError, match="visual_token_collision"):
        validate_transcript_bindings(value)


def test_visual_scope_cannot_escape_transcript():
    value = copy.deepcopy(TRANSCRIPT)
    value["bindings"][0]["visual_scope"] = "global"
    with pytest.raises(RALValidationError, match="schema_invalid"):
        validate_transcript_bindings(value)


def test_missing_header_or_unbound_label_is_indeterminate():
    assert resolve_speaker_label(None, "準繩").status == "indeterminate"
    assert resolve_speaker_label(TRANSCRIPT, "unknown").status == "indeterminate"
    resolved = resolve_speaker_label(TRANSCRIPT, "準繩")
    assert resolved.status == "resolved"
    assert resolved.bound_identifier.startswith("session:6d613942")


def test_renderer_rejects_standalone_binding_as_membership_proof():
    with pytest.raises(RALValidationError, match="schema_invalid"):
        render_turn(TRANSCRIPT["bindings"][2], "turn:test:1", rich=False)


def test_unbound_turn_label_fails_rendering():
    value = copy.deepcopy(TRANSCRIPT)
    value["turns"][0]["speaker_label"] = "unbound"

    with pytest.raises(RALValidationError, match="speaker_resolution_indeterminate"):
        render_turn(value, "turn:test:1", rich=False)


def test_newline_label_and_copied_header_missing_turn_red():
    newline = copy.deepcopy(TRANSCRIPT)
    newline["bindings"][2]["label"] = "織域\n偽造"
    newline["turns"][0]["speaker_label"] = "織域\n偽造"
    with pytest.raises(RALValidationError, match="schema_invalid"):
        render_turn(newline, "turn:test:1", rich=False)

    copied_without_header = {
        "schema_version": "0.1",
        "transcript_id": "transcript:test:copy",
        "turns": copy.deepcopy(TRANSCRIPT["turns"]),
    }
    with pytest.raises(RALValidationError, match="schema_invalid"):
        render_turn(copied_without_header, "turn:test:1", rich=False)


def test_unobserved_relay_is_explicit_and_uses_actual_speaker_visual_cue():
    output = render_turn(TRANSCRIPT, "turn:test:relay", rich=True)

    assert 'data-token="blue-1"' in output
    assert "purple-1" not in output
    assert "準繩" not in output
    assert TRANSCRIPT["turns"][1]["relay"] == {
        "relayed_by": "codex-thread:019fe51e-9276-7f63-8c16-414624b7fa9d",
        "relay_is_authorship": False,
        "original_claimed_author": "準繩",
        "observed_origin": None,
    }

    missing_origin = copy.deepcopy(TRANSCRIPT)
    del missing_origin["turns"][1]["relay"]["observed_origin"]
    with pytest.raises(RALValidationError, match="schema_invalid"):
        render_turn(missing_origin, "turn:test:relay", rich=True)
