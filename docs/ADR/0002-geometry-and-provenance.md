# ADR 0002: Deterministic geometry and explicit provenance

Status: accepted design; implementation deferred to Phase 2. Date: 2026-09-30.

Context: generated images and model text can invent dimensions or lose fixed
constraints across revisions. Architectural output requires a traceable authority.

Decision: the validated Design Graph is authoritative. Canonical lengths use
decimal millimeters and serialize as decimal strings. Derived area/volume and
angles have explicit units. Fix precision/tolerance in Phase 2 with tests before
geometry algorithms are implemented. Transform frames are explicit.

Every assertion carries provenance: user fact, imported measurement, AI assumption
or deterministic derivation. Confidence never promotes an assumption to fact.
Acceptance is explicit and recorded. Constraints include hard/soft priority,
targets, units and evaluability; unsupported constraints remain visible.

Alternatives: free text as the project record and binary floats without declared
tolerances are rejected. Integer whole millimeters would discard sub-mm precision.

Consequences: validators and exporters must preserve units and provenance. A
photorealistic image remains a derivative and cannot certify dimensional accuracy.
No graph classes or constraint solvers are implemented in this ADR's phase.
