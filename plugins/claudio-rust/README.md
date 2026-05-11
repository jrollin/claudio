# claudio-rust

Rust-specific skills for Claude Code: hexagonal architecture, idiomatic patterns, and clean-code review.

## Components

### Skills

- **`rust-hexagonal`** — Ports and adapters architecture in Rust, with clean-code rules. Self-contained: covers idiomatic ownership, errors, async, and testing alongside the architecture. Two modes (scaffold + review) and a layered checklist for audits.
  - `SKILL.md` — core rules, layering invariants, review checklist.
  - `references/generic-crud.md` — UserRepository worked example (textbook).
  - `references/http-service.md` — axum slice, end-to-end.
  - `references/cli-tool.md` — clap slice, end-to-end.
  - `references/openapi-utoipa.md` — axum slice with utoipa-generated OpenAPI 3.1 spec and Swagger UI, all annotations confined to the HTTP adapter.
  - `references/review-checklist.md` — full per-layer audit checklist used in review mode.

## Installation

This plugin is published through the `claudio-power` marketplace. Install via `/plugin` and pick `claudio-rust`.

## Author

Julien Rollin
