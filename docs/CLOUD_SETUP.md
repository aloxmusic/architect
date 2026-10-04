# Cloud validation

Development source only. No verified cloud run is claimed.
Use Python 3.12 or newer and install:

    python -m pip install -e '.[dev,mcp]'

Set ARCHITECT_AI_RUN_LIVE_OPENAI_TESTS=0 and
ARCHITECT_AI_MCP_LIVE_INTERPRETER_ENABLED=false. No API credential is needed.
Run pytest, Ruff check, Ruff format --check, mypy, pip wheel --no-deps,
and python scripts/smoke.py. Report actual platform.system(), command exit codes
and failures. A Windows runner does not establish Linux compatibility.

Personal continuation ZIP is intentionally absent from the source repository.
Transfer it separately for the artifact-portability test; do not reconstruct
accepted evaluations from prose or claim fixture tests prove attachment downloads.
