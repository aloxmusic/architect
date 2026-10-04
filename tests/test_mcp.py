"""Real in-process Streamable HTTP messages; mock interpreter and no external network."""

import asyncio
import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

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
    ReferenceImage,
)
from architect_ai.domain.intent import ArchitecturalIntent, IntentRequest
from architect_ai.domain.patches import (
    AddEntity,
    ADGPatch,
    FurnitureObjectPayload,
    PatchOperation,
    PatchResult,
    UpdateEntity,
    WallChanges,
)
from architect_ai.domain.serialization import deserialize_project, serialize_project
from architect_ai.domain.values import Assertion, Source
from architect_ai.mcp.contracts import (
    BriefData,
    CompileBriefRequest,
    CompileInstructionsRequest,
    EvaluationData,
    InstructionAdapter,
    InstructionsData,
    InterpretationData,
    InterpretationRequest,
    ProjectRequest,
    ProjectSummary,
    ProjectValidation,
    ToolResponse,
)
from architect_ai.mcp.handlers import ArchitecturalTools
from architect_ai.mcp.server import create_mcp_server, tool_bindings
from architect_ai.providers.mock_interpreter import MockArchitecturalInterpreterProvider
from architect_ai.services.brief_contracts import (
    BriefRequest,
    InterpretationProposal,
    InterpreterProviderError,
    ProviderErrorCode,
    ProviderInterpretation,
    ProviderMetadata,
)
from architect_ai.services.brief_interpreter import ArchitecturalBriefInterpreter
from architect_ai.services.patching import apply_patch, project_context
from architect_ai.services.prompt_compiler import compile_generation_brief

FIXTURES = Path(__file__).parent / "fixtures" / "adg"
TOOLS = {
    "validate_project",
    "interpret_architectural_request",
    "evaluate_architectural_request",
    "evaluate_architectural_proposal",
    "compile_visualization_brief",
    "compile_image_instructions",
    "get_project_summary",
}
HEADERS = {"Accept": "application/json, text/event-stream"}


def project(name: str = "living_room") -> Project:
    return deserialize_project((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def accepted_intent(text: str = "Refine existing design") -> ArchitecturalIntent:
    return ArchitecturalIntent(
        goal=Assertion(value=text, source=Source.USER_EXPLICIT), confidence=Decimal("1")
    )


def proposal(
    snapshot: Project, text: str, *ops: PatchOperation, ambiguous: bool = False
) -> ProviderInterpretation:
    intent = accepted_intent(text).model_copy(
        update={
            "requested_operations": tuple(
                IntentRequest(
                    instruction=Assertion(value=text, source=Source.USER_EXPLICIT),
                    operation=o.operation,
                    target_types=("furniture",) if isinstance(o, AddEntity) else ("wall",),
                )
                for o in ops
            ),
            "ambiguities": ("Which wall?",) if ambiguous else (),
        }
    )
    patch = (
        ADGPatch(
            project_id=snapshot.id,
            base_fingerprint=project_context(snapshot).fingerprint,
            operations=ops,
        )
        if ops
        else None
    )
    return ProviderInterpretation(
        proposal=InterpretationProposal(
            intent=intent,
            proposed_patch=patch,
            confidence=Decimal("1"),
            clarification_recommended=ambiguous,
        ),
        metadata=ProviderMetadata(provider="mock", model="offline", instruction_version="test-v1"),
    )


def wall_update(snapshot: Project, text: str) -> UpdateEntity:
    wall = snapshot.walls[0]
    return UpdateEntity(
        target_id=wall.id,
        changes=WallChanges(
            id=wall.id, thickness=Assertion(value=Decimal("200"), source=Source.USER_EXPLICIT)
        ),
        source=Source.USER_EXPLICIT,
        confidence=Decimal("1"),
        origin=text,
    )


def rpc(client: TestClient, method: str, params: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/mcp",
        headers=HEADERS,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )
    assert response.status_code == 200, response.text
    envelope: dict[str, Any] = response.json()
    assert "error" not in envelope, envelope
    result: dict[str, Any] = envelope["result"]
    return result


def call(client: TestClient, name: str, args: dict[str, Any]) -> dict[str, Any]:
    result = rpc(client, "tools/call", {"name": name, "arguments": args})
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    assert result["content"][0]["text"] == result["structuredContent"]["summary"]
    return result


def client_for(provider: MockArchitecturalInterpreterProvider | None = None) -> TestClient:
    return TestClient(
        create_app(
            Settings(_env_file=None, environment="test", mcp_enabled=True),
            interpreter=ArchitecturalBriefInterpreter(provider) if provider else None,
        ),
        base_url="http://127.0.0.1:8000",
    )


@pytest.fixture
def mcp_client() -> Iterator[TestClient]:
    with client_for() as client:
        yield client


def test_initialization_exact_tool_surface_and_health(mcp_client: TestClient) -> None:
    init = rpc(
        mcp_client,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "offline-test", "version": "1"},
        },
    )
    assert init["serverInfo"]["name"] == "architect-ai"
    assert init["serverInfo"]["version"] == "0.1.0"
    assert "No project storage" in init["instructions"]
    inventory = rpc(mcp_client, "tools/list", {})["tools"]
    assert len(inventory) == len(TOOLS) and {t["name"] for t in inventory} == TOOLS
    for tool in inventory:
        assert tool["title"] and tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        assert tool["inputSchema"]["additionalProperties"] is False
        assert tool["outputSchema"]["type"] == "object"
        assert tool["annotations"]["readOnlyHint"] is True
        assert tool["annotations"]["destructiveHint"] is False
        assert tool["annotations"]["openWorldHint"] is False
    assert mcp_client.get("/api/v1/health").json()["status"] == "ok"
    assert set(mcp_client.get("/openapi.json").json()["paths"]) == {"/api/v1/health"}


def test_contracts_validate_valid_inputs_and_reject_extras() -> None:
    snapshot = project()
    assert ProjectRequest.model_validate({"project": snapshot}).project == snapshot
    assert InterpretationRequest(project=snapshot, text="Refine").text == "Refine"
    with pytest.raises(ValidationError):
        ProjectRequest.model_validate({"project": snapshot, "execute": "arbitrary code"})
    with pytest.raises(ValidationError):
        InterpretationRequest(project=snapshot, text=" ")


def test_validate_project_accepts_valid_adg(mcp_client: TestClient) -> None:
    snapshot = project()
    result = call(mcp_client, "validate_project", {"project": snapshot.model_dump(mode="json")})
    parsed = ToolResponse[ProjectValidation].model_validate(result["structuredContent"])
    assert parsed.ok and parsed.data is not None and parsed.data.valid
    assert parsed.data.snapshot == project_context(snapshot)
    assert not result["isError"]
    assert (
        "Mcp-Session-Id"
        not in mcp_client.post(
            "/mcp",
            headers=HEADERS,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        ).headers
    )


def test_validate_project_rejects_malformed_without_echo(mcp_client: TestClient) -> None:
    data = project().model_dump(mode="json")
    data["walls"][0]["height"]["value"] = "secret-invalid-dimension"
    result = call(mcp_client, "validate_project", {"project": data})
    assert result["isError"] and result["structuredContent"]["error"]["code"] == "INVALID_PROJECT"
    assert "secret-invalid-dimension" not in json.dumps(result)
    assert result["structuredContent"]["error"]["issues"]


def test_interpret_only_uses_mock_and_never_applies_candidate() -> None:
    snapshot, text = project(), "Set wall thickness to 200 mm"
    original = serialize_project(snapshot)
    provider = MockArchitecturalInterpreterProvider(
        proposal(snapshot, text, wall_update(snapshot, text))
    )
    with client_for(provider) as client:
        result = call(
            client,
            "interpret_architectural_request",
            {"project": snapshot.model_dump(mode="json"), "text": text},
        )
    parsed = ToolResponse[InterpretationData].model_validate(result["structuredContent"])
    assert parsed.ok and parsed.data is not None and parsed.data.proposal.proposed_patch is not None
    assert provider.last_request is not None and provider.last_request.text == text
    assert "candidate" not in result["structuredContent"]["data"]
    assert serialize_project(snapshot) == original


def test_evaluate_reuses_existing_patch_service(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot, text = project(), "Set wall thickness to 200 mm"
    update = wall_update(snapshot, text)
    provider = MockArchitecturalInterpreterProvider(proposal(snapshot, text, update))
    seen: list[ADGPatch] = []

    def spy(
        current: Project, patch: ADGPatch, *, confirmed_destructive: bool = False
    ) -> PatchResult:
        seen.append(patch)
        return apply_patch(current, patch, confirmed_destructive=confirmed_destructive)

    monkeypatch.setattr("architect_ai.services.brief_interpreter.apply_patch", spy)
    with client_for(provider) as client:
        result = call(
            client,
            "evaluate_architectural_request",
            {"project": snapshot.model_dump(mode="json"), "text": text},
        )
    parsed = ToolResponse[EvaluationData].model_validate(result["structuredContent"])
    assert len(seen) == 1
    assert parsed.ok and parsed.data is not None and parsed.data.candidate is not None
    assert parsed.data.status == "ACCEPTED" and not parsed.data.persisted
    assert parsed.data.candidate.walls[0].thickness.value == Decimal("200")
    assert snapshot.walls[0].thickness.value == Decimal("150")


def test_window_wall_cabinetry_conflict_is_structured() -> None:
    snapshot, text = project("l_layout_kitchen"), "Place cabinetry on the window wall"
    obj_data = snapshot.furniture[0].model_dump(mode="python")
    obj_data["id"] = uuid4()
    for value in obj_data.values():
        if isinstance(value, dict) and "source" in value:
            value["source"] = Source.AI_INFERRED
    obj_data["host_wall_id"] = {
        "value": snapshot.openings[0].host_wall_id.value,
        "source": Source.AI_INFERRED,
    }
    payload = FurnitureObjectPayload.model_validate({"entity": obj_data})
    op = AddEntity(payload=payload, source=Source.AI_INFERRED, confidence=Decimal("1"), origin=text)
    provider = MockArchitecturalInterpreterProvider(proposal(snapshot, text, op))
    with client_for(provider) as client:
        result = call(
            client,
            "evaluate_architectural_request",
            {"project": snapshot.model_dump(mode="json"), "text": text},
        )
    parsed = ToolResponse[EvaluationData].model_validate(result["structuredContent"])
    assert not parsed.ok and parsed.data is not None and parsed.data.candidate is None
    assert "CONSTRAINT_VIOLATION" in {c.code for c in parsed.data.conflicts}
    assert parsed.error is not None and parsed.error.code == "PATCH_REJECTED"


def test_clarification_required_interpretation_and_evaluation() -> None:
    snapshot, text = project(), "Move this wall"
    provider = MockArchitecturalInterpreterProvider(proposal(snapshot, text, ambiguous=True))
    with client_for(provider) as client:
        for name in ("interpret_architectural_request", "evaluate_architectural_request"):
            result = call(client, name, {"project": snapshot.model_dump(mode="json"), "text": text})
            data = result["structuredContent"]
            assert data["error"]["code"] == "CLARIFICATION_REQUIRED"
            if name.startswith("evaluate"):
                assert data["data"]["clarification_required"]
                assert data["data"]["candidate"] is None
            else:
                assert data["data"]["summary"]["clarification_required"]


def test_locked_geometry_is_protected_through_mcp() -> None:
    snapshot, text = project(), "Set wall thickness to 200 mm"
    lock = Lock(
        id=uuid4(),
        kind="locked_geometry",
        target_id=Assertion(value=snapshot.walls[0].id, source=Source.USER_EXPLICIT),
    )
    snapshot = snapshot.model_copy(update={"constraints": (*snapshot.constraints, lock)})
    provider = MockArchitecturalInterpreterProvider(
        proposal(snapshot, text, wall_update(snapshot, text))
    )
    with client_for(provider) as client:
        result = call(
            client,
            "evaluate_architectural_request",
            {"project": snapshot.model_dump(mode="json"), "text": text},
        )
    assert result["structuredContent"]["data"]["candidate"] is None
    assert "LOCKED_ENTITY" in {c["code"] for c in result["structuredContent"]["data"]["conflicts"]}


def compilation() -> CompileBriefRequest:
    return CompileBriefRequest(
        project=project(),
        intent=accepted_intent(),
        accepted_intent=True,
        options=CompilationOptions(
            output=OutputSpecification(target=OutputTarget.ARCHITECTURAL_RENDER),
            mode=GenerationMode.GEOMETRY_LOCKED_RENDER_MODE,
        ),
    )


def test_compile_brief_returns_existing_ir(mcp_client: TestClient) -> None:
    request = compilation()
    result = call(mcp_client, "compile_visualization_brief", request.model_dump(mode="json"))
    parsed = ToolResponse[BriefData].model_validate(result["structuredContent"])
    assert parsed.ok and parsed.data is not None
    assert parsed.data.brief == compile_generation_brief(
        request.project, request.intent, request.options
    )


@pytest.mark.parametrize("adapter", tuple(InstructionAdapter))
def test_instruction_adapter_selection(mcp_client: TestClient, adapter: InstructionAdapter) -> None:
    request = compilation()
    brief = compile_generation_brief(
        request.project,
        request.intent,
        request.options.model_copy(
            update={
                "reference": ReferenceImage(available=True),
            }
        ),
    )
    instructions = CompileInstructionsRequest(brief=brief, adapter=adapter)
    result = call(mcp_client, "compile_image_instructions", instructions.model_dump(mode="json"))
    parsed = ToolResponse[InstructionsData].model_validate(result["structuredContent"])
    assert parsed.ok and parsed.data is not None
    assert parsed.data.instructions.adapter == adapter.value
    assert parsed.data.instructions.permissions == brief.permissions


@pytest.mark.parametrize(
    "tool_name,args,code",
    (
        (
            "compile_image_instructions",
            {"adapter": "arbitrary-provider"},
            "UNSUPPORTED_INSTRUCTION_ADAPTER",
        ),
        ("validate_project", {}, "INVALID_INPUT"),
        ("execute", {"code": "import os"}, "INVALID_INPUT"),
    ),
)
def test_unsupported_and_missing_inputs_fail_safely(
    mcp_client: TestClient, tool_name: str, args: dict[str, Any], code: str
) -> None:
    result = call(mcp_client, tool_name, args)
    assert result["isError"] and result["structuredContent"]["error"]["code"] == code
    assert "Traceback" not in json.dumps(result)


def test_unsupported_mode_and_unaccepted_intent_fail(mcp_client: TestClient) -> None:
    args = compilation().model_dump(mode="json")
    args["options"]["mode"] = "invented-mode"
    assert (
        call(mcp_client, "compile_visualization_brief", args)["structuredContent"]["error"]["code"]
        == "UNSUPPORTED_GENERATION_MODE"
    )
    args = compilation().model_dump(mode="json")
    args["accepted_intent"] = False
    assert (
        call(mcp_client, "compile_visualization_brief", args)["structuredContent"]["error"]["code"]
        == "CLARIFICATION_REQUIRED"
    )
    args["accepted_intent"] = "true"
    assert (
        call(mcp_client, "compile_visualization_brief", args)["structuredContent"]["error"]["code"]
        == "INVALID_INPUT"
    )


def test_no_provider_configured_does_not_use_key(
    mcp_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-do-not-call")
    result = call(
        mcp_client,
        "interpret_architectural_request",
        {"project": project().model_dump(mode="json"), "text": "Refine"},
    )
    assert result["structuredContent"]["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert "secret-do-not-call" not in json.dumps(result)


@pytest.mark.parametrize(
    "code,expected",
    (
        (ProviderErrorCode.MISSING_API_KEY, "PROVIDER_UNAVAILABLE"),
        (ProviderErrorCode.TRANSIENT_FAILURE, "PROVIDER_UNAVAILABLE"),
        (ProviderErrorCode.INVALID_RESPONSE, "INTERPRETATION_FAILED"),
    ),
)
def test_provider_errors_are_safe(code: ProviderErrorCode, expected: str) -> None:
    class FailureProvider:
        def interpret(self, request: BriefRequest) -> ProviderInterpretation:
            raise InterpreterProviderError(code)

    app = create_app(
        Settings(_env_file=None, mcp_enabled=True),
        interpreter=ArchitecturalBriefInterpreter(FailureProvider()),
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        result = call(
            client,
            "interpret_architectural_request",
            {"project": project().model_dump(mode="json"), "text": "Refine"},
        )
    assert result["structuredContent"]["error"]["code"] == expected


def test_internal_exception_never_returns_or_logs_secret(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def crash(self: ArchitecturalTools, request: ProjectRequest) -> ToolResponse[ProjectSummary]:
        raise RuntimeError("secret-token-private-path")

    monkeypatch.setattr(ArchitecturalTools, "get_project_summary", crash)
    with client_for() as client:
        result = call(client, "get_project_summary", {"project": project().model_dump(mode="json")})
    assert result["structuredContent"]["error"]["code"] == "INTERNAL_ERROR"
    assert "secret-token-private-path" not in json.dumps(result)
    assert "Traceback" not in json.dumps(result)
    assert "secret-token-private-path" not in caplog.text


def test_summary_is_deterministic_and_not_persistent(mcp_client: TestClient) -> None:
    args = {"project": project().model_dump(mode="json")}
    first = call(mcp_client, "get_project_summary", args)["structuredContent"]
    second = call(mcp_client, "get_project_summary", args)["structuredContent"]
    assert first == second
    parsed = ToolResponse[ProjectSummary].model_validate(first)
    assert parsed.data is not None and not parsed.data.persisted
    assert parsed.data.snapshot == project_context(project())
    missing = call(mcp_client, "get_project_summary", {"project_id": str(project().id)})
    assert missing["structuredContent"]["error"]["code"] == "INVALID_INPUT"


def test_construction_with_live_opt_in_does_not_construct_openai_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network provider client must remain lazy during construction")

    monkeypatch.setattr(OpenAI, "__init__", forbidden)
    app = create_app(Settings(_env_file=None, mcp_enabled=True, mcp_live_interpreter_enabled=True))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/api/v1/health").status_code == 200
        assert len(rpc(client, "tools/list", {})["tools"]) == 7


def test_sdk_dns_rebinding_protection_remains_enabled() -> None:
    with client_for() as client:
        response = client.post(
            "/mcp",
            headers={**HEADERS, "Host": "untrusted.example:8000"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert response.status_code == 421


def test_each_binding_has_explicit_output_schema() -> None:
    bindings = tool_bindings(ArchitecturalTools())
    assert {b.tool.name for b in bindings} == TOOLS
    assert all(
        b.tool.output_schema is not None and "$defs" in b.tool.output_schema for b in bindings
    )


def test_official_sdk_client_validates_structured_output_schemas() -> None:
    snapshot, text = project(), "Set wall thickness to 200 mm"
    provider = MockArchitecturalInterpreterProvider(
        proposal(snapshot, text, wall_update(snapshot, text))
    )
    server = create_mcp_server(ArchitecturalBriefInterpreter(provider))
    request = compilation()
    brief = compile_generation_brief(request.project, request.intent, request.options)
    inputs: dict[str, dict[str, Any]] = {
        "validate_project": {"project": snapshot.model_dump(mode="json")},
        "get_project_summary": {"project": snapshot.model_dump(mode="json")},
        "interpret_architectural_request": {
            "project": snapshot.model_dump(mode="json"),
            "text": text,
        },
        "evaluate_architectural_request": {
            "project": snapshot.model_dump(mode="json"),
            "text": text,
        },
        "compile_visualization_brief": request.model_dump(mode="json"),
        "compile_image_instructions": CompileInstructionsRequest(
            brief=brief, adapter=InstructionAdapter.OPENAI_IMAGE
        ).model_dump(mode="json"),
    }

    async def run() -> None:
        async with Client(server) as client:
            inventory = await client.list_tools()
            assert {t.name for t in inventory.tools} == TOOLS
            for name, args in inputs.items():
                result = await client.call_tool(name, args)
                assert not result.is_error and result.structured_content["ok"]

    asyncio.run(run())
