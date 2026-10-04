# ADG patch acceptance (Phase 3A)

This provider-neutral safety layer accepts proposals, never a replacement project
document. `domain/intent.py` describes interpretation results without applying
them. `domain/patches.py` defines immutable typed proposals and conflict results;
`services/patching.py` owns deterministic acceptance. No provider or API is wired.

## Immutable flow

`ArchitecturalIntent -> ADGPatch -> apply_patch(existing, patch) -> PatchResult`.
Intent-to-patch translation is deferred. The service compares against the existing
authoritative project, stages explicit fields, validates final entity objects and
the final `Project`, then returns a candidate. It never mutates its input.

Every patch names its project UUID. `base_fingerprint`, when supplied, must match
the SHA-256 of deterministic ADG serialization. The result always includes the
original project UUID, schema version and fingerprint. This is snapshot context,
not a persistent revision ID or revision store. A future authoritative caller must
compare/publish atomically; the service does not provide concurrent storage writes.

## Operations

- `ADD_ENTITY`: typed payload, explicit new UUID, existing ADG assertion fields.
- `UPDATE_ENTITY`: target UUID and typed partial `*Changes` payload with the same UUID.
- `REMOVE_ENTITY`: target UUID and entity type.
- `ADD_CONSTRAINT`: typed constraint payload with a new UUID.
- `UPDATE_CONSTRAINT` / `REMOVE_CONSTRAINT`: represented explicitly, but modifying
  any constraint in the previous authoritative snapshot is rejected. Constraints
  newly staged in the same patch can be edited or removed before acceptance.

Payloads cover the existing ADG entity and constraint types. Operation category
and target type must match. Unknown fields are rejected. Partial updates distinguish
omitted fields from explicit null; null clears optional fields only. Serialization
preserves this distinction without requiring special serialization flags.
Existing UUIDs cannot be reused by remove/add operations to replace identity.

All operations carry action `source`, bounded Decimal `confidence`, and optional
originating text/reference `origin`. Confidence is metadata, not authorization;
there is no automatic confidence threshold or inference acceptance.

## Provenance policy

Each changed assertion is supplied in full, including `value`, `source` and any
new `source_reference`. Unchanged fields retain their original assertions. No
value-only merge inherits the old source accidentally. Supported sources remain
USER_EXPLICIT, USER_REFERENCE, IMPORTED_GEOMETRY, SYSTEM_DERIVED and AI_INFERRED.

New user assertions require matching action provenance. An AI_INFERRED action
cannot introduce assertions claiming another source. An unchanged value cannot
be relabeled to a different source, including an intermediate SYSTEM_DERIVED
label. Replacing an AI_INFERRED value with a genuinely different USER_EXPLICIT
value is allowed when the action is USER_EXPLICIT and supplies `origin`. Missing
origin or replacement with USER_REFERENCE requires clarification; simple
relabeling is rejected. The trusted caller must supply authentic origin labels;
these models cannot authenticate human statements.

Explicit null has action provenance in the patch, while the ADG optional field
becomes absent. Provenance history and component-level provenance are deferred.
The service is a dedicated explicit acceptance boundary using existing model
validation after old/new protection checks. Existing `model_copy` provenance
protections are unchanged and still reject ordinary AI-to-user promotion.

## Conflicts and atomicity

Stable codes: LOCKED_ENTITY, PRESERVED_ELEMENT, CONSTRAINT_VIOLATION,
MISSING_TARGET, ID_MISMATCH, INVALID_REFERENCE, GEOMETRY_VALIDATION_FAILED,
PROVENANCE_CONFLICT, DESTRUCTIVE_CHANGE_REQUIRES_CONFIRMATION, STALE_BASE and
VALIDATION_FAILED. Conflicts include severity, message, entity/constraint IDs,
typed existing/proposed data when available, operation index and clarification flag.

All existing constraints, hard locks, locked cameras and fixed furniture are
protected against the previous snapshot. Removing a referenced entity is rejected,
even if a patch also attempts to remove its referrers. Otherwise removal returns
NEEDS_CLARIFICATION unless the trusted caller passes `confirmed_destructive=True`.
This flag is outside the untrusted patch and never overrides protections.

Hard wall-contact rules evaluate declared furniture host associations and also
detect contradictory allowed/forbidden sets without requiring furniture to exist.
Object-type matching uses existing exact ADG strings; vocabulary normalization is
the future interpreter's responsibility. Other spatial constraints retain Phase 2
validation semantics; no general CAD solver or physical-contact evaluator is added.

Related field updates are combined before entity validation; references are checked
against the final staged graph, allowing additions to refer to later additions.
Operations have deterministic tuple order; later writes to the same field win,
but every proposed assertion still crosses the provenance checks. Any error rejects
the entire patch. Clarification without errors yields NEEDS_CLARIFICATION. Both
outcomes expose no candidate, no applied operations, and all operations as rejected.
ACCEPTED returns the complete validated candidate and all applied operations.
Malformed patch documents fail typed model decoding before service application.

## Deferred

Natural-language parsing, intent translation, OpenAI calls, prompts, MCP, CAD/DXF,
SketchUp, visualization, persistence, revision history, general spatial reasoning,
explicit constraint override/unlock workflows, and confirmation UI are absent.
Phase 3A completes the deterministic boundary, not Phase 3 as a whole.
