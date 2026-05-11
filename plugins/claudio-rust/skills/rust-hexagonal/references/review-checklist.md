# Review Checklist

Use this checklist in **review mode** to audit an existing Rust codebase against `rust-hexagonal`. For every finding, cite a file path and line number. Group findings by category. Report violations of iron rules first, then idiomatic issues.

## Layering

- [ ] Domain crate/module has zero infrastructure dependencies in `Cargo.toml` (no `sqlx`, `reqwest`, `axum`, `tokio::fs`, `clap`).
- [ ] Port traits are defined in the domain, not in the adapter that implements them.
- [ ] No adapter `use`s another adapter.
- [ ] No domain code imports adapter types.
- [ ] Composition root is `lib.rs` (e.g. `pub fn build_app(...) -> Router`). `main.rs` is a thin shim that only calls into `lib.rs`.

## Types and errors

- [ ] Domain IDs and value types are newtypes, not raw primitives.
- [ ] State is expressed with enums, not boolean flags.
- [ ] Each layer has its own error type. Adapter errors convert into domain errors via `From` or `map_err`.
- [ ] No `unwrap()` / `expect()` outside `main.rs` startup and `#[cfg(test)]` code.
- [ ] `thiserror` used in libraries; `anyhow` only at the binary boundary.

## Ports

- [ ] Each port trait is named in business terms (`UserRepository`, not `UserSqlDao`).
- [ ] Each port trait returns domain types and domain errors only.
- [ ] Each port trait has a clear single responsibility (no god traits).
- [ ] Ports used in async shared state are `Send + Sync`.

## Use cases

- [ ] Use cases live in the domain.
- [ ] Use cases are generic over port traits (or take `Arc<dyn Trait>`), not over concrete adapter types.
- [ ] Use cases have unit tests using in-memory port impls.
- [ ] Use cases don't import HTTP/SQL/filesystem types.

## Idiomatic Rust

- [ ] Function parameters borrow (`&T`, `&str`, `&[T]`) unless ownership is required.
- [ ] No `.clone()` calls used to bypass borrow-checker errors.
- [ ] No `panic!` / `unimplemented!` / `todo!` in production paths.
- [ ] Public APIs return `Result<T, ConcreteError>`, not `Result<T, Box<dyn Error>>`.
- [ ] No `#[cfg(test)]` leaking into production type signatures.

## Tests

- [ ] Domain use cases have unit tests against in-memory ports.
- [ ] Adapter tests use real infrastructure (testcontainers, temp dirs) at the integration level.
- [ ] No mocks of `sqlx` or `reqwest` internals.
- [ ] Tests describe behavior, not implementation, in their names.

## Reporting format

When producing the review report, for each violation include:

```text
[<category>] <file>:<line>
  Rule: <quote iron rule or checklist item>
  Finding: <what the code does>
  Fix: <smallest change that resolves the violation>
```

Group by category in the order above. Iron-rule violations come first (highest severity), then idiomatic issues, then test concerns.
