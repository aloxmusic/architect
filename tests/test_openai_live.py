"""One opt-in smoke test; never enabled during normal Phase 3B verification."""

import os
from pathlib import Path

import pytest

from architect_ai.config import Settings
from architect_ai.domain.serialization import deserialize_project
from architect_ai.providers.openai_interpreter import OpenAIArchitecturalInterpreterProvider
from architect_ai.services.brief_interpreter import ArchitecturalBriefInterpreter


@pytest.mark.skipif(
    os.environ.get("ARCHITECT_AI_RUN_LIVE_OPENAI_TESTS") != "1"
    or not os.environ.get("OPENAI_API_KEY", "").strip(),
    reason="Live OpenAI smoke requires an API key and explicit opt-in",
)
def test_optional_live_interpretation() -> None:
    path = Path(__file__).parent / "fixtures/adg/l_layout_kitchen.json"
    project = deserialize_project(path.read_text(encoding="utf-8"))
    service = ArchitecturalBriefInterpreter(
        OpenAIArchitecturalInterpreterProvider(Settings(_env_file=None))
    )
    result = service.interpret_only(
        project, "Move this wall 20 cm. Which wall is unspecified; ask for clarification."
    )
    assert (
        result.proposal.clarification_recommended
        or result.proposal.ambiguities
        or result.proposal.intent.ambiguities
    )
