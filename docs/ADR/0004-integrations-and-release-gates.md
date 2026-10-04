# ADR 0004: Evidence-based integrations and honest release gates

Status: accepted. Date: 2026-09-30.

Context: SDKs and host integration patterns change; old examples and product labels
cannot establish valid API calls. Phase 1 must not silently become a full product.

Decision: consult current official documentation before choosing dependencies or
API patterns. The official MCP SDK v2 is an optional future inbound adapter. OpenAI
Responses is the intended future orchestration API, but no API model ID or provider
implementation is selected now. Recheck the current ChatGPT Plugins guide at that
phase. No legacy manifest or untested endpoint is exposed.

Use local-only binding, validated config, explicit logs and tests. Require a clean
locked install, passing test/type/lint/build gates and real HTTP smoke test before
declaring Phase 1 operational. Network or missing-package failures remain blockers;
never replace required packages with fake modules to produce passing tests.

Consequences: capability breadth grows more slowly but stays verifiable. No API
keys or database are needed now. Public deployment still needs authentication,
tenant isolation, threat review, abuse controls and restore testing.
