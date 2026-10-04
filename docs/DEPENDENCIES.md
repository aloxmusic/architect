# Dependency and official documentation review

Reviewed 2026-09-30. Live official documentation informed these choices. Version
ranges below are compatibility policies. The user reported successful uv.lock
resolution and locked runtime/development installation in local Windows PowerShell.
Work did not independently reproduce that installation. Optional SDK integration
compatibility remains untested; current Work repository read/write access is confirmed.

| Dependency / pattern | Decision | Official source |
| --- | --- | --- |
| Python | 3.12 minimum; local managed runtime 3.12.14 | https://docs.python.org/3.12/library/venv.html |
| FastAPI | Application factory, lifespan context, APIRouter, response models | https://fastapi.tiangolo.com/advanced/events/ |
| Pydantic v2 / settings v2 | Validated immutable settings and versioned wire DTO | https://docs.pydantic.dev/latest/concepts/pydantic_settings/ |
| Uvicorn | Explicit factory command, loopback, access logs off | https://uvicorn.dev/settings/ |
| pytest | Tests configured in pyproject, strict markers/config | https://docs.pytest.org/en/stable/getting-started.html |
| HTTPX2 | Current Starlette TestClient dependency, development only; httpx fallback deprecated | https://starlette.dev/testclient/ and https://pypi.org/project/httpx2/ |
| Ruff | Lint/format gate | https://docs.astral.sh/ruff/ |
| mypy | Strict typing gate | https://mypy.readthedocs.io/en/stable/getting_started.html |
| setuptools | PEP 517 build and src package discovery | https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html |
| uv | uv.lock resolved and locked installation succeeded, as reported by the user | https://docs.astral.sh/uv/guides/projects/ |
| MCP official Python SDK | Current docs specify v2 stable; optional `mcp>=2,<3`, no server yet | https://py.sdk.modelcontextprotocol.io/ and https://github.com/modelcontextprotocol/python-sdk |
| OpenAI Responses | Future provider adapter only; no SDK or guessed model ID | https://developers.openai.com/api/docs/guides/migrate-to-responses |
| ChatGPT integration | Recheck current Plugins guide when implementing | https://developers.openai.com/plugins |
| SQLAlchemy 2 | Planned transactional persistence mapping | https://docs.sqlalchemy.org/en/20/orm/session_transaction.html |
| Alembic | Planned migration ownership in storage | https://alembic.sqlalchemy.org/en/latest/ |

`https://developers.openai.com/apps-sdk/` redirected to the official Plugins guide
when reviewed. Old integration branding must not be used to infer current protocol
or manifest requirements. The official MCP repository also explicitly distinguishes
v2 from the older maintained v1 branch; do not reuse v1 FastMCP examples as v2 code.

Only FastAPI, Uvicorn, Pydantic and pydantic-settings are runtime requirements now.
The MCP extra makes the intended official SDK choice explicit without installing an
unused transport into the foundation. Database drivers and provider SDKs are deferred.
When the MCP adapter is implemented, install the extra, include it in the lock and
test protocol behavior against its exact installed version.

Before upgrading: read official changelogs, update the lock in a dedicated change,
run all gates, verify schema compatibility and record the resolved versions here.
Bounded ranges alone do not guarantee reproducible builds or current security.
