import copy

import pytest

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


CANONICAL_BASES = [
    "peer_assertion",
    "filesystem_observation",
    "own_execution",
    "peer_transcript_observation",
]

POLICY = {
    "policy_id": "policy:test:claim-reliance",
    "authorization_scope": "registry.claim.rely",
    "required_evidence_bases": ["own_execution"],
    "required_verification_status": "verified",
    "required_record_status": "active",
    "required_temporal_validity": "valid",
    "required_scope_refs": ["resident:test"],
    "minimum_distinct_evidence_roots": 2,
    "required_observer_independence_status": "independent",
    "required_evidence_independence_status": "independent",
    "comparability_relations": [CANONICAL_BASES],
}


def attestation(
    index,
    root,
    *,
    observer_independence="independent",
    evidence_independence="independent",
    verification="verified",
    basis="own_execution",
    scope=("resident:test",),
):
    return {
        "schema_version": "0.1",
        "attestation_id": f"attestation:test:{index}",
        "claim_ref": "claim:test",
        "evidence_basis": basis,
        "evidence_root_refs": [root],
        "derivation_parent_refs": [],
        "evidence_refs": [f"evidence:execution:{index}"],
        "record_status": "active",
        "observer_independence_status": observer_independence,
        "evidence_independence_status": evidence_independence,
        "independence_scope": "resident:test",
        "verification_status": verification,
        "scope": list(scope),
        "temporal_validity": "valid",
        "not_claimed": [],
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
                attestation(
                    1,
                    "evidence:root:1",
                    evidence_independence="shared_root",
                ),
                attestation(
                    2,
                    "evidence:root:1",
                    evidence_independence="shared_root",
                ),
                attestation(
                    3,
                    "evidence:root:1",
                    evidence_independence="shared_root",
                ),
            ]
        ),
        "claim:test",
    )
    assert result.row_count == 3
    assert result.distinct_root_count == 1
    assert result.evidence_independence_status == "shared_root"
    assert result.observer_independence_status == "independent"


def test_unmeasured_independence_never_becomes_false_or_independent():
    result = explain_claim(
        events(
            [
                attestation(
                    1,
                    "evidence:root:1",
                    observer_independence="unmeasured",
                    evidence_independence="unmeasured",
                    verification="unverified",
                )
            ]
        ),
        "claim:test",
    )
    assert result.observer_independence_status == "unmeasured"
    assert result.evidence_independence_status == "unmeasured"
    assert result.verification_statuses == ("unverified",)
    assert result.sufficiency == "indeterminate"
    assert result.sufficiency_reason_codes == ("sufficiency_policy_missing",)


def test_distinct_independent_roots_remain_visible():
    result = explain_claim(
        events(
            [
                attestation(1, "evidence:root:1"),
                attestation(2, "evidence:root:2"),
            ]
        ),
        "claim:test",
    )
    assert result.evidence_root_refs == (
        "evidence:root:1",
        "evidence:root:2",
    )
    assert result.distinct_root_count == 2
    assert result.observer_independence_status == "independent"
    assert result.evidence_independence_status == "independent"


def test_duplicate_attestation_row_does_not_inflate_roots():
    duplicated = attestation(1, "evidence:root:1")
    result = explain_claim(events([duplicated, duplicated]), "claim:test")
    assert result.row_count == 2
    assert result.distinct_root_count == 1
    assert result.evidence_independence_status == "shared_root"


def test_matching_scope_policy_is_sufficient_positive_control():
    result = explain_claim(
        events(
            [
                attestation(1, "evidence:root:1"),
                attestation(2, "evidence:root:2"),
            ]
        ),
        "claim:test",
        policy=POLICY,
    )

    assert result.policy_scope == "registry.claim.rely"
    assert result.sufficiency == "sufficient"
    assert result.sufficiency_reason_codes == ()


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda rows: [row.update(evidence_basis="peer_assertion") for row in rows],
            "required_evidence_basis_missing",
        ),
        (
            lambda rows: rows[0].update(verification_status="unverified"),
            "verification_status_insufficient",
        ),
        (
            lambda rows: rows[0].update(scope=["resident:other"]),
            "scope_overlap_missing",
        ),
        (
            lambda rows: rows[0].update(
                observer_independence_status="shared_observer"
            ),
            "observer_independence_insufficient",
        ),
        (
            lambda rows: rows[0].update(
                evidence_independence_status="shared_root"
            ),
            "evidence_independence_insufficient",
        ),
    ],
)
def test_each_sufficiency_term_is_solely_decisive(mutate, expected_code):
    rows = [
        attestation(1, "evidence:root:1"),
        attestation(2, "evidence:root:2"),
    ]
    mutate(rows)

    result = explain_claim(events(rows), "claim:test", policy=POLICY)

    assert result.sufficiency == "insufficient"
    assert result.sufficiency_reason_codes == (expected_code,)


def test_distinct_roots_not_rows_decide_minimum():
    rows = [
        attestation(1, "evidence:root:1"),
        attestation(2, "evidence:root:1"),
    ]

    result = explain_claim(events(rows), "claim:test", policy=POLICY)

    assert result.row_count == 2
    assert result.distinct_root_count == 1
    assert "distinct_evidence_roots_insufficient" in result.sufficiency_reason_codes


def test_derived_shared_root_population_cannot_satisfy_independent_root_policy():
    policy = copy.deepcopy(POLICY)
    policy["minimum_distinct_evidence_roots"] = 1
    rows = [
        attestation(1, "evidence:shared:1"),
        attestation(2, "evidence:shared:1"),
    ]

    result = explain_claim(events(rows), "claim:test", policy=policy)

    assert result.distinct_root_count == 1
    assert result.evidence_independence_status == "shared_root"
    assert result.sufficiency == "insufficient"
    assert result.sufficiency_reason_codes == (
        "evidence_independence_insufficient",
    )


def test_missing_comparability_relation_is_indeterminate():
    policy = copy.deepcopy(POLICY)
    policy["comparability_relations"] = []

    result = explain_claim(
        events(
            [
                attestation(1, "evidence:root:1"),
                attestation(2, "evidence:root:2"),
            ]
        ),
        "claim:test",
        policy=policy,
    )

    assert result.sufficiency == "indeterminate"
    assert result.sufficiency_reason_codes == ("comparability_relation_missing",)


def test_unmeasured_required_policy_term_stays_indeterminate_not_false():
    rows = [
        attestation(1, "evidence:root:1"),
        attestation(2, "evidence:root:2", observer_independence="unmeasured"),
    ]

    result = explain_claim(events(rows), "claim:test", policy=POLICY)

    assert result.sufficiency == "indeterminate"
    assert result.sufficiency_reason_codes == (
        "observer_independence_indeterminate",
    )
