"""Immutable, provider-neutral compilation IR; independent of the ADG schema version."""

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import model_validator

from architect_ai.domain.adg_v1 import (
    Camera,
    Constraint,
    FixedElement,
    FurnitureObject,
    Lighting,
    Material,
    Opening,
    Space,
    Style,
    Wall,
)
from architect_ai.domain.intent import IntentRequest, PreservationInstruction
from architect_ai.domain.patches import EntityType, ProjectContext
from architect_ai.domain.values import Assertion, DomainModel, Positive, Source, Text

COMPILER_VERSION: Literal["generation-brief-v1"] = "generation-brief-v1"


class GenerationMode(StrEnum):
    CONCEPT_MODE = "CONCEPT_MODE"
    DESIGN_DEVELOPMENT_MODE = "DESIGN_DEVELOPMENT_MODE"
    GEOMETRY_LOCKED_RENDER_MODE = "GEOMETRY_LOCKED_RENDER_MODE"
    MATERIAL_REVISION_MODE = "MATERIAL_REVISION_MODE"
    LIGHTING_REVISION_MODE = "LIGHTING_REVISION_MODE"
    CAMERA_LOCKED_MODE = "CAMERA_LOCKED_MODE"


class OutputTarget(StrEnum):
    CONCEPT_IMAGE = "concept_image"
    ARCHITECTURAL_RENDER = "architectural_render"
    IMAGE_EDIT = "image_edit"
    MATERIAL_STUDY = "material_study"
    LIGHTING_STUDY = "lighting_study"
    STYLE_STUDY = "style_study"


class ChangeCategory(StrEnum):
    GEOMETRY = "geometry"
    OPENINGS = "openings"
    FIXED_ELEMENTS = "fixed_elements"
    FURNITURE_POSITIONS = "furniture_positions"
    FURNITURE_DESIGN = "furniture_design"
    MATERIALS = "materials"
    LIGHTING = "lighting"
    CAMERA = "camera"
    STYLE = "style"
    DECOR = "decor"
    ENVIRONMENT = "environment"


class ChangePermission(StrEnum):
    ALLOW = "ALLOW"
    PRESERVE = "PRESERVE"
    LOCKED = "LOCKED"


class ChangeScope(DomainModel):
    """Trusted categorization of an existing accepted request, never free-form parsing."""

    category: ChangeCategory
    request: IntentRequest


class MetadataItem(DomainModel):
    key: Text
    value: Assertion[Text]


class OutputSpecification(DomainModel):
    target: OutputTarget
    space_id: UUID | None = None
    camera_id: UUID | None = None
    output_intent_id: UUID | None = None
    aspect_ratio: Assertion[Positive] | None = None
    presentation: tuple[Assertion[Text], ...] = ()
    metadata: tuple[MetadataItem, ...] = ()


class ReferenceRole(StrEnum):
    GEOMETRY_AUTHORITY = "geometry_authority"
    STYLE_REFERENCE = "style_reference"
    MATERIAL_REFERENCE = "material_reference"


class ReferenceImage(DomainModel):
    """Availability/authority contract only; no asset, upload or storage implementation."""

    available: bool = False
    roles: tuple[ReferenceRole, ...] = ()
    preserve_camera: bool = False
    preserve_composition: bool = False

    @model_validator(mode="after")
    def require_available_reference(self) -> Self:
        if not self.available and (self.roles or self.preserve_camera or self.preserve_composition):
            raise ValueError("Reference authority requires an available reference image")
        return self


class CompilationOptions(DomainModel):
    output: OutputSpecification
    mode: GenerationMode
    reference: ReferenceImage = ReferenceImage()
    change_scopes: tuple[ChangeScope, ...] = ()


class CategoryPermission(DomainModel):
    category: ChangeCategory
    permission: ChangePermission
    allowed_entity_ids: tuple[UUID, ...] = ()
    new_entity_types: tuple[EntityType, ...] = ()
    requests: tuple[IntentRequest, ...] = ()


class EntityPermission(DomainModel):
    entity_id: UUID
    category: ChangeCategory
    permission: ChangePermission


class ModePolicy(DomainModel):
    mode: GenerationMode
    eligible_categories: tuple[ChangeCategory, ...]
    preserve_categories: tuple[ChangeCategory, ...]


class ProjectSubject(DomainModel):
    snapshot: ProjectContext
    name: Assertion[Text]
    project_type: Assertion[Text]
    relevant_space: Space
    locale: Assertion[Text]
    units: Literal["mm"]


class GeometryBrief(DomainModel):
    walls: tuple[Wall, ...]
    openings: tuple[Opening, ...]
    fixed_elements: tuple[FixedElement, ...]
    furniture: tuple[FurnitureObject, ...]
    allowed_geometry_ids: tuple[UUID, ...]
    preserved_geometry_ids: tuple[UUID, ...]
    locked_geometry_ids: tuple[UUID, ...]
    preserved_entity_ids: tuple[UUID, ...]
    spatial_constraints: tuple[Constraint, ...]


class DesignBrief(DomainModel):
    styles: tuple[Style, ...]
    requested_style_changes: tuple[IntentRequest, ...]
    architectural_language: tuple[Assertion[Text], ...] = ()
    furniture_intent: tuple[IntentRequest, ...] = ()
    decorative_intent: tuple[IntentRequest, ...] = ()


class MaterialEntry(DomainModel):
    id: UUID
    generic_material: Assertion[Text]
    verification_status: Assertion[Literal["verified", "unverified"]]
    verified_facts: Material | None = None
    unverified_product_intent: tuple[Assertion[Text], ...] = ()


class MaterialBrief(DomainModel):
    existing: tuple[MaterialEntry, ...]
    requested_changes: tuple[IntentRequest, ...]
    characteristics: tuple[Assertion[tuple[Text, ...]], ...]
    unchanged_material_ids: tuple[UUID, ...]
    unchanged_surfaces: tuple[PreservationInstruction, ...]


class LightingBrief(DomainModel):
    elements: tuple[Lighting, ...]
    requested_changes: tuple[IntentRequest, ...]
    unchanged_ids: tuple[UUID, ...]
    contrast: Assertion[Text] | None = None
    exposure_intent: Assertion[Text] | None = None


class CameraBrief(DomainModel):
    camera: Camera | None
    lock_state: ChangePermission
    preserve_composition: bool
    requested_changes: tuple[IntentRequest, ...]


class RealismBrief(DomainModel):
    """Rendering policies, not invented material, construction or lighting facts."""

    physically_plausible_materials: Assertion[bool]
    texture_scale: Assertion[Text]
    surface_detail: Assertion[Text]
    reflections: Assertion[Text]
    believable_construction: Assertion[bool]
    realistic_lighting: Assertion[bool]
    photographic_intent: Assertion[bool]


class ForbiddenChanges(DomainModel):
    categories: tuple[ChangeCategory, ...]
    protected_ids: tuple[UUID, ...]
    prohibited_style_characteristics: tuple[Assertion[tuple[Text, ...]], ...]
    project_restrictions: tuple[Constraint, ...]
    intent_preservation: tuple[PreservationInstruction, ...]


class CompilationTrace(DomainModel):
    field_path: Text
    origin: Literal["ADG", "ACCEPTED_INTENT", "SYSTEM_COMPILATION"]
    source: Source
    source_reference: Text | None = None


class GenerationBrief(DomainModel):
    compiler_version: Literal["generation-brief-v1"] = COMPILER_VERSION
    project: ProjectSubject
    goal: Assertion[Text]
    output: OutputSpecification
    mode_policy: ModePolicy
    permissions: tuple[CategoryPermission, ...]
    entity_permissions: tuple[EntityPermission, ...]
    geometry: GeometryBrief
    design: DesignBrief
    materials: MaterialBrief
    lighting: LightingBrief
    camera: CameraBrief
    realism: RealismBrief
    forbidden_changes: ForbiddenChanges
    reference: ReferenceImage
    accepted_facts: tuple[Assertion[Text], ...]
    assumptions: tuple[Assertion[Text], ...]
    withheld_requests: tuple[IntentRequest, ...]
    traceability: tuple[CompilationTrace, ...] = ()

    def permission(self, category: ChangeCategory) -> CategoryPermission:
        return next(item for item in self.permissions if item.category == category)


class CompiledInstructionPackage(DomainModel):
    compiler_version: Text
    instruction_version: Text
    adapter: Text
    primary_instruction: Text
    preservation_instruction: Text
    negative_instruction: Text
    reference_guidance: tuple[Text, ...]
    output: OutputSpecification
    mode_policy: ModePolicy
    permissions: tuple[CategoryPermission, ...]
    entity_permissions: tuple[EntityPermission, ...]
    forbidden_changes: ForbiddenChanges
    reference: ReferenceImage
    brief_fingerprint: Text
