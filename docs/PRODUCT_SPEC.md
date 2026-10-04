# Product specification

Status: proposed product contract, Phase 1. Updated 2026-09-30.
Statements about architectural behavior below are requirements, not implemented features.

## Product and users

Architect AI translates natural architectural conversation into reviewable,
structured design intent and validated revisions. Primary users are architects
and interior designers developing concepts, layouts and presentation material.
The user should not need prompt-engineering expertise. The system connects to
design tools through adapters while preserving a project-owned source of truth.

## Central workflow

1. Capture the brief, imported measurements and source references.
2. Extract a proposed structured change and attach evidence to each assertion.
3. Ask focused questions about missing or contradictory hard requirements.
4. Validate references, units, deterministic geometry and constraints.
5. Present a semantic change summary and any assumptions for review.
6. Commit an authorized revision atomically against its expected base revision.
7. Generate prompts, images or technical artifacts from that immutable revision.
8. Record adapter/model versions and link outputs back to the revision.

An LLM may propose dimensions but never silently certify or overwrite measured
geometry. A rendered image is a presentation derivative, not a CAD authority.
Image generation cannot guarantee exact geometric fidelity; expose this limit
and retain the canonical graph and camera references for comparison.

## Architectural Design Graph (Phase 2 specification only)

The graph is a typed domain aggregate, not a provider message history and not
necessarily a graph database. Stable IDs identify projects, levels, spaces,
walls, openings, fixed elements, furniture, materials, cameras and constraints.
Edges explicitly describe containment, hosting, adjacency and references.

| Requirement | Planned representation / acceptance |
| --- | --- |
| Units | Canonical millimeters; input conversions preserve original unit and evidence |
| Coordinates | Right-handed project frame, +Z up; explicit local-to-project transforms |
| Precision | Decimal millimeter values serialized as strings; reject nonfinite values |
| Revisions | Immutable snapshots with project ID, revision ID and base revision |
| Provenance | Per assertion: user fact, imported measurement, AI assumption, deterministic derivation |
| Evidence | Source reference, actor, timestamp; confidence applies to AI inference, not proof |
| Acceptance | Assumptions remain pending until accepted; acceptance history is never erased |
| Constraints | Typed predicate, target IDs, parameters, units, hard/soft priority, provenance |
| Unknown requirements | Explicit unresolved constraint; cannot silently claim validation success |
| Evaluation | satisfied, violated, unresolved, unsupported; deterministic evaluator and reason |
| Intent | Brief, preferences and scope retained independently of visual outputs |

Phase 2 must choose and test quantization and geometric tolerance explicitly;
neither arbitrary binary floats nor an implicit universal tolerance is acceptable.
Areas and volumes use mm² and mm³ with explicit dimensional types. Angles use an
explicit angular type and unit; millimeters apply to length, not every quantity.

Initial constraint families: fixed dimension, min/max dimension, containment,
non-overlap, alignment, clearance, host relationship, adjacency, keep-existing
element and forbidden-placement zone. Code/regulation claims require jurisdiction,
source edition and scoped validation; unsupported rules remain unresolved.

## Representative acceptance scenarios for later phases

- A 3270 × 2580 mm kitchen brief forbids cabinets on window and entrance walls.
  A layout revision cannot place cabinetry there; the violation identifies the
  relevant constraint and entities. The 1730 mm entrance remains explicit.
- User says "make it warmer". A material/lighting proposal leaves walls, openings,
  fixed cabinet dimensions and camera geometry unchanged unless separately authorized.
- A provider invents a wall length. It becomes a pending assumption, never a fact.
- A stale edit is submitted after another revision. Reject with a conflict and
  current revision reference; no silent last-write-wins merge.
- Unsupported constraints survive save/load unchanged and block any claim of
  complete technical validation.
- A CAD export round trip preserves canonical dimensions within its declared
  tolerance; unresolved constraints appear in the accompanying validation report.

## Phase boundaries

Phase 1 delivers architecture and an operational HTTP foundation only. Design
Graph code, CRUD endpoints, SQL tables, generation stubs and CAD exporters are
explicitly excluded. Phases 2–7 have separate acceptance gates in ROADMAP.md.

## Operational and security requirements

Before external project access: authenticated identity, tenant/project isolation,
authorization in use cases, audit records, request size limits, rate limits,
TLS and a secrets policy. Imported text, CAD metadata and provider output are
untrusted data, not instructions granting tool access. Never allow arbitrary
shell commands or file paths from model output. Use scoped artifact handles.

Before paid generation: explicit user intent, cost budget, timeouts, concurrency
limits, cancellation, retry policy and idempotency. Retrying a paid call may
create duplicate charges; retries must be adapter-aware.

Before persistent service deployment: migrations, backup/restore drill,
data-retention/deletion rules and tested authorization. No Phase 1 availability,
throughput or geometric correctness SLA is claimed. Establish measurable targets
and representative benchmark projects before setting those SLAs.

## Completion definition for Phase 1

All requested files reviewed, dependencies resolved reproducibly, application
started, health checked over real HTTP, pytest/lint/type checks passing and state
file updated. A blocked dependency install means this phase is not operationally
complete, regardless of how much code has been written.
