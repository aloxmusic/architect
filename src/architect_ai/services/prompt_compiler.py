"""Deterministic compilation of an authoritative snapshot and caller-accepted intent."""

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from architect_ai.domain.adg_v1 import Camera, Entity, Material, Project, Space
from architect_ai.domain.generation import (
    COMPILER_VERSION,
    CameraBrief,
    CategoryPermission,
    ChangeCategory,
    ChangePermission,
    ChangeScope,
    CompilationOptions,
    CompilationTrace,
    DesignBrief,
    EntityPermission,
    ForbiddenChanges,
    GenerationBrief,
    GenerationMode,
    GeometryBrief,
    LightingBrief,
    MaterialBrief,
    MaterialEntry,
    ModePolicy,
    ProjectSubject,
    RealismBrief,
    ReferenceRole,
)
from architect_ai.domain.intent import ArchitecturalIntent, IntentRequest
from architect_ai.domain.patches import ConflictCode, EntityType
from architect_ai.domain.values import Assertion, Source
from architect_ai.services.patching import entity_type, graph_conflicts, project_context, protection


class CompilationErrorCode(StrEnum):
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    AMBIGUOUS_INTENT = "AMBIGUOUS_INTENT"
    INVALID_SCOPE = "INVALID_SCOPE"
    INVALID_CONSTRAINTS = "INVALID_CONSTRAINTS"
    CONFLICTING_OUTPUT = "CONFLICTING_OUTPUT"


class CompilationError(ValueError):
    def __init__(self, code: CompilationErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


CATEGORY_TYPES: dict[ChangeCategory, tuple[EntityType, ...]] = {
    ChangeCategory.GEOMETRY: ("space", "wall"),
    ChangeCategory.OPENINGS: ("opening",),
    ChangeCategory.FIXED_ELEMENTS: ("fixed_element",),
    ChangeCategory.FURNITURE_POSITIONS: ("furniture",),
    ChangeCategory.FURNITURE_DESIGN: ("furniture",),
    ChangeCategory.MATERIALS: ("material",),
    ChangeCategory.LIGHTING: ("lighting",),
    ChangeCategory.CAMERA: ("camera",),
    ChangeCategory.STYLE: ("style",),
    ChangeCategory.DECOR: (),
    ChangeCategory.ENVIRONMENT: (),
}
GEOMETRIC = (
    ChangeCategory.GEOMETRY,
    ChangeCategory.OPENINGS,
    ChangeCategory.FIXED_ELEMENTS,
    ChangeCategory.FURNITURE_POSITIONS,
)


def mode_policy(mode: GenerationMode) -> ModePolicy:
    preserved: tuple[ChangeCategory, ...] = ()
    if mode in {
        GenerationMode.DESIGN_DEVELOPMENT_MODE,
        GenerationMode.GEOMETRY_LOCKED_RENDER_MODE,
    }:
        preserved = GEOMETRIC
    elif mode == GenerationMode.MATERIAL_REVISION_MODE:
        preserved = tuple(c for c in ChangeCategory if c != ChangeCategory.MATERIALS)
    elif mode == GenerationMode.LIGHTING_REVISION_MODE:
        preserved = tuple(c for c in ChangeCategory if c != ChangeCategory.LIGHTING)
    elif mode == GenerationMode.CAMERA_LOCKED_MODE:
        preserved = (ChangeCategory.CAMERA,)
    return ModePolicy(
        mode=mode,
        eligible_categories=tuple(c for c in ChangeCategory if c not in preserved),
        preserve_categories=preserved,
    )


def intent_requests(intent: ArchitecturalIntent) -> tuple[IntentRequest, ...]:
    return tuple(
        dict.fromkeys(
            (
                *intent.requested_operations,
                *intent.style_changes,
                *intent.material_changes,
                *intent.lighting_changes,
                *intent.furniture_changes,
                *intent.camera_changes,
                *intent.requested_outputs,
            )
        )
    )


def scopes_for(intent: ArchitecturalIntent, options: CompilationOptions) -> tuple[ChangeScope, ...]:
    groups = (
        (ChangeCategory.STYLE, intent.style_changes),
        (ChangeCategory.MATERIALS, intent.material_changes),
        (ChangeCategory.LIGHTING, intent.lighting_changes),
        (ChangeCategory.FURNITURE_DESIGN, intent.furniture_changes),
        (ChangeCategory.CAMERA, intent.camera_changes),
    )
    result = [ChangeScope(category=c, request=r) for c, requests in groups for r in requests]
    requests = intent_requests(intent)
    for scope in options.change_scopes:
        if scope.request not in requests:
            raise CompilationError(CompilationErrorCode.INVALID_SCOPE)
        result.append(scope)
    covered = {s.request for s in result}
    for request in intent.requested_operations:
        if request in covered or request in intent.requested_outputs:
            continue
        for category, kinds in CATEGORY_TYPES.items():
            if category in {ChangeCategory.FURNITURE_DESIGN, ChangeCategory.FURNITURE_POSITIONS}:
                continue
            if request.target_types and set(request.target_types) <= set(kinds):
                result.append(ChangeScope(category=category, request=request))
                break
        else:
            raise CompilationError(CompilationErrorCode.INVALID_SCOPE)
    return tuple(dict.fromkeys(result))


def select_space(project: Project, requested: UUID | None) -> Space:
    candidates = tuple(s for s in project.spaces if requested is None or s.id == requested)
    if len(candidates) != 1:
        raise CompilationError(CompilationErrorCode.AMBIGUOUS_TARGET)
    # ADG v1 has no per-space entity membership. Never pretend to filter multiple rooms.
    if len(project.spaces) != 1:
        raise CompilationError(CompilationErrorCode.AMBIGUOUS_TARGET)
    return candidates[0]


def select_camera(project: Project, options: CompilationOptions) -> Camera | None:
    output = options.output
    output_intents = tuple(o for o in project.output_intents if o.id == output.output_intent_id)
    if output.output_intent_id is not None and len(output_intents) != 1:
        raise CompilationError(CompilationErrorCode.AMBIGUOUS_TARGET)
    selected = output.camera_id
    linked = output_intents[0].camera_id if output_intents else None
    if linked is not None:
        if selected is not None and selected != linked.value:
            raise CompilationError(CompilationErrorCode.CONFLICTING_OUTPUT)
        selected = linked.value
    if selected is None:
        linked_ids = {o.camera_id.value for o in project.output_intents if o.camera_id is not None}
        if len(linked_ids) > 1:
            raise CompilationError(CompilationErrorCode.AMBIGUOUS_TARGET)
        selected = next(iter(linked_ids), None)
    cameras = tuple(c for c in project.cameras if selected is None or c.id == selected)
    if len(cameras) > 1 or (selected is not None and not cameras):
        raise CompilationError(CompilationErrorCode.AMBIGUOUS_TARGET)
    return cameras[0] if cameras else None


def material_entry(material: Material) -> MaterialEntry:
    assertions = (
        material.generic_material,
        material.manufacturer,
        material.collection,
        material.product,
        material.finish,
        material.dimensions,
        material.source_reference,
    )
    verified = material.verification_status.value == "verified" and all(
        a.source != Source.AI_INFERRED for a in assertions if a is not None
    )
    return MaterialEntry(
        id=material.id,
        generic_material=material.generic_material,
        verification_status=material.verification_status,
        verified_facts=material if verified else None,
        unverified_product_intent=tuple(
            a
            for a in (material.manufacturer, material.collection, material.product)
            if a is not None and not verified
        ),
    )


def compilation_traces(data: Any, path: str = "") -> tuple[CompilationTrace, ...]:
    traces: list[CompilationTrace] = []
    if isinstance(data, dict):
        if "source" in data and "value" in data:
            intent_field = path.startswith(
                (
                    "goal",
                    "accepted_facts",
                    "assumptions",
                    "withheld_requests",
                    "design.requested_style_changes",
                    "design.furniture_intent",
                    "design.decorative_intent",
                    "materials.requested_changes",
                    "materials.unchanged_surfaces",
                    "lighting.requested_changes",
                    "camera.requested_changes",
                    "forbidden_changes.intent_preservation",
                )
            )
            intent_field = intent_field or (
                path.startswith("permissions[") and ".requests[" in path
            )
            origin: Literal["ADG", "ACCEPTED_INTENT", "SYSTEM_COMPILATION"] = (
                "SYSTEM_COMPILATION"
                if path.startswith("realism.")
                else "ACCEPTED_INTENT"
                if intent_field or path.startswith("output.")
                else "ADG"
            )
            traces.append(
                CompilationTrace(
                    field_path=path,
                    origin=origin,
                    source=data["source"],
                    source_reference=data.get("source_reference"),
                )
            )
        else:
            for name, value in data.items():
                traces.extend(compilation_traces(value, f"{path}.{name}" if path else name))
    elif isinstance(data, (list, tuple)):
        for index, value in enumerate(data):
            traces.extend(compilation_traces(value, f"{path}[{index}]"))
    return tuple(traces)


def compile_generation_brief(
    project: Project,
    accepted_intent: ArchitecturalIntent,
    options: CompilationOptions,
) -> GenerationBrief:
    """Caller supplies accepted intent; this is not a proposal acceptance boundary."""
    project = Project.model_validate(project)
    intent = ArchitecturalIntent.model_validate(accepted_intent)
    options = CompilationOptions.model_validate(options)
    if intent.ambiguities:
        raise CompilationError(CompilationErrorCode.AMBIGUOUS_INTENT)
    if graph_conflicts(project.entities()):
        raise CompilationError(CompilationErrorCode.INVALID_CONSTRAINTS)
    space, camera = select_space(project, options.output.space_id), select_camera(project, options)
    entities = tuple(sorted(project.entities(), key=lambda e: str(e.id)))
    by_id = {e.id: e for e in entities}
    requests = intent_requests(intent)
    targets = (
        *intent.target_ids,
        *(i for r in requests for i in r.target_ids),
        *(i for f in intent.explicit_facts for i in f.target_ids),
        *(i for p in intent.preservation_instructions for i in p.target_ids),
    )
    if any(i not in by_id for i in targets):
        raise CompilationError(CompilationErrorCode.INVALID_SCOPE)
    protected = {e.id for e in entities if protection(project, e.id) is not None}
    preserved = {
        e.id
        for e in entities
        if (p := protection(project, e.id)) is not None and p[0] == ConflictCode.PRESERVED_ELEMENT
    }
    # A locked wall cannot acquire a changed opening; a locked room protects its architecture.
    if space.id in protected:
        protected.update(e.id for e in (*project.walls, *project.openings, *project.fixed_elements))
    protected.update(o.id for o in project.openings if o.host_wall_id.value in protected)
    for item in intent.preservation_instructions:
        if not item.target_ids and not item.target_types:
            raise CompilationError(CompilationErrorCode.INVALID_SCOPE)
        preserved.update(item.target_ids)
        preserved.update(e.id for e in entities if entity_type(e) in item.target_types)
    if space.id in preserved:
        preserved.update(e.id for e in (*project.walls, *project.openings, *project.fixed_elements))
    preserved.update(o.id for o in project.openings if o.host_wall_id.value in preserved)
    intent_preserved = set(preserved)
    policy = mode_policy(options.mode)
    mode_preserved = set(policy.preserve_categories)
    if ReferenceRole.GEOMETRY_AUTHORITY in options.reference.roles:
        mode_preserved.update(GEOMETRIC)
    if options.reference.preserve_camera or options.reference.preserve_composition:
        mode_preserved.add(ChangeCategory.CAMERA)
    scopes = scopes_for(intent, options)
    category_permissions: list[CategoryPermission] = []
    entity_permissions: list[EntityPermission] = []
    withheld: list[IntentRequest] = []
    for category in ChangeCategory:
        kinds = CATEGORY_TYPES[category]
        relevant = tuple(e for e in entities if entity_type(e) in kinds)
        if category == ChangeCategory.CAMERA:
            relevant = (camera,) if camera is not None else ()
        selected_scopes = tuple(s for s in scopes if s.category == category)
        allowed_ids: set[UUID] = set()
        new_types: set[EntityType] = set()
        effective: list[IntentRequest] = []
        for scope in selected_scopes:
            r = scope.request
            if kinds and (
                any(entity_type(by_id[i]) not in kinds for i in r.target_ids)
                or any(t not in kinds for t in r.target_types)
            ):
                raise CompilationError(CompilationErrorCode.INVALID_SCOPE)
            matched = {
                e.id
                for e in relevant
                if (not r.target_ids or e.id in r.target_ids)
                and (not r.target_types or entity_type(e) in r.target_types)
            }
            denied = matched & (protected | preserved)
            if category in mode_preserved or denied:
                withheld.append(r)
                continue
            if r.target_ids and matched != set(r.target_ids):
                raise CompilationError(CompilationErrorCode.INVALID_SCOPE)
            if kinds and not matched and r.operation != "ADD_ENTITY":
                raise CompilationError(CompilationErrorCode.INVALID_SCOPE)
            effective.append(r)
            allowed_ids.update(matched)
            if r.operation == "ADD_ENTITY":
                new_types.update(r.target_types or kinds)
        all_locked = bool(relevant) and all(e.id in protected for e in relevant)
        permission = (
            ChangePermission.LOCKED
            if all_locked and not effective
            else ChangePermission.ALLOW
            if effective
            else ChangePermission.PRESERVE
        )
        category_permissions.append(
            CategoryPermission(
                category=category,
                permission=permission,
                allowed_entity_ids=tuple(sorted(allowed_ids, key=str)),
                new_entity_types=tuple(sorted(new_types)),
                requests=tuple(dict.fromkeys(effective)),
            )
        )
        for e in relevant:
            entity_permissions.append(
                EntityPermission(
                    entity_id=e.id,
                    category=category,
                    permission=(
                        ChangePermission.LOCKED
                        if e.id in protected
                        else ChangePermission.ALLOW
                        if e.id in allowed_ids
                        else ChangePermission.PRESERVE
                    ),
                )
            )
    permissions = {p.category: p for p in category_permissions}
    ep = tuple(entity_permissions)
    geometry_ep = tuple(p for p in ep if p.category in GEOMETRIC)
    preserved_geometry = {
        p.entity_id for p in geometry_ep if p.permission != ChangePermission.ALLOW
    }
    preserved.update(protected)
    preserved.update(
        e.id
        for e in entities
        if (entity_rules := tuple(p for p in ep if p.entity_id == e.id))
        and all(p.permission != ChangePermission.ALLOW for p in entity_rules)
    )
    camera_permission = permissions[ChangeCategory.CAMERA].permission
    output = options.output
    if camera is not None:
        if (
            output.aspect_ratio is not None
            and output.aspect_ratio.value != camera.aspect_ratio.value
        ):
            if camera_permission != ChangePermission.ALLOW:
                raise CompilationError(CompilationErrorCode.CONFLICTING_OUTPUT)
        output = output.model_copy(
            update={
                "camera_id": camera.id,
                "aspect_ratio": output.aspect_ratio or camera.aspect_ratio,
            }
        )
    output = output.model_copy(update={"space_id": space.id})
    system_bool = Assertion[bool](
        value=True, source=Source.SYSTEM_DERIVED, source_reference=COMPILER_VERSION
    )

    def policy_text(text: str) -> Assertion[str]:
        return Assertion[str](
            value=text, source=Source.SYSTEM_DERIVED, source_reference=COMPILER_VERSION
        )

    def unchanged(category: ChangeCategory) -> tuple[UUID, ...]:
        return tuple(
            p.entity_id
            for p in ep
            if p.category == category and p.permission != ChangePermission.ALLOW
        )

    def ordered[T: Entity](items: tuple[T, ...]) -> tuple[T, ...]:
        return tuple(sorted(items, key=lambda e: str(e.id)))

    brief = GenerationBrief(
        project=ProjectSubject(
            snapshot=project_context(project),
            name=project.name,
            project_type=project.project_type,
            relevant_space=space,
            locale=project.locale,
            units=project.units,
        ),
        goal=intent.goal,
        output=output,
        mode_policy=policy,
        permissions=tuple(category_permissions),
        entity_permissions=ep,
        geometry=GeometryBrief(
            walls=ordered(project.walls),
            openings=ordered(project.openings),
            fixed_elements=ordered(project.fixed_elements),
            furniture=ordered(project.furniture),
            allowed_geometry_ids=tuple(
                sorted(
                    {p.entity_id for p in geometry_ep if p.permission == ChangePermission.ALLOW},
                    key=str,
                )
            ),
            preserved_geometry_ids=tuple(sorted(preserved_geometry, key=str)),
            locked_geometry_ids=tuple(
                sorted(
                    {p.entity_id for p in geometry_ep if p.permission == ChangePermission.LOCKED},
                    key=str,
                )
            ),
            preserved_entity_ids=tuple(sorted(preserved, key=str)),
            spatial_constraints=ordered(project.constraints),
        ),
        design=DesignBrief(
            styles=ordered(project.styles),
            requested_style_changes=permissions[ChangeCategory.STYLE].requests,
            furniture_intent=permissions[ChangeCategory.FURNITURE_DESIGN].requests,
            decorative_intent=permissions[ChangeCategory.DECOR].requests,
        ),
        materials=MaterialBrief(
            existing=tuple(material_entry(m) for m in ordered(project.materials)),
            requested_changes=permissions[ChangeCategory.MATERIALS].requests,
            characteristics=tuple(s.material_characteristics for s in ordered(project.styles)),
            unchanged_material_ids=unchanged(ChangeCategory.MATERIALS),
            unchanged_surfaces=tuple(
                p for p in intent.preservation_instructions if "material" in p.target_types
            ),
        ),
        lighting=LightingBrief(
            elements=ordered(project.lighting),
            requested_changes=permissions[ChangeCategory.LIGHTING].requests,
            unchanged_ids=unchanged(ChangeCategory.LIGHTING),
        ),
        camera=CameraBrief(
            camera=camera,
            lock_state=camera_permission,
            preserve_composition=camera_permission != ChangePermission.ALLOW,
            requested_changes=permissions[ChangeCategory.CAMERA].requests,
        ),
        realism=RealismBrief(
            physically_plausible_materials=system_bool,
            texture_scale=policy_text(
                "Respect represented dimensions; do not invent product scale"
            ),
            surface_detail=policy_text("Use only supported surface detail without product claims"),
            reflections=policy_text("Physically plausible reflections consistent with materials"),
            believable_construction=system_bool,
            realistic_lighting=system_bool,
            photographic_intent=system_bool.model_copy(
                update={"value": options.output.target.value == "architectural_render"}
            ),
        ),
        forbidden_changes=ForbiddenChanges(
            categories=tuple(
                p.category for p in category_permissions if p.permission != ChangePermission.ALLOW
            ),
            protected_ids=tuple(sorted(protected | intent_preserved, key=str)),
            prohibited_style_characteristics=tuple(
                s.prohibited_characteristics for s in ordered(project.styles)
            ),
            project_restrictions=ordered(project.constraints),
            intent_preservation=intent.preservation_instructions,
        ),
        reference=options.reference,
        accepted_facts=tuple(f.statement for f in intent.explicit_facts),
        assumptions=intent.assumptions,
        withheld_requests=tuple(dict.fromkeys(withheld)),
    )
    traces = compilation_traces(brief.model_dump(mode="json"))
    # The derived output ratio retains its ADG origin, including its original Source.
    if camera is not None and options.output.aspect_ratio is None:
        traces = tuple(
            t.model_copy(update={"origin": "ADG"}) if t.field_path == "output.aspect_ratio" else t
            for t in traces
        )
    return brief.model_copy(update={"traceability": traces})
