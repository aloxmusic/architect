"""Real SDK parsing and error mapping with offline HTTP transport only."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest
from openai import OpenAI
from pydantic import SecretStr

from architect_ai.config import Settings
from architect_ai.domain.intent import ArchitecturalIntent, IntentRequest
from architect_ai.domain.patches import AddEntity, UpdateEntity
from architect_ai.domain.serialization import deserialize_project
from architect_ai.domain.values import Assertion, Source
from architect_ai.providers.architectural_instructions import INSTRUCTION_VERSION, INSTRUCTIONS
from architect_ai.providers.openai_brief_schema import WireProposal, decode_proposal
from architect_ai.providers.openai_interpreter import OpenAIArchitecturalInterpreterProvider
from architect_ai.services.brief_context import build_project_context
from architect_ai.services.brief_contracts import (
    BriefRequest,
    InterpreterProviderError,
    ProviderErrorCode,
)


def request() -> BriefRequest:
    path = Path(__file__).parent / "fixtures/adg/l_layout_kitchen.json"
    project = deserialize_project(path.read_text(encoding="utf-8"))
    return BriefRequest(
        text="Set wall thickness to 200 mm.", context=build_project_context(project)
    )


def wire_data(brief: BriefRequest) -> dict[str, Any]:
    wall = next(item.entity for item in brief.context.entities if item.entity_type == "wall")
    intent = ArchitecturalIntent(
        goal=Assertion[str](value=brief.text, source=Source.USER_EXPLICIT),
        requested_operations=(
            IntentRequest(
                instruction=Assertion[str](value=brief.text, source=Source.USER_EXPLICIT),
                operation="UPDATE_ENTITY",
                target_types=("wall",),
            ),
        ),
        confidence=Decimal("1"),
    )
    return {
        "intent": intent.model_dump(mode="json"),
        "operations": [
            {
                "operation": "UPDATE_ENTITY",
                "target_id": str(wall.id),
                "entity_type": "wall",
                "changes": [
                    {
                        "field": "thickness",
                        "value": "200",
                        "source": "USER_EXPLICIT",
                        "source_reference": None,
                    }
                ],
                "source": "USER_EXPLICIT",
                "confidence": "1",
                "origin": brief.text,
            }
        ],
        "ambiguities": [],
        "assumptions": [],
        "confidence": "1",
        "clarification_recommended": False,
    }


def sdk_response(data: dict[str, Any], *, status: str = "completed") -> dict[str, Any]:
    return {
        "id": "resp_offline",
        "created_at": 1,
        "model": "gpt-6-astra",
        "object": "response",
        "status": status,
        "parallel_tool_calls": False,
        "tool_choice": "none",
        "tools": [],
        "output": [
            {
                "id": "msg_offline",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "annotations": [], "text": json.dumps(data)}],
            }
        ],
    }


def assert_supported_schema(node: Any) -> None:
    if isinstance(node, dict):
        assert not {"oneOf", "discriminator", "prefixItems", "default"} & node.keys()
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        for value in node.values():
            assert_supported_schema(value)
    elif isinstance(node, list):
        for value in node:
            assert_supported_schema(value)


def test_sdk_structured_parsing_uses_safe_request_configuration() -> None:
    brief = request()
    sent: list[dict[str, Any]] = []

    def transport(http_request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(http_request.content))
        return httpx2.Response(200, json=sdk_response(wire_data(brief)))

    with httpx2.Client(transport=httpx2.MockTransport(transport)) as http_client:
        with OpenAI(
            api_key="offline-placeholder", http_client=http_client, max_retries=0
        ) as client:
            provider = OpenAIArchitecturalInterpreterProvider(
                Settings(_env_file=None), client=client
            )
            result = provider.interpret(brief)
    assert len(sent) == 1
    body = sent[0]
    assert body["model"] == "gpt-6-astra" and body["store"] is False
    assert body["tools"] == [] and body["tool_choice"] == "none"
    assert body["instructions"] == INSTRUCTIONS
    assert json.loads(body["input"]) == brief.model_dump(mode="json")
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert_supported_schema(body["text"]["format"]["schema"])
    assert result.metadata.instruction_version == INSTRUCTION_VERSION
    assert result.proposal.proposed_patch is not None
    assert result.proposal.proposed_patch.project_id == brief.context.snapshot.project_id
    assert result.proposal.proposed_patch.base_fingerprint == brief.context.snapshot.fingerprint


@pytest.mark.parametrize(
    "status,code",
    [
        (401, ProviderErrorCode.AUTHENTICATION_FAILED),
        (403, ProviderErrorCode.AUTHENTICATION_FAILED),
        (429, ProviderErrorCode.RATE_LIMITED),
        (500, ProviderErrorCode.TRANSIENT_FAILURE),
        (400, ProviderErrorCode.UNSUPPORTED_CONFIGURATION),
        (404, ProviderErrorCode.UNSUPPORTED_CONFIGURATION),
    ],
)
def test_provider_http_failures_are_safe_and_bounded(status: int, code: ProviderErrorCode) -> None:
    count = 0

    def transport(http_request: httpx2.Request) -> httpx2.Response:
        nonlocal count
        count += 1
        return httpx2.Response(
            status, json={"error": {"message": "sensitive-offline-body", "type": "test"}}
        )

    with httpx2.Client(transport=httpx2.MockTransport(transport)) as http_client:
        with OpenAI(
            api_key="offline-placeholder", http_client=http_client, max_retries=0
        ) as client:
            with pytest.raises(InterpreterProviderError) as error:
                OpenAIArchitecturalInterpreterProvider(
                    Settings(_env_file=None), client=client
                ).interpret(request())
    assert error.value.code == code
    assert "sensitive-offline-body" not in str(error.value)
    assert "offline-placeholder" not in str(error.value)
    assert count == 1


def test_connection_failure_is_transient() -> None:
    def transport(http_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("offline failure", request=http_request)

    with httpx2.Client(transport=httpx2.MockTransport(transport)) as http_client:
        with OpenAI(
            api_key="offline-placeholder", http_client=http_client, max_retries=0
        ) as client:
            with pytest.raises(InterpreterProviderError) as error:
                OpenAIArchitecturalInterpreterProvider(
                    Settings(_env_file=None), client=client
                ).interpret(request())
    assert error.value.code == ProviderErrorCode.TRANSIENT_FAILURE


@pytest.mark.parametrize(
    "case,code",
    [
        ("refusal", ProviderErrorCode.REFUSAL),
        ("incomplete", ProviderErrorCode.INCOMPLETE_RESPONSE),
        ("truncated", ProviderErrorCode.INCOMPLETE_RESPONSE),
        ("malformed", ProviderErrorCode.INVALID_RESPONSE),
        ("missing", ProviderErrorCode.INVALID_RESPONSE),
    ],
)
def test_invalid_incomplete_and_refused_structured_outputs(
    case: str, code: ProviderErrorCode
) -> None:
    brief = request()
    body = sdk_response(wire_data(brief))
    if case == "refusal":
        body["output"][0]["content"] = [{"type": "refusal", "refusal": "Cannot help"}]
    elif case in {"incomplete", "truncated"}:
        body["status"] = "incomplete"
        body["incomplete_details"] = {"reason": "max_output_tokens"}
        if case == "truncated":
            body["output"][0]["content"][0]["text"] = '{"intent":'
    elif case == "malformed":
        body["output"][0]["content"][0]["text"] = "{invalid"
    else:
        body["output"] = []

    def transport(http_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=body)

    with httpx2.Client(transport=httpx2.MockTransport(transport)) as http_client:
        with OpenAI(
            api_key="offline-placeholder", http_client=http_client, max_retries=0
        ) as client:
            with pytest.raises(InterpreterProviderError) as error:
                OpenAIArchitecturalInterpreterProvider(
                    Settings(_env_file=None), client=client
                ).interpret(brief)
    assert error.value.code == code


def test_missing_key_is_detected_without_client_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIArchitecturalInterpreterProvider(Settings(_env_file=None))
    with pytest.raises(InterpreterProviderError) as error:
        provider.interpret(request())
    assert error.value.code == ProviderErrorCode.MISSING_API_KEY


def test_settings_load_model_and_hide_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "offline-sensitive-key")
    monkeypatch.setenv("ARCHITECT_AI_OPENAI_MODEL", "custom-model")
    settings = Settings(_env_file=None)
    assert settings.openai_api_key == SecretStr("offline-sensitive-key")
    assert settings.openai_model == "custom-model"
    assert "offline-sensitive-key" not in repr(settings)
    assert "openai_api_key" not in settings.model_dump()
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "OPENAI_API_KEY=offline-dotenv\nARCHITECT_AI_OPENAI_MODEL=dotenv-model\n", encoding="utf-8"
    )
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.delenv("ARCHITECT_AI_OPENAI_MODEL")
    assert Settings(_env_file=dotenv).openai_api_key == SecretStr("offline-dotenv")


def test_decoder_rejects_unknown_or_duplicate_field_changes() -> None:
    brief = request()
    data = wire_data(brief)
    data["operations"][0]["changes"][0]["field"] = "arbitrary_dictionary"
    with pytest.raises(ValueError):
        decode_proposal(WireProposal.model_validate(data), brief)
    data = wire_data(brief)
    data["operations"][0]["changes"] *= 2
    with pytest.raises(ValueError, match="Duplicate"):
        decode_proposal(WireProposal.model_validate(data), brief)


def test_context_limit_fails_before_client_creation() -> None:
    brief = request().model_copy(update={"text": "x" * 60001})
    with pytest.raises(InterpreterProviderError) as error:
        OpenAIArchitecturalInterpreterProvider(Settings(_env_file=None)).interpret(brief)
    assert error.value.code == ProviderErrorCode.CONTEXT_TOO_LARGE


def test_addition_ids_are_application_allocated_and_repeatable() -> None:
    brief = request().model_copy(update={"text": "Add a natural stone material record."})
    data = wire_data(brief)
    data["operations"] = [
        {
            "operation": "ADD_ENTITY",
            "target_id": None,
            "entity_type": "material",
            "changes": [
                {
                    "field": "generic_material",
                    "value": "natural stone",
                    "source": "USER_EXPLICIT",
                    "source_reference": None,
                },
                {
                    "field": "verification_status",
                    "value": "unverified",
                    "source": "SYSTEM_DERIVED",
                    "source_reference": None,
                },
            ],
            "source": "USER_EXPLICIT",
            "confidence": "1",
            "origin": brief.text,
        }
    ]
    wire = WireProposal.model_validate(data)
    first = decode_proposal(wire, brief)
    second = decode_proposal(wire, brief)
    assert first == second and first.proposed_patch is not None
    operation = first.proposed_patch.operations[0]
    assert isinstance(operation, AddEntity)
    assert operation.payload.entity.id not in {item.entity.id for item in brief.context.entities}
    data["operations"][0]["target_id"] = str(brief.context.entities[0].entity.id)
    with pytest.raises(ValueError, match="allocated"):
        decode_proposal(WireProposal.model_validate(data), brief)


def test_wire_geometry_uses_decimal_strings_and_validated_domain_objects() -> None:
    brief = request()
    data = wire_data(brief)
    wall = next(item.entity for item in brief.context.entities if item.entity_type == "wall")
    data["operations"][0]["target_id"] = str(wall.id)
    data["operations"][0]["changes"] = [
        {
            "field": "start",
            "value": {"kind": "point", "x": "100", "y": "0", "z": "0"},
            "source": "SYSTEM_DERIVED",
            "source_reference": None,
        }
    ]
    output = decode_proposal(WireProposal.model_validate(data), brief)
    assert output.proposed_patch is not None
    operation = output.proposed_patch.operations[0]
    assert isinstance(operation, UpdateEntity)
    dumped = operation.changes.model_dump(mode="json")
    assert dumped["start"]["value"] == {"x": "100", "y": "0", "z": "0"}


def test_provider_transport_rejects_an_accepted_project_field() -> None:
    data = wire_data(request())
    data["accepted_project"] = {"id": "not-a-proposal"}
    with pytest.raises(ValueError):
        WireProposal.model_validate(data)
