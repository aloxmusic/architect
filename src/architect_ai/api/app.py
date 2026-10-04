"""Composition root for the Phase 1 HTTP application."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from architect_ai import __version__
from architect_ai.api.health import router
from architect_ai.api.middleware import RequestLoggingMiddleware
from architect_ai.config import Settings
from architect_ai.logging import configure_logging
from architect_ai.services.brief_interpreter import ArchitecturalBriefInterpreter

logger = logging.getLogger("architect_ai.lifecycle")


def create_app(
    settings: Settings | None = None,
    *,
    interpreter: ArchitecturalBriefInterpreter | None = None,
) -> FastAPI:
    """Create an isolated app; no network, DB, or provider work at import time."""
    config = settings if settings is not None else Settings()
    mcp_lifecycle: Callable[[], AbstractAsyncContextManager[None]] | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config.log_level)
        logger.info("application.started")
        try:
            async with AsyncExitStack() as stack:
                if mcp_lifecycle is not None:
                    await stack.enter_async_context(mcp_lifecycle())
                yield
        finally:
            logger.info("application.stopped")

    app = FastAPI(
        title="Architect AI",
        version=__version__,
        description="Phase 1 foundation. Architectural operations are not implemented yet.",
        lifespan=lifespan,
        docs_url="/docs" if config.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.docs_enabled else None,
    )
    app.state.settings = config
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(router, prefix="/api/v1")
    if config.mcp_enabled:
        from architect_ai.mcp.bootstrap import install_mcp

        mcp_lifecycle = install_mcp(app, config, interpreter)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unavailable")
        logger.error(
            "http.unhandled_error",
            extra={"request_id": request_id},
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )

    return app
