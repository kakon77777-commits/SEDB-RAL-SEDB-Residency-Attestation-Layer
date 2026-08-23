from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import combinations

from .contracts import validate_contract
from .errors import RALValidationError

_POLICY_FIELDS = {
    "policy_id",
    "authorization_scope",
    "required_evidence_bases",
    "required_verification_status",
    "required_record_status",
    "required_temporal_validity",
    "required_scope_refs",
    "minimum_distinct_evidence_roots",
    "required_observer_independence_status",
    "required_evidence_independence_status",
    "comparability_relations",
}


@dataclass(frozen=True)
class ClaimExplanation:
    claim_id: str
    evidence_basis: tuple[str, ...]
    verification_statuses: tuple[str, ...]
    evidence_root_refs: tuple[str, ...]
    distinct_root_count: int
    row_count: int
    observer_independence_status: str
    evidence_independence_status: str
    policy_scope: str | None
    sufficiency: str
    sufficiency_reason_codes: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "evidence_basis": list(self.evidence_basis),
            "verification_statuses": list(self.verification_statuses),
            "evidence_root_refs": list(self.evidence_root_refs),
            "distinct_root_count": self.distinct_root_count,
            "row_count": self.row_count,
            "observer_independence_status": self.observer_independence_status,
            "evidence_independence_status": self.evidence_independence_status,
            "policy_scope": self.policy_scope,
            "sufficiency": self.sufficiency,
            "sufficiency_reason_codes": list(self.sufficiency_reason_codes),
        }


def _aggregate_independence(
    statuses: Iterable[str],
    *,
    shared_status: str,
    inferred_shared: bool = False,
) -> str:
    values = tuple(statuses)
    if not values or "unmeasured" in values:
        return "unmeasured"
    if shared_status in values or inferred_shared:
        return shared_status
    if "indeterminate" in values:
        return "indeterminate"
    if all(value == "independent" for value in values):
        return "independent"
    return "indeterminate"


def _policy_value(
    policy: Mapping[str, object], field: str, kind: type
) -> object:
    value = policy[field]
    if type(value) is not kind:
        raise RALValidationError(
            "sufficiency_policy_invalid", f"{field} has the wrong type"
        )
    return value


def _validate_policy(policy: Mapping[str, object]) -> None:
    if set(policy) != _POLICY_FIELDS:
        raise RALValidationError(
            "sufficiency_policy_invalid", "policy fields differ from contract"
        )
    for field in (
        "policy_id",
        "authorization_scope",
        "required_verification_status",
        "required_record_status",
        "required_temporal_validity",
        "required_observer_independence_status",
        "required_evidence_independence_status",
    ):
        if not _policy_value(policy, field, str):
            raise RALValidationError(
                "sufficiency_policy_invalid", f"{field} must not be empty"
            )
    for field in (
        "required_evidence_bases",
        "required_scope_refs",
        "comparability_relations",
    ):
        _policy_value(policy, field, list)
    minimum = _policy_value(
        policy, "minimum_distinct_evidence_roots", int
    )
    if minimum < 1:
        raise RALValidationError(
            "sufficiency_policy_invalid", "minimum roots must be positive"
        )
    if not policy["required_evidence_bases"] or not policy["required_scope_refs"]:
        raise RALValidationError(
            "sufficiency_policy_invalid", "required sets must not be empty"
        )
    if any(
        not isinstance(value, str) or not value
        for value in [
            *policy["required_evidence_bases"],
            *policy["required_scope_refs"],
        ]
    ):
        raise RALValidationError(
            "sufficiency_policy_invalid", "required values must be strings"
        )
    if any(
        not isinstance(relation, list)
        or not relation
        or any(not isinstance(value, str) or not value for value in relation)
        for relation in policy["comparability_relations"]
    ):
        raise RALValidationError(
            "sufficiency_policy_invalid", "comparability relations are invalid"
        )


def _basis_pairs_are_comparable(
    attestations: Iterable[Mapping[str, object]],
    relations: Iterable[Iterable[str]],
) -> bool:
    groups = tuple(frozenset(group) for group in relations)
    bases = [str(item["evidence_basis"]) for item in attestations]
    return all(
        any({left, right}.issubset(group) for group in groups)
        for left, right in combinations(bases, 2)
    )


def _evaluate_sufficiency(
    attestations: tuple[Mapping[str, object], ...],
    roots: tuple[str, ...],
    evidence_independence_status: str,
    policy: Mapping[str, object] | None,
) -> tuple[str, tuple[str, ...], str | None]:
    if policy is None:
        return "indeterminate", ("sufficiency_policy_missing",), None
    _validate_policy(policy)
    scope = str(policy["authorization_scope"])
    if not policy["comparability_relations"]:
        return "indeterminate", ("comparability_relation_missing",), scope
    if not _basis_pairs_are_comparable(
        attestations, policy["comparability_relations"]
    ):
        return "indeterminate", ("comparability_relation_undeclared",), scope
    if not attestations:
        return "insufficient", ("attestation_population_missing",), scope

    failures: list[str] = []
    indeterminate: list[str] = []
    bases = {item["evidence_basis"] for item in attestations}
    if not set(policy["required_evidence_bases"]).issubset(bases):
        failures.append("required_evidence_basis_missing")
    verification_values = {
        item["verification_status"] for item in attestations
    }
    if "indeterminate" in verification_values:
        indeterminate.append("verification_status_indeterminate")
    if any(
        value not in {policy["required_verification_status"], "indeterminate"}
        for value in verification_values
    ):
        failures.append("verification_status_insufficient")
    if any(
        item["record_status"] != policy["required_record_status"]
        for item in attestations
    ):
        failures.append("record_status_insufficient")
    temporal_values = {item["temporal_validity"] for item in attestations}
    if temporal_values.intersection({"indeterminate", "unmeasured"}):
        indeterminate.append("temporal_validity_indeterminate")
    if any(
        value
        not in {
            policy["required_temporal_validity"],
            "indeterminate",
            "unmeasured",
        }
        for value in temporal_values
    ):
        failures.append("temporal_validity_insufficient")
    required_scope = set(policy["required_scope_refs"])
    if any(
        not required_scope.intersection(item["scope"])
        for item in attestations
    ):
        failures.append("scope_overlap_missing")
    observer_values = {
        item["observer_independence_status"] for item in attestations
    }
    if observer_values.intersection({"indeterminate", "unmeasured"}):
        indeterminate.append("observer_independence_indeterminate")
    if any(
        value
        not in {
            policy["required_observer_independence_status"],
            "indeterminate",
            "unmeasured",
        }
        for value in observer_values
    ):
        failures.append("observer_independence_insufficient")
    evidence_values = {
        item["evidence_independence_status"] for item in attestations
    }
    if evidence_values.intersection({"indeterminate", "unmeasured"}):
        indeterminate.append("evidence_independence_indeterminate")
    if any(
        value
        not in {
            policy["required_evidence_independence_status"],
            "indeterminate",
            "unmeasured",
        }
        for value in evidence_values
    ):
        failures.append("evidence_independence_insufficient")
    if evidence_independence_status in {"indeterminate", "unmeasured"}:
        if "evidence_independence_indeterminate" not in indeterminate:
            indeterminate.append("evidence_independence_indeterminate")
    elif (
        evidence_independence_status
        != policy["required_evidence_independence_status"]
        and "evidence_independence_insufficient" not in failures
    ):
        failures.append("evidence_independence_insufficient")
    if len(roots) < policy["minimum_distinct_evidence_roots"]:
        failures.append("distinct_evidence_roots_insufficient")
    if failures:
        return "insufficient", tuple(failures), scope
    if indeterminate:
        return "indeterminate", tuple(indeterminate), scope
    return "sufficient", (), scope


def explain_claim(
    events: Iterable[Mapping[str, object]],
    claim_id: str,
    *,
    policy: Mapping[str, object] | None = None,
) -> ClaimExplanation:
    claim = None
    attestations: list[Mapping[str, object]] = []
    for event in sorted(events, key=lambda item: item["ledger_seq"]):
        if event["event_type"] == "claim.recorded":
            candidate = event["payload"]["claim"]
            validate_contract("claim.schema.json", candidate)
            if candidate["claim_id"] == claim_id:
                claim = candidate
        elif event["event_type"] == "attestation.recorded":
            candidate = event["payload"]["attestation"]
            validate_contract("attestation.schema.json", candidate)
            if candidate["claim_ref"] == claim_id:
                attestations.append(candidate)
    if claim is None:
        raise RALValidationError("claim_not_found", claim_id)

    roots = [
        root
        for attestation in attestations
        for root in attestation["evidence_root_refs"]
    ]
    root_counts = Counter(roots)
    distinct_roots = tuple(sorted(root_counts))
    observer_independence = _aggregate_independence(
        (item["observer_independence_status"] for item in attestations),
        shared_status="shared_observer",
    )
    evidence_independence = _aggregate_independence(
        (item["evidence_independence_status"] for item in attestations),
        shared_status="shared_root",
        inferred_shared=any(count > 1 for count in root_counts.values()),
    )
    sufficiency, reason_codes, policy_scope = _evaluate_sufficiency(
        tuple(attestations),
        distinct_roots,
        evidence_independence,
        policy,
    )
    return ClaimExplanation(
        claim_id=claim_id,
        evidence_basis=tuple(
            sorted({item["evidence_basis"] for item in attestations})
        ),
        verification_statuses=tuple(
            sorted({item["verification_status"] for item in attestations})
        ),
        evidence_root_refs=distinct_roots,
        distinct_root_count=len(distinct_roots),
        row_count=len(attestations),
        observer_independence_status=observer_independence,
        evidence_independence_status=evidence_independence,
        policy_scope=policy_scope,
        sufficiency=sufficiency,
        sufficiency_reason_codes=reason_codes,
    )
