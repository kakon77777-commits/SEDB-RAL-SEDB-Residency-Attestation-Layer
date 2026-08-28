from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

import sedb_ral.registration_wave_context as context_module
from sedb_ral.canonical import canonical_bytes, sha256_ref
from sedb_ral.errors import RALValidationError
from sedb_ral.registration_wave_context import (
    SYNTHETIC_MARKER_NAME,
    SyntheticWaveExecutionContext,
    WaveEffectJournal,
    WaveExecutionMode,
)


def marker_value(ref: str = "fixture:wave-1") -> dict[str, object]:
    return {
        "schema": "sedb-ral.synthetic-wave-fixture-marker/0.1",
        "fixture_marker_ref": ref,
        "not_claimed": ["production_root", "real_applicant", "private_access"],
    }


def synthetic_context(
    tmp_path: Path,
    *,
    target_root: Path | None = None,
    forbidden_roots: tuple[Path, ...] = (),
    marker: dict[str, object] | None = None,
    journal: WaveEffectJournal | None = None,
) -> SyntheticWaveExecutionContext:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir(exist_ok=True)
    value = marker_value() if marker is None else marker
    (fixture_root / SYNTHETIC_MARKER_NAME).write_bytes(canonical_bytes(value))
    target = fixture_root / "wave" if target_root is None else target_root
    return SyntheticWaveExecutionContext.sealed(
        mode=WaveExecutionMode.SYNTHETIC_TEST,
        fixture_root=fixture_root,
        target_root=target,
        fixture_marker_ref=str(value["fixture_marker_ref"]),
        fixture_marker_digest=sha256_ref(value),
        forbidden_roots=forbidden_roots,
        journal=journal or WaveEffectJournal(),
    )


@pytest.mark.parametrize("suffix", ("", "child"))
def test_synthetic_context_rejects_production_root_before_domain_effect(
    tmp_path, suffix
):
    production = Path(r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL")
    target = production if not suffix else production / suffix
    journal = WaveEffectJournal()
    context = synthetic_context(
        tmp_path,
        target_root=target,
        forbidden_roots=(production,),
        journal=journal,
    )

    with pytest.raises(RALValidationError, match="synthetic_wave_boundary_refused"):
        context.verify_before_io("prepare", target)

    assert journal.nonzero_dimensions() == ()


@pytest.mark.parametrize(
    "forbidden",
    (
        Path(r"D:\AI_RESIDENCE\AI_HOME\00_RESIDENCE"),
        Path(r"D:\Ai\work together\SEDB-RAL"),
    ),
)
def test_private_and_git_roots_are_refused_before_domain_effect(tmp_path, forbidden):
    journal = WaveEffectJournal()
    context = synthetic_context(
        tmp_path,
        target_root=forbidden,
        forbidden_roots=(forbidden,),
        journal=journal,
    )

    with pytest.raises(RALValidationError, match="synthetic_wave_boundary_refused"):
        context.verify_before_io("prepare", forbidden)

    assert journal.nonzero_dimensions() == ()


def test_callers_cannot_label_production_as_synthetic(tmp_path):
    production = Path(r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL")
    context = synthetic_context(
        tmp_path,
        target_root=production,
        forbidden_roots=(production,),
    )

    with pytest.raises(RALValidationError, match="synthetic_wave_boundary_refused"):
        context.verify_before_io("policy_activate", production)


@pytest.mark.parametrize(
    "target",
    (
        Path(r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL\future-candidate"),
        Path(r"D:\AI_RESIDENCE\AI_HOME\sibling-private-candidate"),
        Path(r"D:\Ai\work together\SEDB-RAL\__r3bc_main_checkout_candidate__"),
    ),
)
def test_mandatory_roots_refuse_without_caller_supplied_boundaries_before_path_io(
    tmp_path, monkeypatch, target
):
    value = marker_value()
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    (fixture_root / SYNTHETIC_MARKER_NAME).write_bytes(canonical_bytes(value))
    journal = WaveEffectJournal()
    context = SyntheticWaveExecutionContext.sealed(
        mode=WaveExecutionMode.REAL_STAGING_CANDIDATE,
        fixture_root=fixture_root,
        target_root=target,
        fixture_marker_ref=str(value["fixture_marker_ref"]),
        fixture_marker_digest=sha256_ref(value),
        forbidden_roots=(),
        journal=journal,
    )

    def path_io_would_be_a_bug(path):
        raise AssertionError(f"boundary read occurred: {path}")

    monkeypatch.setattr(context_module, "_existing_path_chain", path_io_would_be_a_bug)

    with pytest.raises(RALValidationError, match="synthetic_wave_boundary_refused"):
        context.verify_before_io("prepare", target)
    assert journal.nonzero_dimensions() == ()


def test_ads_and_device_paths_are_refused(tmp_path):
    fixture = tmp_path / "fixture"
    for target in (
        Path(str(fixture / "wave") + ":hidden"),
        Path(r"\\server\share\wave"),
        Path(r"\\?\D:\synthetic\wave"),
    ):
        context = synthetic_context(tmp_path, target_root=target)
        with pytest.raises(RALValidationError, match="synthetic_wave_boundary_refused"):
            context.verify_before_io("prepare", target)


def test_valid_synthetic_context_verifies_marker_and_containment(tmp_path):
    context = synthetic_context(tmp_path)

    context.verify_before_io("prepare", context.target_root / "candidate.json")

    assert context.mode is WaveExecutionMode.SYNTHETIC_TEST
    assert context.journal.nonzero_dimensions() == ()


def test_tampered_context_digest_fails_before_domain_effect(tmp_path):
    context = synthetic_context(tmp_path)
    tampered = replace(context, context_digest=sha256_ref({"wrong": True}))

    with pytest.raises(RALValidationError, match="synthetic_wave_context_digest_mismatch"):
        tampered.verify_before_io("prepare", tampered.target_root)
    assert context.journal.nonzero_dimensions() == ()


def test_tampered_fixture_marker_fails_closed(tmp_path):
    context = synthetic_context(tmp_path)
    marker_path = context.fixture_root / SYNTHETIC_MARKER_NAME
    marker_path.write_bytes(canonical_bytes(marker_value("fixture:changed")))

    with pytest.raises(RALValidationError, match="synthetic_wave_marker_mismatch"):
        context.verify_before_io("prepare", context.target_root)
    assert context.journal.nonzero_dimensions() == ()


def test_reparse_alias_is_refused_when_supported(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    alias = fixture / "alias"
    try:
        os.symlink(outside, alias, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink unavailable: {error}")
    value = marker_value()
    (fixture / SYNTHETIC_MARKER_NAME).write_bytes(canonical_bytes(value))
    context = SyntheticWaveExecutionContext.sealed(
        mode=WaveExecutionMode.SYNTHETIC_TEST,
        fixture_root=fixture,
        target_root=alias,
        fixture_marker_ref=str(value["fixture_marker_ref"]),
        fixture_marker_digest=sha256_ref(value),
        forbidden_roots=(outside,),
        journal=WaveEffectJournal(),
    )

    with pytest.raises(RALValidationError, match="synthetic_wave_boundary_refused"):
        context.verify_before_io("prepare", alias)


def test_existing_hardlink_inside_target_is_refused_before_domain_effect(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    selected_context = synthetic_context(tmp_path)
    selected_context.target_root.mkdir()
    linked = selected_context.target_root / "linked.txt"
    os.link(outside, linked)

    with pytest.raises(RALValidationError, match="synthetic_wave_boundary_refused"):
        selected_context.verify_before_io("prepare", selected_context.target_root)

    assert linked.stat().st_nlink == 2
    assert selected_context.journal.nonzero_dimensions() == ()


def test_real_staging_candidate_refuses_temp_root(tmp_path):
    value = marker_value()
    marker_root = tmp_path / "fixture"
    marker_root.mkdir()
    (marker_root / SYNTHETIC_MARKER_NAME).write_bytes(canonical_bytes(value))
    context = SyntheticWaveExecutionContext.sealed(
        mode=WaveExecutionMode.REAL_STAGING_CANDIDATE,
        fixture_root=marker_root,
        target_root=tmp_path / "candidate",
        fixture_marker_ref=str(value["fixture_marker_ref"]),
        fixture_marker_digest=sha256_ref(value),
        forbidden_roots=(),
        journal=WaveEffectJournal(),
    )

    with pytest.raises(RALValidationError, match="wave_staging_root_refused"):
        context.verify_before_io("prepare", context.target_root)


def test_effect_journal_retains_exact_refs_and_separates_forbidden_effects():
    journal = WaveEffectJournal()

    journal.record("fixture_reads", "fixture:claim:1")
    journal.record("staging_writes", "staging:candidate:1")
    journal.record("network_calls", "network:blocked-control")

    assert journal.fixture_reads == 1
    assert journal.staging_writes == 1
    assert journal.refs("fixture_reads") == ("fixture:claim:1",)
    assert journal.allowed_refs() == {
        "fixture_reads": ("fixture:claim:1",),
        "staging_writes": ("staging:candidate:1",),
    }
    assert journal.forbidden_nonzero_dimensions() == ("network_calls",)


def test_effect_journal_rejects_unknown_dimension_and_empty_ref():
    journal = WaveEffectJournal()

    with pytest.raises(RALValidationError, match="wave_effect_dimension_invalid"):
        journal.record("unknown", "ref:1")
    with pytest.raises(RALValidationError, match="wave_effect_ref_invalid"):
        journal.record("fixture_reads", "")
