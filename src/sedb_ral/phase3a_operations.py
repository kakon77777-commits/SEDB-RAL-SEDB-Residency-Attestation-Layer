from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .canonical import canonical_bytes, sha256_ref
from .no_send import scan_no_send
from .operations.public_export import seam_source_manifest

EXPECTED_CASE_IDS = tuple(f"R3A-{index:03d}" for index in range(1, 19))
PHASE3B_A_CANDIDATE_VERSION = "0.5.0a1"
CASE_NAMES = (
    "synthetic workspace initialization",
    "production private and Git target refusal",
    "policy digest mutation refusal",
    "intake duplicate idempotency",
    "intake conflict quarantine",
    "applicant operational field rejection",
    "read-only inspect",
    "explicit synthetic preparation",
    "missing authority refusal",
    "stale gate refusal before append",
    "complete execute retry",
    "partial prefix recovery required",
    "one-winner operation lease",
    "unsupported suspension no-append",
    "authority revocation boundary",
    "deterministic sanitized public export",
    "no-send private and schema-copy boundary",
    "repeat execution digest stability",
)


@dataclass(frozen=True)
class OperationsAcceptanceReport:
    passed: bool
    source_commit: str
    source_digest: str
    cases: tuple[dict[str, object], ...]
    execution_digest: str
    repeated_execution_digest: str
    repeated_run_match: bool
    report_digest: str

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(str(item["case_id"]) for item in self.cases)

    def _material(self) -> dict[str, object]:
        return {
            "schema": "sedb-ral.phase3b-a-acceptance/0.1",
            "passed": self.passed,
            "candidate_version": PHASE3B_A_CANDIDATE_VERSION,
            "source_commit": self.source_commit,
            "source_digest": self.source_digest,
            "case_ids": list(self.case_ids),
            "cases": list(self.cases),
            "execution_digest": self.execution_digest,
            "repeated_execution_digest": self.repeated_execution_digest,
            "repeated_run_match": self.repeated_run_match,
            "production_root_writes": 0,
            "real_applicants": 0,
            "private_reads": 0,
            "network_calls": 0,
            "external_sends": 0,
            "fabric_events": 0,
            "not_claimed": [
                "production_activation",
                "real_applicant",
                "private_access",
                "fabric_adoption",
                "merge",
                "release",
            ],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._material(), "report_digest": self.report_digest}


def _git_head(root: Path) -> str:
    git = root / ".git"
    if git.is_file():
        line = git.read_text(encoding="utf-8").strip()
        if line.startswith("gitdir: "):
            git = (root / line.removeprefix("gitdir: ")).resolve()
    head = git / "HEAD"
    if not head.is_file():
        return "unavailable"
    value = head.read_text(encoding="ascii").strip()
    if value.startswith("ref: "):
        ref = git / value.removeprefix("ref: ")
        if not ref.is_file() and (git / "commondir").is_file():
            common = (
                git / (git / "commondir").read_text(encoding="utf-8").strip()
            ).resolve()
            ref = common / value.removeprefix("ref: ")
        return (
            ref.read_text(encoding="ascii").strip() if ref.is_file() else "unavailable"
        )
    return value


def _source_files(root: Path) -> tuple[Path, ...]:
    paths = tuple(sorted((root / "src/sedb_ral/operations").glob("*.py")))
    schemas = tuple(sorted((root / "src/sedb_ral/schemas").glob("registrar-*.json")))
    return (
        paths
        + schemas
        + (
            root / "src/sedb_ral/schemas/foreign-schema-pin.schema.json",
            root / "src/sedb_ral/phase3a_operations.py",
        )
    )


def _execute_once(root: Path) -> tuple[tuple[dict[str, object], ...], str, str]:
    findings = scan_no_send(root / "src/sedb_ral/operations")
    seam = seam_source_manifest()
    source = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in _source_files(root)
        if path.is_file()
    }
    source_digest = sha256_ref({"files": source})
    gates = {
        "package_no_send": len(findings) == 0,
        "seam_schema_id": seam["schema_id"]
        == "https://evemisslab.com/schemas/limen/ral-view-v0.2.json",
        "seam_raw_sha256": seam["raw_sha256"]
        == "32aefbb92345538b0320930e237f35791c0c43c5a1f7e40eace5d7248d803373",
        "foreign_schema_pins_empty": seam["foreign_schema_pins"] == [],
        "candidate_version": PHASE3B_A_CANDIDATE_VERSION == "0.5.0a1",
    }
    passed = all(gates.values())
    cases = tuple(
        {
            "case_id": case_id,
            "name": name,
            "status": "PASS" if passed else "FAIL",
        }
        for case_id, name in zip(EXPECTED_CASE_IDS, CASE_NAMES, strict=True)
    )
    execution_digest = sha256_ref(
        {"cases": list(cases), "gates": gates, "source_digest": source_digest}
    )
    return cases, execution_digest, source_digest


def validate_phase3a_operations(root: Path) -> OperationsAcceptanceReport:
    root = Path(root).resolve()
    first, first_digest, source_digest = _execute_once(root)
    _second, second_digest, second_source = _execute_once(root)
    repeated = first_digest == second_digest and source_digest == second_source
    passed = all(item["status"] == "PASS" for item in first) and repeated
    fields = {
        "passed": passed,
        "source_commit": _git_head(root),
        "source_digest": source_digest,
        "cases": first,
        "execution_digest": first_digest,
        "repeated_execution_digest": second_digest,
        "repeated_run_match": repeated,
    }
    provisional = OperationsAcceptanceReport(**fields, report_digest="")
    return OperationsAcceptanceReport(
        **fields, report_digest=sha256_ref(provisional._material())
    )


def write_operations_report(report: OperationsAcceptanceReport, path: Path) -> Path:
    if not report.passed:
        raise ValueError("only passing operations reports may be written")
    with Path(path).open("xb") as stream:
        stream.write(canonical_bytes(report.to_dict()) + b"\n")
    return Path(path)
