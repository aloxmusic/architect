"""Provider-neutral interpretation ports and proposal contracts, outside the domain."""

from enum import StrEnum
from typing import Protocol

from architect_ai.domain.intent import ArchitecturalIntent
from architect_ai.domain.patches import ADGPatch, Confidence, EntityPayload, ProjectContext
from architect_ai.domain.values import Assertion, DomainModel, Text


class InterpretationContext(DomainModel):
    snapshot: ProjectContext
    name: Assertion[Text]
    project_type: Assertion[Text]
    locale: Assertion[Text]
    status: Assertion[Text]
    units: str
    entities: tuple[EntityPayload, ...]
    locked_ids: tuple[str, ...]
    preserved_ids: tuple[str, ...]


class BriefReference(DomainModel):
    reference_id: Text
    text: Text


class BriefRequest(DomainModel):
    text: Text
    context: InterpretationContext
    references: tuple[BriefReference, ...] = ()


class InterpretationProposal(DomainModel):
    intent: ArchitecturalIntent
    proposed_patch: ADGPatch | None = None
    ambiguities: tuple[Text, ...] = ()
    assumptions: tuple[Assertion[Text], ...] = ()
    confidence: Confidence
    clarification_recommended: bool = False


class ProviderMetadata(DomainModel):
    provider: Text
    model: Text
    response_id: Text | None = None
    instruction_version: Text


class ProviderInterpretation(DomainModel):
    proposal: InterpretationProposal
    metadata: ProviderMetadata


class ProviderErrorCode(StrEnum):
    MISSING_API_KEY = "MISSING_API_KEY"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INCOMPLETE_RESPONSE = "INCOMPLETE_RESPONSE"
    REFUSAL = "REFUSAL"
    UNSUPPORTED_CONFIGURATION = "UNSUPPORTED_CONFIGURATION"
    CONTEXT_TOO_LARGE = "CONTEXT_TOO_LARGE"


class InterpreterProviderError(Exception):
    """Only a stable code is exposed; SDK error bodies and secrets are never copied."""

    def __init__(self, code: ProviderErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class ArchitecturalInterpreterProvider(Protocol):
    def interpret(self, request: BriefRequest) -> ProviderInterpretation: ...
