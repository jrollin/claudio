# claudio-rust

Rust-specific skills and agents for Claude Code: hexagonal architecture, parallel slice implementation, idiomatic patterns, and clean-code review.

## Components

### Skills

- **`rust-hexagonal`** — Ports and adapters architecture in Rust, with clean-code rules. Self-contained: covers idiomatic ownership, errors, async, and testing alongside the architecture. Two modes (scaffold + review) and a layered checklist for audits.
  - `SKILL.md` — core rules, layering invariants, review checklist.
  - `references/generic-crud.md` — UserRepository worked example (textbook).
  - `references/http-service.md` — axum slice, end-to-end.
  - `references/cli-tool.md` — clap slice, end-to-end.
  - `references/openapi-utoipa.md` — axum slice with utoipa-generated OpenAPI 3.1 spec and Swagger UI, all annotations confined to the HTTP adapter.
  - `references/review-checklist.md` — full per-layer audit checklist used in review mode.
- **`rust-hexagonal-impl`** — Orchestrator that dispatches the hexagonal agents to implement one slice end to end. Sequences: domain core first (serial), driven + driving adapters in parallel (non-overlapping file sets), bootstrap wiring serially, optional review. Defers all rules to `rust-hexagonal`.

### Agents

The agents below implement and review a hexagonal slice. The port-and-adapter pattern lets the two adapters be built **in parallel** once the domain core is frozen, because they share only a read-only contract (ports, use-case signatures, `DomainError`).

- **`hexagonal-core-builder`** — Phase 1 (serial). Builds the domain core: entities, value objects, `DomainError`, port traits, and use cases generic over those ports, with in-memory unit tests. Freezes the contract the adapters depend on. Writes only `domain/**`.
- **`hexagonal-driven-adapter`** — Phase 2 (parallel). Implements one driven port (SQLx repository, reqwest client, SMTP sender, S3 store). Reads `domain/**` read-only; writes only `driven/<adapter>/**`. Maps infra errors into `DomainError`.
- **`hexagonal-driving-adapter`** — Phase 2 (parallel). Implements one driving surface (axum handler, clap command, gRPC server). Reads `domain/**` read-only; writes only `driving/<adapter>/**`. Maps `DomainError` into a transport response.
- **`hexagonal-review`** — Read-only auditor. Reviews a finished slice against the iron rules, citing violations with file paths and line numbers.

Bootstrap wiring (`build_app()`) is the one shared file, so it is a serial step after both adapters return — not owned by either adapter.

## Installation

This plugin is published through the `claudio-power` marketplace. Install via `/plugin` and pick `claudio-rust`.

## Author

Julien Rollin
