"""Explicit version dispatch; no migrations or implicit schema upgrades."""

import json
from typing import Any

from architect_ai.domain.adg_v1 import Project


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def deserialize_project(document: str) -> Project:
    data = json.loads(document, object_pairs_hook=reject_duplicate_keys)
    if not isinstance(data, dict) or data.get("schema_version") != "1.0.0":
        raise ValueError("Unsupported or missing ADG schema_version; expected 1.0.0")
    return Project.model_validate(data)


def serialize_project(project: Project) -> str:
    validated = Project.model_validate(project)
    return json.dumps(validated.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
