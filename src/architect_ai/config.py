"""Validated process configuration, loaded only at application creation."""

from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process settings; provider secrets are excluded from repr and model dumps."""

    model_config = SettingsConfigDict(
        env_prefix="ARCHITECT_AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    environment: Literal["local", "test", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    docs_enabled: bool = True
    mcp_enabled: bool = False
    mcp_live_interpreter_enabled: bool = False
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias="OPENAI_API_KEY", repr=False, exclude=True
    )
    openai_model: str = Field(default="gpt-6-astra", min_length=1, pattern=r"^\S+$")
    openai_timeout_seconds: float = Field(default=30, gt=0, le=120)
    openai_max_output_tokens: int = Field(default=6000, ge=256, le=16000)

    @model_validator(mode="after")
    def require_private_production_docs(self) -> Self:
        if self.environment == "production" and self.docs_enabled:
            raise ValueError("Disable docs_enabled in production")
        return self
