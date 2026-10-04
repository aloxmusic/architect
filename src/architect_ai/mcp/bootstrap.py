"""Development transport composition; localhost Streamable HTTP, no project persistence."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI

from architect_ai.config import Settings
from architect_ai.mcp.server import create_mcp_server
from architect_ai.providers.openai_interpreter import OpenAIArchitecturalInterpreterProvider
from architect_ai.services.brief_interpreter import ArchitecturalBriefInterpreter


def install_mcp(
    app: FastAPI,
    settings: Settings,
    interpreter: ArchitecturalBriefInterpreter | None,
) -> Callable[[], AbstractAsyncContextManager[None]]:
    if interpreter is None and settings.mcp_live_interpreter_enabled:
        interpreter = ArchitecturalBriefInterpreter(
            OpenAIArchitecturalInterpreterProvider(settings)
        )
    server = create_mcp_server(interpreter)
    transport = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host="127.0.0.1",
    )
    # Mount last at root: existing FastAPI routes win; SDK handles /mcp without a nested path.
    app.mount("/", transport)
    return server.session_manager.run


def create_development_app() -> FastAPI:
    from architect_ai.api.app import create_app

    return create_app(Settings(mcp_enabled=True))
