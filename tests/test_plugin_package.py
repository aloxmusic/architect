"""Small offline checks for development packaging and tool workflow references."""

import json
import re
from pathlib import Path

from architect_ai.mcp.handlers import ArchitecturalTools
from architect_ai.mcp.server import tool_bindings

PACKAGE = Path(__file__).resolve().parents[1] / "plugin" / "architect-ai"
SKILL = PACKAGE / "skills" / "architectural-design" / "SKILL.md"


def test_portable_development_manifest() -> None:
    manifest = json.loads((PACKAGE / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert manifest["name"] == "architect-ai"
    assert manifest["version"] == "0.1.0"
    assert "DEVELOPMENT / NOT FOR SUBMISSION" in manifest["description"]
    bundled = json.loads((PACKAGE / "mcp.json").read_text(encoding="utf-8"))
    config = json.loads((PACKAGE / "mcp.development.json").read_text(encoding="utf-8"))
    assert config["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
    assert config["mcpServers"] == {
        "architect-ai": {"type": "streamable-http", "url": "http://127.0.0.1:8000/mcp"}
    }
    assert bundled == config


def test_skill_metadata_and_real_tool_inventory() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    frontmatter = skill.split("---", 2)[1]
    assert "name: architectural-design" in frontmatter
    assert re.search(r"^description: .+", frontmatter, re.MULTILINE)
    names = {binding.tool.name for binding in tool_bindings(ArchitecturalTools())}
    references = set(re.findall(r"`([a-z]+_[a-z_]+)`", skill)) - {"accepted_intent"}
    assert references == names
    for source in (
        "USER_EXPLICIT",
        "USER_REFERENCE",
        "IMPORTED_GEOMETRY",
        "SYSTEM_DERIVED",
        "AI_INFERRED",
    ):
        assert source in skill


def test_evaluation_specifications_are_unexecuted_and_use_real_tools() -> None:
    data = json.loads((PACKAGE / "evals" / "developer_mode_cases.json").read_text("utf-8"))
    assert data["status"] == "NOT_EXECUTED"
    cases = data["cases"]
    assert len(cases) >= 12
    assert len({case["id"] for case in cases}) == len(cases)
    names = {binding.tool.name for binding in tool_bindings(ArchitecturalTools())}
    categories = {case["category"] for case in cases}
    assert categories == {
        "positive_direct",
        "positive_indirect",
        "clarification",
        "conflict",
        "out_of_scope",
    }
    for case in cases:
        assert isinstance(case["expected_activation"], bool)
        assert case["prompt"] and case["context"] and case["expected_outcome"]
        assert case["must_not_happen"]
        assert set(case["likely_tools"]) <= names
        assert case["execution_status"] == "NOT_EXECUTED"
        if not case["expected_activation"]:
            assert case["likely_tools"] == []


def test_package_has_no_escape_credentials_or_legacy_manifest() -> None:
    for path in PACKAGE.rglob("*"):
        assert path.resolve().is_relative_to(PACKAGE.resolve())
        assert path.name not in {"ai-plugin.json", ".env", "openapi.yaml", "openapi.json"}
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            assert "example.com" not in content
            assert not re.search(r"\bsk-[A-Za-z0-9_-]{12,}", content)
            assert not re.search(r'"(?:api_key|authorization|password)"\s*:', content, re.I)
    assert "DEVELOPMENT / NOT FOR SUBMISSION" in (PACKAGE / "README.md").read_text("utf-8")
