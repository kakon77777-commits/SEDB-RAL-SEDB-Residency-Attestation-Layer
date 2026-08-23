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
    exemplar = value["identifier_exemplar"]
    if exemplar["subject_kind"] != value["discrimination_target"]:
        return DiscriminationResult(
            DiscriminationDecision.REJECT,
            ("identifier_subject_mismatch",),
            0,
            0,
        )

    observations = value["observations"]
    by_resident: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    value_to_residents: dict[str, set[str]] = defaultdict(set)
    by_runtime: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    observation_ids: list[str] = []
    instance_to_residents: dict[str, set[str]] = defaultdict(set)
    instance_to_runtimes: dict[str, set[str]] = defaultdict(set)
    observation_contract_mismatch = False
    for observation in observations:
        resident = observation["resident_ref"]
        instance = observation["instance_ref"]
        runtime = observation["runtime_ref"]
        by_resident[resident].append(observation)
        value_to_residents[observation["observed_value"]].add(resident)
        by_runtime[runtime][resident].add(instance)
        observation_ids.append(observation["observation_id"])
        instance_to_residents[instance].add(resident)
        instance_to_runtimes[instance].add(runtime)
        if (
            observation["namespace"] != exemplar["namespace"]
            or observation["identifier_kind"]
            != exemplar["identifier_kind"]
        ):
            observation_contract_mismatch = True

    distinct_residents = len(by_resident)
    distinct_values = len(value_to_residents)
    required_instances = value["required_instances_per_resident"]
    if len(set(observation_ids)) != len(observation_ids):
        return DiscriminationResult(
            DiscriminationDecision.REJECT,
            ("observation_id_collision",),
            distinct_residents,
            distinct_values,
        )
    if observation_contract_mismatch:
        return DiscriminationResult(
            DiscriminationDecision.REJECT,
            ("observation_contract_mismatch",),
            distinct_residents,
            distinct_values,
        )
    if exemplar["value"] not in value_to_residents:
        return DiscriminationResult(
            DiscriminationDecision.REJECT,
            ("identifier_exemplar_unobserved",),
            distinct_residents,
            distinct_values,
        )
    if any(len(residents) > 1 for residents in instance_to_residents.values()):
        return DiscriminationResult(
            DiscriminationDecision.REJECT,
            ("instance_resident_conflict",),
            distinct_residents,
            distinct_values,
        )
    if any(len(runtimes) > 1 for runtimes in instance_to_runtimes.values()):
        return DiscriminationResult(
            DiscriminationDecision.REJECT,
            ("instance_runtime_conflict",),
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
    if distinct_residents < 2:
        return DiscriminationResult(
            DiscriminationDecision.INDETERMINATE,
            ("population_too_small",),
            distinct_residents,
            distinct_values,
        )
    same_runtime_population_exists = any(
        len(residents) >= 2 for residents in by_runtime.values()
    )
    if not same_runtime_population_exists:
        return DiscriminationResult(
            DiscriminationDecision.INDETERMINATE,
            ("same_runtime_population_unmeasured",),
            distinct_residents,
            distinct_values,
        )
    qualifying_runtime_exists = any(
        sum(
            1
            for instances in residents.values()
            if len(instances) >= required_instances
        )
        >= 2
        for residents in by_runtime.values()
    )
    if not qualifying_runtime_exists:
        return DiscriminationResult(
            DiscriminationDecision.INDETERMINATE,
            ("instances_per_resident_unmeasured",),
            distinct_residents,
            distinct_values,
        )
    return DiscriminationResult(
        DiscriminationDecision.ADMIT,
        ("admissible_resident_discriminator",),
        distinct_residents,
        distinct_values,
    )
