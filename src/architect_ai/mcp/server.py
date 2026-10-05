"""Official SDK server with explicit schemas and a sanitized tool-result boundary."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import anyio
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolAnnotations,
)
from pydantic import BaseModel, ValidationError

from architect_ai import __version__
from architect_ai.mcp.contracts import (
    BriefData,
    CompileBriefRequest,
    CompileInstructionsRequest,
    ErrorCode,
    EvaluationData,
    InstructionsData,
    InterpretationData,
    InterpretationRequest,
    ProjectRequest,
    ProjectSummary,
    ProjectValidation,
    ProposalRequest,
    ToolError,
    ToolResponse,
    ValidationIssue,
)
from architect_ai.mcp.handlers import ArchitecturalTools, WorkflowError
from architect_ai.services.brief_contracts import InterpreterProviderError, ProviderErrorCode
from architect_ai.services.brief_interpreter import ArchitecturalBriefInterpreter
from architect_ai.services.prompt_compiler import CompilationError, CompilationErrorCode

logger = logging.getLogger("architect_ai.mcp")
SERVER_INSTRUCTIONS = (
    "Architect AI computes results from explicitly supplied immutable project snapshots. "
    "No project storage or image generation exists. Interpretation returns proposals only; "
    "evaluation returns an unpersisted candidate only after deterministic acceptance. "
    "Preserve locks and constraints. Compilation requires caller-accepted intent."
)


def failure(code: ErrorCode, issues: tuple[ValidationIssue, ...] = ()) -> ToolResponse[Any]:
    message = {
        ErrorCode.INVALID_PROJECT: "The supplied ADG project is invalid.",
        ErrorCode.VALIDATION_FAILED: "Architectural validation failed.",
        ErrorCode.INTERPRETATION_FAILED: "The architectural request could not be interpreted.",
        ErrorCode.PROVIDER_UNAVAILABLE: "The interpreter provider is unavailable or not enabled.",
        ErrorCode.CLARIFICATION_REQUIRED: "Clarification or accepted intent is required.",
        ErrorCode.PATCH_REJECTED: "The proposed patch was rejected.",
        ErrorCode.UNSUPPORTED_GENERATION_MODE: "Select a supported generation mode.",
        ErrorCode.UNSUPPORTED_INSTRUCTION_ADAPTER: "Select a supported instruction adapter.",
        ErrorCode.INVALID_INPUT: "Tool arguments are invalid.",
        ErrorCode.INTERNAL_ERROR: "The architectural tool could not complete the request.",
    }[code]
    return ToolResponse(
        ok=False, summary=message, error=ToolError(code=code, message=message, issues=issues)
    )


def safe_validation_error(exc: ValidationError) -> ToolResponse[Any]:
    errors = exc.errors(include_input=False, include_context=False, include_url=False)
    locations = {tuple(e["loc"]) for e in errors}
    code = ErrorCode.INVALID_INPUT
    if any(
        e["loc"][:1] == ("project",) and (len(e["loc"]) > 1 or e["type"] != "missing")
        for e in errors
    ):
        code = ErrorCode.INVALID_PROJECT
    elif ("options", "mode") in locations:
        code = ErrorCode.UNSUPPORTED_GENERATION_MODE
    elif ("adapter",) in locations and any(e["type"] == "enum" for e in errors):
        code = ErrorCode.UNSUPPORTED_INSTRUCTION_ADAPTER
    fields = {
        "project",
        "text",
        "references",
        "intent",
        "patch",
        "evaluation",
        "options",
        "brief",
        "adapter",
    }
    issues = tuple(
        ValidationIssue.model_validate(
            {
                "field": str(e["loc"][0]) if e["loc"] and e["loc"][0] in fields else "arguments",
                "reason": e["type"],
            }
        )
        for e in errors[:20]
    )
    return failure(code, issues)


def result(response: ToolResponse[Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=response.summary)],
        structured_content=response.model_dump(mode="json"),
        is_error=not response.ok,
    )


@dataclass(frozen=True)
class ToolBinding:
    tool: Tool
    invoke: Callable[[dict[str, Any]], Awaitable[CallToolResult]]


def connector_schema(value: Any) -> Any:
    """Express nonblank text as a whole-string match for connector compatibility."""
    if isinstance(value, dict):
        return {
            key: r"^[\s\S]*\S[\s\S]*$"
            if key == "pattern" and item == r"\S"
            else connector_schema(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [connector_schema(item) for item in value]
    return value


def binding[R: BaseModel, T: BaseModel](
    name: str,
    title: str,
    description: str,
    request_model: type[R],
    response_model: type[ToolResponse[T]],
    handler: Callable[[R], ToolResponse[T]],
) -> ToolBinding:
    async def invoke(arguments: dict[str, Any]) -> CallToolResult:
        try:
            request = request_model.model_validate(arguments)
        except ValidationError as exc:
            logger.info("mcp.invalid_input")
            return result(safe_validation_error(exc))
        except Exception as exc:
            logger.error("mcp.validation_error.%s", type(exc).__name__)
            return result(failure(ErrorCode.INTERNAL_ERROR))
        try:
            response = await anyio.to_thread.run_sync(lambda: handler(request))
            # Validate the declared structured output as well as the external arguments.
            response = response_model.model_validate(response)
            return result(response)
        except WorkflowError as exc:
            logger.info("mcp.workflow_error.%s", exc.code.value)
            return result(failure(exc.code))
        except InterpreterProviderError as exc:
            logger.warning("mcp.provider_error.%s", exc.code.value)
            unavailable = exc.code in {
                ProviderErrorCode.MISSING_API_KEY,
                ProviderErrorCode.AUTHENTICATION_FAILED,
                ProviderErrorCode.RATE_LIMITED,
                ProviderErrorCode.TRANSIENT_FAILURE,
                ProviderErrorCode.UNSUPPORTED_CONFIGURATION,
            }
            return result(
                failure(
                    ErrorCode.PROVIDER_UNAVAILABLE
                    if unavailable
                    else ErrorCode.INTERPRETATION_FAILED
                )
            )
        except CompilationError as exc:
            logger.info("mcp.compilation_error.%s", exc.code.value)
            clarification = exc.code in {
                CompilationErrorCode.AMBIGUOUS_TARGET,
                CompilationErrorCode.AMBIGUOUS_INTENT,
            }
            return result(
                failure(
                    ErrorCode.CLARIFICATION_REQUIRED
                    if clarification
                    else ErrorCode.VALIDATION_FAILED
                )
            )
        except Exception as exc:
            # Never log exception values, inputs, secrets or raw stack traces.
            logger.error(
                "mcp.internal_error.%s", type(exc).__name__, extra={"request_id": uuid4().hex}
            )
            return result(failure(ErrorCode.INTERNAL_ERROR))

    return ToolBinding(
        tool=Tool(
            name=name,
            title=title,
            description=description,
            input_schema=connector_schema(request_model.model_json_schema()),
            # Wrapped patch serializers erase union discriminators in serialization schemas.
            # Validation schemas retain the typed omission-aware fields and validate emitted JSON.
            output_schema=connector_schema(response_model.model_json_schema(mode="validation")),
            annotations=ToolAnnotations(
                read_only_hint=True, destructive_hint=False, open_world_hint=False
            ),
        ),
        invoke=invoke,
    )


def tool_bindings(tools: ArchitecturalTools) -> tuple[ToolBinding, ...]:
    return (
        binding(
            "validate_project",
            "Validate architectural project",
            "Validate the supplied ADG snapshot and supported symbolic constraints; no storage.",
            ProjectRequest,
            ToolResponse[ProjectValidation],
            tools.validate_project,
        ),
        binding(
            "interpret_architectural_request",
            "Interpret architectural request",
            "Interpret language against the supplied project into a proposal; never apply changes. "
            "Requires an explicitly requested, enabled server-side interpreter. "
            "ChatGPT/Codex should interpret in the host by default and ask about ambiguous targets "
            "without calling this tool. May send bounded context to enabled OpenAI.",
            InterpretationRequest,
            ToolResponse[InterpretationData],
            tools.interpret_architectural_request,
        ),
        binding(
            "evaluate_architectural_request",
            "Evaluate architectural request",
            "Interpret then evaluate through the existing deterministic patch/conflict engine. "
            "Return an accepted candidate only on acceptance; never persist or confirm removals. "
            "Requires an explicitly requested, enabled server-side interpreter; not the default "
            "ChatGPT/Codex route. Ask about ambiguous targets directly; use "
            "evaluate_architectural_proposal for host-constructed intent/patch. "
            "May send bounded context to the configured OpenAI interpreter when enabled.",
            InterpretationRequest,
            ToolResponse[EvaluationData],
            tools.evaluate_architectural_request,
        ),
        binding(
            "evaluate_architectural_proposal",
            "Evaluate architectural proposal",
            "Validate supplied project, intent and patch against supplied user text/references and "
            "the deterministic patch engine. Return same accepted intent and candidate; "
            "no provider calls, API key, persistence or destructive confirmation.",
            ProposalRequest,
            ToolResponse[EvaluationData],
            tools.evaluate_architectural_proposal,
        ),
        binding(
            "compile_visualization_brief",
            "Compile visualization brief",
            "Compile supplied project and caller-accepted intent into GenerationBrief; no images.",
            CompileBriefRequest,
            ToolResponse[BriefData],
            tools.compile_visualization_brief,
        ),
        binding(
            "compile_image_instructions",
            "Compile image instructions",
            "Convert GenerationBrief through a supported instruction adapter; no provider calls.",
            CompileInstructionsRequest,
            ToolResponse[InstructionsData],
            tools.compile_image_instructions,
        ),
        binding(
            "get_project_summary",
            "Summarize architectural project",
            "Summarize supplied ADG IDs, counts, style and protections; no project storage.",
            ProjectRequest,
            ToolResponse[ProjectSummary],
            tools.get_project_summary,
        ),
    )


def create_mcp_server(interpreter: ArchitecturalBriefInterpreter | None = None) -> Server[None]:
    bindings = tool_bindings(ArchitecturalTools(interpreter))
    by_name = {b.tool.name: b for b in bindings}

    async def list_tools(
        ctx: ServerRequestContext[None], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=[b.tool for b in bindings])

    async def call_tool(
        ctx: ServerRequestContext[None], params: CallToolRequestParams
    ) -> CallToolResult:
        selected = by_name.get(params.name)
        if selected is None:
            return result(failure(ErrorCode.INVALID_INPUT))
        return await selected.invoke(params.arguments or {})

    return Server(
        name="architect-ai",
        version=__version__,
        title="Architect AI",
        instructions=SERVER_INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
