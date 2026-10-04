"""Offline fixed-proposal provider for deterministic orchestration tests."""

from architect_ai.services.brief_contracts import BriefRequest, ProviderInterpretation


class MockArchitecturalInterpreterProvider:
    def __init__(self, result: ProviderInterpretation) -> None:
        self.result = result
        self.last_request: BriefRequest | None = None

    def interpret(self, request: BriefRequest) -> ProviderInterpretation:
        self.last_request = request
        return self.result
