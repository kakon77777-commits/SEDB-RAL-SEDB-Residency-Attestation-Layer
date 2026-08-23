from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .errors import RALValidationError


def default_schema_root() -> Path:
    return Path(__file__).with_name("schemas")


def load_schema(
    name: str, schema_root: Path | None = None
) -> dict[str, object]:
    source = (schema_root or default_schema_root()) / name
    return json.loads(source.read_text(encoding="utf-8"))


def _registry(schema_root: Path) -> Registry:
    registry = Registry()
    for path in sorted(schema_root.glob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema)
        )
    return registry


def validate_contract(
    name: str,
    value: object,
    schema_root: Path | None = None,
) -> None:
    root = schema_root or default_schema_root()
    errors = sorted(
        Draft202012Validator(
            load_schema(name, root),
            registry=_registry(root),
        ).iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.path),
    )
    if errors:
        error = errors[0]
        raise RALValidationError(
            "schema_invalid",
            error.message,
            tuple(str(part) for part in error.path),
        )
