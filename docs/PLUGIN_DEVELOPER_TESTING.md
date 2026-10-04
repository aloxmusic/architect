# Plugin developer testing — Phases 5B / 6A / 6B preparation

2026-10-03: private ChatGPT workflows and related evidence across twelve categories
are audited in CHATGPT_MANUAL_EVIDENCE.md. Guided/shared-context checks do not replace
the canonical fresh-conversation suite. Later desktop compilation succeeded, but
attachment access and intermittent connector errors remain unresolved. This update
supersedes earlier statements that no remote connection had been tested.

2026-10-02 update: local desktop installation, the actual seven-tool MCP inventory,
native three-tool chain and two protection rejections are verified. A controlled
backend restart and subsequent installed-plugin validation also passed. See
LOCAL_MCP_RECOVERY.md. Remote ChatGPT Developer Mode/tunnel and the complete model
evaluation set remain pending. Historical statements below about unexecuted local
installation/Inspector checks are superseded by this update.

DEVELOPMENT / NOT FOR SUBMISSION. Phase 5B prepared packaging; Phase 6A adds the
offline native workflow. Neither phase creates a remote connection, tunnel,
installation, publication or live provider use. The user's earlier local Inspector
checkpoint is recorded separately below.

## Architecture and current format

The portable source package lives at `plugin/architect-ai/`. Root `plugin.json`
packages `skills/architectural-design/SKILL.md`; the skill coordinates the existing
seven MCP tools. Phase 6B local preparation adds root `mcp.json` with explicit
Streamable HTTP transport at `http://127.0.0.1:8000/mcp`; the original
`mcp.development.json` remains unchanged. This is local desktop testing only,
not a production or hosted ChatGPT connection. The repo marketplace references
the existing package without copying it. See the package README for manual
restart/install instructions. Actual remote configuration and registered ChatGPT
connection mapping remain deferred. No legacy OpenAPI plugin manifest is used.

Official guidance consulted on 2026-10-01:

- [Plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Skills](https://developers.openai.com/plugins/build/skills)
- [Developer connections](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector)

## Local backend and Inspector

From the repository root, using the already installed environment:

```powershell
$env:ARCHITECT_AI_MCP_LIVE_INTERPRETER_ENABLED = 'false'
$env:ARCHITECT_AI_RUN_LIVE_OPENAI_TESTS = '0'
.\.venv\Scripts\python.exe -m uvicorn architect_ai.mcp.bootstrap:create_development_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

In a second terminal, with Node/npm available and Inspector already available or
an intentional manual download permitted:

```powershell
npx @modelcontextprotocol/inspector@latest
```

`npx` can download Inspector if absent. This phase does not install Node/npm or
download Inspector. It is an optional manual step, not a Python dependency.
Open the URL/token printed by Inspector, select **Streamable HTTP**, enter
`http://127.0.0.1:8000/mcp`, connect, then list tools. Expect exactly:

- `validate_project`
- `interpret_architectural_request`
- `evaluate_architectural_request`
- `evaluate_architectural_proposal`
- `compile_visualization_brief`
- `compile_image_instructions`
- `get_project_summary`

Check input/output schemas and each tool's `readOnlyHint=true`,
`destructiveHint=false`, `openWorldHint=false`. These are hints, not authorization.
All results have a short content summary and structured `ok/summary/data/error`.

Prepare a complete fixture argument to paste into Inspector:

```powershell
$architectAiProject = Get-Content tests/fixtures/adg/living_room.json -Raw | ConvertFrom-Json
@{ project = $architectAiProject } | ConvertTo-Json -Depth 100
```

Call `validate_project` and `get_project_summary` with that JSON; expect valid
snapshot information and stable IDs/protections. For interpretation/evaluation:

```powershell
@{ project = $architectAiProject; text = 'Make this living room more luxurious without changing the architecture.'; references = @() } | ConvertTo-Json -Depth 100
```

With the default offline server, both language tools must return
`PROVIDER_UNAVAILABLE`; no semantic acceptance is expected. Offline mock coverage
is in `tests/test_mcp.py`; the startup factory has no mock-provider switch.

For a deterministic compilation smoke, explicitly acknowledge this test-only
unchanged snapshot/intent, not approval of a real project or persistent revision:

```powershell
$architectAiIntent = @{ goal = @{ value = 'Prepare a visualization of the supplied unchanged design'; source = 'USER_EXPLICIT' }; confidence = '1' }
@{ project = $architectAiProject; intent = $architectAiIntent; accepted_intent = $true; options = @{ mode = 'GEOMETRY_LOCKED_RENDER_MODE'; output = @{ target = 'architectural_render' } } } | ConvertTo-Json -Depth 100
```

Call `compile_visualization_brief`; pass its actual `data.brief` to
`compile_image_instructions` as `{"brief": <actual returned object>,
"adapter": "openai_image"}`. Substitute the object, not that illustrative token.
Expect instructions only, no image request. Retain actual structured results.

Invalid checks: `{}` to validation → `INVALID_INPUT`; `{"project":{}}` →
`INVALID_PROJECT`; valid compilation payload with `accepted_intent=false` →
`CLARIFICATION_REQUIRED`; unknown mode → `UNSUPPORTED_GENERATION_MODE`;
valid brief with unknown adapter → `UNSUPPORTED_INSTRUCTION_ADAPTER`.
No rejected input, secrets or raw traceback should appear in errors.

## ChatGPT Developer Mode and private tunnel

Hosted ChatGPT cannot connect directly to loopback. Prefer Secure MCP Tunnel for
private local testing. An intentionally configured reachable HTTPS development
endpoint is another supported route, but none exists here. Do not bind publicly,
create firewall rules, or automatically configure third-party tunnels.

Future manual tunnel steps, requiring separate credentials/organization setup:

1. In OpenAI Platform tunnel settings, create a tunnel for the intended Platform
   organization and ChatGPT workspace. Creation requires Tunnels Read/Manage;
   runtime/selection requires Read/Use and the appropriate workspace permissions.
2. Obtain the official `tunnel-client` using the current guide. Its local HTTP
   upstream is `http://127.0.0.1:8000/mcp`; this server is not a stdio command.
3. Run `tunnel-client help quickstart` and configure an HTTP profile named
   `architect-ai-local` using the real Platform tunnel ID and
   `--mcp-server-url http://127.0.0.1:8000/mcp`. Provide the required runtime API
   credential securely according to the client guide; never commit it or a key
   containing profile. This phase neither obtains nor uses that credential.
4. Run `tunnel-client doctor --profile architect-ai-local --explain`, then
   `tunnel-client run --profile architect-ai-local`. Inspect the client's reported
   health/readiness endpoints and local status UI; retain redacted diagnostics.
5. In ChatGPT Settings → Security and login, enable Developer mode if allowed.
   In Plugins, create a developer MCP connection, choose **Tunnel**, and select
   the real available tunnel. Review discovered tools and metadata. Missing
   tunnels require checking workspace association, permissions and client health.
6. In a new conversation, select the connection through the tools menu. Start
   with validation and summary only. Refresh the connection after server metadata
   changes, then use a fresh conversation for retesting.

Secure MCP Tunnel is private developer access, not a substitute for the public
production endpoint needed for submission. No tunnel is created by this runbook.

## Skill installation and evaluations

A developer MCP connection alone does not load the skill. After obtaining real
connection details, configure the package's supported host binding (including
the actual registered `plugin_asdk_app...` identifier in OpenAI extension mappings
where required), and install through a local marketplace/Plugins Directory flow.
The current skills-only package does not claim automatic MCP dependency binding.

Run `evals/developer_mode_cases.json` in fresh conversations with the stated
project/protection context. Fixture names are symbolic: map `living_room` and
`l_layout_kitchen` to repository `tests/fixtures/adg/`. Supply actual full snapshots
and resolve specified targets to actual IDs; never invent IDs or constraints.
Cases needing extra locks or ambiguity require a validated test snapshot with
that context. Record activation, tool names/arguments, result status/conflicts,
clarification, preserved IDs/camera/geometry and prohibited behavior. Distinguish
transport checks from semantic evaluation. All cases are currently NOT_EXECUTED in ChatGPT Developer Mode.

Plugin-native language cases use the host-created typed proposal with actual user
text and evaluate_architectural_proposal; no backend provider is required. Only
standalone language tools require a deliberately configured interpreter. On
acceptance, retain the actual returned candidate, accepted_intent and full
evaluation data for compilation; do not substitute another proposal. See
PLUGIN_NATIVE_WORKFLOW.md for the complete provider-free handoff. Do not enable
live interpretation or spend credits in this phase.

## Limits and public submission follow-up

No live model quality, installed plugin behavior, Phase 6A native Inspector flow,
Developer Mode connection or tunnel was verified. Static/offline MCP tests do not
prove model activation accuracy. No persistence, authentication/OAuth, per-user
isolation, image generation, CAD, UI or product catalogue exists. Existing compiler
and spatial limits remain. Before any separately authorized submission: establish
real production hosting and security, actual MCP/skill connection bindings,
required submission metadata, and live developer evaluation evidence. Phase 6A
implements the provider-free handoff; Phase 6B has not begun.

## Local checkpoint and native retest

The user manually verified the Phase 5 backend health, Inspector connection,
six-tool discovery, validate_project and get_project_summary. This is not manual
Developer Mode evaluation. Node/npm/npx and Inspector are now installed locally.
Phase 6A adds a seventh tool: restart the backend using the command above, refresh
Inspector discovery and test a typed host proposal with the live interpreter still
disabled. No tunnel or ChatGPT connection is needed for that local test.
