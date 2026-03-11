"""JSON, YAML, and schema helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

try:
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover
    Draft7Validator = None


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def validate_schema(instance: Any, schema_path: Path) -> list[str]:
    if Draft7Validator is None:
        return ["jsonschema not installed; validation skipped"]
    schema = read_json(schema_path)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda err: list(err.path))
    return [error.message for error in errors]
