"""Offline semantic proposal examples and deterministic acceptance-boundary checks."""

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from architect_ai.domain.adg_v1 import Lock, Project, WallContact
from architect_ai.domain.intent import ArchitecturalIntent, IntentRequest, PreservationInstruction
from architect_ai.domain.patches import (
    ADGPatch,
    CameraChanges,
    ConflictCode,
    FurnitureObjectChanges,
    MaterialChanges,
    PatchOperation,
    PatchStatus,
    SpaceChanges,
    StyleChanges,
    UpdateEntity,
    WallChanges,
)
from architect_ai.domain.serialization import deserialize_project, serialize_project
from architect_ai.domain.values import Assertion, Dimensions, Source
from architect_ai.providers.mock_interpreter import MockArchitecturalInterpreterProvider
from architect_ai.services.brief_context import build_project_context
from architect_ai.services.brief_contracts import (
    BriefReference,
    BriefRequest,
    InterpretationProposal,
    InterpreterProviderError,
    ProviderErrorCode,
    ProviderInterpretation,
    ProviderMetadata,
)
from architect_ai.services.brief_interpreter import (
    ArchitecturalBriefInterpreter,
    numeric_evidence,
    proposal_type,
)
from architect_ai.services.patching import apply_patch, project_context

FIXTURES = Path(__file__).parent / "fixtures" / "adg"


def kitchen() -> Project:
    return deserialize_project((FIXTURES / "l_layout_kitchen.json").read_text(encoding="utf-8"))


def interpretation(
    project: Project,
    text: str,
    *operations: PatchOperation,
    ambiguities: tuple[str, ...] = (),
    preserved: tuple[PreservationInstruction, ...] = (),
) -> ProviderInterpretation:
    statement = Assertion[str](value=text, source=Source.USER_EXPLICIT)
    requests = tuple(
        IntentRequest(
            instruction=statement,
            operation=op.operation,
            target_types=(proposal_type(op),),
            target_ids=(),
        )
        for op in operations
    )
    intent = ArchitecturalIntent(
        goal=statement,
        requested_operations=requests,
        preservation_instructions=preserved,
        ambiguities=ambiguities,
        confidence=Decimal("0.9"),
    )
    proposed = (
        ADGPatch(
            project_id=project.id,
            base_fingerprint=project_context(project).fingerprint,
            operations=operations,
        )
        if operations
        else None
    )
    return ProviderInterpretation(
        proposal=InterpretationProposal(
            intent=intent,
            proposed_patch=proposed,
            ambiguities=ambiguities,
            confidence=Decimal("0.9"),
            clarification_recommended=bool(ambiguities),
        ),
        metadata=ProviderMetadata(provider="mock", model="offline", instruction_version="test-v1"),
    )


def wall_change(project: Project, text: str) -> UpdateEntity:
    wall = project.walls[0]
    return UpdateEntity(
        target_id=wall.id,
        changes=WallChanges(
            id=wall.id,
            thickness=Assertion[Decimal](value=Decimal("200"), source=Source.USER_EXPLICIT),
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
        origin=text,
    )


@pytest.mark.parametrize(
    "text", ["Bu duvarın kalınlığını 200 mm yap.", "Set this wall thickness to 200 mm."]
)
def test_explicit_brief_passes_proposal_to_deterministic_engine(text: str) -> None:
    project = kitchen()
    original = serialize_project(project)
    provider = MockArchitecturalInterpreterProvider(
        interpretation(project, text, wall_change(project, text))
    )
    service = ArchitecturalBriefInterpreter(provider)
    only = service.interpret_only(project, text)
    assert serialize_project(project) == original
    assert only.proposal.proposed_patch is not None
    expected = apply_patch(project, only.proposal.proposed_patch)
    evaluated = service.interpret_and_evaluate(project, text)
    assert evaluated.patch_result == expected
    assert expected.status == PatchStatus.ACCEPTED and expected.candidate is not None
    assert expected.candidate.walls[0].id == project.walls[0].id
    assert expected.candidate.walls[0].thickness.value == Decimal("200")
    assert serialize_project(project) == original
    assert provider.last_request is not None and provider.last_request.text == text


def test_vague_aesthetic_request_refines_style_without_geometry() -> None:
    project = kitchen()
    text = "Bu salonu daha lüks yap."
    style = project.styles[0]
    operation = UpdateEntity(
        target_id=style.id,
        changes=StyleChanges(
            id=style.id, mood=Assertion[str](value="luxurious", source=Source.AI_INFERRED)
        ),
        source=Source.AI_INFERRED,
        confidence=Decimal("0.8"),
        origin=text,
    )
    provider = MockArchitecturalInterpreterProvider(interpretation(project, text, operation))
    result = (
        ArchitecturalBriefInterpreter(provider).interpret_and_evaluate(project, text).patch_result
    )
    assert result.status == PatchStatus.ACCEPTED and result.candidate is not None
    candidate = result.candidate
    assert candidate.walls == project.walls and candidate.openings == project.openings
    assert candidate.furniture == project.furniture and candidate.cameras == project.cameras
    assert candidate.styles[0].mood.source == Source.AI_INFERRED


def test_material_only_brief_preserves_geometry_and_camera() -> None:
    project = kitchen()
    text = (
        "Duvarları, pencereleri, mobilya konumlarını ve kamerayı aynen koru. "
        "Sadece malzemeleri değiştir."
    )
    preservation = PreservationInstruction(
        instruction=Assertion[str](value=text, source=Source.USER_EXPLICIT),
        target_types=("wall", "opening", "furniture", "camera"),
    )
    material = project.materials[0]
    operation = UpdateEntity(
        target_id=material.id,
        changes=MaterialChanges(
            id=material.id,
            generic_material=Assertion[str](value="natural stone", source=Source.AI_INFERRED),
        ),
        source=Source.AI_INFERRED,
        confidence=Decimal("0.8"),
        origin=text,
    )
    provider = MockArchitecturalInterpreterProvider(
        interpretation(project, text, operation, preserved=(preservation,))
    )
    service = ArchitecturalBriefInterpreter(provider)
    result = service.interpret_and_evaluate(project, text).patch_result
    assert result.status == PatchStatus.ACCEPTED and result.candidate is not None
    assert result.candidate.walls == project.walls
    assert result.candidate.openings == project.openings
    assert result.candidate.furniture == project.furniture
    assert result.candidate.cameras == project.cameras
    provider.result = interpretation(
        project, text, operation, wall_change(project, text), preserved=(preservation,)
    )
    rejected = service.interpret_and_evaluate(project, text).patch_result
    assert rejected.status == PatchStatus.REJECTED and rejected.candidate is None
    assert ConflictCode.PRESERVED_ELEMENT in {c.code for c in rejected.conflicts}


def test_camera_preservation_blocks_proposal_even_for_unlocked_camera() -> None:
    project = kitchen()
    data = project.model_dump(mode="python")
    data["cameras"][0]["locked"]["value"] = False
    project = Project.model_validate(data)
    camera = project.cameras[0]
    text = "Keep the camera unchanged."
    preservation = PreservationInstruction(
        instruction=Assertion[str](value=text, source=Source.USER_EXPLICIT), target_ids=(camera.id,)
    )
    operation = UpdateEntity(
        target_id=camera.id,
        changes=CameraChanges(
            id=camera.id,
            focal_length=Assertion[Decimal](value=Decimal("50"), source=Source.USER_EXPLICIT),
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
        origin=text,
    )
    provider = MockArchitecturalInterpreterProvider(
        interpretation(project, text, operation, preserved=(preservation,))
    )
    result = (
        ArchitecturalBriefInterpreter(provider).interpret_and_evaluate(project, text).patch_result
    )
    assert result.status == PatchStatus.REJECTED
    assert any(c.code == ConflictCode.PRESERVED_ELEMENT for c in result.conflicts)


def test_ambiguous_wall_request_does_not_guess_or_accept_a_candidate() -> None:
    project = kitchen()
    text = "Move this wall 20 cm."
    provider = MockArchitecturalInterpreterProvider(
        interpretation(project, text, ambiguities=("Which wall?",))
    )
    service = ArchitecturalBriefInterpreter(provider)
    result = service.interpret_and_evaluate(project, text)
    assert result.interpretation.proposal.proposed_patch is None
    assert result.patch_result.status == PatchStatus.NEEDS_CLARIFICATION
    assert result.patch_result.candidate is None
    provider.result = interpretation(
        project, text, wall_change(project, text), ambiguities=("Which wall?",)
    )
    result = service.interpret_and_evaluate(project, text)
    assert result.patch_result.status == PatchStatus.NEEDS_CLARIFICATION
    assert result.patch_result.candidate is None and not result.patch_result.applied_operations


def test_explicit_user_correction_of_ai_height_is_validated_atomically() -> None:
    project = kitchen()
    data = project.model_dump(mode="python")
    data["spaces"][0]["ceiling_height"]["source"] = "AI_INFERRED"
    data["spaces"][0]["ceiling_height"]["value"] = "2700"
    data["spaces"][0]["dimensions"]["source"] = "AI_INFERRED"
    data["spaces"][0]["dimensions"]["value"]["height"] = "2700"
    project = Project.model_validate(data)
    room = project.spaces[0]
    text = "Change the AI-inferred ceiling height to 2800 mm."
    operation = UpdateEntity(
        target_id=room.id,
        changes=SpaceChanges(
            id=room.id,
            ceiling_height=Assertion[Decimal](value=Decimal("2800"), source=Source.USER_EXPLICIT),
            dimensions=Assertion[Dimensions](
                value=room.dimensions.value.model_copy(update={"height": "2800"}),
                source=Source.SYSTEM_DERIVED,
            ),
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
        origin=text,
    )
    provider = MockArchitecturalInterpreterProvider(interpretation(project, text, operation))
    result = (
        ArchitecturalBriefInterpreter(provider).interpret_and_evaluate(project, text).patch_result
    )
    assert result.status == PatchStatus.ACCEPTED and result.candidate is not None
    assert result.candidate.spaces[0].ceiling_height.value == Decimal("2800")
    assert result.candidate.spaces[0].ceiling_height.source == Source.USER_EXPLICIT
    assert project.spaces[0] == room


def test_nonexistent_patch_target_rejected_by_phase3a() -> None:
    project = kitchen()
    text = "Change this wall."
    operation = wall_change(project, text).model_copy(update={"target_id": uuid4()})
    provider = MockArchitecturalInterpreterProvider(interpretation(project, text, operation))
    result = (
        ArchitecturalBriefInterpreter(provider).interpret_and_evaluate(project, text).patch_result
    )
    assert result.status == PatchStatus.REJECTED
    assert any(c.code == ConflictCode.MISSING_TARGET for c in result.conflicts)


def test_cabinetry_window_wall_constraint_flows_into_phase3a() -> None:
    project = kitchen()
    text = "Put cabinetry on the window wall."
    window = next(o for o in project.openings if o.opening_type.value == "window")
    furniture = project.furniture[0]
    operation = UpdateEntity(
        target_id=furniture.id,
        changes=FurnitureObjectChanges(
            id=furniture.id,
            host_wall_id=Assertion[UUID](
                value=window.host_wall_id.value, source=Source.USER_EXPLICIT
            ),
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
        origin=text,
    )
    provider = MockArchitecturalInterpreterProvider(interpretation(project, text, operation))
    result = (
        ArchitecturalBriefInterpreter(provider).interpret_and_evaluate(project, text).patch_result
    )
    assert result.status == PatchStatus.REJECTED and result.candidate is None
    assert any(c.code == ConflictCode.CONSTRAINT_VIOLATION for c in result.conflicts)
    assert any(
        isinstance(c, WallContact) and c.kind == "cannot_touch_wall" for c in project.constraints
    )


def test_existing_locked_geometry_is_not_overridden_by_user_text() -> None:
    project = kitchen()
    lock = Lock(
        id=uuid4(),
        kind="locked_geometry",
        target_id=Assertion[UUID](value=project.walls[0].id, source=Source.USER_EXPLICIT),
    )
    project = project.model_copy(update={"constraints": (*project.constraints, lock)})
    text = "Change the locked wall."
    provider = MockArchitecturalInterpreterProvider(
        interpretation(project, text, wall_change(project, text))
    )
    result = (
        ArchitecturalBriefInterpreter(provider).interpret_and_evaluate(project, text).patch_result
    )
    assert result.status == PatchStatus.REJECTED
    assert any(
        c.code == ConflictCode.LOCKED_ENTITY and lock.id in c.constraint_ids
        for c in result.conflicts
    )


def test_context_retains_real_ids_provenance_constraints_and_protection() -> None:
    project = kitchen()
    context = build_project_context(project)
    assert build_project_context(project).model_dump_json() == context.model_dump_json()
    assert {item.entity.id for item in context.entities} == {e.id for e in project.entities()}
    assert context.snapshot == project_context(project)
    assert all(UUID(target) in {e.id for e in project.entities()} for target in context.locked_ids)
    assert str(project.cameras[0].id) in context.locked_ids
    style = next(item.entity for item in context.entities if item.entity.id == project.styles[0].id)
    assert style == project.styles[0]
    assert context.model_dump(mode="json")["entities"]


def test_provider_failure_is_explicit_not_an_empty_intent() -> None:
    class FailedProvider:
        def interpret(self, request: BriefRequest) -> ProviderInterpretation:
            raise InterpreterProviderError(ProviderErrorCode.RATE_LIMITED)

    with pytest.raises(InterpreterProviderError) as error:
        ArchitecturalBriefInterpreter(FailedProvider()).interpret_only(kitchen(), "Change style")
    assert error.value.code == ProviderErrorCode.RATE_LIMITED


def test_malformed_provider_result_is_revalidated() -> None:
    class MalformedProvider:
        def interpret(self, request: BriefRequest) -> ProviderInterpretation:
            intent = ArchitecturalIntent(
                goal=Assertion[str](value=request.text, source=Source.USER_EXPLICIT),
                confidence=Decimal("1"),
            )
            invalid = InterpretationProposal.model_construct(intent=intent, confidence=Decimal("2"))
            return ProviderInterpretation.model_construct(
                proposal=invalid,
                metadata=ProviderMetadata(
                    provider="mock", model="invalid", instruction_version="test-v1"
                ),
            )

    with pytest.raises(InterpreterProviderError) as error:
        ArchitecturalBriefInterpreter(MalformedProvider()).interpret_only(kitchen(), "Change style")
    assert error.value.code == ProviderErrorCode.INVALID_RESPONSE


def test_explicit_origin_cannot_be_invented_by_provider() -> None:
    project = kitchen()
    text = "Make the room nicer."
    operation = wall_change(project, "Set wall thickness to 200 mm.")
    provider = MockArchitecturalInterpreterProvider(interpretation(project, text, operation))
    result = (
        ArchitecturalBriefInterpreter(provider).interpret_and_evaluate(project, text).patch_result
    )
    assert result.status == PatchStatus.REJECTED
    assert any(c.code == ConflictCode.PROVENANCE_CONFLICT for c in result.conflicts)


def test_named_product_intent_does_not_fabricate_product_properties() -> None:
    project = kitchen()
    text = "Use Porcelanosa XYZ collection."
    provider = MockArchitecturalInterpreterProvider(interpretation(project, text))
    result = ArchitecturalBriefInterpreter(provider).interpret_and_evaluate(project, text)
    assert result.interpretation.proposal.intent.goal.value == text
    assert result.patch_result.status == PatchStatus.NEEDS_CLARIFICATION
    material = project.materials[0]
    fabricated = UpdateEntity(
        target_id=material.id,
        changes=MaterialChanges(
            id=material.id, product=Assertion[str](value="XYZ-123", source=Source.AI_INFERRED)
        ),
        source=Source.AI_INFERRED,
        confidence=Decimal("0.8"),
        origin=text,
    )
    provider.result = interpretation(project, text, fabricated)
    rejected = (
        ArchitecturalBriefInterpreter(provider).interpret_and_evaluate(project, text).patch_result
    )
    assert rejected.status == PatchStatus.REJECTED
    assert any(c.code == ConflictCode.PROVENANCE_CONFLICT for c in rejected.conflicts)


def test_explicit_numeric_fact_cannot_be_fabricated_from_vague_request() -> None:
    project = kitchen()
    text = "Make the room nicer."
    provider = MockArchitecturalInterpreterProvider(
        interpretation(project, text, wall_change(project, text))
    )
    result = (
        ArchitecturalBriefInterpreter(provider).interpret_and_evaluate(project, text).patch_result
    )
    assert result.status == PatchStatus.REJECTED
    assert any(c.code == ConflictCode.PROVENANCE_CONFLICT for c in result.conflicts)
    assert numeric_evidence("20 cm, 2,8 m and 2800 mm") >= {Decimal("200"), Decimal("2800")}


def test_reference_derived_material_fact_requires_supplied_reference() -> None:
    project = kitchen()
    text = "Use the referenced material."
    material = project.materials[0]
    operation = UpdateEntity(
        target_id=material.id,
        changes=MaterialChanges(
            id=material.id,
            manufacturer=Assertion[str](
                value="Porcelanosa",
                source=Source.USER_REFERENCE,
                source_reference="brief:catalogue",
            ),
        ),
        source=Source.USER_REFERENCE,
        confidence=Decimal("1"),
        origin="brief:catalogue",
    )
    provider = MockArchitecturalInterpreterProvider(interpretation(project, text, operation))
    service = ArchitecturalBriefInterpreter(provider)
    without = service.interpret_and_evaluate(project, text).patch_result
    assert without.status == PatchStatus.REJECTED
    ref = BriefReference(reference_id="brief:catalogue", text="Requested manufacturer: Porcelanosa")
    with_ref = service.interpret_and_evaluate(project, text, references=(ref,)).patch_result
    assert with_ref.status == PatchStatus.ACCEPTED and with_ref.candidate is not None
    assert with_ref.candidate.materials[0].manufacturer is not None
    assert with_ref.candidate.materials[0].manufacturer.source == Source.USER_REFERENCE


def test_unrequested_geometry_change_is_outside_aesthetic_intent() -> None:
    project = kitchen()
    text = "Make the room luxurious."
    style = project.styles[0]
    style_op = UpdateEntity(
        target_id=style.id,
        changes=StyleChanges(
            id=style.id, mood=Assertion[str](value="luxurious", source=Source.AI_INFERRED)
        ),
        source=Source.AI_INFERRED,
        confidence=Decimal("0.8"),
        origin=text,
    )
    output = interpretation(project, text, style_op)
    assert output.proposal.proposed_patch is not None
    extra = wall_change(project, text).model_copy(
        update={
            "changes": WallChanges(
                id=project.walls[0].id,
                thickness=Assertion[Decimal](value=Decimal("200"), source=Source.AI_INFERRED),
            ),
            "source": Source.AI_INFERRED,
        }
    )
    proposal = output.proposal.model_copy(
        update={"proposed_patch": ADGPatch(project_id=project.id, operations=(style_op, extra))}
    )
    provider = MockArchitecturalInterpreterProvider(
        output.model_copy(update={"proposal": proposal})
    )
    result = (
        ArchitecturalBriefInterpreter(provider).interpret_and_evaluate(project, text).patch_result
    )
    assert result.status == PatchStatus.REJECTED and result.candidate is None
    assert any(c.code == ConflictCode.VALIDATION_FAILED for c in result.conflicts)
