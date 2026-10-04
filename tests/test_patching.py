"""Acceptance-boundary tests reuse Phase 2's ADG scenarios."""

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from architect_ai.domain.adg_v1 import Lock, Project, WallContact
from architect_ai.domain.intent import ArchitecturalIntent, IntentRequest
from architect_ai.domain.patches import (
    AddConstraint,
    AddEntity,
    ADGPatch,
    CameraChanges,
    CameraPayload,
    ConflictCode,
    FurnitureObjectChanges,
    FurnitureObjectPayload,
    LightingChanges,
    LockChanges,
    LockPayload,
    MaterialChanges,
    OutputIntentPayload,
    PatchOperation,
    PatchResult,
    PatchStatus,
    RemoveConstraint,
    RemoveEntity,
    StyleChanges,
    UpdateConstraint,
    UpdateEntity,
    WallChanges,
    WallContactPayload,
)
from architect_ai.domain.serialization import deserialize_project, serialize_project
from architect_ai.domain.values import Assertion, Point3, Source
from architect_ai.services.patching import apply_patch, project_context

FIXTURES = Path(__file__).parent / "fixtures" / "adg"


def kitchen() -> Project:
    return deserialize_project((FIXTURES / "l_layout_kitchen.json").read_text(encoding="utf-8"))


def patch(project: Project, *operations: PatchOperation) -> ADGPatch:
    return ADGPatch(
        project_id=project.id,
        base_fingerprint=project_context(project).fingerprint,
        operations=operations,
    )


def accepted(result: PatchResult) -> Project:
    assert result.status == PatchStatus.ACCEPTED, result.conflicts
    assert result.candidate is not None
    assert not result.conflicts and not result.rejected_operations
    return result.candidate


def rejected(result: PatchResult, code: ConflictCode) -> None:
    assert result.status == PatchStatus.REJECTED
    assert result.candidate is None and not result.applied_operations
    assert code in {conflict.code for conflict in result.conflicts}
    assert result.rejected_operations


def wall_update(project: Project, target: UUID | None = None) -> UpdateEntity:
    wall = project.walls[0]
    return UpdateEntity(
        target_id=target or wall.id,
        changes=WallChanges(
            id=wall.id,
            thickness=Assertion[Decimal](value=Decimal("200"), source=Source.USER_EXPLICIT),
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
        origin="Make wall 200 mm",
    )


def ordinary_furniture(project: Project) -> Project:
    obj = project.furniture[0].model_copy(
        update={"fixed_or_movable": {"value": "movable", "source": "USER_EXPLICIT"}}
    )
    data = project.model_dump(mode="python")
    data["furniture"] = (obj,)
    return Project.model_validate(data)


def test_update_preserves_id_provenance_and_original_snapshot() -> None:
    project = kitchen()
    original = serialize_project(project)
    operation = wall_update(project)
    request = patch(project, operation)
    restored = ADGPatch.model_validate_json(request.model_dump_json())
    assert restored == request
    assert restored.operations[0] == operation
    result = apply_patch(project, restored)
    candidate = accepted(result)
    assert candidate.walls[0].id == project.walls[0].id
    assert candidate.walls[0].thickness.value == Decimal("200")
    assert candidate.walls[0].thickness.source == Source.USER_EXPLICIT
    assert candidate.walls[0].start == project.walls[0].start
    assert result.applied_operations == request.operations
    assert result.original == project_context(project)
    assert serialize_project(project) == original
    assert deserialize_project(serialize_project(candidate)) == candidate


def test_add_entity_and_duplicate_id_rejection() -> None:
    project = kitchen()
    obj = project.furniture[0].model_copy(update={"id": uuid4()})
    operation = AddEntity(
        payload=FurnitureObjectPayload(entity=obj),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    candidate = accepted(apply_patch(project, patch(project, operation)))
    assert candidate.furniture[-1] == obj
    assert project.furniture != candidate.furniture
    duplicate = operation.model_copy(
        update={"payload": FurnitureObjectPayload(entity=project.furniture[0])}
    )
    rejected(apply_patch(project, patch(project, duplicate)), ConflictCode.ID_MISMATCH)


def test_remove_ordinary_entity_requires_external_confirmation() -> None:
    project = ordinary_furniture(kitchen())
    operation = RemoveEntity(
        target_id=project.furniture[0].id,
        entity_type="furniture",
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    request = patch(project, operation)
    result = apply_patch(project, request)
    assert result.status == PatchStatus.NEEDS_CLARIFICATION
    assert result.conflicts[0].code == ConflictCode.DESTRUCTIVE_CHANGE_REQUIRES_CONFIRMATION
    assert result.conflicts[0].requires_clarification and result.candidate is None
    assert not result.applied_operations and result.rejected_operations == request.operations
    assert accepted(apply_patch(project, request, confirmed_destructive=True)).furniture == ()
    assert project.furniture


@pytest.mark.parametrize("kind", ["locked_geometry", "preserved_element"])
@pytest.mark.parametrize("remove", [False, True])
def test_existing_wall_protection_cannot_be_bypassed(kind: str, remove: bool) -> None:
    project = kitchen()
    lock = Lock.model_validate(
        {
            "id": uuid4(),
            "kind": kind,
            "target_id": {"value": project.walls[0].id, "source": "USER_EXPLICIT"},
        }
    )
    project = project.model_copy(update={"constraints": (*project.constraints, lock)})
    original = serialize_project(project)
    operation: PatchOperation = (
        RemoveEntity(
            target_id=project.walls[0].id,
            entity_type="wall",
            source=Source.USER_EXPLICIT,
            confidence=Decimal("1"),
        )
        if remove
        else wall_update(project)
    )
    result = apply_patch(project, patch(project, operation), confirmed_destructive=True)
    code = (
        ConflictCode.PRESERVED_ELEMENT
        if kind == "preserved_element"
        else ConflictCode.LOCKED_ENTITY
    )
    rejected(result, code)
    assert lock.id in result.conflicts[0].constraint_ids
    assert result.conflicts[0].proposed == operation
    assert serialize_project(project) == original


def test_locked_camera_cannot_be_updated_or_removed() -> None:
    project = kitchen()
    camera = project.cameras[0]
    update = UpdateEntity(
        target_id=camera.id,
        changes=CameraChanges(
            id=camera.id,
            focal_length=Assertion[Decimal](value=Decimal("50"), source=Source.USER_EXPLICIT),
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    remove = RemoveEntity(
        target_id=camera.id,
        entity_type="camera",
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    for operation in (update, remove):
        rejected(
            apply_patch(project, patch(project, operation), confirmed_destructive=True),
            ConflictCode.LOCKED_ENTITY,
        )


def test_fixed_furniture_update_and_removal_rejected() -> None:
    project = kitchen()
    project = project.model_copy(
        update={
            "furniture": (
                project.furniture[0].model_copy(
                    update={"fixed_or_movable": {"value": "fixed", "source": "USER_EXPLICIT"}}
                ),
            )
        }
    )
    obj = project.furniture[0]
    assert obj.fixed_or_movable.value == "fixed"
    update = UpdateEntity(
        target_id=obj.id,
        changes=FurnitureObjectChanges(
            id=obj.id, rotation=Assertion[Decimal](value=Decimal("90"), source=Source.USER_EXPLICIT)
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    remove = RemoveEntity(
        target_id=obj.id,
        entity_type="furniture",
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    for operation in (update, remove):
        rejected(
            apply_patch(project, patch(project, operation), confirmed_destructive=True),
            ConflictCode.PRESERVED_ELEMENT,
        )


def test_existing_constraints_cannot_be_removed_even_with_confirmation() -> None:
    project = kitchen()
    constraint = next(c for c in project.constraints if isinstance(c, WallContact))
    operation = RemoveConstraint(
        target_id=constraint.id,
        entity_type="wall_contact",
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    result = apply_patch(project, patch(project, operation), confirmed_destructive=True)
    rejected(result, ConflictCode.CONSTRAINT_VIOLATION)
    assert result.conflicts[0].constraint_ids == (constraint.id,)
    assert project.constraints


def test_existing_constraint_update_and_unlock_rejected() -> None:
    project = kitchen()
    lock = Lock(
        kind="locked_geometry",
        id=uuid4(),
        target_id=Assertion[UUID](value=project.walls[0].id, source=Source.USER_EXPLICIT),
    )
    project = project.model_copy(update={"constraints": (*project.constraints, lock)})
    weaken = UpdateConstraint(
        target_id=lock.id,
        changes=LockChanges(id=lock.id, strength="soft"),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    rejected(
        apply_patch(project, patch(project, weaken, wall_update(project))),
        ConflictCode.CONSTRAINT_VIOLATION,
    )


def test_missing_target_and_uuid_mismatch() -> None:
    project = kitchen()
    rejected(
        apply_patch(project, patch(project, wall_update(project, uuid4()))),
        ConflictCode.MISSING_TARGET,
    )
    operation = wall_update(project).model_copy(
        update={"changes": WallChanges(id=uuid4(), thickness=project.walls[0].thickness)}
    )
    rejected(apply_patch(project, patch(project, operation)), ConflictCode.ID_MISMATCH)
    rejected(
        apply_patch(
            project, patch(project, wall_update(project)).model_copy(update={"project_id": uuid4()})
        ),
        ConflictCode.ID_MISMATCH,
    )


def test_invalid_reference_and_referenced_removal_rejected() -> None:
    project = ordinary_furniture(kitchen())
    obj = project.furniture[0]
    operation = UpdateEntity(
        target_id=obj.id,
        changes=FurnitureObjectChanges(
            id=obj.id, host_wall_id=Assertion[UUID](value=uuid4(), source=Source.USER_EXPLICIT)
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    rejected(apply_patch(project, patch(project, operation)), ConflictCode.INVALID_REFERENCE)
    remove = RemoveEntity(
        target_id=project.walls[0].id,
        entity_type="wall",
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    rejected(
        apply_patch(project, patch(project, remove), confirmed_destructive=True),
        ConflictCode.INVALID_REFERENCE,
    )


def test_explicit_new_user_statement_replaces_ai_inference() -> None:
    project = kitchen()
    style = project.styles[0]
    assert style.primary_style.source == Source.AI_INFERRED
    operation = UpdateEntity(
        target_id=style.id,
        changes=StyleChanges(
            id=style.id,
            primary_style=Assertion[str](
                value="industrial", source=Source.USER_EXPLICIT, source_reference="brief:2"
            ),
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
        origin="Use industrial style",
    )
    candidate = accepted(apply_patch(project, patch(project, operation)))
    assert candidate.styles[0].primary_style.source == Source.USER_EXPLICIT
    assert candidate.styles[0].primary_style.source_reference == "brief:2"
    assert candidate.styles[0].primary_style.value == "industrial"
    assert project.styles[0] == style
    assert isinstance(operation.changes, StyleChanges)
    with pytest.raises(ValueError, match="promotion"):
        style.model_copy(update={"primary_style": operation.changes.primary_style})
    no_origin = operation.model_copy(update={"origin": None})
    assert apply_patch(project, patch(project, no_origin)).status == PatchStatus.NEEDS_CLARIFICATION


@pytest.mark.parametrize("new_source", list(Source))
def test_unchanged_ai_value_cannot_be_relabelled(new_source: Source) -> None:
    project = kitchen()
    style = project.styles[0]
    operation = UpdateEntity(
        target_id=style.id,
        changes=StyleChanges(
            id=style.id,
            primary_style=Assertion[str](value=style.primary_style.value, source=new_source),
        ),
        source=new_source,
        confidence=Decimal("1"),
        origin="Repeat style",
    )
    result = apply_patch(project, patch(project, operation))
    if new_source == Source.AI_INFERRED:
        accepted(result)
    else:
        rejected(result, ConflictCode.PROVENANCE_CONFLICT)


def test_ai_operation_cannot_claim_user_facts() -> None:
    project = kitchen()
    operation = wall_update(project).model_copy(update={"source": Source.AI_INFERRED})
    rejected(apply_patch(project, patch(project, operation)), ConflictCode.PROVENANCE_CONFLICT)


@pytest.mark.parametrize("source", list(Source))
def test_changed_value_explicitly_receives_new_provenance(source: Source) -> None:
    project = kitchen()
    operation = UpdateEntity(
        target_id=project.walls[0].id,
        changes=WallChanges(
            id=project.walls[0].id,
            thickness=Assertion[Decimal](
                value=Decimal("250"), source=source, source_reference="brief:3"
            ),
        ),
        source=source,
        confidence=Decimal("0.9"),
    )
    candidate = accepted(apply_patch(project, patch(project, operation)))
    restored = deserialize_project(serialize_project(candidate))
    assert restored.walls[0].thickness.source == source
    assert restored.walls[0].thickness.source_reference == "brief:3"


def test_related_geometry_updates_are_atomic() -> None:
    project = kitchen()
    wall = project.walls[0]
    moved_start = Assertion[Point3](
        value=wall.start.value.model_copy(update={"z": "100"}), source=Source.USER_EXPLICIT
    )
    moved_end = Assertion[Point3](
        value=wall.end.value.model_copy(update={"z": "100"}), source=Source.USER_EXPLICIT
    )
    start = UpdateEntity(
        target_id=wall.id,
        changes=WallChanges(id=wall.id, start=moved_start),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    end = UpdateEntity(
        target_id=wall.id,
        changes=WallChanges(id=wall.id, end=moved_end),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    result = apply_patch(project, patch(project, start, end))
    candidate = accepted(result)
    assert candidate.walls[0].start.value.z == candidate.walls[0].end.value.z == Decimal("100")
    assert project.walls[0] == wall


def test_one_invalid_operation_rejects_all_operations() -> None:
    project = kitchen()
    original = serialize_project(project)
    request = patch(project, wall_update(project), wall_update(project, uuid4()))
    result = apply_patch(project, request)
    rejected(result, ConflictCode.MISSING_TARGET)
    assert result.rejected_operations == request.operations
    assert serialize_project(project) == original


def test_cabinetry_window_wall_conflict_keeps_constraint() -> None:
    project = ordinary_furniture(kitchen())
    rule = next(
        c
        for c in project.constraints
        if isinstance(c, WallContact) and c.kind == "cannot_touch_wall"
    )
    obj = project.furniture[0]
    operation = UpdateEntity(
        target_id=obj.id,
        changes=FurnitureObjectChanges(
            id=obj.id,
            host_wall_id=Assertion[UUID](value=rule.wall_ids.value[0], source=Source.USER_EXPLICIT),
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    result = apply_patch(project, patch(project, operation))
    rejected(result, ConflictCode.CONSTRAINT_VIOLATION)
    conflict = next(
        c
        for c in result.conflicts
        if c.code == ConflictCode.CONSTRAINT_VIOLATION and rule.id in c.constraint_ids
    )
    assert conflict.target_ids == (obj.id,) and conflict.constraint_ids == (rule.id,)
    assert conflict.proposed == operation
    assert rule in project.constraints


def test_new_contradictory_wall_rule_detected_without_furniture() -> None:
    project = kitchen()
    data = project.model_dump(mode="python")
    data["furniture"] = ()
    project = Project.model_validate(data)
    forbidden = next(
        c
        for c in project.constraints
        if isinstance(c, WallContact) and c.kind == "cannot_touch_wall"
    )
    new_rule = forbidden.model_copy(update={"id": uuid4(), "kind": "must_touch_wall"})
    operation = AddConstraint(
        payload=WallContactPayload(entity=new_rule),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    result = apply_patch(project, patch(project, operation))
    rejected(result, ConflictCode.CONSTRAINT_VIOLATION)
    assert new_rule.id in result.conflicts[0].constraint_ids


def test_geometry_invalid_patch_has_structured_result() -> None:
    project = kitchen()
    wall = project.walls[0]
    operation = UpdateEntity(
        target_id=wall.id,
        changes=WallChanges(id=wall.id, end=wall.start),
        source=wall.start.source,
        confidence=Decimal("1"),
    )
    rejected(
        apply_patch(project, patch(project, operation)), ConflictCode.GEOMETRY_VALIDATION_FAILED
    )


def test_patch_payload_is_typed_and_requires_provenance() -> None:
    with pytest.raises(ValidationError):
        ADGPatch.model_validate(
            {
                "project_id": uuid4(),
                "operations": [
                    {
                        "operation": "UPDATE_ENTITY",
                        "target_id": uuid4(),
                        "source": "USER_EXPLICIT",
                        "confidence": "1",
                        "changes": {
                            "entity_type": "wall",
                            "id": uuid4(),
                            "arbitrary": {"value": "bad", "source": "USER_EXPLICIT"},
                        },
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        WallChanges.model_validate({"id": uuid4(), "thickness": {"value": "200"}})
    with pytest.raises(ValidationError):
        WallChanges(id=uuid4())


def test_stale_snapshot_rejected() -> None:
    project = kitchen()
    request = patch(project, wall_update(project)).model_copy(
        update={"base_fingerprint": "outdated"}
    )
    rejected(apply_patch(project, request), ConflictCode.STALE_BASE)


def test_intent_is_provider_neutral_and_does_not_modify_project() -> None:
    project = kitchen()
    original = serialize_project(project)
    statement = Assertion[str](value="Change wall thickness", source=Source.USER_EXPLICIT)
    intent = ArchitecturalIntent(
        goal=statement,
        target_ids=(project.walls[0].id,),
        target_types=("wall",),
        requested_operations=(IntentRequest(instruction=statement, operation="UPDATE_ENTITY"),),
        assumptions=(Assertion[str](value="Keep height", source=Source.AI_INFERRED),),
        ambiguities=("Which wall?",),
        confidence=Decimal("0.8"),
    )
    assert ArchitecturalIntent.model_validate_json(intent.model_dump_json()) == intent
    assert serialize_project(project) == original


@pytest.mark.parametrize("kind", ["locked_object", "preserved_element"])
def test_explicit_furniture_lock_is_protected(kind: str) -> None:
    project = kitchen()
    obj = project.furniture[0]
    lock = Lock.model_validate(
        {"id": uuid4(), "kind": kind, "target_id": {"value": obj.id, "source": "USER_EXPLICIT"}}
    )
    project = project.model_copy(update={"constraints": (*project.constraints, lock)})
    remove = RemoveEntity(
        target_id=obj.id,
        entity_type="furniture",
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    update = UpdateEntity(
        target_id=obj.id,
        changes=FurnitureObjectChanges(
            id=obj.id, rotation=Assertion[Decimal](value=Decimal("90"), source=Source.USER_EXPLICIT)
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    code = ConflictCode.LOCKED_ENTITY if kind == "locked_object" else ConflictCode.PRESERVED_ELEMENT
    for operation in (remove, update):
        rejected(apply_patch(project, patch(project, operation), confirmed_destructive=True), code)


def test_add_related_entities_resolves_forward_reference_atomically() -> None:
    project = kitchen()
    camera = project.cameras[0].model_copy(update={"id": uuid4()})
    output = project.output_intents[0].model_copy(
        update={
            "id": uuid4(),
            "camera_id": Assertion[UUID](value=camera.id, source=Source.USER_EXPLICIT),
        }
    )
    add_output = AddEntity(
        payload=OutputIntentPayload(entity=output),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    add_camera = AddEntity(
        payload=CameraPayload(entity=camera), source=Source.USER_EXPLICIT, confidence=Decimal("1")
    )
    result = apply_patch(project, patch(project, add_output, add_camera))
    candidate = accepted(result)
    assert candidate.output_intents[-1].camera_id == output.camera_id
    assert candidate.cameras[-1] == camera
    assert len(result.applied_operations) == 2
    rejected(apply_patch(project, patch(project, add_output)), ConflictCode.INVALID_REFERENCE)


def test_add_constraint_and_edit_new_constraint_in_one_patch() -> None:
    project = kitchen()
    lock = Lock(
        id=uuid4(),
        kind="locked_geometry",
        strength="soft",
        target_id=Assertion[UUID](value=project.walls[0].id, source=Source.USER_EXPLICIT),
    )
    add = AddConstraint(
        payload=LockPayload(entity=lock), source=Source.USER_EXPLICIT, confidence=Decimal("1")
    )
    update = UpdateConstraint(
        target_id=lock.id,
        changes=LockChanges(id=lock.id, strength="hard"),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    candidate = accepted(apply_patch(project, patch(project, add, update)))
    assert candidate.constraints[-1].strength == "hard"
    assert candidate.constraints[:-1] == project.constraints
    remove = RemoveConstraint(
        target_id=lock.id, entity_type="lock", source=Source.USER_EXPLICIT, confidence=Decimal("1")
    )
    candidate = accepted(
        apply_patch(project, patch(project, add, remove), confirmed_destructive=True)
    )
    assert candidate == project


def test_material_and_lighting_updates_preserve_unrelated_fields() -> None:
    project = kitchen()
    material = project.materials[0]
    lighting = project.lighting[0]
    finish = Assertion[str](
        value="matte", source=Source.USER_EXPLICIT, source_reference="brief:finish"
    )
    mood = Assertion[str](value="warm", source=Source.USER_EXPLICIT)
    operations = (
        UpdateEntity(
            target_id=material.id,
            changes=MaterialChanges(id=material.id, finish=finish),
            source=Source.USER_EXPLICIT,
            confidence=Decimal("1"),
        ),
        UpdateEntity(
            target_id=lighting.id,
            changes=LightingChanges(id=lighting.id, lighting_mood=mood),
            source=Source.USER_EXPLICIT,
            confidence=Decimal("1"),
        ),
    )
    request = ADGPatch.model_validate_json(patch(project, *operations).model_dump_json())
    candidate = accepted(apply_patch(project, request))
    assert candidate.materials[0].finish == finish
    assert candidate.materials[0].generic_material == material.generic_material
    assert candidate.lighting[0].lighting_mood == mood
    assert candidate.lighting[0].color_temperature == lighting.color_temperature


def test_explicit_null_clears_only_optional_field_across_patch_roundtrip() -> None:
    project = ordinary_furniture(kitchen())
    obj = project.furniture[0].model_copy(
        update={"object_type": {"value": "chair", "source": "USER_EXPLICIT"}}
    )
    project = project.model_copy(update={"furniture": (obj,)})
    operation = UpdateEntity(
        target_id=obj.id,
        changes=FurnitureObjectChanges(id=obj.id, host_wall_id=None),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    request = ADGPatch.model_validate_json(patch(project, operation).model_dump_json())
    candidate = accepted(apply_patch(project, request))
    assert candidate.furniture[0].host_wall_id is None
    assert candidate.furniture[0].dimensions == obj.dimensions
    invalid = UpdateEntity(
        target_id=project.walls[0].id,
        changes=WallChanges(id=project.walls[0].id, thickness=None),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    rejected(apply_patch(project, patch(project, invalid)), ConflictCode.GEOMETRY_VALIDATION_FAILED)


def test_final_project_geometry_validation_is_not_bypassed() -> None:
    project = kitchen()
    wall_id = project.openings[0].host_wall_id.value
    wall = next(w for w in project.walls if w.id == wall_id)
    operation = UpdateEntity(
        target_id=wall.id,
        changes=WallChanges(
            id=wall.id, height=Assertion[Decimal](value=Decimal("1"), source=Source.USER_EXPLICIT)
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    rejected(
        apply_patch(project, patch(project, operation)), ConflictCode.GEOMETRY_VALIDATION_FAILED
    )


def test_remove_and_readd_cannot_replace_identity_or_strip_constraints() -> None:
    project = kitchen()
    obj = project.furniture[0]
    remove = RemoveEntity(
        target_id=obj.id,
        entity_type="furniture",
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    add = AddEntity(
        payload=FurnitureObjectPayload(entity=obj),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    rejected(
        apply_patch(project, patch(project, remove, add), confirmed_destructive=True),
        ConflictCode.ID_MISMATCH,
    )


def test_confirmation_cannot_be_embedded_in_untrusted_patch() -> None:
    operation = {
        "operation": "REMOVE_ENTITY",
        "target_id": str(uuid4()),
        "entity_type": "wall",
        "source": "USER_EXPLICIT",
        "confidence": "1",
        "confirmed_destructive": True,
    }
    with pytest.raises(ValidationError):
        ADGPatch.model_validate({"project_id": uuid4(), "operations": [operation]})


def test_clarification_does_not_allow_other_operations_to_apply() -> None:
    project = kitchen()
    remove = RemoveEntity(
        target_id=project.furniture[0].id,
        entity_type="furniture",
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
    )
    original = serialize_project(project)
    request = patch(project, wall_update(project), remove)
    result = apply_patch(project, request)
    assert result.status == PatchStatus.NEEDS_CLARIFICATION
    assert result.candidate is None and not result.applied_operations
    assert result.rejected_operations == request.operations
    assert serialize_project(project) == original
