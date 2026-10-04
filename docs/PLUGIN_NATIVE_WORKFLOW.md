# Plugin-native workflow — Phase 6A

## Two execution modes

Inside ChatGPT/Codex, the architectural-design skill interprets the actual user
request using supplied project data and discovers the typed MCP input schemas.
The host constructs ArchitecturalIntent and ADGPatch; it does not approve its
own proposal. `evaluate_architectural_proposal` evaluates them without a provider,
API key or backend OpenAI request. The existing standalone interpreter remains
available through `interpret_architectural_request` and
`evaluate_architectural_request` for deliberately configured external clients.
That standalone path may use the existing Phase 3B OpenAI provider; it is disabled
by default. No provider is instantiated or invoked by proposal evaluation.

## Typed evaluation and exact handoff

The new input contains current `project`, complete `intent`, typed `patch`, actual
user `text`, and optional typed `references`. Text is limited to 60,000 characters,
patch operations to 100, references to 32; the existing HTTP body bound also applies.
Every payload is revalidated. Unknown IDs, stale fingerprints, invalid geometry,
source conflicts and protection violations are handled by the existing Phase 3A
engine. Shared deterministic evaluation also checks intent scope, preservation,
ambiguity and evidence. No destructive-confirmation boolean is delegated to the
host. Existing ADG/patch/compiler domain contracts are unchanged.

Both evaluation tools retain the existing status, original fingerprint, safe
conflict summaries, clarification flag and candidate fields. On ACCEPTED they
add `accepted_intent` and `evaluated_patch`. The former is the complete exact
intent from that evaluation, not a summary or another model's result; the latter
preserves patch project/base/operations for traceability. This avoids duplicating
the entire PatchResult and its candidate/operation payloads. On REJECTED or
NEEDS_CLARIFICATION the accepted pair and patch handoff are absent. Stop there.

Pass the actual returned data as follows:

```text
evaluate_architectural_proposal(project, intent, patch, text, references)
  -> ok=true, data.status=ACCEPTED
compile_visualization_brief(
  project=data.candidate,
  intent=data.accepted_intent,
  accepted_intent=true,
  evaluation=data,
  options=actual_valid_compilation_options
)
  -> data.brief
compile_image_instructions(brief=data.brief, adapter=openai_image)
  -> data.instructions
```

The optional `evaluation` argument checks accepted status, no unresolved
conflicts/clarification, and exact project/intent equality. Substitution is rejected.
The old direct compiler input remains supported for explicitly caller-accepted
designs; it is not a patch acceptance tool. Plugin-native revisions must supply
the handoff. The Skill selects workflow; the existing Prompt Compiler determines
visualization permissions and prepares instructions. No image is generated.

## Provenance and trust limits

Host and provider proposals cross the same evaluation boundary. USER_EXPLICIT
requires supplied actual user text and operation origin quoting it; explicit text
assertions must be quotes rather than model paraphrases. Numeric evidence uses
existing unit-aware checks. USER_REFERENCE requires supplied reference IDs and
assertion source_reference. Unchanged authoritative assertions are retained;
unsupported new product facts and verification claims are rejected. AI choices
and assumptions remain AI_INFERRED. IMPORTED_GEOMETRY and SYSTEM_DERIVED retain
their existing distinct domain semantics. No source is promoted merely because
the host is ChatGPT/Codex.

Supplied text/references, project history and acceptance acknowledgement are not
authenticated. Evidence checks are conservative structural/lexical checks, not a
proof that the host quoted the real human or understood their semantics. The
stateless evaluation handoff is not a signed approval receipt: a malicious caller
can forge fresh payloads or use the legacy direct compiler contract. It prevents
accidental continuation/substitution when used as prescribed, not hostile caller
forgery. Authentication, durable receipts and revision storage remain deferred.

The plugin-native backend adds no OpenAI API cost. This does not claim that the
host ChatGPT/Codex session has no usage cost. Existing spatial and compiler limits
remain; neither a general solver nor a catalogue verification system was added.
Language quality and actual installed Skill behavior still require separate manual
evaluation. Developer Mode cases remain NOT_EXECUTED. Phase 6B has not begun.
