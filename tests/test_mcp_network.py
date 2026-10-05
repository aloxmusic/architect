"""Real isolated HTTP transport: acceptance chain and protected/rejected proposals."""

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest

from architect_ai.domain.serialization import deserialize_project
from architect_ai.services.patching import project_context

ROOT = Path(__file__).resolve().parents[1]


def rpc(url: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urlopen(request, timeout=15) as response:
        envelope = json.load(response)
    assert "error" not in envelope, envelope
    result: dict[str, Any] = envelope["result"]
    structured: dict[str, Any] = result["structuredContent"]
    return structured


@pytest.fixture(scope="module")
def endpoint(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {
        **os.environ,
        "ARCHITECT_AI_ENVIRONMENT": "test",
        "ARCHITECT_AI_MCP_LIVE_INTERPRETER_ENABLED": "false",
        "ARCHITECT_AI_RUN_LIVE_OPENAI_TESTS": "0",
    }
    log_path = tmp_path_factory.mktemp("mcp-network") / "server.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "architect_ai.mcp.bootstrap:create_development_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                assert process.poll() is None, log_path.read_text()
                try:
                    with urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=1) as response:
                        assert json.load(response)["status"] == "ok"
                    break
                except URLError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(log_path.read_text()) from None
                    time.sleep(0.1)
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def inputs() -> dict[str, Any]:
    project = deserialize_project((ROOT / "tests/fixtures/adg/living_room.json").read_text())
    snapshot = project.model_dump(mode="json")
    target = str(project.styles[0].id)
    text = "Set mood to warm_and_inviting."
    request = {
        "instruction": {"value": text, "source": "USER_EXPLICIT"},
        "operation": "UPDATE_ENTITY",
        "target_ids": [target],
        "target_types": ["style"],
    }
    return {
        "project": snapshot,
        "text": text,
        "intent": {
            "goal": {"value": text, "source": "USER_EXPLICIT"},
            "requested_operations": [request],
            "style_changes": [request],
            "confidence": "1",
        },
        "patch": {
            "project_id": str(project.id),
            "base_fingerprint": project_context(project).fingerprint,
            "operations": [
                {
                    "operation": "UPDATE_ENTITY",
                    "target_id": target,
                    "source": "USER_EXPLICIT",
                    "confidence": "1",
                    "origin": text,
                    "changes": {
                        "id": target,
                        "entity_type": "style",
                        "mood": {"value": "warm_and_inviting", "source": "USER_EXPLICIT"},
                    },
                }
            ],
        },
    }


def test_real_http_acceptance_and_exact_compilation_chain(endpoint: str) -> None:
    args = inputs()
    original = json.dumps(args, sort_keys=True)
    result = rpc(endpoint, "evaluate_architectural_proposal", args)
    data = result["data"]
    assert result["ok"] and data["status"] == "ACCEPTED" and not data["conflicts"]
    assert data["persisted"] is False and not data["clarification_required"]
    expected = json.loads(json.dumps(args["project"]))
    expected["styles"][0]["mood"]["value"] = "warm_and_inviting"
    assert data["candidate"] == expected
    brief = rpc(
        endpoint,
        "compile_visualization_brief",
        {
            "project": data["candidate"],
            "intent": data["accepted_intent"],
            "accepted_intent": True,
            "evaluation": data,
            "options": {
                "mode": "GEOMETRY_LOCKED_RENDER_MODE",
                "output": {"target": "architectural_render"},
            },
        },
    )
    assert brief["ok"] and brief["error"] is None
    instructions = rpc(
        endpoint,
        "compile_image_instructions",
        {"brief": brief["data"]["brief"], "adapter": "openai_image"},
    )
    assert instructions["ok"] and instructions["error"] is None
    compiled = brief["data"]["brief"]
    emitted = instructions["data"]["instructions"]
    assert emitted["permissions"] == compiled["permissions"]
    assert emitted["entity_permissions"] == compiled["entity_permissions"]
    assert compiled["camera"]["lock_state"] == "LOCKED"
    assert compiled["camera"]["preserve_composition"] is True
    allowed = [p for p in compiled["permissions"] if p["permission"] == "ALLOW"]
    assert len(allowed) == 1 and allowed[0]["category"] == "style"
    assert emitted["adapter"] == "openai_image"
    assert json.dumps(args, sort_keys=True) == original


@pytest.mark.parametrize("case", ["provenance", "preservation", "camera"])
def test_real_http_rejections_stop_without_compilation(endpoint: str, case: str) -> None:
    args = inputs()
    op = args["patch"]["operations"][0]
    expected = "PROVENANCE_CONFLICT"
    if case == "provenance":
        op.pop("origin")
    elif case == "preservation":
        args["intent"]["preservation_instructions"] = [
            {
                "instruction": {"value": "Preserve style.", "source": "USER_EXPLICIT"},
                "target_types": ["style"],
            }
        ]
        args["text"] += " Preserve style."
        expected = "PRESERVED_ELEMENT"
    else:
        camera = args["project"]["cameras"][0]
        op["target_id"] = camera["id"]
        op["changes"] = {
            "id": camera["id"],
            "entity_type": "camera",
            "position": {"value": {"x": "2600", "y": "3900", "z": "1600"}, "source": "AI_INFERRED"},
        }
        op["source"] = "AI_INFERRED"
        expected = "LOCKED_ENTITY"
    result = rpc(endpoint, "evaluate_architectural_proposal", args)
    assert not result["ok"]
    assert result["data"]["candidate"] is None
    assert result["data"]["persisted"] is False
    assert expected in {c["code"] for c in result["data"]["conflicts"]}
