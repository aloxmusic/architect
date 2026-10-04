# Architect AI — DEVELOPMENT / NOT FOR SUBMISSION

Portable Agent Plugins source package, using root `plugin.json` and automatically
discovered `skills/`. Phase 6B packages the existing skill and a loopback MCP
connection for local desktop testing. Manual installation is pending; nothing
has been published or uploaded. No public MCP endpoint exists.

Root `mcp.json` bundles `http://127.0.0.1:8000/mcp` using `streamable-http`.
The existing `mcp.development.json` is preserved unchanged as an explicit local
development reference. Hosted/cloud clients cannot reach this machine's loopback
URL; this package is for a supported local desktop client only, with the existing
backend running and live interpretation disabled.
There are no credentials, registered connection IDs, or production placeholders.

The repo marketplace is `.agents/plugins/marketplace.json`, with identity
`architect-ai-local` and display name `Architect AI Development`. Its only entry
points to `./plugin/architect-ai`, relative to the repository root, not the
`.agents/plugins/` directory. No plugin copy or registered remote app mapping is
needed for this local preparation. No credentials or production URLs are added.

After restarting ChatGPT Desktop manually, use the repository as the project
context and open the Plugins Directory. Select `Architect AI Development` and
manually install `architect-ai`. Discovery, installation, bundled MCP loading,
and model activation remain unverified until performed in the actual client.
The official workflow is documented at:
https://developers.openai.com/plugins/build/plugins (checked 2026-10-01).

No project `.codex/config.toml` is added. Although project plugin enablement is
supported for trusted projects, configured plugins can be installed/refreshed
during marketplace refresh. This preparation intentionally leaves installation
to the user. No user-level marketplace/configuration is modified.

The skill needs the seven MCP tools, including provider-free
`evaluate_architectural_proposal`. It cannot substitute for a missing
connection. Connecting the server alone does not install the skill. Install the
package through the supported local marketplace/Plugins Directory flow separately
when intentionally testing it; no installation is performed by this preparation.

`evals/developer_mode_cases.json` contains manual evaluation specifications,
not execution results. See repository `docs/PLUGIN_DEVELOPER_TESTING.md` for
startup, Inspector, Developer Mode, Secure MCP Tunnel and evaluation instructions.
