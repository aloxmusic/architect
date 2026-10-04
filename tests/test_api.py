import re

from fastapi.testclient import TestClient

from architect_ai.api.app import create_app
from architect_ai.config import Settings


def test_health_contract(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0",
        "status": "ok",
        "service": "architect-ai",
        "version": "0.1.0",
    }
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def test_correlation_is_generated_per_request(client: TestClient) -> None:
    first = client.get("/api/v1/health", headers={"X-Request-ID": "untrusted"})
    second = client.get("/missing")
    assert first.headers["x-request-id"] != "untrusted"
    assert first.headers["x-request-id"] != second.headers["x-request-id"]
    assert second.status_code == 404


def test_openapi_contains_only_real_feature(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert set(response.json()["paths"]) == {"/api/v1/health"}
    assert client.post("/api/v1/health").status_code == 405
    assert client.get("/mcp").status_code == 404


def test_production_disables_docs() -> None:
    settings = Settings(_env_file=None, environment="production", docs_enabled=False)
    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/api/v1/health").status_code == 200


def test_internal_error_is_redacted() -> None:
    app = create_app(Settings(_env_file=None, environment="test"))

    @app.get("/test-error")
    async def error() -> None:
        raise RuntimeError("private-provider-key")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test-error")
    assert response.status_code == 500
    assert response.json()["error"] == "internal_server_error"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "private-provider-key" not in response.text
