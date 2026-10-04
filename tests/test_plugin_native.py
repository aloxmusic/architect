"""Provider-free proposal acceptance and compilation over real in-process MCP."""

import asyncio
import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from mcp import Client
from openai import OpenAI
from pydantic import ValidationError

from architect_ai.api.app import create_app
from architect_ai.config import Settings
from architect_ai.domain.adg_v1 import Lock, Project
from architect_ai.domain.generation import (
    CompilationOptions,
    GenerationMode,
    OutputSpecification,
    OutputTarget,
)
from architect_ai.domain.intent import ArchitecturalIntent, IntentRequest, PreservationInstruction
from architect_ai.domain.patches import (
    ADGPatch,
    CameraChanges,
    FurnitureObjectChanges,
    MaterialChanges,
    PatchResult,
    PatchStatus,
    StyleChanges,
    UpdateEntity,
    WallChanges,
)
from architect_ai.domain.serialization import deserialize_project, serialize_project
from architect_ai.domain.values import Assertion, Source
from architect_ai.mcp.contracts import (
    CompileBriefRequest,
    EvaluationData,
    InterpretationRequest,
    ProposalRequest,
    ToolResponse,
)
from architect_ai.mcp.handlers import ArchitecturalTools, WorkflowError
from architect_ai.mcp.server import create_mcp_server
from architect_ai.providers.mock_interpreter import MockArchitecturalInterpreterProvider
from architect_ai.providers.openai_interpreter import OpenAIArchitecturalInterpreterProvider
from architect_ai.services.brief_contracts import (
    BriefReference,
    InterpretationProposal,
    ProviderInterpretation,
    ProviderMetadata,
)
from architect_ai.services.brief_interpreter import ArchitecturalBriefInterpreter
from architect_ai.services.patching import apply_patch, project_context

FIXTURES = Path(__file__).parent / "fixtures" / "adg"
HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture(autouse=True)
def prohibit_provider_and_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ARCHITECT_AI_MCP_LIVE_INTERPRETER_ENABLED", "false")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Plugin-native tests must not call a provider or network")

    monkeypatch.setattr(OpenAI, "__init__", forbidden)
    monkeypatch.setattr(OpenAIArchitecturalInterpreterProvider, "interpret", forbidden)
    # Block outbound HTTP transports, preserving Windows event-loop socketpair wakeups.
    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", forbidden)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None, environment="test", mcp_enabled=True))
    with TestClient(app, base_url="http://127.0.0.1:8000") as session:
        yield session


def snapshot(name: str = "living_room") -> Project:
    return deserialize_project((FIXTURES / f"{name}.json").read_text("utf-8"))


def proposal(
    project: Project,
    operation: UpdateEntity | None = None,
    *,
    text: str = "Make this room luxurious without changing architecture or camera.",
) -> ProposalRequest:
    style = project.styles[0]
    operation = operation or UpdateEntity(
        target_id=style.id,
        changes=StyleChanges(
            id=style.id, mood=Assertion(value="luxurious", source=Source.AI_INFERRED)
        ),
        source=Source.AI_INFERRED,
        confidence=Decimal("0.8"),
        origin=text,
    )
    request = IntentRequest(
        instruction=Assertion(value=text, source=Source.USER_EXPLICIT),
        operation="UPDATE_ENTITY",
        target_ids=(operation.target_id,),
        target_types=(operation.changes.entity_type,),
    )
    intent = ArchitecturalIntent(
        goal=Assertion(value=text, source=Source.USER_EXPLICIT),
        requested_operations=(request,),
        style_changes=(request,) if operation.changes.entity_type == "style" else (),
        material_changes=(request,) if operation.changes.entity_type == "material" else (),
        confidence=Decimal("0.8"),
    )
    patch = ADGPatch(
        project_id=project.id,
        base_fingerprint=project_context(project).fingerprint,
        operations=(operation,),
    )
    return ProposalRequest.model_validate(
        {
            "project": project,
            "text": text,
            "intent": intent,
            "patch": patch.model_dump(mode="python"),
        }
    )


def call(client: TestClient, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/mcp",
        headers=HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200
    result: dict[str, Any] = response.json()["result"]
    structured: dict[str, Any] = result["structuredContent"]
    return structured


def test_turkish_material_normalization_preserves_other_fields(client: TestClient) -> None:
    project = snapshot()
    material = project.materials[0]
    text = (
        "Mevcut meşe malzemeyi ceviz yap. Diğer bütün değerler aynı kalsın. "
        "Üretici veya ürün bilgisi ekleme. Şimdilik görsel üretme."
    )
    operation = UpdateEntity(
        target_id=material.id,
        changes=MaterialChanges(
            id=material.id,
            generic_material=Assertion(value="walnut", source=Source.AI_INFERRED),
        ),
        source=Source.AI_INFERRED,
        confidence=Decimal("1"),
        origin="Mevcut meşe malzemeyi ceviz yap.",
    )
    request = proposal(project, operation, text=text)
    preservation = PreservationInstruction(
        instruction=Assertion(
            value="Diğer bütün değerler aynı kalsın.", source=Source.USER_EXPLICIT
        ),
        target_ids=tuple(entity.id for entity in project.entities() if entity.id != material.id),
    )
    request = request.model_copy(
        update={
            "intent": request.intent.model_copy(
                update={"preservation_instructions": (preservation,)}
            )
        }
    )
    response = call(client, "evaluate_architectural_proposal", request.model_dump(mode="json"))
    assert response["ok"] is True
    result = EvaluationData.model_validate(response["data"])
    assert result.status == PatchStatus.ACCEPTED
    assert result.conflicts == ()
    assert result.candidate is not None
    assert isinstance(operation.changes, MaterialChanges)
    expected = project.model_copy(
        update={
            "materials": (
                material.model_copy(
                    update={"generic_material": operation.changes.generic_material}
                ),
            )
        }
    )
    assert result.candidate == expected


def options() -> CompilationOptions:
    return CompilationOptions(
        mode=GenerationMode.GEOMETRY_LOCKED_RENDER_MODE,
        output=OutputSpecification(target=OutputTarget.ARCHITECTURAL_RENDER),
    )


def compilation(
    result: EvaluationData,
    *,
    project: Project | None = None,
    intent: ArchitecturalIntent | None = None,
) -> CompileBriefRequest:
    assert result.candidate is not None and result.accepted_intent is not None
    return CompileBriefRequest(
        project=project or result.candidate,
        intent=intent or result.accepted_intent,
        options=options(),
        accepted_intent=True,
        evaluation=result,
    )


def test_proposal_uses_phase3a_and_returns_same_intent_and_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = proposal(snapshot())
    before = serialize_project(request.project)
    seen: list[ADGPatch] = []

    def spy(
        project: Project, patch: ADGPatch, *, confirmed_destructive: bool = False
    ) -> PatchResult:
        seen.append(patch)
        return apply_patch(project, patch, confirmed_destructive=confirmed_destructive)

    monkeypatch.setattr("architect_ai.services.brief_interpreter.apply_patch", spy)
    response = ArchitecturalTools().evaluate_architectural_proposal(request)
    assert response.ok and response.data is not None
    result = response.data
    assert len(seen) == 1
    assert result.status == PatchStatus.ACCEPTED
    assert result.accepted_intent == request.intent
    assert result.evaluated_patch is not None
    assert result.evaluated_patch.model_dump(mode="json") == request.patch.model_dump(mode="json")
    assert result.candidate == apply_patch(request.project, request.patch).candidate
    assert result.candidate is not None
    assert result.candidate.styles[0].mood.source == Source.AI_INFERRED
    assert result.candidate.walls == request.project.walls
    assert result.candidate.cameras == request.project.cameras
    assert serialize_project(request.project) == before


def test_full_mcp_evaluation_brief_instructions_without_provider(client: TestClient) -> None:
    request = proposal(snapshot())
    envelope = call(client, "evaluate_architectural_proposal", request.model_dump(mode="json"))
    result = ToolResponse[EvaluationData].model_validate(envelope)
    assert result.ok and result.data is not None
    compiled = call(
        client, "compile_visualization_brief", compilation(result.data).model_dump(mode="json")
    )
    assert compiled["ok"]
    brief = compiled["data"]["brief"]
    assert brief["goal"] == request.intent.goal.model_dump(mode="json")
    instructions = call(
        client, "compile_image_instructions", {"brief": brief, "adapter": "openai_image"}
    )
    assert instructions["ok"] and instructions["data"]["instructions"]
    assert not result.data.persisted


def test_official_sdk_checks_new_tool_output_schema() -> None:
    request = proposal(snapshot())

    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            result = await client.call_tool(
                "evaluate_architectural_proposal", request.model_dump(mode="json")
            )
            assert not result.is_error and result.structured_content["ok"]
            assert result.structured_content["data"][
                "accepted_intent"
            ] == request.intent.model_dump(mode="json")

    asyncio.run(run())


@pytest.mark.parametrize("change", ["intent", "project"])
def test_compiler_rejects_substituted_handoff(change: str) -> None:
    result = ArchitecturalTools().evaluate_architectural_proposal(proposal(snapshot())).data
    assert result is not None
    assert result.accepted_intent is not None and result.candidate is not None
    request = compilation(
        result,
        intent=result.accepted_intent.model_copy(update={"confidence": "0.5"})
        if change == "intent"
        else None,
        project=snapshot() if change == "project" else None,
    )
    with pytest.raises(WorkflowError):
        ArchitecturalTools().compile_visualization_brief(request)


@pytest.mark.parametrize("ambiguity", [False, True])
def test_nonaccepted_handoff_cannot_compile(ambiguity: bool) -> None:
    request = proposal(snapshot())
    if ambiguity:
        request = request.model_copy(
            update={"intent": request.intent.model_copy(update={"ambiguities": ("Which wall?",)})}
        )
    else:
        request = request.model_copy(
            update={"patch": request.patch.model_copy(update={"base_fingerprint": "stale"})}
        )
    tools = ArchitecturalTools()
    response = tools.evaluate_architectural_proposal(request)
    assert not response.ok and response.data is not None
    result = response.data
    assert result.status == (PatchStatus.NEEDS_CLARIFICATION if ambiguity else PatchStatus.REJECTED)
    assert result.candidate is None and result.accepted_intent is None
    with pytest.raises(WorkflowError):
        tools.compile_visualization_brief(
            CompileBriefRequest(
                project=request.project,
                intent=request.intent,
                options=options(),
                accepted_intent=True,
                evaluation=result,
            )
        )
    with pytest.raises(ValidationError):
        result.model_copy(update={"candidate": request.project, "accepted_intent": request.intent})


@pytest.mark.parametrize("kind", ["geometry", "camera", "window_wall"])
def test_architectural_protections_remain_enforced(kind: str) -> None:
    project = snapshot("l_layout_kitchen")
    text = "Change the selected entity."
    changes: WallChanges | CameraChanges | FurnitureObjectChanges
    if kind == "geometry":
        wall = project.walls[0]
        lock = Lock(
            id=uuid4(),
            kind="locked_geometry",
            target_id=Assertion(value=wall.id, source=Source.USER_EXPLICIT),
        )
        project = project.model_copy(update={"constraints": (*project.constraints, lock)})
        changes = WallChanges(
            id=wall.id, thickness=Assertion(value=Decimal("200"), source=Source.AI_INFERRED)
        )
        target = wall.id
    elif kind == "camera":
        camera = project.cameras[0]
        changes = CameraChanges(
            id=camera.id, focal_length=Assertion(value=Decimal("50"), source=Source.AI_INFERRED)
        )
        target = camera.id
    else:
        furniture = project.furniture[0]
        window = next(o for o in project.openings if o.opening_type.value == "window")
        changes = FurnitureObjectChanges(
            id=furniture.id,
            host_wall_id=Assertion[UUID](
                value=window.host_wall_id.value, source=Source.AI_INFERRED
            ),
        )
        target = furniture.id
    operation = UpdateEntity(
        target_id=target,
        changes=changes,
        source=Source.AI_INFERRED,
        confidence=Decimal("0.8"),
        origin=text,
    )
    response = ArchitecturalTools().evaluate_architectural_proposal(
        proposal(project, operation, text=text)
    )
    assert not response.ok and response.data is not None
    assert response.data.candidate is None and response.data.accepted_intent is None
    assert ("CONSTRAINT_VIOLATION" if kind == "window_wall" else "LOCKED_ENTITY") in {
        c.code for c in response.data.conflicts
    }


@pytest.mark.parametrize("origin", ["Set wall thickness to 200 mm.", "Invented user origin."])
def test_user_explicit_requires_actual_origin(origin: str) -> None:
    project = snapshot()
    text = "Set wall thickness to 200 mm."
    operation = UpdateEntity(
        target_id=project.walls[0].id,
        changes=WallChanges(
            id=project.walls[0].id,
            thickness=Assertion(value=Decimal("200"), source=Source.USER_EXPLICIT),
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
        origin=origin,
    )
    response = ArchitecturalTools().evaluate_architectural_proposal(
        proposal(project, operation, text=text)
    )
    assert response.ok == (origin == text)
    assert response.data is not None
    if origin != text:
        assert "PROVENANCE_CONFLICT" in {c.code for c in response.data.conflicts}


def test_host_cannot_label_inferred_style_as_explicit() -> None:
    request = proposal(snapshot(), text="Make the room nicer.")
    operation = request.patch.operations[0]
    assert isinstance(operation, UpdateEntity)
    data = request.model_dump(mode="json")
    data["patch"]["operations"][0]["source"] = "USER_EXPLICIT"
    data["patch"]["operations"][0]["changes"]["mood"]["source"] = "USER_EXPLICIT"
    response = ArchitecturalTools().evaluate_architectural_proposal(
        ProposalRequest.model_validate(data)
    )
    assert not response.ok and response.data is not None
    assert "PROVENANCE_CONFLICT" in {c.code for c in response.data.conflicts}


def test_unknown_intent_id_rejected() -> None:
    request = proposal(snapshot())
    request = request.model_copy(
        update={"intent": request.intent.model_copy(update={"target_ids": (uuid4(),)})}
    )
    response = ArchitecturalTools().evaluate_architectural_proposal(request)
    assert not response.ok and response.data is not None
    assert "INVALID_REFERENCE" in {c.code for c in response.data.conflicts}


def test_unknown_patch_id_rejected() -> None:
    request = proposal(snapshot())
    data = request.model_dump(mode="json")
    data["patch"]["operations"][0]["target_id"] = str(uuid4())
    response = ArchitecturalTools().evaluate_architectural_proposal(
        ProposalRequest.model_validate(data)
    )
    assert not response.ok and response.data is not None
    assert "MISSING_TARGET" in {c.code for c in response.data.conflicts}


@pytest.mark.parametrize("field", ["intent", "patch", "extra"])
def test_malformed_proposal_safe_error(client: TestClient, field: str) -> None:
    data = proposal(snapshot()).model_dump(mode="json")
    if field == "extra":
        data["execute"] = "private-rejected-input"
    else:
        data[field] = {"private": "private-rejected-input"}
    result = call(client, "evaluate_architectural_proposal", data)
    assert not result["ok"] and result["error"]["code"] == "INVALID_INPUT"
    assert "private-rejected-input" not in json.dumps(result)


def test_proposal_bounds_are_explicit() -> None:
    data = proposal(snapshot()).model_dump(mode="json")
    data["patch"]["operations"] *= 101
    with pytest.raises(ValidationError):
        ProposalRequest.model_validate(data)
    data = proposal(snapshot()).model_dump(mode="json")
    data["text"] = "x" * 60001
    with pytest.raises(ValidationError):
        ProposalRequest.model_validate(data)


def test_standalone_mock_returns_corresponding_intent() -> None:
    request = proposal(snapshot())
    provider = MockArchitecturalInterpreterProvider(
        ProviderInterpretation(
            proposal=InterpretationProposal(
                intent=request.intent, proposed_patch=request.patch, confidence=Decimal("0.8")
            ),
            metadata=ProviderMetadata(
                provider="mock", model="offline", instruction_version="test-v1"
            ),
        )
    )
    tools = ArchitecturalTools(ArchitecturalBriefInterpreter(provider))
    response = tools.evaluate_architectural_request(
        InterpretationRequest(project=request.project, text=request.text)
    )
    assert response.ok and response.data is not None
    assert response.data.accepted_intent == request.intent
    assert tools.compile_visualization_brief(compilation(response.data)).ok


def test_preservation_scope_and_reference_evidence_are_not_bypassed() -> None:
    project = snapshot()
    material = project.materials[0]
    operation = UpdateEntity(
        target_id=material.id,
        changes=MaterialChanges(
            id=material.id,
            manufacturer=Assertion(
                value="UnknownBrand",
                source=Source.USER_REFERENCE,
                source_reference="missing-catalogue",
            ),
        ),
        source=Source.USER_REFERENCE,
        confidence=Decimal("1"),
        origin="missing-catalogue",
    )
    request = proposal(project, operation)
    intent = request.intent.model_copy(
        update={
            "preservation_instructions": (
                PreservationInstruction(instruction=request.intent.goal, target_ids=(material.id,)),
            )
        }
    )
    response = ArchitecturalTools().evaluate_architectural_proposal(
        request.model_copy(update={"intent": intent})
    )
    assert not response.ok and response.data is not None
    assert {"PRESERVED_ELEMENT", "PROVENANCE_CONFLICT"} <= {c.code for c in response.data.conflicts}


def test_unsupported_explicit_intent_and_assumptions_are_rejected() -> None:
    request = proposal(snapshot())
    data = request.model_dump(mode="json")
    data["intent"]["goal"]["value"] = "User explicitly requested demolition."
    data["intent"]["assumptions"] = [{"value": request.text, "source": "USER_EXPLICIT"}]
    response = ArchitecturalTools().evaluate_architectural_proposal(
        ProposalRequest.model_validate(data)
    )
    assert not response.ok and response.data is not None
    assert response.data.accepted_intent is None
    assert "PROVENANCE_CONFLICT" in {c.code for c in response.data.conflicts}


def test_supplied_reference_fact_keeps_reference_source() -> None:
    project = snapshot()
    material = project.materials[0]
    text = "Use the supplied material reference."
    operation = UpdateEntity(
        target_id=material.id,
        changes=MaterialChanges(
            id=material.id,
            manufacturer=Assertion(
                value="KnownBrand",
                source=Source.USER_REFERENCE,
                source_reference="catalogue:1",
            ),
        ),
        source=Source.USER_REFERENCE,
        confidence=Decimal("1"),
        origin="catalogue:1",
    )
    request = proposal(project, operation, text=text).model_copy(
        update={
            "references": (
                BriefReference(reference_id="catalogue:1", text="Manufacturer: KnownBrand"),
            )
        }
    )
    response = ArchitecturalTools().evaluate_architectural_proposal(request)
    assert response.ok and response.data is not None and response.data.candidate is not None
    value = response.data.candidate.materials[0].manufacturer
    assert value is not None and value.source == Source.USER_REFERENCE
    assert value.source_reference == "catalogue:1"


def test_patch_outside_intent_is_rejected() -> None:
    request = proposal(snapshot())
    data = request.model_dump(mode="json")
    data["intent"]["requested_operations"] = []
    data["intent"]["style_changes"] = []
    response = ArchitecturalTools().evaluate_architectural_proposal(
        ProposalRequest.model_validate(data)
    )
    assert not response.ok and response.data is not None
    assert "VALIDATION_FAILED" in {c.code for c in response.data.conflicts}
