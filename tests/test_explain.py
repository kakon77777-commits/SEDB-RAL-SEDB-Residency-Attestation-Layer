from sedb_ral.explain import explain_claim

CLAIM = {
    "schema_version": "0.1",
    "claim_id": "claim:test",
    "claimant_ref": "resident:test",
    "subject_ref": "resident:test",
    "predicate": "reachable",
    "object": True,
    "claimed_time": None,
    "claimed_authored_by_instance": "instance:test:1",
    "claimed_on_behalf_of_line": None,
}


def attestation(index, root, independence="shared_root", verification="verified"):
    return {
        "schema_version": "0.1",
        "attestation_id": f"attestation:test:{index}",
        "claim_ref": "claim:test",
        "evidence_basis": "own_execution",
        "evidence_root_refs": [root],
        "derivation_parent_refs": [],
        "independence_status": independence,
        "verification_status": verification,
    }


def events(attestations):
    values = [
        {
            "ledger_seq": 1,
            "event_id": "evt_claim_test",
            "event_type": "claim.recorded",
            "payload": {"claim": CLAIM},
        }
    ]
    for index, value in enumerate(attestations, start=2):
        values.append(
            {
                "ledger_seq": index,
                "event_id": f"evt_attestation_{index}",
                "event_type": "attestation.recorded",
                "payload": {"attestation": value},
            }
        )
    return values


def test_transitive_relay_rows_count_as_one_root():
    result = explain_claim(
        events(
            [
                attestation(1, "evidence:root:1"),
                attestation(2, "evidence:root:1"),
                attestation(3, "evidence:root:1"),
            ]
        ),
        "claim:test",
    )
    assert result.row_count == 3
    assert result.distinct_root_count == 1
    assert result.independence_status == "shared_root"


def test_unmeasured_independence_never_becomes_false_or_independent():
    result = explain_claim(
        events([attestation(1, "evidence:root:1", "unmeasured", "unverified")]),
        "claim:test",
    )
    assert result.independence_status == "unmeasured"
    assert result.verification_statuses == ("unverified",)


def test_distinct_independent_roots_remain_visible():
    result = explain_claim(
        events(
            [
                attestation(1, "evidence:root:1", "independent"),
                attestation(2, "evidence:root:2", "independent"),
            ]
        ),
        "claim:test",
    )
    assert result.evidence_root_refs == (
        "evidence:root:1",
        "evidence:root:2",
    )
    assert result.distinct_root_count == 2
    assert result.independence_status == "independent"


def test_duplicate_attestation_row_does_not_inflate_roots():
    duplicated = attestation(1, "evidence:root:1", "independent")
    result = explain_claim(events([duplicated, duplicated]), "claim:test")
    assert result.row_count == 2
    assert result.distinct_root_count == 1
    assert result.independence_status == "shared_root"
