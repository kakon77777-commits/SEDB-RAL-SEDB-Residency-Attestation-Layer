from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .contracts import validate_contract
from .errors import RALValidationError


@dataclass(frozen=True)
class ClaimExplanation:
    claim_id: str
    evidence_basis: tuple[str, ...]
    verification_statuses: tuple[str, ...]
    evidence_root_refs: tuple[str, ...]
    distinct_root_count: int
    row_count: int
    independence_status: str
    sufficiency: str

    def as_json(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "evidence_basis": list(self.evidence_basis),
            "verification_statuses": list(self.verification_statuses),
            "evidence_root_refs": list(self.evidence_root_refs),
            "distinct_root_count": self.distinct_root_count,
            "row_count": self.row_count,
            "independence_status": self.independence_status,
            "sufficiency": self.sufficiency,
        }


def explain_claim(
    events: Iterable[Mapping[str, object]],
    claim_id: str,
) -> ClaimExplanation:
    claim = None
    attestations = []
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
    statuses = [item["independence_status"] for item in attestations]
    if not statuses or "unmeasured" in statuses:
        independence = "unmeasured"
    elif (
        "shared_root" in statuses
        or any(count > 1 for count in root_counts.values())
    ):
        independence = "shared_root"
    elif "indeterminate" in statuses:
        independence = "indeterminate"
    elif all(status == "independent" for status in statuses):
        independence = "independent"
    else:
        independence = "indeterminate"

    distinct_roots = tuple(sorted(root_counts))
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
        independence_status=independence,
        sufficiency="not_evaluated",
    )
