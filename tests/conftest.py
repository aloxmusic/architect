import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from architect_ai.api.app import create_app
from architect_ai.config import Settings


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in tuple(os.environ):
        if name.startswith("ARCHITECT_AI_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def client() -> Iterator[TestClient]:
    # Test values are explicit; never load a developer's .env.
    settings = Settings(_env_file=None, environment="test", log_level="INFO", docs_enabled=True)
    with TestClient(create_app(settings)) as test_client:
        yield test_client
