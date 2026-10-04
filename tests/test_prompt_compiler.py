"""Offline deterministic compilation and adapter preservation contracts."""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from architect_ai.domain.adg_v1 import Lock, Project, WallContact
from architect_ai.domain.generation import (
    ChangeCategory,
    ChangePermission,
    ChangeScope,
    CompilationOptions,
    GenerationBrief,
    GenerationMode,
    MetadataItem,
    OutputSpecification,
    OutputTarget,
    ReferenceImage,
    ReferenceRole,
)
from architect_ai.domain.intent import ArchitecturalIntent, IntentRequest, PreservationInstruction
from architect_ai.domain.serialization import deserialize_project, serialize_project
from architect_ai.domain.values import Assertion, Dimensions, Source
from architect_ai.providers.image_instructions import (
    GenericImageToImageInstructionAdapter,
    GenericTextToImageInstructionAdapter,
    ImageInstructionAdapter,
    OpenAIImageInstructionAdapter,
)
from architect_ai.services.prompt_compiler import (
    CompilationError,
    CompilationErrorCode,
    compile_generation_brief,
)

FIXTURES = Path(__file__).parent / "fixtures" / "adg"


def project_fixture(name: str = "living_room") -> Project:
    return deserialize_project((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def statement(value: str) -> Assertion[str]:
    return Assertion[str](value=value, source=Source.USER_EXPLICIT)


def request(category: str, text: str) -> IntentRequest:
    return IntentRequest.model_validate(
        {
            "instruction": statement(text),
            "operation": "UPDATE_ENTITY",
            "target_types": (category,),
        }
    )


def intent(**updates: object) -> ArchitecturalIntent:
    data: dict[str, object] = {
        "goal": statement("Make this living room more luxurious"),
        "confidence": Decimal("1"),
    }
    data.update(updates)
    return ArchitecturalIntent.model_validate(data)


def options(mode: GenerationMode = GenerationMode.CONCEPT_MODE) -> CompilationOptions:
    return CompilationOptions(
        output=OutputSpecification(target=OutputTarget.ARCHITECTURAL_RENDER), mode=mode
    )


def brief(mode: GenerationMode = GenerationMode.CONCEPT_MODE) -> GenerationBrief:
    return compile_generation_brief(project_fixture(), intent(), options(mode))


def test_vague_luxury_does_not_grant_unsolicited_changes() -> None:
    result = brief()
    for category in (
        ChangeCategory.GEOMETRY,
        ChangeCategory.OPENINGS,
        ChangeCategory.FURNITURE_POSITIONS,
        ChangeCategory.CAMERA,
    ):
        assert result.permission(category).permission != ChangePermission.ALLOW
    assert not result.geometry.allowed_geometry_ids


def test_accepted_aesthetic_categories_allow_only_aesthetic_scopes() -> None:
    styles = request("style", "Refine the luxury style")
    materials = request("material", "Refine material quality without invented product claims")
    lighting = request("lighting", "Refine the lighting")
    result = compile_generation_brief(
        project_fixture(),
        intent(
            style_changes=(styles,),
            material_changes=(materials,),
            lighting_changes=(lighting,),
        ),
        options(),
    )
    for category in (ChangeCategory.STYLE, ChangeCategory.MATERIALS, ChangeCategory.LIGHTING):
        assert result.permission(category).permission == ChangePermission.ALLOW
    assert result.permission(ChangeCategory.GEOMETRY).permission == ChangePermission.PRESERVE


def test_material_only_preserves_other_categories() -> None:
    change = request("material", "Only change the existing oak material")
    result = compile_generation_brief(
        project_fixture(),
        intent(material_changes=(change,)),
        options(GenerationMode.MATERIAL_REVISION_MODE),
    )
    assert result.permission(ChangeCategory.MATERIALS).permission == ChangePermission.ALLOW
    for category in ChangeCategory:
        if category != ChangeCategory.MATERIALS:
            assert result.permission(category).permission != ChangePermission.ALLOW
    assert result.camera.preserve_composition


def test_lighting_only_preserves_geometry_materials_furniture_camera() -> None:
    change = request("lighting", "Change artificial lighting to a calmer mood")
    result = compile_generation_brief(
        project_fixture(),
        intent(lighting_changes=(change,)),
        options(GenerationMode.LIGHTING_REVISION_MODE),
    )
    assert result.permission(ChangeCategory.LIGHTING).permission == ChangePermission.ALLOW
    for category in (
        ChangeCategory.GEOMETRY,
        ChangeCategory.MATERIALS,
        ChangeCategory.FURNITURE_POSITIONS,
        ChangeCategory.FURNITURE_DESIGN,
        ChangeCategory.CAMERA,
    ):
        assert result.permission(category).permission != ChangePermission.ALLOW


@pytest.mark.parametrize("mode", tuple(GenerationMode))
def test_locked_camera_survives_every_mode(mode: GenerationMode) -> None:
    change = request("camera", "Move camera to another position")
    result = compile_generation_brief(
        project_fixture(), intent(camera_changes=(change,)), options(mode)
    )
    assert result.camera.lock_state == ChangePermission.LOCKED
    assert result.camera.preserve_composition
    assert change in result.withheld_requests
    assert not result.camera.requested_changes


def test_hard_geometry_lock_overrides_concept_scope() -> None:
    project = project_fixture()
    wall = project.walls[0]
    lock = Lock(
        id=uuid4(),
        kind="locked_geometry",
        target_id=Assertion(value=wall.id, source=Source.USER_EXPLICIT),
    )
    project = project.model_copy(update={"constraints": (*project.constraints, lock)})
    change = request("wall", "Move the selected wall").model_copy(update={"target_ids": (wall.id,)})
    result = compile_generation_brief(project, intent(requested_operations=(change,)), options())
    assert wall.id in result.geometry.locked_geometry_ids
    assert wall.id not in result.geometry.allowed_geometry_ids
    assert change in result.withheld_requests


def test_preserved_element_and_accepted_preservation_survive() -> None:
    project = project_fixture()
    obj = project.furniture[0]
    lock = Lock(
        id=uuid4(),
        kind="preserved_element",
        target_id=Assertion(value=obj.id, source=Source.USER_EXPLICIT),
    )
    project = project.model_copy(update={"constraints": (*project.constraints, lock)})
    preserve = PreservationInstruction(
        instruction=statement("Preserve all materials"), target_types=("material",)
    )
    result = compile_generation_brief(
        project, intent(preservation_instructions=(preserve,)), options()
    )
    assert obj.id in result.geometry.preserved_entity_ids
    assert obj.id in result.forbidden_changes.protected_ids
    assert project.materials[0].id in result.geometry.preserved_entity_ids


def test_verified_material_facts_are_emitted_without_source_changes() -> None:
    project = project_fixture()
    material = project.materials[0].model_copy(
        update={
            "manufacturer": statement("Verified maker"),
            "product": statement("Product A"),
            "finish": statement("matte"),
            "dimensions": Assertion(
                value=Dimensions(width=Decimal("100"), depth=Decimal("20"), height=Decimal("10")),
                source=Source.USER_REFERENCE,
            ),
            "verification_status": {"value": "verified", "source": "USER_REFERENCE"},
            "source_reference": Assertion(
                value="supplied-product-sheet", source=Source.USER_REFERENCE
            ),
        }
    )
    project = project.model_copy(update={"materials": (material,)})
    result = compile_generation_brief(project, intent(), options())
    assert result.materials.existing[0].verified_facts == material
    assert not result.materials.existing[0].unverified_product_intent
    package = OpenAIImageInstructionAdapter().compile(result)
    assert "Product A" in package.primary_instruction
    assert "supplied-product-sheet" in package.primary_instruction


def test_unverified_product_intent_does_not_fabricate_properties() -> None:
    project = project_fixture()
    material = project.materials[0].model_copy(
        update={
            "manufacturer": statement("Requested maker"),
            "product": statement("Unknown product"),
        }
    )
    project = project.model_copy(update={"materials": (material,)})
    change = request("material", "Use Requested maker Unknown product, specification unknown")
    result = compile_generation_brief(project, intent(material_changes=(change,)), options())
    entry = result.materials.existing[0]
    assert entry.verified_facts is None
    assert tuple(a.value for a in entry.unverified_product_intent) == (
        "Requested maker",
        "Unknown product",
    )
    assert material.finish is None and material.dimensions is None
    package = OpenAIImageInstructionAdapter().compile(result)
    assert "Unknown product" in package.primary_instruction
    assert "not verified specifications" in package.primary_instruction
    assert '"finish"' not in package.primary_instruction


def test_ai_product_assertions_cannot_be_emitted_as_verified() -> None:
    project = project_fixture()
    material = project.materials[0].model_copy(
        update={
            "product": Assertion(value="Possible product", source=Source.AI_INFERRED),
            "verification_status": {"value": "verified", "source": "USER_REFERENCE"},
            "source_reference": Assertion(value="sheet", source=Source.USER_REFERENCE),
        }
    )
    project = project.model_copy(update={"materials": (material,)})
    entry = compile_generation_brief(project, intent(), options()).materials.existing[0]
    assert entry.verified_facts is None
    assert entry.unverified_product_intent[0].source == Source.AI_INFERRED


def test_camera_output_metadata_survives_compilation() -> None:
    project = project_fixture()
    output = OutputSpecification(
        target=OutputTarget.IMAGE_EDIT,
        output_intent_id=project.output_intents[0].id,
        presentation=(statement("Landscape presentation"),),
        metadata=(MetadataItem(key="purpose", value=statement("Review")),),
    )
    result = compile_generation_brief(
        project, intent(), options().model_copy(update={"output": output})
    )
    assert result.camera.camera == project.cameras[0]
    assert result.output.aspect_ratio == project.cameras[0].aspect_ratio
    assert result.output.presentation == output.presentation
    assert result.output.metadata == output.metadata
    package = OpenAIImageInstructionAdapter().compile(result)
    assert package.output == result.output
    assert package.output.aspect_ratio is not None
    assert package.output.aspect_ratio.value == Decimal("1.5")


@pytest.mark.parametrize(
    "adapter",
    (
        OpenAIImageInstructionAdapter(),
        GenericTextToImageInstructionAdapter(),
        GenericImageToImageInstructionAdapter(),
    ),
)
def test_adapters_preserve_permissions_constraints_and_metadata(
    adapter: ImageInstructionAdapter,
) -> None:
    result = compile_generation_brief(
        project_fixture(),
        intent(),
        options().model_copy(
            update={
                "reference": ReferenceImage(available=True, roles=(ReferenceRole.STYLE_REFERENCE,)),
            }
        ),
    )
    before = result.model_dump_json()
    package = adapter.compile(result)
    assert package.permissions == result.permissions
    assert package.entity_permissions == result.entity_permissions
    assert package.forbidden_changes == result.forbidden_changes
    assert package.reference == result.reference
    assert str(project_fixture().cameras[0].id) in package.preservation_instruction
    assert "Hard constraints are mandatory" in package.preservation_instruction
    assert result.model_dump_json() == before


def test_geometry_locked_openai_instructions_preserve_architecture() -> None:
    result = brief(GenerationMode.GEOMETRY_LOCKED_RENDER_MODE)
    package = OpenAIImageInstructionAdapter().compile(result)
    for word in (
        "walls",
        "openings",
        "fixed elements",
        "furniture positions",
        "Camera/composition",
    ):
        assert word in package.preservation_instruction
    assert not result.geometry.allowed_geometry_ids
    assert result.mode_policy.preserve_categories


def test_image_to_image_reference_geometry_and_camera_preservation() -> None:
    reference = ReferenceImage(
        available=True,
        roles=(ReferenceRole.GEOMETRY_AUTHORITY, ReferenceRole.MATERIAL_REFERENCE),
        preserve_camera=True,
        preserve_composition=True,
    )
    result = compile_generation_brief(
        project_fixture(),
        intent(),
        options().model_copy(
            update={
                "reference": reference,
            }
        ),
    )
    package = GenericImageToImageInstructionAdapter().compile(result)
    assert package.reference == reference
    assert "geometry_authority" in package.reference_guidance[0]
    assert "Preserve reference camera: True" in package.reference_guidance[0]
    assert "preserve reference composition: True" in package.reference_guidance[0]
    assert not result.geometry.allowed_geometry_ids


def test_reference_authority_requires_available_reference() -> None:
    with pytest.raises(ValidationError):
        ReferenceImage(preserve_camera=True)
    with pytest.raises(ValueError, match="available reference"):
        GenericImageToImageInstructionAdapter().compile(brief())


def test_same_inputs_are_deterministic_and_immutable() -> None:
    project, accepted, settings = project_fixture(), intent(), options()
    before = serialize_project(project), accepted.model_dump_json(), settings.model_dump_json()
    first = compile_generation_brief(project, accepted, settings)
    second = compile_generation_brief(project, accepted, settings)
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert GenerationBrief.model_validate_json(first.model_dump_json()) == first
    assert OpenAIImageInstructionAdapter().compile(
        first
    ) == OpenAIImageInstructionAdapter().compile(second)
    assert before == (
        serialize_project(project),
        accepted.model_dump_json(),
        settings.model_dump_json(),
    )


def test_ai_inferred_style_preserves_source_and_adg_trace() -> None:
    result = brief()
    style = result.design.styles[0]
    assert style.primary_style.source == Source.AI_INFERRED
    trace = next(t for t in result.traceability if t.field_path == "design.styles[0].primary_style")
    assert trace.origin == "ADG" and trace.source == Source.AI_INFERRED
    assert all(
        t.source == Source.SYSTEM_DERIVED
        for t in result.traceability
        if t.origin == "SYSTEM_COMPILATION"
    )
    ratio = next(t for t in result.traceability if t.field_path == "output.aspect_ratio")
    assert ratio.origin == "ADG"


def test_unsupported_output_and_ambiguous_space_fail_cleanly() -> None:
    with pytest.raises(ValidationError):
        OutputSpecification.model_validate({"target": "dxf"})
    project = project_fixture()
    other = project.spaces[0].model_copy(update={"id": uuid4()})
    project = project.model_copy(update={"spaces": (*project.spaces, other)})
    with pytest.raises(CompilationError) as error:
        compile_generation_brief(project, intent(), options())
    assert error.value.code == CompilationErrorCode.AMBIGUOUS_TARGET


def test_ambiguous_camera_and_locked_aspect_override_fail() -> None:
    project = project_fixture()
    second = project.cameras[0].model_copy(update={"id": uuid4()})
    project = project.model_copy(
        update={"cameras": (*project.cameras, second), "output_intents": ()}
    )
    with pytest.raises(CompilationError) as error:
        compile_generation_brief(project, intent(), options())
    assert error.value.code == CompilationErrorCode.AMBIGUOUS_TARGET
    output = options().output.model_copy(
        update={
            "aspect_ratio": Assertion(value=Decimal("2"), source=Source.USER_EXPLICIT),
        }
    )
    with pytest.raises(CompilationError) as error:
        compile_generation_brief(
            project_fixture(), intent(), options().model_copy(update={"output": output})
        )
    assert error.value.code == CompilationErrorCode.CONFLICTING_OUTPUT


def test_unresolved_intent_or_unscoped_preservation_is_rejected() -> None:
    with pytest.raises(CompilationError) as error:
        compile_generation_brief(project_fixture(), intent(ambiguities=("Which wall?",)), options())
    assert error.value.code == CompilationErrorCode.AMBIGUOUS_INTENT
    preserve = PreservationInstruction(instruction=statement("Keep that unchanged"))
    with pytest.raises(CompilationError) as error:
        compile_generation_brief(
            project_fixture(), intent(preservation_instructions=(preserve,)), options()
        )
    assert error.value.code == CompilationErrorCode.INVALID_SCOPE


def test_explicit_position_scope_is_required_and_cannot_bypass_modes() -> None:
    change = request("furniture", "Move the sofa").model_copy(
        update={
            "target_ids": (project_fixture().furniture[0].id,),
        }
    )
    accepted = intent(requested_operations=(change,))
    with pytest.raises(CompilationError):
        compile_generation_brief(project_fixture(), accepted, options())
    scope = ChangeScope(category=ChangeCategory.FURNITURE_POSITIONS, request=change)
    scoped = options().model_copy(update={"change_scopes": (scope,)})
    result = compile_generation_brief(project_fixture(), accepted, scoped)
    assert (
        result.permission(ChangeCategory.FURNITURE_POSITIONS).permission == ChangePermission.ALLOW
    )
    result = compile_generation_brief(
        project_fixture(),
        accepted,
        scoped.model_copy(
            update={
                "mode": GenerationMode.MATERIAL_REVISION_MODE,
            }
        ),
    )
    assert (
        result.permission(ChangeCategory.FURNITURE_POSITIONS).permission
        == ChangePermission.PRESERVE
    )


def test_unrelated_materials_remain_preserved_under_targeted_change() -> None:
    project = project_fixture()
    original = project.materials[0]
    other = original.model_copy(update={"id": uuid4(), "generic_material": statement("stone")})
    project = project.model_copy(update={"materials": (original, other)})
    change = request("material", "Change only this material").model_copy(
        update={"target_ids": (original.id,)}
    )
    result = compile_generation_brief(
        project, intent(material_changes=(change,)), options(GenerationMode.MATERIAL_REVISION_MODE)
    )
    assert result.permission(ChangeCategory.MATERIALS).allowed_entity_ids == (original.id,)
    assert other.id in result.materials.unchanged_material_ids
    package = OpenAIImageInstructionAdapter().compile(result)
    assert str(other.id) in package.preservation_instruction


def test_change_scope_cannot_introduce_unaccepted_instruction() -> None:
    scope = ChangeScope(category=ChangeCategory.DECOR, request=request("style", "Add carvings"))
    with pytest.raises(CompilationError) as error:
        compile_generation_brief(
            project_fixture(),
            intent(),
            options().model_copy(
                update={
                    "change_scopes": (scope,),
                }
            ),
        )
    assert error.value.code == CompilationErrorCode.INVALID_SCOPE


def test_supported_symbolic_constraint_conflict_is_not_compiled() -> None:
    project = project_fixture()
    wall_ids = (project.walls[0].id,)
    required = WallContact(
        id=uuid4(),
        kind="must_touch_wall",
        wall_ids=Assertion(value=wall_ids, source=Source.USER_EXPLICIT),
        object_type=statement("cabinetry"),
    )
    forbidden = required.model_copy(update={"id": uuid4(), "kind": "cannot_touch_wall"})
    project = project.model_copy(
        update={"constraints": (*project.constraints, required, forbidden)}
    )
    with pytest.raises(CompilationError) as error:
        compile_generation_brief(project, intent(), options())
    assert error.value.code == CompilationErrorCode.INVALID_CONSTRAINTS


def test_furniture_design_permission_does_not_preserve_whole_movable_object() -> None:
    project = project_fixture()
    change = request("furniture", "Refine sofa design within its existing dimensions and position")
    result = compile_generation_brief(project, intent(furniture_changes=(change,)), options())
    assert result.permission(ChangeCategory.FURNITURE_DESIGN).permission == ChangePermission.ALLOW
    assert (
        result.permission(ChangeCategory.FURNITURE_POSITIONS).permission
        == ChangePermission.PRESERVE
    )
    assert project.furniture[0].id not in result.geometry.preserved_entity_ids
    assert project.furniture[0].id in result.geometry.preserved_geometry_ids


def test_reference_geometry_authority_withholds_real_geometry_request() -> None:
    project = project_fixture()
    change = request("wall", "Move this wall").model_copy(
        update={"target_ids": (project.walls[0].id,)}
    )
    accepted = intent(requested_operations=(change,))
    allowed = compile_generation_brief(project, accepted, options())
    assert project.walls[0].id in allowed.geometry.allowed_geometry_ids
    settings = options().model_copy(
        update={
            "reference": ReferenceImage(available=True, roles=(ReferenceRole.GEOMETRY_AUTHORITY,)),
        }
    )
    result = compile_generation_brief(project, accepted, settings)
    assert not result.geometry.allowed_geometry_ids
    assert change in result.withheld_requests


def test_camera_locked_mode_preserves_unlocked_camera_and_composition() -> None:
    project = project_fixture()
    camera = project.cameras[0].model_copy(
        update={"locked": {"value": False, "source": "USER_EXPLICIT"}}
    )
    data = project.model_dump(mode="python")
    data.update(cameras=(camera,), constraints=())
    project = Project.model_validate(data)
    change = request("camera", "Change camera position")
    accepted = intent(camera_changes=(change,))
    assert (
        compile_generation_brief(project, accepted, options()).camera.lock_state
        == ChangePermission.ALLOW
    )
    result = compile_generation_brief(project, accepted, options(GenerationMode.CAMERA_LOCKED_MODE))
    assert result.camera.lock_state == ChangePermission.PRESERVE
    assert result.camera.preserve_composition


def test_locked_host_wall_also_protects_existing_opening() -> None:
    project = project_fixture("l_layout_kitchen")
    opening = project.openings[0]
    lock = Lock(
        id=uuid4(),
        kind="locked_geometry",
        target_id=Assertion(value=opening.host_wall_id.value, source=Source.USER_EXPLICIT),
    )
    project = project.model_copy(update={"constraints": (*project.constraints, lock)})
    change = request("opening", "Widen this opening").model_copy(
        update={"target_ids": (opening.id,)}
    )
    result = compile_generation_brief(project, intent(requested_operations=(change,)), options())
    assert opening.id in result.geometry.locked_geometry_ids
    assert change in result.withheld_requests


def test_unverified_product_trace_records_adg_origin() -> None:
    project = project_fixture()
    material = project.materials[0].model_copy(update={"product": statement("Requested product")})
    project = project.model_copy(update={"materials": (material,)})
    result = compile_generation_brief(project, intent(), options())
    trace = next(
        t
        for t in result.traceability
        if t.field_path == "materials.existing[0].unverified_product_intent[0]"
    )
    assert trace.origin == "ADG"
