# ADR: Connector-compatible nonblank text patterns

Accepted 2026-10-03. Domain text validation remains unchanged.

The private connector rejected valid multi-character strings against the published
pattern \\S, while local MCP accepted the same actual data. JSON Schema patterns
are search matches, not implicitly anchored, per
https://json-schema.org/draft/2020-12/json-schema-core#regex . Observed behavior is
consistent with a full-match implementation; its internal cause is not proven.

At the MCP schema boundary only, replace exact \\S with ^[\\s\\S]*\\S[\\s\\S]*$.
This preserves the nonblank rule for search/full-match engines, including multiline
text. Do not strip validation, normalize payloads, or change fingerprints. Input
and output schemas receive the same recursive conversion; other patterns stay.
Domain validation remains the authority. Compatibility tests precede remote retry.
Existing connectors may require schema refresh and server restart before testing.
