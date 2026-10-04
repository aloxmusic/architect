"""Thin architectural workflow handlers; every result is a supplied-snapshot computation."""

from architect_ai.domain.patches import ConflictCode, PatchResult, PatchStatus
from architect_ai.domain.values import Assertion
from architect_ai.mcp.contracts import (
    BriefData,
    CompileBriefRequest,
    CompileInstructionsRequest,
    ConflictSummary,
    EntityCount,
    ErrorCode,
    EvaluationData,
    InstructionAdapter,
    InstructionsData,
    InterpretationData,
    InterpretationRequest,
    InterpretationSummary,
    ProjectRequest,
    ProjectSummary,
    ProjectValidation,
    ProposalRequest,
    ToolError,
    ToolResponse,
)
from architect_ai.providers.image_instructions import (
    GenericImageToImageInstructionAdapter,
    GenericTextToImageInstructionAdapter,
    ImageInstructionAdapter,
    OpenAIImageInstructionAdapter,
)
from architect_ai.services.brief_contracts import InterpretationProposal
from architect_ai.services.brief_interpreter import ArchitecturalBriefInterpreter, evaluate_proposal
from architect_ai.services.patching import graph_conflicts, project_context, protection
from architect_ai.services.prompt_compiler import compile_generation_brief

ADAPTERS: dict[InstructionAdapter, ImageInstructionAdapter] = {
    InstructionAdapter.OPENAI_IMAGE: OpenAIImageInstructionAdapter(),
    InstructionAdapter.GENERIC_TEXT_TO_IMAGE: GenericTextToImageInstructionAdapter(),
    InstructionAdapter.GENERIC_IMAGE_TO_IMAGE: GenericImageToImageInstructionAdapter(),
}


class WorkflowError(Exception):
    def __init__(self, code: ErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


def interpretation_summary(proposal: InterpretationProposal) -> InterpretationSummary:
    ambiguities = tuple(dict.fromkeys((*proposal.ambiguities, *proposal.intent.ambiguities)))
    return InterpretationSummary(
        goal=proposal.intent.goal,
        confidence=proposal.confidence,
        clarification_required=proposal.clarification_recommended or bool(ambiguities),
        ambiguities=ambiguities,
    )


class ArchitecturalTools:
    def __init__(self, interpreter: ArchitecturalBriefInterpreter | None = None) -> None:
        self.interpreter = interpreter

    def require_interpreter(self) -> ArchitecturalBriefInterpreter:
        if self.interpreter is None:
            raise WorkflowError(ErrorCode.PROVIDER_UNAVAILABLE)
        return self.interpreter

    def validate_project(self, request: ProjectRequest) -> ToolResponse[ProjectValidation]:
        if graph_conflicts(request.project.entities()):
            raise WorkflowError(ErrorCode.VALIDATION_FAILED)
        return ToolResponse(
            ok=True,
            summary="Supplied ADG is valid; no project was stored.",
            data=ProjectValidation(
                valid=True,
                snapshot=project_context(request.project),
                entity_count=len(request.project.entities()),
            ),
        )

    def interpret_architectural_request(
        self, request: InterpretationRequest
    ) -> ToolResponse[InterpretationData]:
        result = self.require_interpreter().interpret_only(
            request.project, request.text, references=request.references
        )
        summary = interpretation_summary(result.proposal)
        return ToolResponse(
            ok=True,
            summary="Interpretation proposal only; no project changes were applied.",
            data=InterpretationData(
                summary=summary, proposal=result.proposal, snapshot=project_context(request.project)
            ),
            error=ToolError(
                code=ErrorCode.CLARIFICATION_REQUIRED,
                message="Clarification is required before accepting changes.",
            )
            if summary.clarification_required
            else None,
        )

    def evaluate_architectural_request(
        self, request: InterpretationRequest
    ) -> ToolResponse[EvaluationData]:
        # Destructive confirmation is deliberately not delegated to an untrusted tool boolean.
        result = self.require_interpreter().interpret_and_evaluate(
            request.project, request.text, references=request.references
        )
        return evaluation_response(result.interpretation.proposal, result.patch_result)

    def evaluate_architectural_proposal(
        self, request: ProposalRequest
    ) -> ToolResponse[EvaluationData]:
        proposal = InterpretationProposal(
            intent=request.intent,
            proposed_patch=request.patch,
            confidence=request.intent.confidence,
        )
        result = evaluate_proposal(
            request.project,
            proposal,
            request.text,
            references=request.references,
        )
        return evaluation_response(proposal, result)

    def compile_visualization_brief(self, request: CompileBriefRequest) -> ToolResponse[BriefData]:
        if not request.accepted_intent:
            raise WorkflowError(ErrorCode.CLARIFICATION_REQUIRED)
        evaluation = request.evaluation
        if evaluation is not None:
            if (
                evaluation.status != PatchStatus.ACCEPTED
                or evaluation.clarification_required
                or evaluation.conflicts
                or evaluation.accepted_intent is None
                or evaluation.candidate is None
                or evaluation.evaluated_patch is None
            ):
                raise WorkflowError(ErrorCode.CLARIFICATION_REQUIRED)
            if (
                evaluation.accepted_intent != request.intent
                or evaluation.candidate != request.project
            ):
                raise WorkflowError(ErrorCode.INVALID_INPUT)
        brief = compile_generation_brief(request.project, request.intent, request.options)
        return ToolResponse(
            ok=True,
            summary="Visualization brief compiled; no image was generated.",
            data=BriefData(brief=brief),
        )

    def compile_image_instructions(
        self, request: CompileInstructionsRequest
    ) -> ToolResponse[InstructionsData]:
        if (
            request.adapter == InstructionAdapter.GENERIC_IMAGE_TO_IMAGE
            and not request.brief.reference.available
        ):
            raise WorkflowError(ErrorCode.INVALID_INPUT)
        package = ADAPTERS[request.adapter].compile(request.brief)
        return ToolResponse(
            ok=True,
            summary="Image instructions compiled; no provider was called.",
            data=InstructionsData(instructions=package),
        )

    def get_project_summary(self, request: ProjectRequest) -> ToolResponse[ProjectSummary]:
        project = request.project
        entities = tuple(sorted(project.entities(), key=lambda e: str(e.id)))
        protections = {e.id: p for e in entities if (p := protection(project, e.id)) is not None}
        collections = (
            "spaces",
            "walls",
            "openings",
            "fixed_elements",
            "furniture",
            "styles",
            "materials",
            "lighting",
            "cameras",
            "output_intents",
            "constraints",
        )
        data = ProjectSummary(
            snapshot=project_context(project),
            name=project.name,
            project_type=project.project_type,
            units=project.units,
            locale=project.locale,
            counts=tuple(
                EntityCount(collection=name, count=len(getattr(project, name)))
                for name in collections
            ),
            space_ids=tuple(sorted((s.id for s in project.spaces), key=str)),
            locked_ids=tuple(
                i for i, p in protections.items() if p[0] == ConflictCode.LOCKED_ENTITY
            ),
            preserved_ids=tuple(
                i for i, p in protections.items() if p[0] == ConflictCode.PRESERVED_ELEMENT
            ),
            primary_styles=tuple(
                s.primary_style for s in sorted(project.styles, key=lambda s: str(s.id))
            ),
            output_types=tuple(
                Assertion[str].model_validate(o.output_type.model_dump())
                for o in sorted(project.output_intents, key=lambda o: str(o.id))
            ),
        )
        return ToolResponse(
            ok=True,
            summary="Summary of supplied snapshot; no persistent project exists.",
            data=data,
        )


def evaluation_response(
    proposal: InterpretationProposal, patch: PatchResult
) -> ToolResponse[EvaluationData]:
    clarification = patch.status == PatchStatus.NEEDS_CLARIFICATION or any(
        c.requires_clarification for c in patch.conflicts
    )
    code = ErrorCode.CLARIFICATION_REQUIRED if clarification else ErrorCode.PATCH_REJECTED
    accepted = patch.status == PatchStatus.ACCEPTED
    return ToolResponse(
        ok=accepted,
        summary=f"Patch evaluation: {patch.status.value}; nothing was persisted.",
        data=EvaluationData(
            interpretation=interpretation_summary(proposal),
            status=patch.status,
            conflicts=tuple(
                ConflictSummary(
                    code=c.code,
                    severity=c.severity,
                    target_ids=c.target_ids,
                    constraint_ids=c.constraint_ids,
                    requires_clarification=c.requires_clarification,
                )
                for c in patch.conflicts
            ),
            clarification_required=clarification,
            candidate=patch.candidate if accepted else None,
            original=patch.original,
            accepted_intent=proposal.intent if accepted else None,
            evaluated_patch=proposal.proposed_patch if accepted else None,
        ),
        error=None
        if accepted
        else ToolError(code=code, message="Patch requires review or clarification."),
    )
