# MCP server and architectural tools (Phases 5A / 6A)

This boundary exposes verified architectural services through the official Python
MCP SDK `mcp` 2.2.0. It adds no project database, image generation, custom UI,
authentication, public deployment, or plugin installation. Every project operation
requires an explicit current ADG payload; project IDs identify supplied snapshots,
not records held by this server.

Current official documentation consulted on 2026-10-01:

- [OpenAI: Build an MCP server](https://developers.openai.com/plugins/build/mcp-server).
- [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk).
- [Official SDK low-level Server](https://py.sdk.modelcontextprotocol.io/advanced/low-level-server/).
- [Official SDK mounting/lifecycle guidance](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md).

## Architecture and transport

`mcp/contracts.py` defines typed external request/result/error models.
`mcp/handlers.py` calls existing serialization/context, interpreter/patch and
compiler/adapters. `mcp/server.py` constructs the official SDK low-level `Server`
with stable name/version, explicit Pydantic JSON schemas, `tools/list` and
`tools/call` handlers, and sanitized results. `mcp/bootstrap.py` handles transport
and development composition. No MCP types enter domain/services.

The supported low-level API is used to control input validation, concise text,
structured output and errors explicitly. No third-party FastMCP wrapper or obsolete
v1 decorators are used. Output schemas use Pydantic validation-mode schema:
the existing omission-aware patch wrap serializer produces serialization schemas
that erase change-type discriminators. Validation-mode schemas retain typed
branches and validate the emitted JSON. Runtime response models are also validated.
Tests use the official SDK client to check all seven structured output schemas.

Streamable HTTP uses stateless requests and JSON responses at exactly `/mcp`.
The SDK ASGI app is mounted last at `/`, so existing FastAPI routes retain
precedence and no duplicated `/mcp/mcp` path or redirect is introduced. The parent
FastAPI lifespan enters `server.session_manager.run()`; mounted child lifespans
do not start automatically. Each application factory creates a fresh manager.
The normal `/api/v1/health` endpoint and OpenAPI contract remain operational.
There is no MCP project cache or persistent session/project store.

## Development startup

Use the existing virtual environment; install the optional official SDK extra:

```powershell
.\.venv\Scripts\uv.exe sync --locked --extra dev --extra mcp
.\.venv\Scripts\python.exe -m uvicorn architect_ai.mcp.bootstrap:create_development_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

This factory explicitly enables MCP. The ordinary HTTP factory defaults to
`ARCHITECT_AI_MCP_ENABLED=false` and retains its existing `/mcp` 404 behavior.
Alternatively enable that setting to mount MCP in the ordinary app. The SDK's
localhost Host/Origin DNS rebinding protection remains enabled. Use
`http://127.0.0.1:8000/mcp`; a bare `testserver` Host is deliberately rejected.
Bind only to loopback during this unauthenticated development phase.

## Tool inventory

| Tool | Input | Result |
| --- | --- | --- |
| `validate_project` | `project: Project` | Validation status, snapshot fingerprint and entity count |
| `interpret_architectural_request` | Project, text, optional typed text references | Interpretation summary and proposal; no accepted candidate |
| `evaluate_architectural_request` | Project, text, optional references | Summary, status, safe conflicts, clarification and exact intent/patch/candidate handoff only when accepted |
| `evaluate_architectural_proposal` | Project, intent, bounded patch, actual user text, optional references | Provider-free evaluation and exact accepted intent/candidate handoff |
| `compile_visualization_brief` | Project, intent, compilation options, strict `accepted_intent` boolean, optional evaluation handoff | Existing provider-neutral GenerationBrief |
| `compile_image_instructions` | GenerationBrief and supported adapter enum | Existing CompiledInstructionPackage; no image/provider request |
| `get_project_summary` | Project | Stable counts, IDs, styles, output types and protections |

The compiler acknowledgement must be `true`. It records a caller assertion of
acceptance, not authenticated evidence or a new approval authority. All supplied
snapshots, intents and briefs remain caller data; this stateless server cannot
authenticate their history. Patch acceptance continues to use the existing Phase
3A engine through the interpreter service. Destructive confirmation is not exposed
as an untrusted boolean: removal workflows requiring confirmation remain withheld.

Supported instruction adapters are `openai_image`, `generic_text_to_image`, and
`generic_image_to_image`. The last requires an available reference contract.
There is no generic mutation/execute/run/eval/file tool or unrestricted provider
name. CAD, catalogue, shell and filesystem operations are absent.

## Results, errors and annotations

Every tool supplies one short model-readable `content` text summary and a typed
`structuredContent` envelope: `ok`, `summary`, `data`, `error`. Error results set
`isError=true`; patch rejection still includes useful evaluation data and no
candidate. Interpretation clarification may accompany a successful proposal as
an advisory error code, while evaluation requiring clarification is not accepted.
Application `_meta` is unused; the SDK may add protocol-defined server identity.

Errors distinguish `INVALID_PROJECT`, `VALIDATION_FAILED`, `INTERPRETATION_FAILED`,
`PROVIDER_UNAVAILABLE`, `CLARIFICATION_REQUIRED`, `PATCH_REJECTED`,
`UNSUPPORTED_GENERATION_MODE`, `UNSUPPORTED_INSTRUCTION_ADAPTER`, `INVALID_INPUT`,
and `INTERNAL_ERROR`. Validation issues expose only allowlisted root fields and
stable reason codes, bounded to 20. Raw rejected values, exception messages,
stack traces, keys, provider prompts and debugging state are never copied into
error results. Conflicts retain stable target/constraint IDs and safe typed codes;
underlying exception text is omitted. Existing safe JSON logging records static
events, stable provider/compiler codes, error types and internal correlation IDs,
without inputs, secrets or exception bodies.

All seven tools set `readOnlyHint=true`, `destructiveHint=false`,
`openWorldHint=false`. They compute from bounded supplied data and never mutate
server-side persistent architectural state. Interpreter calls can use an externally
hosted OpenAI service when enabled, but do not browse or access open-ended entities;
the descriptions disclose that bounded context may be sent. Annotations are hints,
not authentication or a substitute for validation.

## Mock and live interpreter behavior

Tests inject the existing `MockArchitecturalInterpreterProvider`; all normal tests
are offline. Server construction/startup and tool discovery perform no API calls.
Without injection the interpreter is unavailable unless
`ARCHITECT_AI_MCP_LIVE_INTERPRETER_ENABLED=true` is explicitly configured. Merely
setting `OPENAI_API_KEY` does not enable it. When enabled, the existing lazy OpenAI
provider uses existing model, key, timeout and output-budget settings; no second
client implementation exists. Provider availability/errors become safe MCP codes.

The Phase 3 live smoke test still requires its existing separate explicit test
opt-in and API key. Phase 5A verification explicitly sets that test flag to `0`
and restores its prior process value. Do not enable it for ordinary verification.
The runtime MCP opt-in does not opt tests into live calls. There is no image provider
call under any setting in this phase.

## Inspector and verification

MCP Inspector is an optional external development client, not a Python dependency:

```sh
npx @modelcontextprotocol/inspector@latest
```

Select Streamable HTTP and `http://127.0.0.1:8000/mcp`; inspect initialization,
seven tools, input/output schemas, annotations and error cases. Interpretation tools
return `PROVIDER_UNAVAILABLE` unless a mock is injected or runtime live use is
explicitly enabled. Inspector and external ChatGPT/Codex connections were not run
as Phase 5A verification. Automated tests use in-process ASGI JSON-RPC messages and
the official SDK's in-memory client, without sockets or external clients. They
cover schemas, proposals, deterministic patch acceptance/conflicts, locks,
compilation, adapter selection, redaction, absence of persistence, startup and health.

## Known limitations

This is a local development boundary without OAuth, authorization, per-user
isolation, durable projects, revision storage or plugin distribution. Do not
expose it publicly in this phase. Existing domain, interpreter and compiler limits
remain unchanged, including probabilistic language interpretation, conservative
removals, no general spatial solver, and rejected multi-space compilation. Input
JSON schemas are substantial because the full typed ADG is supplied explicitly;
there is no silent field omission, fake persistence or arbitrary input dictionary.
The SDK bounds HTTP request bodies to its supported default 4 MiB. No image/model
quality or live account/service access is claimed as verified.

## Phase 6A plugin-native path

The seven-tool inventory preserves all six Phase 5 names and adds only
`evaluate_architectural_proposal`. Host-assisted evaluation requires no provider
or API key. Both evaluation tools now include the complete corresponding accepted
intent and evaluated patch on acceptance; non-accepted results have no accepted
project/intent pair. Supply the returned data in the optional compiler evaluation
argument to guard against substitution or continuation of rejected work. The
legacy direct compiler acknowledgement remains compatible and is not authenticated
approval. See `PLUGIN_NATIVE_WORKFLOW.md` for evidence checks and trust limits.

The earlier Phase 5 Inspector checkpoint externally verified discovery and the
validate_project/get_project_summary calls. Phase 6A tests run in-process; the new
seven-tool server and full native flow have not yet been manually tested in
Inspector or installed ChatGPT/Codex. Restart the old backend before inspecting
new tools. No external connection, live provider call or image generation is
performed by Phase 6A.
