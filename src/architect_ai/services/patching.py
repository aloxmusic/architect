"""Atomic patch acceptance against the previous authoritative ADG snapshot."""

from hashlib import sha256
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from architect_ai.domain.adg_v1 import (
    Alignment,
    Camera,
    ConstraintBase,
    Distance,
    Entity,
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
from architect_ai.domain.patches import (
    AddConstraint,
    AddEntity,
    ADGPatch,
    ChangesBase,
    Conflict,
    ConflictCode,
    EntityPayload,
    EntityType,
    PatchOperation,
    PatchResult,
    PatchStatus,
    ProjectContext,
    RemoveConstraint,
    RemoveEntity,
    UpdateConstraint,
    UpdateEntity,
)
from architect_ai.domain.serialization import serialize_project
from architect_ai.domain.values import Assertion, Source

MODELS: dict[EntityType, type[Entity]] = {
    "space": Space,
    "wall": Wall,
    "opening": Opening,
    "fixed_element": FixedElement,
    "furniture": FurnitureObject,
    "style": Style,
    "material": Material,
    "lighting": Lighting,
    "camera": Camera,
    "output_intent": OutputIntent,
    "forbidden_area": ForbiddenArea,
    "required_clearance": RequiredClearance,
    "wall_contact": WallContact,
    "alignment": Alignment,
    "distance": Distance,
    "lock": Lock,
}
COLLECTIONS: dict[EntityType, str] = {
    "space": "spaces",
    "wall": "walls",
    "opening": "openings",
    "fixed_element": "fixed_elements",
    "furniture": "furniture",
    "style": "styles",
    "material": "materials",
    "lighting": "lighting",
    "camera": "cameras",
    "output_intent": "output_intents",
    "forbidden_area": "constraints",
    "required_clearance": "constraints",
    "wall_contact": "constraints",
    "alignment": "constraints",
    "distance": "constraints",
    "lock": "constraints",
}
PAYLOAD = TypeAdapter[EntityPayload](EntityPayload)


def project_context(project: Project) -> ProjectContext:
    """Content fingerprint is snapshot context, not persistent revision history."""
    return ProjectContext(
        project_id=project.id,
        fingerprint=sha256(serialize_project(project).encode("utf-8")).hexdigest(),
    )


def entity_type(entity: Entity) -> EntityType:
    return next(kind for kind, model in MODELS.items() if type(entity) is model)


def payload(entity: Entity) -> EntityPayload:
    return PAYLOAD.validate_python({"entity_type": entity_type(entity), "entity": entity})


def references(entity: Entity) -> tuple[UUID, ...]:
    if isinstance(entity, (Opening, FurnitureObject)):
        return (entity.host_wall_id.value,) if entity.host_wall_id is not None else ()
    if isinstance(entity, OutputIntent):
        return (entity.camera_id.value,) if entity.camera_id is not None else ()
    if isinstance(entity, WallContact):
        return entity.wall_ids.value
    if isinstance(entity, (Alignment, Distance)):
        return entity.target_ids.value
    if isinstance(entity, (Lock, RequiredClearance)):
        return (entity.target_id.value,)
    return ()


def protection(project: Project, target: UUID) -> tuple[ConflictCode, tuple[UUID, ...]] | None:
    locks = [
        c
        for c in project.constraints
        if isinstance(c, Lock) and c.strength == "hard" and c.target_id.value == target
    ]
    if locks:
        code = (
            ConflictCode.PRESERVED_ELEMENT
            if any(c.kind == "preserved_element" for c in locks)
            else ConflictCode.LOCKED_ENTITY
        )
        return code, tuple(c.id for c in locks)
    if any(c.id == target and c.locked.value for c in project.cameras):
        return ConflictCode.LOCKED_ENTITY, ()
    if any(f.id == target and f.fixed_or_movable.value == "fixed" for f in project.furniture):
        return ConflictCode.PRESERVED_ELEMENT, ()
    return None


def provenance_conflicts(
    before: Entity | None,
    after: Entity | ChangesBase,
    operation: PatchOperation,
    index: int,
) -> list[Conflict]:
    conflicts: list[Conflict] = []
    for field in type(after).model_fields:
        if isinstance(after, ChangesBase) and field not in after.model_fields_set:
            continue
        new = getattr(after, field)
        old = getattr(before, field, None) if before is not None else None
        if new == old or not isinstance(new, Assertion):
            continue
        message: str | None = None
        clarification = False
        if operation.source == Source.AI_INFERRED and new.source != Source.AI_INFERRED:
            message = "An AI-inferred operation cannot assert another source of new information"
        elif new.source in {Source.USER_EXPLICIT, Source.USER_REFERENCE}:
            if operation.source != new.source:
                message = "User facts require matching operation provenance"
        if isinstance(old, Assertion) and old.source != new.source:
            if old.value == new.value:
                message = "Relabeling an unchanged value requires a separate acceptance workflow"
            elif old.source == Source.AI_INFERRED and new.source in {
                Source.USER_EXPLICIT,
                Source.USER_REFERENCE,
            }:
                if new.source != Source.USER_EXPLICIT:
                    message = (
                        "Replacing an AI inference with a user reference requires clarification"
                    )
                    clarification = True
                elif not operation.origin:
                    message = (
                        "A new explicit user statement must provide its originating text/reference"
                    )
                    clarification = True
        if message:
            conflicts.append(
                Conflict(
                    code=ConflictCode.PROVENANCE_CONFLICT,
                    message=message,
                    target_ids=(after.id,),
                    fields=(field,),
                    existing=payload(before) if before is not None else None,
                    proposed=operation,
                    operation_index=index,
                    requires_clarification=clarification,
                    severity="clarification" if clarification else "error",
                )
            )
    return conflicts


def graph_conflicts(entities: tuple[Entity, ...]) -> list[Conflict]:
    """Evaluate reference integrity and the supported symbolic wall-contact rules."""
    conflicts: list[Conflict] = []
    by_id = {entity.id: entity for entity in entities}
    geometry = (Space, Wall, Opening, FixedElement, FurnitureObject)
    for entity in entities:
        refs = references(entity)
        expected: tuple[type[Entity], ...] = ()
        if isinstance(entity, (Opening, FurnitureObject, WallContact)):
            expected = (Wall,)
        elif isinstance(entity, OutputIntent) or (
            isinstance(entity, Lock) and entity.kind == "locked_camera"
        ):
            expected = (Camera,)
        elif isinstance(entity, Lock) and entity.kind == "locked_object":
            expected = (FixedElement, FurnitureObject)
        elif isinstance(entity, Lock) and entity.kind == "preserved_element":
            expected = (
                Space,
                Wall,
                Opening,
                FixedElement,
                FurnitureObject,
                Style,
                Material,
                Lighting,
                Camera,
                OutputIntent,
            )
        elif isinstance(entity, (Alignment, Distance, Lock, RequiredClearance)):
            expected = geometry
        if len(set(refs)) != len(refs) or any(
            ref not in by_id or not isinstance(by_id[ref], expected) for ref in refs
        ):
            conflicts.append(
                Conflict(
                    code=ConflictCode.INVALID_REFERENCE,
                    message="Missing, duplicate or incompatible reference",
                    target_ids=(entity.id, *refs),
                    constraint_ids=(entity.id,) if isinstance(entity, ConstraintBase) else (),
                    existing=payload(entity),
                )
            )
    wall_rules = [e for e in entities if isinstance(e, WallContact) and e.strength == "hard"]
    for rule in wall_rules:
        for obj in entities:
            if (
                not isinstance(obj, FurnitureObject)
                or obj.object_type.value != rule.object_type.value
            ):
                continue
            host = obj.host_wall_id.value if obj.host_wall_id is not None else None
            if (rule.kind == "must_touch_wall" and host not in rule.wall_ids.value) or (
                rule.kind == "cannot_touch_wall" and host in rule.wall_ids.value
            ):
                conflicts.append(
                    Conflict(
                        code=ConflictCode.CONSTRAINT_VIOLATION,
                        message="Furniture host wall violates a hard wall-contact rule",
                        target_ids=(obj.id,),
                        constraint_ids=(rule.id,),
                        existing=payload(rule),
                    )
                )
    for object_type in sorted({r.object_type.value for r in wall_rules}):
        rules = [r for r in wall_rules if r.object_type.value == object_type]
        required = [set(r.wall_ids.value) for r in rules if r.kind == "must_touch_wall"]
        forbidden = {
            wall for r in rules if r.kind == "cannot_touch_wall" for wall in r.wall_ids.value
        }
        if required and not set.intersection(*required) - forbidden:
            conflicts.append(
                Conflict(
                    code=ConflictCode.CONSTRAINT_VIOLATION,
                    message="Hard wall-contact rules leave no allowed host wall",
                    constraint_ids=tuple(r.id for r in rules),
                )
            )
    return conflicts


def apply_patch(
    project: Project,
    patch: ADGPatch,
    *,
    confirmed_destructive: bool = False,
) -> PatchResult:
    """Never publish a partial candidate; confirmation belongs to the trusted caller."""
    context = project_context(project)
    conflicts: list[Conflict] = []
    before = {entity.id: entity for entity in project.entities()}
    staged = dict(before)
    pending: dict[UUID, dict[str, Any]] = {}
    pending_indices: dict[UUID, list[int]] = {}
    if patch.project_id != project.id:
        conflicts.append(
            Conflict(
                code=ConflictCode.ID_MISMATCH,
                message="Patch project ID does not match the authoritative project",
                target_ids=(patch.project_id, project.id),
            )
        )
    if patch.base_fingerprint is not None and patch.base_fingerprint != context.fingerprint:
        conflicts.append(
            Conflict(
                code=ConflictCode.STALE_BASE,
                message="Patch was prepared against a different snapshot",
            )
        )

    for index, operation in enumerate(patch.operations):
        new: Entity
        if isinstance(operation, (AddEntity, AddConstraint)):
            kind = operation.payload.entity_type
            target = operation.payload.entity.id
        elif isinstance(operation, (UpdateEntity, UpdateConstraint)):
            kind = operation.changes.entity_type
            target = operation.target_id
        else:
            kind = operation.entity_type
            target = operation.target_id
        old = staged.get(target)

        def report(
            code: ConflictCode,
            message: str,
            *,
            related: tuple[UUID, ...] = (),
            clarification: bool = False,
            target: UUID = target,
            old: Entity | None = old,
            operation: PatchOperation = operation,
            index: int = index,
        ) -> None:
            conflicts.append(
                Conflict(
                    code=code,
                    message=message,
                    target_ids=(target,),
                    constraint_ids=related,
                    existing=payload(old) if old is not None else None,
                    proposed=operation,
                    operation_index=index,
                    requires_clarification=clarification,
                    severity="clarification" if clarification else "error",
                )
            )

        is_constraint = COLLECTIONS[kind] == "constraints"
        if is_constraint != isinstance(
            operation, (AddConstraint, UpdateConstraint, RemoveConstraint)
        ):
            report(ConflictCode.VALIDATION_FAILED, "Operation category does not match payload type")
            continue
        if isinstance(operation, (AddEntity, AddConstraint)):
            if target == project.id or target in before or target in staged:
                report(ConflictCode.ID_MISMATCH, "Addition must use a new unique entity ID")
                continue
            new = operation.payload.entity
        else:
            if old is None:
                report(ConflictCode.MISSING_TARGET, "Target does not exist")
                continue
            if type(old) is not MODELS[kind]:
                report(ConflictCode.ID_MISMATCH, "Target entity type does not match")
                continue
            if (
                isinstance(operation, (UpdateEntity, UpdateConstraint))
                and operation.changes.id != target
            ):
                report(ConflictCode.ID_MISMATCH, "Updates must preserve the target UUID")
                continue
            protected = protection(project, target)
            if protected is not None:
                report(
                    protected[0],
                    "Existing locked or preserved entity cannot be changed",
                    related=protected[1],
                )
                continue
            if isinstance(old, ConstraintBase) and target in before:
                report(
                    ConflictCode.CONSTRAINT_VIOLATION,
                    "Existing constraints cannot be changed or removed",
                    related=(target,),
                )
                continue
            if isinstance(operation, (RemoveEntity, RemoveConstraint)):
                referrers = [e for e in project.entities() if target in references(e)]
                referrers.extend(
                    e for e in staged.values() if e.id not in before and target in references(e)
                )
                if referrers:
                    report(
                        ConflictCode.INVALID_REFERENCE,
                        "Referenced entity cannot be removed",
                        related=tuple(e.id for e in referrers if isinstance(e, ConstraintBase)),
                    )
                    continue
                if not confirmed_destructive:
                    report(
                        ConflictCode.DESTRUCTIVE_CHANGE_REQUIRES_CONFIRMATION,
                        "Removal requires explicit confirmation from the caller",
                        clarification=True,
                    )
                    continue
                del staged[target]
                pending.pop(target, None)
                pending_indices.pop(target, None)
                continue
            # Only typed, explicitly supplied fields enter this internal validation dictionary.
            found = provenance_conflicts(old, operation.changes, operation, index)
            conflicts.extend(found)
            if found:
                continue
            data = pending.setdefault(target, old.model_dump(mode="python"))
            data.update(operation.changes.model_dump(exclude_unset=True, exclude={"entity_type"}))
            pending_indices.setdefault(target, []).append(index)
            continue
        found = provenance_conflicts(old, new, operation, index)
        conflicts.extend(found)
        if not found:
            staged[target] = new

    # Related fields may be temporarily inconsistent; validate each final entity only once.
    for target, data in pending.items():
        old = staged[target]
        try:
            staged[target] = type(old).model_validate(data)
        except ValidationError as exc:
            code = (
                ConflictCode.VALIDATION_FAILED
                if isinstance(old, (Material, Style, Lighting, OutputIntent))
                else ConflictCode.GEOMETRY_VALIDATION_FAILED
            )
            conflicts.append(
                Conflict(
                    code=code,
                    message=str(exc),
                    target_ids=(target,),
                    existing=payload(old),
                    proposed=patch.operations[pending_indices[target][-1]],
                    operation_index=pending_indices[target][-1],
                )
            )

    # Compare final objects with the authoritative snapshot, independently of deserialization.
    for target, old in before.items():
        if isinstance(old, ConstraintBase) and staged.get(target) != old:
            conflicts.append(
                Conflict(
                    code=ConflictCode.CONSTRAINT_VIOLATION,
                    message="Candidate must retain every existing constraint",
                    target_ids=(target,),
                    constraint_ids=(target,),
                    existing=payload(old),
                )
            )
        protected = protection(project, target)
        if protected is not None and staged.get(target) != old:
            conflicts.append(
                Conflict(
                    code=protected[0],
                    message="Candidate changed a protected entity",
                    target_ids=(target,),
                    constraint_ids=protected[1],
                    existing=payload(old),
                )
            )
    graph = graph_conflicts(tuple(staged.values()))
    # Attach proposed operations to graph conflicts so callers can identify the offending request.
    for conflict in graph:
        affected = set(conflict.target_ids) | set(conflict.constraint_ids)
        operation_index = next(
            (i for i, op in enumerate(patch.operations) if operation_target(op) in affected), None
        )
        conflicts.append(
            conflict.model_copy(
                update={
                    "proposed": patch.operations[operation_index]
                    if operation_index is not None
                    else None,
                    "operation_index": operation_index,
                }
            )
        )

    candidate: Project | None = None
    if not conflicts:
        changes: dict[str, Any] = {
            collection: tuple(
                e for e in staged.values() if COLLECTIONS[entity_type(e)] == collection
            )
            for collection in dict.fromkeys(COLLECTIONS.values())
        }
        data = project.model_dump(mode="python")
        data.update(changes)
        try:
            # This is the explicit acceptance boundary. Earlier old/new checks replace no ADG rules.
            candidate = Project.model_validate(data)
        except ValidationError as exc:
            conflicts.append(
                Conflict(
                    code=ConflictCode.GEOMETRY_VALIDATION_FAILED,
                    message=str(exc),
                    target_ids=tuple(operation_target(op) for op in patch.operations),
                )
            )
    if conflicts:
        status = (
            PatchStatus.REJECTED
            if any(c.severity == "error" for c in conflicts)
            else PatchStatus.NEEDS_CLARIFICATION
        )
        return PatchResult(
            status=status,
            original=context,
            conflicts=tuple(conflicts),
            rejected_operations=patch.operations,
        )
    return PatchResult(
        status=PatchStatus.ACCEPTED,
        original=context,
        candidate=candidate,
        applied_operations=patch.operations,
    )


def operation_target(operation: PatchOperation) -> UUID:
    if isinstance(operation, (AddEntity, AddConstraint)):
        return operation.payload.entity.id
    return operation.target_id
