# Project state — cloud source handoff

Architect AI 0.1.0 development snapshot, 2026-10-04.
Phase 6A complete; Phase 6B host evaluation remains open. Phase 7 not started.
Local Windows checks passed. User-reported cloud run on Debian 13 / Python 3.12.14
passed pytest (238 passed, 2 skipped), Ruff, wheel build and HTTP smoke. Mypy
reported Windows-only msvcrt attributes in the lock integration test. Added an
explicit sys.platform guard so Linux type checking excludes that Windows code.
User-reported published cloud task verified the correction: mypy, pytest and HTTP
smoke passed at commit 7a30f59 on Debian 13 / Python 3.12.14. The personal ZIP
transfer and real brief/instruction chain passed; exported evidence was locally
verified by SHA-256 and manifest on 2026-10-05.
Linux scheduled source checks now use GitHub Actions: hourly quick at minute 17,
daily full at 03:37 Europe/Istanbul (00:37 UTC), with manual full/quick selection.
Reports and logs are retained for 30 days, including test failures. First remote
execution is pending. These checks do not repeat connector or private ZIP tests.
2026-10-05: added four real subprocess HTTP MCP tests, included in daily full
pytest runs on Windows/Linux. They verify accepted style change, exact returned
evaluation-to-brief-to-instructions handoff, unchanged permissions, locked camera,
and provenance/preservation/camera rejections. Windows: 243 passed, 1 live skip;
Ruff, mypy (50 files), wheel and HTTP smoke passed. Local venv lacked the wheel
build backend; bundled Python built successfully instead. Remote verification
of these new tests is pending. Host skill activation remains a manual gate.
No project persistence, image provider invocation or public production deployment.
Personal local operational logs, continuation receipts and machine paths excluded.

Cloud verification: use Python 3.12+, install editable .[dev,mcp], then run pytest,
Ruff check/format, mypy, wheel build and scripts/smoke.py. Keep live OpenAI tests
and the live interpreter disabled. No API key is needed for offline verification.
