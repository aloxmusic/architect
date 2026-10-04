# Development contract

Read PROJECT_STATE.md and ADRs before work. Complete one authorized phase at a
time. Update PROJECT_STATE.md at the end of every future development phase with
completed work, pending work, known limitations, decisions and next action.

Use Python 3.12+, typed code and deterministic tests. Keep domain/geometry imports
free of transport/provider/database code. Read current official dependency/API
documentation before introducing or upgrading an integration. Record source links
and installed versions. Never guess model identifiers or claim a stub is complete.

Run pytest, Ruff check/format, mypy, wheel build and the real HTTP smoke script.
Fix failures before claiming completion; if the environment blocks execution,
record commands/errors and keep the phase gate open. Do not fabricate a lockfile.

Never commit .env, keys, database files or user project data. Log fixed event names
and safe operational metadata only. Add compatibility fixtures before changing a
published schema. Architectural changes need an ADR explaining alternatives and
consequences. Publishing, licensing and hosting are separate product decisions.
