# ADR 0001: Domain-centered modular monolith

Status: accepted. Date: 2026-09-30.

Context: multiple AI, HTTP, MCP and desktop integrations must share architectural
intent without binding the product to one SDK or splitting it into premature services.

Decision: use a typed Python modular monolith with a src layout. Domain and
deterministic geometry are inward dependencies. Services own use cases and ports;
providers, storage and transports implement adapters. The composition root wires
them. Reserved packages have no fake implementations in Phase 1.

Alternatives: provider-centric orchestration would leak model behavior into the
domain; early microservices would add deployment and consistency overhead before
domain contracts stabilize. Both are rejected for the initial product.

Consequences: adapters can change independently; import boundaries need tests and
review. Pydantic is permitted as validation infrastructure, but provider, ORM and
transport objects are prohibited in domain contracts.
