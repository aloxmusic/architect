"""Provider-neutral, immutable patch contracts; no untyped authoritative payloads."""

from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from architect_ai.domain.adg_v1 import (
    Alignment,
    Boundary,
    Camera,
    Distance,
    FixedElement,
    ForbiddenArea,
    FurnitureObject,
    Lighting,
    Lock,
    Material,
    Opening,
    OutputIntent,
    Project,
    RequiredClearance,
    Space,
    Style,
    Wall,
    WallContact,
)
from architect_ai.domain.values import (
    Angle,
    Assertion,
    Clearance,
    Dimensions,
    DomainModel,
    NonNegative,
    Number,
    Point3,
    Positive,
    Source,
    Text,
)

Confidence = Annotated[Number, Field(ge=0, le=1)]
EntityType = Literal[
    "space",
    "wall",
    "opening",
    "fixed_element",
    "furniture",
    "style",
    "material",
    "lighting",
    "camera",
    "output_intent",
    "forbidden_area",
    "required_clearance",
    "wall_contact",
    "alignment",
    "distance",
    "lock",
]


class ChangesBase(DomainModel):
    id: UUID

    @model_serializer(mode="wrap")
    def serialize_changes(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Omitted fields must stay omitted across patch JSON round trips."""
        data: dict[str, Any] = handler(self)
        return {
            key: value
            for key, value in data.items()
            if key in self.model_fields_set or key in {"id", "entity_type"}
        }

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if not self.model_fields_set - {"id", "entity_type"}:
            raise ValueError("An update must explicitly supply at least one field")
        return self


class SpacePayload(DomainModel):
    entity_type: Literal["space"] = "space"
    entity: Space


class SpaceChanges(ChangesBase):
    entity_type: Literal["space"] = "space"
    space_type: Assertion[Text] | None = None
    dimensions: Assertion[Dimensions] | None = None
    floor_elevation: Assertion[Number] | None = None
    ceiling_height: Assertion[Positive] | None = None
    boundary: Assertion[Boundary] | None = None


class WallPayload(DomainModel):
    entity_type: Literal["wall"] = "wall"
    entity: Wall


class WallChanges(ChangesBase):
    entity_type: Literal["wall"] = "wall"
    start: Assertion[Point3] | None = None
    end: Assertion[Point3] | None = None
    thickness: Assertion[Positive] | None = None
    height: Assertion[Positive] | None = None
    wall_type: Assertion[Text] | None = None


class OpeningPayload(DomainModel):
    entity_type: Literal["opening"] = "opening"
    entity: Opening


class OpeningChanges(ChangesBase):
    entity_type: Literal["opening"] = "opening"
    opening_type: Assertion[Literal["door", "window", "opening"]] | None = None
    host_wall_id: Assertion[UUID] | None = None
    position: Assertion[NonNegative] | None = None
    width: Assertion[Positive] | None = None
    height: Assertion[Positive] | None = None
    sill_height: Assertion[NonNegative] | None = None


class FixedElementPayload(DomainModel):
    entity_type: Literal["fixed_element"] = "fixed_element"
    entity: FixedElement


class FixedElementChanges(ChangesBase):
    entity_type: Literal["fixed_element"] = "fixed_element"
    element_type: (
        Assertion[
            Literal[
                "structural_column",
                "shaft",
                "plumbing_point",
                "hvac",
                "electrical_constraint",
                "built_in_element",
            ]
        ]
        | None
    ) = None
    dimensions: Assertion[Dimensions] | None = None
    position: Assertion[Point3] | None = None
    rotation: Assertion[Angle] | None = None


class FurnitureObjectPayload(DomainModel):
    entity_type: Literal["furniture"] = "furniture"
    entity: FurnitureObject


class FurnitureObjectChanges(ChangesBase):
    entity_type: Literal["furniture"] = "furniture"
    object_type: Assertion[Text] | None = None
    dimensions: Assertion[Dimensions] | None = None
    position: Assertion[Point3] | None = None
    rotation: Assertion[Angle] | None = None
    clearance_requirements: Assertion[Clearance] | None = None
    fixed_or_movable: Assertion[Literal["fixed", "movable"]] | None = None
    host_wall_id: Assertion[UUID] | None = None


class StylePayload(DomainModel):
    entity_type: Literal["style"] = "style"
    entity: Style


class StyleChanges(ChangesBase):
    entity_type: Literal["style"] = "style"
    primary_style: Assertion[Text] | None = None
    secondary_influences: Assertion[tuple[Text, ...]] | None = None
    palette: Assertion[tuple[Text, ...]] | None = None
    material_characteristics: Assertion[tuple[Text, ...]] | None = None
    mood: Assertion[Text] | None = None
    design_intensity: Assertion[Annotated[Number, Field(ge=0, le=1)]] | None = None
    prohibited_characteristics: Assertion[tuple[Text, ...]] | None = None


class MaterialPayload(DomainModel):
    entity_type: Literal["material"] = "material"
    entity: Material


class MaterialChanges(ChangesBase):
    entity_type: Literal["material"] = "material"
    generic_material: Assertion[Text] | None = None
    manufacturer: Assertion[Text] | None = None
    collection: Assertion[Text] | None = None
    product: Assertion[Text] | None = None
    finish: Assertion[Text] | None = None
    dimensions: Assertion[Dimensions] | None = None
    verification_status: Assertion[Literal["verified", "unverified"]] | None = None
    source_reference: Assertion[Text] | None = None


class LightingPayload(DomainModel):
    entity_type: Literal["lighting"] = "lighting"
    entity: Lighting


class LightingChanges(ChangesBase):
    entity_type: Literal["lighting"] = "lighting"
    fixture_intent: Assertion[Text] | None = None
    color_temperature: Assertion[Annotated[Positive, Field(le=100000)]] | None = None
    daylight_intent: Assertion[Text] | None = None
    artificial_lighting_intent: Assertion[Text] | None = None
    lighting_mood: Assertion[Text] | None = None


class CameraPayload(DomainModel):
    entity_type: Literal["camera"] = "camera"
    entity: Camera


class CameraChanges(ChangesBase):
    entity_type: Literal["camera"] = "camera"
    position: Assertion[Point3] | None = None
    target: Assertion[Point3] | None = None
    focal_length: Assertion[Positive] | None = None
    field_of_view: Assertion[Annotated[Positive, Field(lt=180)]] | None = None
    aspect_ratio: Assertion[Positive] | None = None
    locked: Assertion[bool] | None = None


class OutputIntentPayload(DomainModel):
    entity_type: Literal["output_intent"] = "output_intent"
    entity: OutputIntent


class OutputIntentChanges(ChangesBase):
    entity_type: Literal["output_intent"] = "output_intent"
    output_type: (
        Assertion[
            Literal[
                "concept",
                "render",
                "floor_plan",
                "elevation",
                "section",
                "dxf",
                "sketchup",
                "animation",
            ]
        ]
        | None
    ) = None
    camera_id: Assertion[UUID] | None = None


class ForbiddenAreaPayload(DomainModel):
    entity_type: Literal["forbidden_area"] = "forbidden_area"
    entity: ForbiddenArea


class ForbiddenAreaChanges(ChangesBase):
    entity_type: Literal["forbidden_area"] = "forbidden_area"
    strength: Literal["hard", "soft"] | None = None
    kind: Literal["forbidden_area"] | None = None
    area: Assertion[Boundary] | None = None
    object_type: Assertion[Text] | None = None


class RequiredClearancePayload(DomainModel):
    entity_type: Literal["required_clearance"] = "required_clearance"
    entity: RequiredClearance


class RequiredClearanceChanges(ChangesBase):
    entity_type: Literal["required_clearance"] = "required_clearance"
    strength: Literal["hard", "soft"] | None = None
    kind: Literal["required_clearance"] | None = None
    target_id: Assertion[UUID] | None = None
    clearance: Assertion[Clearance] | None = None


class WallContactPayload(DomainModel):
    entity_type: Literal["wall_contact"] = "wall_contact"
    entity: WallContact


class WallContactChanges(ChangesBase):
    entity_type: Literal["wall_contact"] = "wall_contact"
    strength: Literal["hard", "soft"] | None = None
    kind: Literal["must_touch_wall", "cannot_touch_wall"] | None = None
    wall_ids: Assertion[Annotated[tuple[UUID, ...], Field(min_length=1)]] | None = None
    object_type: Assertion[Text] | None = None


class AlignmentPayload(DomainModel):
    entity_type: Literal["alignment"] = "alignment"
    entity: Alignment


class AlignmentChanges(ChangesBase):
    entity_type: Literal["alignment"] = "alignment"
    strength: Literal["hard", "soft"] | None = None
    kind: Literal["alignment"] | None = None
    target_ids: Assertion[Annotated[tuple[UUID, ...], Field(min_length=2)]] | None = None
    axis: Assertion[Literal["x", "y", "z"]] | None = None


class DistancePayload(DomainModel):
    entity_type: Literal["distance"] = "distance"
    entity: Distance


class DistanceChanges(ChangesBase):
    entity_type: Literal["distance"] = "distance"
    strength: Literal["hard", "soft"] | None = None
    kind: Literal["minimum_distance", "maximum_distance"] | None = None
    target_ids: Assertion[tuple[UUID, UUID]] | None = None
    distance: Assertion[NonNegative] | None = None


class LockPayload(DomainModel):
    entity_type: Literal["lock"] = "lock"
    entity: Lock


class LockChanges(ChangesBase):
    entity_type: Literal["lock"] = "lock"
    strength: Literal["hard", "soft"] | None = None
    kind: (
        Literal["locked_geometry", "locked_camera", "locked_object", "preserved_element"] | None
    ) = None
    target_id: Assertion[UUID] | None = None


EntityPayload = Annotated[
    SpacePayload
    | WallPayload
    | OpeningPayload
    | FixedElementPayload
    | FurnitureObjectPayload
    | StylePayload
    | MaterialPayload
    | LightingPayload
    | CameraPayload
    | OutputIntentPayload
    | ForbiddenAreaPayload
    | RequiredClearancePayload
    | WallContactPayload
    | AlignmentPayload
    | DistancePayload
    | LockPayload,
    Field(discriminator="entity_type"),
]

EntityChanges = Annotated[
    SpaceChanges
    | WallChanges
    | OpeningChanges
    | FixedElementChanges
    | FurnitureObjectChanges
    | StyleChanges
    | MaterialChanges
    | LightingChanges
    | CameraChanges
    | OutputIntentChanges
    | ForbiddenAreaChanges
    | RequiredClearanceChanges
    | WallContactChanges
    | AlignmentChanges
    | DistanceChanges
    | LockChanges,
    Field(discriminator="entity_type"),
]


class OperationContext(DomainModel):
    source: Source
    confidence: Confidence
    origin: Text | None = None


class AddEntity(OperationContext):
    operation: Literal["ADD_ENTITY"] = "ADD_ENTITY"
    payload: EntityPayload


class UpdateEntity(OperationContext):
    operation: Literal["UPDATE_ENTITY"] = "UPDATE_ENTITY"
    target_id: UUID
    changes: EntityChanges


class RemoveEntity(OperationContext):
    operation: Literal["REMOVE_ENTITY"] = "REMOVE_ENTITY"
    target_id: UUID
    entity_type: EntityType


class AddConstraint(OperationContext):
    operation: Literal["ADD_CONSTRAINT"] = "ADD_CONSTRAINT"
    payload: EntityPayload


class UpdateConstraint(OperationContext):
    operation: Literal["UPDATE_CONSTRAINT"] = "UPDATE_CONSTRAINT"
    target_id: UUID
    changes: EntityChanges


class RemoveConstraint(OperationContext):
    operation: Literal["REMOVE_CONSTRAINT"] = "REMOVE_CONSTRAINT"
    target_id: UUID
    entity_type: EntityType


PatchOperation = Annotated[
    AddEntity | UpdateEntity | RemoveEntity | AddConstraint | UpdateConstraint | RemoveConstraint,
    Field(discriminator="operation"),
]


class ADGPatch(DomainModel):
    project_id: UUID
    base_fingerprint: Text | None = None
    operations: Annotated[tuple[PatchOperation, ...], Field(min_length=1)]


class ConflictCode(StrEnum):
    LOCKED_ENTITY = "LOCKED_ENTITY"
    PRESERVED_ELEMENT = "PRESERVED_ELEMENT"
    CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"
    MISSING_TARGET = "MISSING_TARGET"
    ID_MISMATCH = "ID_MISMATCH"
    INVALID_REFERENCE = "INVALID_REFERENCE"
    GEOMETRY_VALIDATION_FAILED = "GEOMETRY_VALIDATION_FAILED"
    PROVENANCE_CONFLICT = "PROVENANCE_CONFLICT"
    DESTRUCTIVE_CHANGE_REQUIRES_CONFIRMATION = "DESTRUCTIVE_CHANGE_REQUIRES_CONFIRMATION"
    STALE_BASE = "STALE_BASE"
    VALIDATION_FAILED = "VALIDATION_FAILED"


class Conflict(DomainModel):
    code: ConflictCode
    severity: Literal["error", "clarification"] = "error"
    message: Text
    target_ids: tuple[UUID, ...] = ()
    constraint_ids: tuple[UUID, ...] = ()
    fields: tuple[str, ...] = ()
    existing: EntityPayload | None = None
    proposed: PatchOperation | None = None
    operation_index: int | None = None
    requires_clarification: bool = False


class PatchStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class ProjectContext(DomainModel):
    project_id: UUID
    schema_version: Literal["1.0.0"] = "1.0.0"
    fingerprint: Text


class PatchResult(DomainModel):
    status: PatchStatus
    original: ProjectContext
    candidate: Project | None = None
    conflicts: tuple[Conflict, ...] = ()
    applied_operations: tuple[PatchOperation, ...] = ()
    rejected_operations: tuple[PatchOperation, ...] = ()
