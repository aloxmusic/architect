"""Typed external workflow contracts; no MCP types enter domain or services."""

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from architect_ai.domain.adg_v1 import Project
from architect_ai.domain.generation import (
    CompilationOptions,
    CompiledInstructionPackage,
    GenerationBrief,
)
from architect_ai.domain.intent import ArchitecturalIntent
from architect_ai.domain.patches import (
    ADGPatch,
    Confidence,
    ConflictCode,
    PatchOperation,
    PatchStatus,
    ProjectContext,
)
from architect_ai.domain.values import Assertion, DomainModel, Text
from architect_ai.services.brief_contracts import BriefReference, InterpretationProposal


class ErrorCode(StrEnum):
    INVALID_PROJECT = "INVALID_PROJECT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INTERPRETATION_FAILED = "INTERPRETATION_FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    PATCH_REJECTED = "PATCH_REJECTED"
    UNSUPPORTED_GENERATION_MODE = "UNSUPPORTED_GENERATION_MODE"
    UNSUPPORTED_INSTRUCTION_ADAPTER = "UNSUPPORTED_INSTRUCTION_ADAPTER"
    INVALID_INPUT = "INVALID_INPUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ValidationIssue(DomainModel):
    field: Literal[
        "project",
        "text",
        "references",
        "intent",
        "patch",
        "evaluation",
        "options",
        "brief",
        "adapter",
        "arguments",
    ]
    reason: Text


class ToolError(DomainModel):
    code: ErrorCode
    message: Text
    issues: tuple[ValidationIssue, ...] = ()


class ToolResponse[T](DomainModel):
    ok: bool
    summary: Text
    data: T | None = None
    error: ToolError | None = None


class ProjectRequest(DomainModel):
    project: Project


class InterpretationRequest(ProjectRequest):
    text: Text
    references: tuple[BriefReference, ...] = ()


class ProposalPatch(ADGPatch):
    operations: Annotated[tuple[PatchOperation, ...], Field(min_length=1, max_length=100)]


class ProposalRequest(ProjectRequest):
    text: Annotated[Text, Field(max_length=60000)]
    intent: ArchitecturalIntent
    patch: ProposalPatch
    references: Annotated[tuple[BriefReference, ...], Field(max_length=32)] = ()


class InstructionAdapter(StrEnum):
    OPENAI_IMAGE = "openai_image"
    GENERIC_TEXT_TO_IMAGE = "generic_text_to_image"
    GENERIC_IMAGE_TO_IMAGE = "generic_image_to_image"


class CompileInstructionsRequest(DomainModel):
    brief: GenerationBrief
    adapter: InstructionAdapter


class EntityCount(DomainModel):
    collection: Text
    count: int


class ProjectValidation(DomainModel):
    valid: bool
    snapshot: ProjectContext
    entity_count: int


class InterpretationSummary(DomainModel):
    goal: Assertion[Text]
    confidence: Confidence
    clarification_required: bool
    ambiguities: tuple[Text, ...]


class InterpretationData(DomainModel):
    summary: InterpretationSummary
    proposal: InterpretationProposal
    snapshot: ProjectContext


class ConflictSummary(DomainModel):
    code: ConflictCode
    severity: Literal["error", "clarification"]
    target_ids: tuple[UUID, ...]
    constraint_ids: tuple[UUID, ...]
    requires_clarification: bool


class EvaluationData(DomainModel):
    interpretation: InterpretationSummary
    status: PatchStatus
    conflicts: tuple[ConflictSummary, ...]
    clarification_required: bool
    candidate: Project | None
    original: ProjectContext
    persisted: Literal[False] = False
    accepted_intent: ArchitecturalIntent | None = None
    evaluated_patch: ADGPatch | None = None

    @model_validator(mode="after")
    def accepted_pair_only(self) -> Self:
        if self.status != PatchStatus.ACCEPTED and (
            self.candidate is not None or self.accepted_intent is not None
        ):
            raise ValueError(
                "Non-accepted evaluation cannot supply an accepted project/intent pair"
            )
        if self.accepted_intent is not None and (
            self.candidate is None
            or self.evaluated_patch is None
            or self.conflicts
            or self.clarification_required
            or self.accepted_intent.goal != self.interpretation.goal
            or self.candidate.id != self.original.project_id
            or self.evaluated_patch.project_id != self.original.project_id
        ):
            raise ValueError("Accepted handoff must contain a consistent project, intent and patch")
        return self


class CompileBriefRequest(ProjectRequest):
    intent: ArchitecturalIntent
    options: CompilationOptions
    accepted_intent: StrictBool
    evaluation: EvaluationData | None = None


class BriefData(DomainModel):
    brief: GenerationBrief


class InstructionsData(DomainModel):
    instructions: CompiledInstructionPackage


class ProjectSummary(DomainModel):
    snapshot: ProjectContext
    name: Assertion[Text]
    project_type: Assertion[Text]
    units: Literal["mm"]
    locale: Assertion[Text]
    counts: tuple[EntityCount, ...]
    space_ids: tuple[UUID, ...]
    locked_ids: tuple[UUID, ...]
    preserved_ids: tuple[UUID, ...]
    primary_styles: tuple[Assertion[Text], ...]
    output_types: tuple[Assertion[Text], ...]
    persisted: Literal[False] = False
