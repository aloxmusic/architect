"""Versioned liveness response. This does not claim database/provider readiness."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from architect_ai import __version__

router = APIRouter(tags=["operations"])


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["ok"] = "ok"
    service: Literal["architect-ai"] = "architect-ai"
    version: str = __version__


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Confirm that this process can serve an HTTP request."""
    return HealthResponse()
