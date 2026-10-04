# Architectural Brief Interpreter (Phase 3B)

The interpreter produces proposals, never an authoritative `Project` replacement.
`ArchitecturalBriefInterpreter` depends on the provider-neutral
`ArchitecturalInterpreterProvider` port in `services/brief_contracts.py`.
`OpenAIArchitecturalInterpreterProvider` and the offline fixed-proposal
`MockArchitecturalInterpreterProvider` implement that port. No API route or UI
is introduced; callers explicitly compose the service with a provider.

## Flow and contracts

`brief + current ADG -> structured context -> provider -> ArchitecturalIntent +
proposed ADGPatch -> Phase 3A apply_patch -> deterministic PatchResult`.

- `interpret_only(project, text, references=...)` returns a validated proposal and
  provider metadata. It neither evaluates nor publishes a project.
- `interpret_and_evaluate(...)` sends the proposed patch through Phase 3A.
  The orchestration layer can reject/withhold an otherwise valid candidate for
  unresolved ambiguity, preservation instructions, intent-scope mismatch or unsupported
  evidence. Only Phase 3A constructs an accepted candidate. Nothing is persisted.
- `confirmed_destructive` is a trusted caller argument; it is never model output.

The proposal includes intent, optional patch, ambiguity and assumption lists,
bounded Decimal confidence and a clarification recommendation. Metadata outside
the domain includes provider/model, response ID and instruction version. No proposal
contract accepts an already accepted project. Provider output is revalidated even
when it arrives as a Pydantic object.

`build_project_context` uses typed metadata and sorted existing entity payloads,
geometry, constraints, style, material, lighting and camera assertions, plus explicit
locked/preserved ID lists. Every supplied entity ID is a real current ADG ID.
The snapshot fingerprint covers the entire authoritative project. Context is JSON,
not Python repr or a prose summary. The provider rejects requests over 60,000 JSON
characters instead of silently truncating constraints. No selective retrieval is added.

## Structured OpenAI transport

The official SDK's `responses.with_raw_response.parse(text_format=WireProposal)`
performs Pydantic Structured Outputs parsing via the returned response's `parse()`.
The SDK's typed `Response` envelope is checked first, so incomplete/truncated output
and refusal are classified before parsing generated text. This uses one request;
generated output is never parsed as free-form JSON. A separate transport schema uses
all fields are required, optional values use null, unions use supported `anyOf`,
and decimals/confidence are strings. Existing ADG/patch schemas are unchanged.
Typed field entries decode into the existing discriminated Phase 3A operations;
unknown/duplicate fields and malformed values fail validation.

ADD operations use `target_id=null`; UUIDs are allocated by the application with
UUID5 over snapshot, request, operation index and type. Models never allocate or
invent IDs. References can use current IDs only; unresolved relationships between
new entities require clarification instead of invented temporary IDs. Replaying
against an altered snapshot fails the existing fingerprint check.

Instructions in `providers/architectural_instructions.py` are versioned as
`architectural-brief-v1`. Vague aesthetic requests concern style/material/lighting;
they do not authorize unsolicited geometry, furniture-position or camera changes.
Material-only and preservation requests are retained and checked. Ambiguous wall
identity requires clarification. Named-product requests can remain intent-only.

## Provenance, evidence and ambiguity

Unknown choices/assumptions are AI_INFERRED; direct user facts are USER_EXPLICIT;
supplied reference facts use USER_REFERENCE and a reference ID. Updated assertions
carry explicit new source information. Phase 3A's separate explicit-statement
policy allows a different user value to replace an AI inference; ordinary ADG copy
protections remain intact. Derived dependent dimensions may use SYSTEM_DERIVED.

Explicit operation origins must quote actual brief text; reference operations must
identify supplied references. Explicit scalar numeric facts require numeric evidence
in the brief, including exact mm/cm/m conversions. This evidence check is conservative,
not a complete natural-language or authenticity verifier. Manufacturer/collection/
product claims and properties of named products require supplied literal evidence;
new verification claims are rejected. Generic aesthetic finishes may remain inferred.
No product catalogue or web lookup is performed.

Any ambiguity list or clarification recommendation withholds the entire candidate,
even if a proposed patch passes domain validation. Intent-only results return
NEEDS_CLARIFICATION when evaluated. Ordinary hard-constraint/lock failures remain
Phase 3A conflicts, including the cabinetry/window-wall case.

## Configuration and privacy

Install the locked dependencies with the existing uv workflow. Settings support
`OPENAI_API_KEY`, `ARCHITECT_AI_OPENAI_MODEL` (default `gpt-6-astra`),
`ARCHITECT_AI_OPENAI_TIMEOUT_SECONDS` (default 30, at most 120), and
`ARCHITECT_AI_OPENAI_MAX_OUTPUT_TOKENS` (default 6000, at most 16000).
Missing keys do not prevent offline app/test use. Keys use SecretStr and are
excluded from settings repr/model dumps; provider code never logs them.

Requests use `store=False`, `tools=[]`, `tool_choice="none"` and zero SDK retries,
with explicit timeout/output bounds. There is no stateful conversation or hidden
provider work at import/application startup. `store=False` disables response storage;
it is not an additional zero-data-retention guarantee.

Failures have stable safe codes for missing key, authentication, rate limit, transient
failure, invalid/incomplete response, refusal, unsupported configuration and excessive
context. Raw SDK error bodies are not exposed or converted into empty intents.

## Verification and limitations

Normal tests use fixed mock proposals and the real SDK with offline HTTP transport.
They test orchestration, schema compatibility, provenance, preservation and failure
handling; they do not establish live-model language quality or account/model access.
One optional smoke test in `tests/test_openai_live.py` is skipped unless both
`OPENAI_API_KEY` and `ARCHITECT_AI_RUN_LIVE_OPENAI_TESTS=1` are present in the
process environment. Only explicitly authorized live testing should enable it.
No live call was made during Phase 3B verification.

Natural-language semantics remain probabilistic and need review; evidence checks
cannot authenticate references or prove interpretation correctness. Context limits,
compound-value provenance and Phase 3A's conservative removal/protection policies
still apply. Prompt Compiler, tools/MCP, CAD, visualization, catalogues, persistence,
revision history and Phase 4 are deferred.

Official references reviewed on 2026-10-01:
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Responses migration and storage](https://developers.openai.com/api/docs/guides/migrate-to-responses).
