"""An interpreter's proposal, independent of providers and authoritative ADG updates."""

from typing import Literal
from uuid import UUID

from architect_ai.domain.patches import Confidence, EntityType
from architect_ai.domain.values import Assertion, DomainModel, Text

OperationName = Literal[
    "ADD_ENTITY",
    "UPDATE_ENTITY",
    "REMOVE_ENTITY",
    "ADD_CONSTRAINT",
    "UPDATE_CONSTRAINT",
    "REMOVE_CONSTRAINT",
]


class IntentRequest(DomainModel):
    instruction: Assertion[Text]
    operation: OperationName
    target_ids: tuple[UUID, ...] = ()
    target_types: tuple[EntityType, ...] = ()


class ArchitecturalFact(DomainModel):
    statement: Assertion[Text]
    target_ids: tuple[UUID, ...] = ()


class PreservationInstruction(DomainModel):
    instruction: Assertion[Text]
    target_ids: tuple[UUID, ...] = ()
    target_types: tuple[EntityType, ...] = ()


class ArchitecturalIntent(DomainModel):
    goal: Assertion[Text]
    target_ids: tuple[UUID, ...] = ()
    target_types: tuple[EntityType, ...] = ()
    requested_operations: tuple[IntentRequest, ...] = ()
    explicit_facts: tuple[ArchitecturalFact, ...] = ()
    style_changes: tuple[IntentRequest, ...] = ()
    material_changes: tuple[IntentRequest, ...] = ()
    lighting_changes: tuple[IntentRequest, ...] = ()
    furniture_changes: tuple[IntentRequest, ...] = ()
    camera_changes: tuple[IntentRequest, ...] = ()
    requested_outputs: tuple[IntentRequest, ...] = ()
    preservation_instructions: tuple[PreservationInstruction, ...] = ()
    ambiguities: tuple[Text, ...] = ()
    assumptions: tuple[Assertion[Text], ...] = ()
    confidence: Confidence
