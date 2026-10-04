# ADR 0003: Versioned snapshots with transactional revisions

Status: accepted design; implementation deferred to Phase 3. Date: 2026-09-30.

Context: project history must survive provider changes, concurrent edits and schema
evolution. SQLite local use must not prevent a PostgreSQL deployment.

Decision: repository/unit-of-work ports backed by relational transactions. Start
with immutable portable JSON graph snapshots plus normalized project, revision,
audit and artifact metadata. Use SQLAlchemy 2/Alembic when implementing storage.
Optimistic concurrency compares the expected revision in the database transaction.

Graph schema version and project revision are separate. Preserve original stored
documents; upcast explicitly with fixtures for supported historic versions. Unknown
major versions fail clearly. Public HTTP versions evolve independently.

Alternatives: a graph database is not required to represent a domain graph. Event
sourcing adds replay complexity before the domain stabilizes. Unversioned mutable
JSON would lose auditability and is rejected.

Consequences: dual-database contract and migration tests are required. Database
readiness is not claimed until an actual adapter exists. Phase 1 has no SQL tables,
connection string setting, migrations or persistence implementation.
