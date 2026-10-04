"""SDK-compatible structured transport; decoded into existing domain proposals."""

from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, TypeAdapter

from architect_ai.domain.intent import ArchitecturalIntent, OperationName
from architect_ai.domain.patches import ADGPatch, EntityType, PatchOperation
from architect_ai.domain.values import Assertion, Source, exact_decimal
from architect_ai.services.brief_contracts import BriefRequest, InterpretationProposal


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WireTextAssertion(WireModel):
    value: str
    source: Source
    source_reference: str | None


class WireIntentRequest(WireModel):
    instruction: WireTextAssertion
    operation: OperationName
    target_ids: list[UUID]
    target_types: list[EntityType]


class WireFact(WireModel):
    statement: WireTextAssertion
    target_ids: list[UUID]


class WirePreservation(WireModel):
    instruction: WireTextAssertion
    target_ids: list[UUID]
    target_types: list[EntityType]


class WirePoint(WireModel):
    kind: Literal["point"]
    x: str
    y: str
    z: str | None


class WireDimensions(WireModel):
    kind: Literal["dimensions"]
    width: str
    depth: str
    height: str


class WireClearance(WireModel):
    kind: Literal["clearance"]
    front: str
    back: str
    left: str
    right: str
    above: str


class WireBoundary(WireModel):
    kind: Literal["boundary"]
    vertices: list[WirePoint]


WireValue = (
    StrictStr
    | StrictBool
    | list[str]
    | WirePoint
    | WireDimensions
    | WireClearance
    | WireBoundary
    | None
)


FieldName = Literal[
    "area",
    "artificial_lighting_intent",
    "aspect_ratio",
    "axis",
    "boundary",
    "camera_id",
    "ceiling_height",
    "clearance",
    "clearance_requirements",
    "collection",
    "color_temperature",
    "daylight_intent",
    "design_intensity",
    "dimensions",
    "distance",
    "element_type",
    "end",
    "field_of_view",
    "finish",
    "fixed_or_movable",
    "fixture_intent",
    "floor_elevation",
    "focal_length",
    "generic_material",
    "height",
    "host_wall_id",
    "kind",
    "lighting_mood",
    "locked",
    "manufacturer",
    "material_characteristics",
    "mood",
    "object_type",
    "opening_type",
    "output_type",
    "palette",
    "position",
    "primary_style",
    "product",
    "prohibited_characteristics",
    "rotation",
    "secondary_influences",
    "sill_height",
    "source_reference",
    "space_type",
    "start",
    "strength",
    "target",
    "target_id",
    "target_ids",
    "thickness",
    "verification_status",
    "vertices",
    "wall_ids",
    "wall_type",
    "width",
]


class WireChange(WireModel):
    field: FieldName
    value: WireValue
    source: Source
    source_reference: str | None


class WireOperation(WireModel):
    operation: OperationName
    target_id: UUID | None
    entity_type: EntityType
    changes: list[WireChange]
    source: Source
    confidence: str
    origin: str | None


class WireIntent(WireModel):
    goal: WireTextAssertion
    target_ids: list[UUID]
    target_types: list[EntityType]
    requested_operations: list[WireIntentRequest]
    explicit_facts: list[WireFact]
    style_changes: list[WireIntentRequest]
    material_changes: list[WireIntentRequest]
    lighting_changes: list[WireIntentRequest]
    furniture_changes: list[WireIntentRequest]
    camera_changes: list[WireIntentRequest]
    requested_outputs: list[WireIntentRequest]
    preservation_instructions: list[WirePreservation]
    ambiguities: list[str]
    assumptions: list[WireTextAssertion]
    confidence: str


class WireProposal(WireModel):
    intent: WireIntent
    operations: list[WireOperation]
    ambiguities: list[str]
    assumptions: list[WireTextAssertion]
    confidence: str
    clarification_recommended: bool


PATCH_OPERATION = TypeAdapter[PatchOperation](PatchOperation)


def decode_value(value: WireValue) -> Any:
    if isinstance(value, WireBoundary):
        return {"vertices": [decode_value(point) for point in value.vertices]}
    if isinstance(value, WireModel):
        return value.model_dump(exclude={"kind"}, exclude_none=True)
    return value


def decode_proposal(wire: WireProposal, request: BriefRequest) -> InterpretationProposal:
    operations: list[PatchOperation] = []
    for index, operation in enumerate(wire.operations):
        fields: dict[str, Any] = {}
        for change in operation.changes:
            if change.field in fields or change.field in {"id", "entity_type", "operation"}:
                raise ValueError("Duplicate or structural ID field in proposal")
            value = decode_value(change.value)
            fields[change.field] = (
                value
                if value is None or change.field in {"kind", "strength"}
                else {
                    "value": value,
                    "source": change.source,
                    "source_reference": change.source_reference,
                }
            )
        data: dict[str, Any] = {
            "operation": operation.operation,
            "source": operation.source,
            "confidence": operation.confidence,
            "origin": operation.origin,
        }
        if operation.operation.startswith("ADD_"):
            if operation.target_id is not None:
                raise ValueError("New IDs are allocated by the application, not the model")
            new_id = uuid5(
                request.context.snapshot.project_id,
                f"{request.context.snapshot.fingerprint}:{request.text}:{index}:{operation.entity_type}",
            )
            data["payload"] = {
                "entity_type": operation.entity_type,
                "entity": {"id": new_id, **fields},
            }
        else:
            if operation.target_id is None:
                raise ValueError("Existing operations require a target ID")
            data["target_id"] = operation.target_id
            if operation.operation.startswith("UPDATE_"):
                data["changes"] = {
                    "entity_type": operation.entity_type,
                    "id": operation.target_id,
                    **fields,
                }
            else:
                if fields:
                    raise ValueError("Removal must not carry field changes")
                data["entity_type"] = operation.entity_type
        operations.append(PATCH_OPERATION.validate_python(data))
    patch = (
        ADGPatch(
            project_id=request.context.snapshot.project_id,
            base_fingerprint=request.context.snapshot.fingerprint,
            operations=tuple(operations),
        )
        if operations
        else None
    )
    return InterpretationProposal(
        intent=ArchitecturalIntent.model_validate(wire.intent.model_dump()),
        proposed_patch=patch,
        ambiguities=tuple(wire.ambiguities),
        assumptions=tuple(
            Assertion[str].model_validate(item.model_dump()) for item in wire.assumptions
        ),
        confidence=exact_decimal(wire.confidence),
        clarification_recommended=wire.clarification_recommended,
    )
