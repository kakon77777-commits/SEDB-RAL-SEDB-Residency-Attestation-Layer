from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from .contracts import validate_contract


class DiscriminationDecision(str, Enum):
    ADMIT = "admit"
    REJECT = "reject"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class DiscriminationResult:
    decision: DiscriminationDecision
    reason_codes: tuple[str, ...]
    distinct_residents: int
    distinct_values: int

    def as_json(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "reason_codes": list(self.reason_codes),
            "distinct_residents": self.distinct_residents,
            "distinct_values": self.distinct_values,
        }


def evaluate_identifier_fixture(
    value: Mapping[str, object],
) -> DiscriminationResult:
    validate_contract("identifier-discrimination.schema.json", value)
    identifier = value["identifier"]
    if identifier["subject_kind"] != value["discrimination_target"]:
        return DiscriminationResult(
            DiscriminationDecision.REJECT,
            ("identifier_subject_mismatch",),
            0,
            0,
        )

    observations = value["observations"]
    by_resident: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    value_to_residents: dict[str, set[str]] = defaultdict(set)
    for observation in observations:
        resident = observation["resident_ref"]
        by_resident[resident].append(observation)
        value_to_residents[observation["observed_value"]].add(resident)

    distinct_residents = len(by_resident)
    distinct_values = len(value_to_residents)
    required_instances = value["required_instances_per_resident"]
    if distinct_residents < 2:
        return DiscriminationResult(
            DiscriminationDecision.INDETERMINATE,
            ("population_too_small",),
            distinct_residents,
            distinct_values,
        )
    if any(
        len({item["instance_ref"] for item in items}) < required_instances
        for items in by_resident.values()
    ):
        return DiscriminationResult(
            DiscriminationDecision.INDETERMINATE,
            ("instances_per_resident_unmeasured",),
            distinct_residents,
            distinct_values,
        )
    if any(
        len({item["observed_value"] for item in items}) > 1
        for items in by_resident.values()
    ):
        return DiscriminationResult(
            DiscriminationDecision.REJECT,
            ("unstable_within_resident",),
            distinct_residents,
            distinct_values,
        )
    if any(len(residents) > 1 for residents in value_to_residents.values()):
        return DiscriminationResult(
            DiscriminationDecision.REJECT,
            ("does_not_distinguish_residents",),
            distinct_residents,
            distinct_values,
        )
    return DiscriminationResult(
        DiscriminationDecision.ADMIT,
        ("admissible_resident_discriminator",),
        distinct_residents,
        distinct_values,
    )
