from pathlib import Path

import pytest
from pydantic import ValidationError

from architect_ai.config import Settings


def test_environment_overrides_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("ARCHITECT_AI_LOG_LEVEL=WARNING\n", encoding="utf-8")
    monkeypatch.setenv("ARCHITECT_AI_LOG_LEVEL", "ERROR")
    assert Settings(_env_file=dotenv).log_level == "ERROR"


def test_unknown_dotenv_key_rejected(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("ARCHITECT_AI_LOG_LEVLE=DEBUG\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        Settings(_env_file=dotenv)


def test_invalid_log_level_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHITECT_AI_LOG_LEVEL", "verbose")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_production_requires_disabled_docs() -> None:
    with pytest.raises(ValidationError, match="Disable docs_enabled"):
        Settings(_env_file=None, environment="production", docs_enabled=True)
