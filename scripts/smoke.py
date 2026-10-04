"""Run a real loopback HTTP smoke check; stop only the process this script starts."""

import json
import os
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


def main() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {
        **os.environ,
        "ARCHITECT_AI_ENVIRONMENT": "test",
        "ARCHITECT_AI_DOCS_ENABLED": "false",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "architect_ai.api.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        env=env,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Backend exited before ready: {process.returncode}")
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=1) as response:
                    body = json.load(response)
                    assert response.status == 200
                    assert body["status"] == "ok"
                    assert body["schema_version"] == "1.0"
                    assert response.headers["X-Request-ID"]
                print("PASS: real HTTP health and request correlation")
                return
            except URLError:
                time.sleep(0.1)
        raise TimeoutError("Backend did not become healthy within 15 seconds")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
