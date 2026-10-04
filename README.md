# Architect AI

Architectural AI orchestration for architects and interior designers.

**Phases 1–4 are complete; Phase 5A adds the optional development MCP boundary.**
The current local verification and phase status are recorded in `PROJECT_STATE.md`.
See `PROJECT_STATE.md` and `docs/VERIFICATION.md` for exact evidence.

## Scope

Included: immutable ADG, deterministic patch/conflict engine, architectural brief
interpreter, prompt compiler, optional MCP workflow tools, FastAPI health endpoint,
validated settings, safe JSON operational logs and offline tests.

Not included: persistence, image generation, authentication, CAD integrations,
custom UI, public deployment or plugin packaging.

## Local setup (Windows PowerShell)

Prerequisite: Python 3.12+ installed and available via `py`.
Run from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev,mcp]'
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn architect_ai.api.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

This workspace already contains a `.venv` created with the managed Python 3.12.14;
the user reported successful dependency installation into it. No activation or
execution-policy change is required. Do not overwrite a populated `.env` during subsequent setup.

On macOS/Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,mcp]'
cp .env.example .env
.venv/bin/python -m uvicorn architect_ai.api.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Open <http://127.0.0.1:8000/docs> or request
<http://127.0.0.1:8000/api/v1/health>:

```json
{"schema_version":"1.0","status":"ok","service":"architect-ai","version":"0.1.0"}
```

This checks process liveness only. It does not claim database, AI provider or MCP
readiness. `X-Request-ID` is generated for each request. Stop with Ctrl+C.
Use `--reload` only during development. Uvicorn access logging is disabled because
its default URL logging can expose sensitive query parameters; application logs
record method, status, duration and correlation ID without URLs or bodies.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe scripts/smoke.py
```

`scripts/verify.ps1` runs the four static/test commands and stops on any failure.
The smoke script starts a real Uvicorn subprocess on a loopback ephemeral port,
checks HTTP health and correlation, and stops only that child process.
CI has the same checks plus wheel building on Windows and Linux. CI has not run
in this workspace; a workflow file is not evidence of passing CI.

Dependencies have bounded compatibility ranges in `pyproject.toml`. The user
reported successful `uv.lock` resolution and `uv sync --locked --extra dev`.
Before release, review and commit the lockfile and switch CI to frozen installation. Do not
present an ad hoc `pip freeze` from the shared managed runtime as a project lock.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `ARCHITECT_AI_ENVIRONMENT` | `local` | `local`, `test`, or `production` |
| `ARCHITECT_AI_LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `ARCHITECT_AI_DOCS_ENABLED` | `true` | Disable OpenAPI and Swagger in production |

Precedence: explicit factory settings > process environment > root `.env` > defaults.
Unknown keys in `.env` are rejected; unrelated process environment variables are
ignored. Production mode requires docs disabled. This is a configuration guard,
not authorization or a declaration that the application is ready for public use.
No secrets are required for Phase 1. Later adapters must use secret-typed settings
and a deployment secret manager; never commit API keys or actual credentials.

The official MCP SDK is optional through `.[mcp]`; the full test suite needs both
`dev` and `mcp` extras. The default HTTP app keeps MCP disabled. To serve the local
`/mcp` development endpoint alongside health, run the factory documented in
`docs/MCP_SERVER.md`. The OpenAI interpreter is opt-in; no image API is implemented.

## Repository layout

```text
architect-ai/
  .github/workflows/ci.yml
  .env.example, .gitignore, .gitattributes, .python-version
  pyproject.toml
  README.md, PROJECT_STATE.md, CONTRIBUTING.md
  docs/
    PRODUCT_SPEC.md
    ARCHITECTURE.md
    ROADMAP.md
    DEPENDENCIES.md
    VERIFICATION.md
    ADR/
      0001-domain-boundaries.md
      0002-geometry-and-provenance.md
      0003-persistence-and-versioning.md
      0004-integrations-and-release-gates.md
  scripts/
    verify.ps1
    smoke.py
  src/architect_ai/
    __init__.py, py.typed, config.py, logging.py
    api/{__init__.py,app.py,health.py,middleware.py}
    domain/__init__.py
    services/__init__.py
    mcp/__init__.py
    providers/__init__.py
    geometry/__init__.py
    storage/__init__.py
  tests/
    conftest.py
    test_api.py
    test_architecture.py
    test_config.py
    test_logging.py
```

## Development order

Read `PROJECT_STATE.md`, `docs/ARCHITECTURE.md` and the ADRs before changes.
Phase 1 is complete on the evidence above. Phase 2 implements and validates the versioned
Architectural Design Graph in isolation. No model, CAD integration or remote
side effect should be introduced as part of Phase 2 without a scope change.

No source license is granted by this scaffold; choose a distribution/license
policy before publishing. No remote repository, hosting or paid API resource
has been created.
