from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .canonical import loads_strict
from .contracts import validate_contract
from .errors import RALValidationError

CORPUS_SOURCE_SHA256 = (
    "9A4A504621D6837B0724CBFEBC7A9DB84A5F260103D9CE585A3087A39A6A3828"
)
_REQUIRED_NEGATIVE_IDS = (3, 24, 25)


@dataclass(frozen=True)
class IncidentGateCase:
    incident_id: int
    gate: str
    expected_code: str
    title: str


def load_incidents(path: Path) -> tuple[dict[str, object], ...]:
    rows = []
    ids = set()
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line:
            continue
        value = loads_strict(line)
        if not isinstance(value, dict):
            raise RALValidationError(
                "incident_not_object", f"line {line_number}"
            )
        validate_contract("incident-record.schema.json", value)
        if value["id"] in ids:
            raise RALValidationError(
                "incident_id_duplicate", str(value["id"])
            )
        ids.add(value["id"])
        rows.append(value)
    return tuple(rows)


def incident_counts(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, dict[str, int]]:
    values = tuple(rows)
    return {
        "class": dict(sorted(Counter(row["cls"] for row in values).items())),
        "origin_strength": dict(
            sorted(Counter(row["origin_strength"] for row in values).items())
        ),
        "status": dict(
            sorted(Counter(row["status"] for row in values).items())
        ),
    }


def negative_gate_cases(
    rows: Iterable[Mapping[str, object]],
) -> dict[int, IncidentGateCase]:
    definitions = {
        3: ("resident_identifier_discrimination", "does_not_distinguish_residents"),
        24: ("adapter_route_readiness", "adapter_submits_unavailable"),
        25: ("address_failure_classification", "address_failure_indeterminate"),
    }
    cases = {}
    for row in rows:
        incident_id = row["id"]
        if incident_id not in definitions:
            continue
        gate, code = definitions[incident_id]
        cases[incident_id] = IncidentGateCase(
            incident_id=incident_id,
            gate=gate,
            expected_code=code,
            title=row["title"],
        )
    return cases


def validate_required_negative_cases(
    cases: Mapping[int, IncidentGateCase],
) -> tuple[str, ...]:
    return tuple(
        f"required_negative_incident_missing:{incident_id}"
        for incident_id in _REQUIRED_NEGATIVE_IDS
        if incident_id not in cases
    )


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_incidents(rows: Iterable[Mapping[str, object]]) -> str:
    values = tuple(rows)
    counts = incident_counts(values)
    class_summary = " / ".join(
        f"{key} {value}" for key, value in counts["class"].items()
    )
    strength_summary = " / ".join(
        f"{key} {value}" for key, value in counts["origin_strength"].items()
    )
    lines = [
        "# SEDB-RAL Incident Corpus",
        "",
        "> DO NOT EDIT: generated from `incidents.jsonl`.",
        "",
        f"Total: **{len(values)}**",
        "",
        f"Classes: {class_summary}",
        "",
        f"Origin strength: {strength_summary}",
        "",
        "| ID | Class | Title | Actor claim | Origin strength | Status |",
        "|---:|:---:|---|---|---|---|",
    ]
    for row in values:
        lines.append(
            "| {id} | {cls} | {title} | {actor} | {strength} | {status} |".format(
                id=row["id"],
                cls=_cell(row["cls"]),
                title=_cell(row["title"]),
                actor=_cell(row["actor_claim"]),
                strength=_cell(row["origin_strength"]),
                status=_cell(row["status"]),
            )
        )
    weak = [row for row in values if row["origin_strength"] == "peer_assertion"]
    lines.extend(
        [
            "",
            "## Peer-assertion boundary",
            "",
            "These rows require direct verification from the claimed actor; do not cite this corpus as independent confirmation:",
            "",
            *[f"- {row['id']}: {_cell(row['title'])}" for row in weak],
            "",
        ]
    )
    return "\n".join(lines)
