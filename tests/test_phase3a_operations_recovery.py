from __future__ import annotations

import shutil

import pytest
from test_phase3_registrar_recovery import (
    _trim_to_valid_prefix,
    committed_registration,
)
from test_phase3a_operations_engine import planned_fixture

from sedb_ral.errors import RALValidationError


def test_partial_phase3a_prefix_remains_recovery_required(tmp_path):
    (
        engine,
        _,
        _,
        _,
        authority,
        request,
        observation,
        plan,
    ) = planned_fixture(tmp_path)
    source, *_ = committed_registration(tmp_path / "partial-source")
    shutil.copytree(source, engine.ledger_root)
    _trim_to_valid_prefix(engine.ledger_root, keep=2)

    with pytest.raises(RALValidationError) as caught:
        engine.execute(
            request.to_dict()["operation_id"],
            plan,
            authority=authority,
            ctcl_receipt=__import__("test_phase3_registrar_plan").CTCL,
            verified_attestation_refs=__import__(
                "test_phase3_registration_admission"
            ).VERIFIED,
            operator_observation=observation,
            checkpoint_evidence_digest=request.to_dict()["checkpoint_evidence_digest"],
        )

    assert caught.value.code == "registrar_partial_transaction"
