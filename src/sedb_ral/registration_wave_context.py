from __future__ import annotations

import ntpath
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .canonical import canonical_bytes, loads_strict, sha256_ref
from .errors import RALValidationError
from .registry_root import _reject_alternate_streams

SYNTHETIC_MARKER_NAME = ".sedb-ral-synthetic-wave-fixture.json"
PRODUCTION_REGISTRY_ROOT = Path(r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL")
PRIVATE_RESIDENCE_ROOT = Path(r"D:\AI_RESIDENCE\AI_HOME")


def _discover_repository_roots() -> tuple[Path, ...]:
    current = Path(__file__).absolute().parents[2]
    roots = [current]
    dot_git = current / ".git"
    if dot_git.is_file():
        try:
            line = dot_git.read_text(encoding="utf-8").strip()
            if line.startswith("gitdir: "):
                git_dir = (current / line.removeprefix("gitdir: ")).resolve()
                common_ref = git_dir / "commondir"
                common = (
                    (git_dir / common_ref.read_text(encoding="utf-8").strip()).resolve()
                    if common_ref.is_file()
                    else git_dir
                )
                roots.append(common.parent)
        except (OSError, UnicodeError):
            pass
    elif dot_git.is_dir():
        roots.append(current)
    for parent in current.parents:
        if parent.name.casefold() == ".worktrees":
            roots.append(parent.parent)
            break
    unique: dict[str, Path] = {}
    for root in roots:
        absolute = Path(os.path.abspath(root))
        key = ntpath.normcase(ntpath.normpath(str(absolute)))
        unique[key] = absolute
    return tuple(unique.values())


REPOSITORY_ROOTS = _discover_repository_roots()
_MANDATORY_FORBIDDEN_ROOTS = (
    PRODUCTION_REGISTRY_ROOT,
    PRIVATE_RESIDENCE_ROOT,
    *REPOSITORY_ROOTS,
)
_DRIVE = re.compile(r"^[A-Za-z]:")
_ALLOWED_EFFECTS = (
    "fixture_reads",
    "staging_writes",
    "synthetic_ledger_writes",
    "synthetic_receipt_writes",
)
_FORBIDDEN_EFFECTS = (
    "production_reads",
    "production_writes",
    "private_reads",
    "private_writes",
    "network_calls",
    "provider_calls",
    "fabric_calls",
    "mcp_calls",
    "external_cli_calls",
)
_EFFECT_DIMENSIONS = _ALLOWED_EFFECTS + _FORBIDDEN_EFFECTS


class WaveExecutionMode(StrEnum):
    SYNTHETIC_TEST = "synthetic_test"
    REAL_STAGING_CANDIDATE = "real_staging_candidate"


@dataclass
class WaveEffectJournal:
    fixture_reads: int = 0
    staging_writes: int = 0
    synthetic_ledger_writes: int = 0
    synthetic_receipt_writes: int = 0
    production_reads: int = 0
    production_writes: int = 0
    private_reads: int = 0
    private_writes: int = 0
    network_calls: int = 0
    provider_calls: int = 0
    fabric_calls: int = 0
    mcp_calls: int = 0
    external_cli_calls: int = 0
    _refs: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def record(self, dimension: str, ref: str) -> None:
        if dimension not in _EFFECT_DIMENSIONS:
            raise RALValidationError(
                "wave_effect_dimension_invalid", "effect dimension is not closed"
            )
        if not isinstance(ref, str) or not ref:
            raise RALValidationError(
                "wave_effect_ref_invalid", "effect reference must be non-empty"
            )
        setattr(self, dimension, getattr(self, dimension) + 1)
        self._refs.setdefault(dimension, []).append(ref)

    def refs(self, dimension: str) -> tuple[str, ...]:
        if dimension not in _EFFECT_DIMENSIONS:
            raise RALValidationError(
                "wave_effect_dimension_invalid", "effect dimension is not closed"
            )
        return tuple(self._refs.get(dimension, ()))

    def nonzero_dimensions(self) -> tuple[str, ...]:
        return tuple(name for name in _EFFECT_DIMENSIONS if getattr(self, name))

    def forbidden_nonzero_dimensions(self) -> tuple[str, ...]:
        return tuple(name for name in _FORBIDDEN_EFFECTS if getattr(self, name))

    def allowed_refs(self) -> dict[str, tuple[str, ...]]:
        return {
            name: self.refs(name)
            for name in _ALLOWED_EFFECTS
            if getattr(self, name)
        }


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _windows_key(path: Path) -> str:
    return ntpath.normcase(ntpath.normpath(str(_absolute(path))))


def _within(path: Path, root: Path) -> bool:
    selected = _windows_key(path)
    boundary = _windows_key(root)
    return selected == boundary or selected.startswith(boundary + "\\")


def _raw_path_forbidden(path: Path) -> bool:
    raw = str(path)
    normalized = raw.replace("/", "\\")
    if normalized.startswith(("\\\\", "\\?\\", "\\.\\")):
        return True
    remainder = normalized[2:] if _DRIVE.match(normalized) else normalized
    return ":" in remainder


def _is_reparse(path: Path) -> bool:
    try:
        stat = path.lstat()
    except OSError as error:
        raise RALValidationError(
            "synthetic_wave_path_unreadable", "path metadata cannot be inspected"
        ) from error
    return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & 0x400)


def _existing_path_chain(path: Path) -> Iterable[Path]:
    current = _absolute(path)
    while True:
        if current.exists() or current.is_symlink():
            yield current
        if current.parent == current:
            break
        current = current.parent


def _reject_existing_tree_hazards(root: Path) -> None:
    if not root.exists():
        return
    files: list[Path] = []
    if root.is_file():
        files.append(root)
    else:
        for current, names, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            if _is_reparse(current_path):
                raise RALValidationError(
                    "synthetic_wave_boundary_refused",
                    "synthetic target contains a reparse point",
                )
            for name in names:
                path = current_path / name
                if _is_reparse(path):
                    raise RALValidationError(
                        "synthetic_wave_boundary_refused",
                        "synthetic target contains a reparse point",
                    )
            files.extend(current_path / name for name in filenames)
    for path in files:
        if _is_reparse(path) or path.stat().st_nlink != 1:
            raise RALValidationError(
                "synthetic_wave_boundary_refused",
                "synthetic target contains linked file evidence",
            )
    _reject_alternate_streams(files)


def _context_material(
    *,
    mode: WaveExecutionMode,
    fixture_root: Path,
    target_root: Path,
    fixture_marker_ref: str,
    fixture_marker_digest: str,
    forbidden_roots: tuple[Path, ...],
) -> dict[str, object]:
    return {
        "schema": "sedb-ral.synthetic-wave-execution-context/0.1",
        "mode": mode.value,
        "fixture_root": _windows_key(fixture_root),
        "target_root": _windows_key(target_root),
        "fixture_marker_ref": fixture_marker_ref,
        "fixture_marker_digest": fixture_marker_digest,
        "forbidden_roots": [_windows_key(path) for path in forbidden_roots],
    }


@dataclass(frozen=True)
class SyntheticWaveExecutionContext:
    mode: WaveExecutionMode
    fixture_root: Path
    target_root: Path
    fixture_marker_ref: str
    fixture_marker_digest: str
    forbidden_roots: tuple[Path, ...]
    context_digest: str
    journal: WaveEffectJournal = field(compare=False, repr=False)

    def record_effect(self, dimension: str, ref: str) -> None:
        """Record one runtime effect against this sealed execution context."""
        self._verify_digest()
        self.journal.record(dimension, ref)

    @classmethod
    def sealed(
        cls,
        *,
        mode: WaveExecutionMode | str,
        fixture_root: Path,
        target_root: Path,
        fixture_marker_ref: str,
        fixture_marker_digest: str,
        forbidden_roots: tuple[Path, ...],
        journal: WaveEffectJournal,
    ) -> SyntheticWaveExecutionContext:
        parsed_mode = WaveExecutionMode(mode)
        material = _context_material(
            mode=parsed_mode,
            fixture_root=fixture_root,
            target_root=target_root,
            fixture_marker_ref=fixture_marker_ref,
            fixture_marker_digest=fixture_marker_digest,
            forbidden_roots=forbidden_roots,
        )
        return cls(
            mode=parsed_mode,
            fixture_root=_absolute(fixture_root),
            target_root=_absolute(target_root),
            fixture_marker_ref=fixture_marker_ref,
            fixture_marker_digest=fixture_marker_digest,
            forbidden_roots=tuple(_absolute(path) for path in forbidden_roots),
            context_digest=sha256_ref(material),
            journal=journal,
        )

    def _verify_digest(self) -> None:
        material = _context_material(
            mode=self.mode,
            fixture_root=self.fixture_root,
            target_root=self.target_root,
            fixture_marker_ref=self.fixture_marker_ref,
            fixture_marker_digest=self.fixture_marker_digest,
            forbidden_roots=self.forbidden_roots,
        )
        if sha256_ref(material) != self.context_digest:
            raise RALValidationError(
                "synthetic_wave_context_digest_mismatch",
                "synthetic execution context digest differs",
            )

    def _verify_marker(self) -> None:
        marker = self.fixture_root / SYNTHETIC_MARKER_NAME
        try:
            if _is_reparse(marker) or marker.stat().st_nlink != 1:
                raise RALValidationError(
                    "synthetic_wave_marker_mismatch",
                    "synthetic marker is linked or reparsed",
                )
            _reject_alternate_streams([marker])
            raw = marker.read_bytes()
            value = loads_strict(raw.decode("utf-8"))
        except RALValidationError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            raise RALValidationError(
                "synthetic_wave_marker_mismatch", "synthetic marker cannot be read"
            ) from error
        if (
            not isinstance(value, dict)
            or set(value) != {"schema", "fixture_marker_ref", "not_claimed"}
            or value.get("schema")
            != "sedb-ral.synthetic-wave-fixture-marker/0.1"
            or value.get("fixture_marker_ref") != self.fixture_marker_ref
            or canonical_bytes(value) != raw
            or sha256_ref(value) != self.fixture_marker_digest
        ):
            raise RALValidationError(
                "synthetic_wave_marker_mismatch", "synthetic marker binding differs"
            )

    def _reject_boundaries(self, target: Path) -> None:
        if any(
            _raw_path_forbidden(path)
            for path in (self.fixture_root, self.target_root, target)
        ):
            raise RALValidationError(
                "synthetic_wave_boundary_refused",
                "device, network, or alternate-stream path is forbidden",
            )
        boundaries = _MANDATORY_FORBIDDEN_ROOTS + self.forbidden_roots
        for boundary in boundaries:
            if _within(self.target_root, boundary) or _within(target, boundary):
                raise RALValidationError(
                    "synthetic_wave_boundary_refused", "target reaches forbidden root"
                )

        for candidate in _existing_path_chain(self.target_root):
            if _is_reparse(candidate):
                raise RALValidationError(
                    "synthetic_wave_boundary_refused", "target contains reparse point"
                )
            git_marker = candidate / ".git"
            if git_marker.is_file() or git_marker.is_dir():
                raise RALValidationError(
                    "synthetic_wave_boundary_refused",
                    "target is inside a Git checkout or worktree",
                )

        _reject_existing_tree_hazards(self.target_root)

        resolved_root = self.target_root.resolve(strict=False)
        resolved_target = target.resolve(strict=False)
        for boundary in boundaries:
            if _within(resolved_root, boundary) or _within(resolved_target, boundary):
                raise RALValidationError(
                    "synthetic_wave_boundary_refused",
                    "resolved target reaches forbidden root",
                )

    def verify_before_io(self, operation: str, target: Path) -> None:
        if not isinstance(operation, str) or not operation:
            raise RALValidationError(
                "synthetic_wave_operation_invalid", "operation must be non-empty"
            )
        selected = _absolute(Path(target))
        self._verify_digest()
        self._reject_boundaries(selected)

        resolved_root = self.target_root.resolve(strict=False)
        resolved_target = selected.resolve(strict=False)
        if not _within(resolved_target, resolved_root):
            raise RALValidationError(
                "synthetic_wave_boundary_refused", "operation escapes target root"
            )

        if self.mode is WaveExecutionMode.SYNTHETIC_TEST:
            fixture = self.fixture_root.resolve(strict=False)
            if not _within(resolved_root, fixture):
                raise RALValidationError(
                    "synthetic_wave_boundary_refused",
                    "synthetic target is outside sealed fixture root",
                )
            self._verify_marker()
            return

        temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
        if _within(resolved_root, temp_root):
            raise RALValidationError(
                "wave_staging_root_refused", "real staging cannot use temp storage"
            )
        if not self.target_root.parent.is_dir() or self.target_root.exists():
            raise RALValidationError(
                "wave_staging_root_refused",
                "real staging requires existing parent and absent target",
            )
        self._verify_marker()
