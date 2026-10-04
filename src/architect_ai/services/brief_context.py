"""Compact deterministic structured context, retaining ADG facts and UUIDs."""

from architect_ai.domain.adg_v1 import Project
from architect_ai.domain.patches import ConflictCode
from architect_ai.domain.values import Assertion
from architect_ai.services.brief_contracts import InterpretationContext
from architect_ai.services.patching import payload, project_context, protection


def build_project_context(project: Project) -> InterpretationContext:
    entities = sorted(project.entities(), key=lambda entity: str(entity.id))
    locked: list[str] = []
    preserved: list[str] = []
    for entity in entities:
        protected = protection(project, entity.id)
        if protected is not None:
            (preserved if protected[0] == ConflictCode.PRESERVED_ELEMENT else locked).append(
                str(entity.id)
            )
    return InterpretationContext(
        snapshot=project_context(project),
        name=project.name,
        project_type=project.project_type,
        locale=Assertion[str].model_validate(project.locale.model_dump()),
        status=Assertion[str].model_validate(project.status.model_dump()),
        units=project.units,
        entities=tuple(payload(entity) for entity in entities),
        locked_ids=tuple(locked),
        preserved_ids=tuple(preserved),
    )
