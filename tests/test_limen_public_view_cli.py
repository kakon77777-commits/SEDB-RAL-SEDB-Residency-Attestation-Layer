import hashlib
import json

from test_phase3_registrar_plan import CTCL, VERIFIED, build_plan

from sedb_ral.canonical import canonical_bytes
from sedb_ral.cli import main
from sedb_ral.ledger import read_verified_events
from sedb_ral.limen_public_view import build_limen_public_view
from sedb_ral.projection import project_events
from sedb_ral.registrar import commit_admission_plan

ZERO_HEAD = "sha256:sedb-ral-chain-v1:" + "0" * 64


def committed_ledger(tmp_path):
    canonical, prepared, authority, decision, plan = build_plan(tmp_path)
    receipt = commit_admission_plan(
        canonical,
        plan,
        prepared,
        decision,
        authority,
        CTCL,
        verified_attestation_refs=VERIFIED,
    )
    events = read_verified_events(canonical, receipt.final_head)
    return canonical, receipt.final_head, events


def tree_fingerprint(root):
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_limen_view_cli_matches_direct_core_bytes(tmp_path, capfd):
    root, head, events = committed_ledger(tmp_path)
    expected = build_limen_public_view(
        project_events(events), ledger_head=head, sequence=len(events)
    )

    code = main(
        [
            "registry",
            "limen-view",
            "--ledger-root",
            str(root),
            "--expected-head",
            head,
        ]
    )

    assert code == 0
    emitted = json.loads(capfd.readouterr().out)
    assert canonical_bytes(emitted) == canonical_bytes(expected.to_dict())


def test_limen_view_cli_output_uses_create_new_canonical_bytes(tmp_path, capfd):
    root, head, events = committed_ledger(tmp_path)
    expected = build_limen_public_view(
        project_events(events), ledger_head=head, sequence=len(events)
    )
    output = tmp_path / "public-view.json"

    assert (
        main(
            [
                "registry",
                "limen-view",
                "--ledger-root",
                str(root),
                "--expected-head",
                head,
                "--output",
                str(output),
            ]
        )
        == 0
    )

    assert output.read_bytes() == canonical_bytes(expected.to_dict())
    assert json.loads(capfd.readouterr().out) == expected.to_dict()

    original = output.read_bytes()
    assert (
        main(
            [
                "registry",
                "limen-view",
                "--ledger-root",
                str(root),
                "--expected-head",
                head,
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert output.read_bytes() == original
    assert json.loads(capfd.readouterr().out)["reason_codes"] == [
        "output_exists"
    ]


def test_wrong_head_refuses_without_output_or_registry_write(tmp_path, capfd):
    root, _, _ = committed_ledger(tmp_path)
    before = tree_fingerprint(tmp_path)
    output = tmp_path / "must-not-exist.json"

    code = main(
        [
            "registry",
            "limen-view",
            "--ledger-root",
            str(root),
            "--expected-head",
            ZERO_HEAD,
            "--output",
            str(output),
        ]
    )

    assert code == 2
    assert json.loads(capfd.readouterr().out)["reason_codes"] == [
        "external_anchor_mismatch"
    ]
    assert not output.exists()
    assert tree_fingerprint(tmp_path) == before


def test_registry_limen_view_requires_explicit_head_and_root(capfd):
    assert main(["registry", "limen-view"]) == 2
    assert json.loads(capfd.readouterr().out)["reason_codes"] == [
        "cli_usage_error"
    ]


def test_empty_or_missing_ledger_is_not_exported_as_genesis(tmp_path, capfd):
    root = tmp_path / "missing-ledger"

    assert (
        main(
            [
                "registry",
                "limen-view",
                "--ledger-root",
                str(root),
                "--expected-head",
                ZERO_HEAD,
            ]
        )
        == 2
    )
    assert json.loads(capfd.readouterr().out)["reason_codes"] == [
        "external_anchor_mismatch"
    ]
    assert not root.exists()


def test_limen_view_error_never_leaks_path_or_stack(tmp_path, capfd):
    secret_named_root = tmp_path / "private-looking-name"

    assert (
        main(
            [
                "registry",
                "limen-view",
                "--ledger-root",
                str(secret_named_root),
                "--expected-head",
                ZERO_HEAD,
            ]
        )
        == 2
    )
    output = capfd.readouterr().out
    assert str(secret_named_root) not in output
    assert "Traceback" not in output


def test_repeated_cli_output_is_byte_identical(tmp_path, capfd):
    root, head, _ = committed_ledger(tmp_path)
    args = [
        "registry",
        "limen-view",
        "--ledger-root",
        str(root),
        "--expected-head",
        head,
    ]

    assert main(args) == 0
    first = capfd.readouterr().out.encode("utf-8")
    assert main(args) == 0
    second = capfd.readouterr().out.encode("utf-8")

    assert first == second
