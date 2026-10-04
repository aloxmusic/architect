# Phase 1 verification evidence

Date: 2026-09-30. Host: Windows. Python: 3.12.14.

## Current status and evidence attribution

**PHASE 1: COMPLETE — USER-REPORTED LOCAL WINDOWS VERIFICATION**

The following successful results were reported by the user from local Windows
PowerShell. Work did not independently execute these historical passes:

| Check | User-reported result |
| --- | --- |
| Dependency installation | uv lock resolved 47 packages; uv sync --locked --extra dev succeeded |
| pytest | 12 passed in 0.15s |
| Ruff lint | All checks passed! |
| Ruff formatting | 31 files already formatted |
| mypy | Success: no issues found in 18 source files |
| Backend and HTTP smoke | Uvicorn started; health returned HTTP 200; PASS: real HTTP health and request correlation |

The Windows sandbox issue has been repaired. Current Work repository read access
and write access were independently confirmed. The write check created exactly
`.work_write_test.tmp`, wrote and read back the expected content, deleted the file,
and verified that it no longer exists. No temporary test file remains.
No active Phase 1 blocker is known. The full suite and dependency downloads were
not rerun in Work for this documentation correction. Phase 2 has not started.
CI execution and clean-environment wheel installation are not claimed as verified.

## Historical evidence (superseded by the results above)

All failures and pending results below describe earlier attempts, not current
blockers. Previous Work failures also included `sandbox provisioning failed`.

## Local installation and first test results — 15:07 Europe/Istanbul

User-supplied output confirms successful uv lock (50 packages) and uv sync
(32 packages installed). At that time, Work failed reading installed package files
with PermissionError, so runtime verification continued in the user's PowerShell.
pytest collection failed because Starlette 1.7.0 deprecated the httpx fallback.
The warnings-as-errors policy correctly caught this incompatibility.

Minimal fixes: dev dependency httpx2>=2.13.1,<3 (official TestClient documentation:
https://starlette.dev/testclient/), source formatting in middleware.py and
test_architecture.py, and explicit Ruff exclusion of generated build/dist/.venv.
No test or warning filter was weakened. At that point uv.lock needed regeneration and synchronization before rerunning
verification. The later successful user-reported results above supersede this
pending state.

## Verification retry — 2026-09-30, 14:56 Europe/Istanbul

Historical status at that attempt: **PHASE 1: IMPLEMENTED / VERIFICATION BLOCKED**.
One `pip install -e '.[dev]'` attempt with retries disabled failed obtaining
`setuptools>=77,<85`. A direct TCP diagnostic to pypi.org:443 independently
returned `PermissionError: [WinError 10013]`, confirming the environmental block.
No repeated download attempts were made.

The six offline checks listed below passed again, including parsing all 19 Python
files and checking the existing wheel's contents. The wheel was not rebuilt in
this retry. pytest, Ruff and mypy were invoked but failed with `No module named`
errors. The smoke script launched its child, which failed with `No module named
uvicorn`; no health response was received. Zero pytest tests executed. Ruff
formatting remains unverified. No source or tests were changed; no lockfile was
fabricated. Phase 2 was not started.

On Windows, from this repository root with Python 3.12 and package access:

```powershell
py -3.12 -m pip install uv
py -3.12 -m uv lock
py -3.12 -m uv sync --locked --extra dev
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe scripts/smoke.py
```

The smoke script starts and stops the backend and checks `/api/v1/health` over
real HTTP. Stop and report any failing command; do not mark the phase complete
until all required gates pass. Preserve the generated uv.lock for review.

## Passed checks

| Check | Observed result |
| --- | --- |
| Source syntax | All 19 authored Python source/test/script files parsed successfully |
| Project config | pyproject.toml parsed; Python requirement is >=3.12 |
| Architecture boundary | Domain/geometry import assertion passed when called directly |
| JSON logging | Formatter emitted expected metadata and excluded arbitrary fields/exception text |
| Logging setup | Repeated configuration emitted one record, not duplicate records |
| Wheel contents | Package, application module and py.typed present; no .env included |
| Source wheel build | architect_ai-0.1.0-py3-none-any.whl built offline with installed setuptools |

These checks do not substitute for pytest, type checking or application runtime
verification. Direct checks used Python's real standard library and actual project
logging code; no fake FastAPI, MCP, pytest or provider modules were created.

## Blocked / unsuccessful commands

| Command | Result |
| --- | --- |
| `python -m pip install uv` | Network denied, WinError 10013 |
| `.venv/Scripts/python -m pip install -e '.[dev]'` | Build dependency download denied, WinError 10013 |
| `.venv/Scripts/python -m pytest` | No module named pytest; zero tests executed |
| `.venv/Scripts/python -m uvicorn architect_ai.api.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log` | No module named uvicorn; backend did not start |
| `.venv/Scripts/python -m ruff check .` | No module named ruff |
| `.venv/Scripts/python -m mypy` | No module named mypy |
| `.venv/Scripts/python scripts/smoke.py` | Child failed to import Uvicorn and exited 1 before readiness |

Ruff formatting was unverified at that attempt. CI is authored but has not executed remotely.
At that attempt, none of the 12 pytest tests could run. The sandbox disallowed
approval escalation;
no network restrictions were changed or bypassed.

## Inspection and fixes

Reviewed authored source, configuration, scripts and documents after writing.
Fixed fixture isolation from ambient `.env`/environment settings, import ordering,
typed log-record construction and multiline formatting during source inspection.
Validated wheel entries and parsed each authored Python file. Reserved packages
contain explanatory docstrings only. No secrets or actual API credentials were added.

## Reference verification commands

From the repository root in an environment with package access:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe scripts/smoke.py
```

For a new machine, create `.venv` first as documented in README and use the
existing reviewed uv.lock for locked installation. Future verification should
record its execution environment and observed results separately from the
user-reported historical passes above.
