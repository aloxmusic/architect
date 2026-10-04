# Implementation roadmap

Each phase ends with code review, tests, limitations and an updated
`PROJECT_STATE.md`. Begin the next phase only after the current gate is satisfied.
Effort estimates are intentionally omitted until Phase 2 contracts are agreed; subscription limits are not engineering estimates.

| Phase | Deliverables | Acceptance gate |
| --- | --- | --- |
| 1 — Foundation | Repository, app, health, config/logging, docs, tests | Locked install, pytest/lint/types/build, real HTTP startup and shutdown pass |
| 2 — Domain graph | Versioned value types, nodes/edges, provenance, constraints, proposals, revisions | Pure deterministic tests; explicit mm conversions; round-trip serialization; invalid/unknown input handling; no provider or SQL dependencies |
| 3 — Persistence/use cases | Repository ports, SQLite/PostgreSQL adapters, migrations, revision transactions | Same contract suite on both engines; stale updates rejected; rollback, schema evolution and backup/restore verified |
| 4 — Intent and MCP | One intent adapter, shared services, official MCP transport, authenticated project access | Protocol integration tests; tenant isolation; prompt injection tests; structured proposals never auto-commit facts |
| 5 — Visual generation | One image provider, prompt compilation, revision-linked jobs/artifacts | Budget/idempotency/timeouts/cancellation tested; fixtures track intent; geometry-fidelity limitations visible |
| 6 — Technical 2D | Deterministic primitives, constraint evaluation, one CAD interchange exporter | Golden files, unit metadata, round-trip dimensions/topology within declared tolerance; unresolved rules reported |
| 7 — Desktop pilot | One integration selected after user workflow testing | Explicit document IDs, geometry diff, undo, scoped permissions and reproducible end-to-end test |

## Phase 1 status

Phase 1 is complete based on user-reported local Windows dependency installation,
12 pytest tests, Ruff lint/format, mypy and real HTTP backend/health smoke results.
Work did not independently execute these historical passes. Current Work repository
read/write access is confirmed after sandbox repair; no active Phase 1 blocker is
known. CI and clean-environment wheel installation remain release follow-ups.
The repository is ready for Phase 2, which has not started.

## Phase 2 implementation order

1. Specify numeric precision/tolerance, coordinate frames and conversion rules.
2. Implement versioned IDs and typed architectural values with invalid-input tests.
3. Implement provenance/evidence and explicit assumption acceptance histories.
4. Implement initial node/edge definitions and reference integrity checks.
5. Implement typed constraints and unresolved/unsupported outcomes.
6. Implement immutable revisions and change proposals with preserved intent.
7. Add golden serialization fixtures and deterministic migration policy tests.
8. Review with representative kitchen/room cases, update state and stop for phase review.

Phase 2 excludes LLM calls, persistence, CAD exports and desktop connectors.
Domain acceptance tests should include fractional millimeters, mixed input units,
invalid references, cyclic containment, opening host mismatch, conflicting hard
constraints and proposals that attempt to promote AI assumptions silently.

## Deferred choices

Choose the first desktop integration from a verified user workflow (SketchUp is a
strong candidate, not a committed implementation). Select exact CAD format and
geometry kernel when Phase 6 requirements are established. Choose queue/object
storage infrastructure only when asynchronous generation workloads justify it.
Provider model IDs and pricing must be revalidated at implementation time.
