---
name: rust-hexagonal
description: Design or review Rust services using hexagonal (ports and adapters) architecture with idiomatic ownership, errors, and testing. Use when structuring a Rust project, deciding where a trait or dependency belongs, or auditing layering between domain and infrastructure.
---

# Rust + Hexagonal Architecture

This skill teaches and enforces hexagonal (ports and adapters) architecture in Rust, using idiomatic patterns. It is self-contained on layering; for how to split a module or long function internally it points to the separate `rust-decompose` skill.

Two modes:

- **Scaffold** — design new code with the right layering from the start
- **Review** — audit existing Rust code against the rules below

After reading this file, the agent should produce: port traits in the domain, adapter implementations outside it, and a composition root that wires them. In review mode, the output is a layered report citing iron-rule violations with file paths and line numbers.

This skill covers the **boundaries** (where code goes across the domain/adapter line). How a module or long function is **internally decomposed** — file→directory splits, orchestrator + phase functions, keeping an owned resource out of extracted helpers — is the separate, non-hexagonal `rust-decompose` skill. Apply both when writing a feature.

Worked examples live in `references/`. Pick one after reading this file (see "Picking a worked example" at the end).

## The core idea

Business logic depends on **abstractions** (traits), not on databases, HTTP frameworks, or filesystems. Adapters at the edge implement those abstractions. The domain core knows nothing about them.

- **Driving adapters** call into the domain (HTTP handler, CLI command, gRPC server).
- **Driven adapters** are called by the domain through ports (DB, message bus, email sender).
- **Ports** are trait declarations that live in the domain. **Adapters** are the concrete impls that live outside it.

## Layering rules (the iron rules)

1. **Domain depends on nothing infrastructural.** No `sqlx`, `reqwest`, `tokio::fs`, `axum`, `clap` types in the domain crate or module.
2. **Ports are traits, defined in the domain.** Adapters live outside the domain and implement those traits.
3. **Adapters never know about each other.** A Postgres adapter does not import an HTTP adapter.
4. **Composition root is `lib.rs`, not `main.rs`.** Wire concrete adapters into use cases inside a `pub fn build_app(...)` (or `run()`) in `lib.rs`. `main.rs` is a thin shim that parses env, calls `build_app()`, and serves. This is required for integration tests to reach the wired application.
5. **No `unwrap()` / `expect()` in domain or adapter code.** Only acceptable in `main.rs` for startup failures and in tests.
6. **Errors cross layers explicitly.** Each layer has its own error type; adapters convert their errors into domain errors via `From` or `map_err`.

If any rule is broken, the architecture is broken. Fix it before adding features.

## Cargo workspace layout

For non-trivial projects, use a workspace with a virtual root manifest (no crate at the workspace root):

```text
my-app/
├── Cargo.toml              # workspace = { members = ["crates/*"] }
├── crates/
│   ├── domain/             # lib crate. Zero infra deps.
│   ├── driving/            # adapters that CALL INTO the domain.
│   │   ├── http/           #   axum routes → use cases
│   │   └── cli/            #   clap subcommands → use cases
│   ├── driven/             # adapters CALLED BY the domain via ports.
│   │   ├── postgres/       #   impl UserRepository for PostgresUserRepository
│   │   └── smtp/           #   impl Notifier for SmtpNotifier
│   └── bootstrap/          # lib + bin: build_app() wires driving + driven into use cases.
```

**Driving vs driven, concretely:**

| Aspect | Driving adapter | Driven adapter |
| --- | --- | --- |
| Direction | Calls into the domain | Called by the domain through a port |
| Imports | `domain::use_cases::*` | `domain::ports::*` (implements the trait) |
| Examples | axum handlers, clap commands, gRPC servers, message-bus consumers | sqlx repositories, reqwest API clients, SMTP senders, S3 stores |
| What it owns | Request/response shapes, route mounting, argv parsing | Connection pools, retry policies, marshalling to/from infra types |
| Failure surface | Maps `DomainError` → transport response (HTTP status, exit code) | Maps infra error (`sqlx::Error`, `reqwest::Error`) → `DomainError` |

A driving adapter never implements a domain port. A driven adapter never owns a route or a CLI command. If you find an adapter doing both, it's two adapters wearing one hat — split them.

The `bootstrap` crate exposes both `[lib]` and `[[bin]]` targets from the same `Cargo.toml`. Integration tests in `crates/bootstrap/tests/` call `build_app()` directly and exercise the fully wired application without binding to a network port.

For small projects, modules inside a single crate work:

```text
src/
├── lib.rs            # mod domain; mod driving; mod driven; pub fn build_app(...) -> Router
├── main.rs           # 5-line shim: parse env, call build_app(), serve
├── domain/           # entities, ports, use cases
├── driving/          # http, cli — call into the domain
└── driven/           # postgres, smtp — called by the domain via ports
```

Whichever layout you pick:

- Directory structure mirrors the dependency direction: `adapters` can `use domain`; `domain` cannot `use adapters`.
- All composition lives in `lib.rs`, never in `main.rs`. `main.rs` is a binary entrypoint, nothing more.

## Defining a port

A port is a trait on the domain side that describes what the domain needs in business terms, not in storage terms. Minimal shape:

```rust
#[async_trait::async_trait]
pub trait UserRepository: Send + Sync {
    async fn find_by_id(&self, id: UserId) -> Result<Option<User>, DomainError>;
    async fn save(&self, user: &User) -> Result<(), DomainError>;
}
```

Rules for ports:

- **Name in domain terms.** `UserRepository`, not `UserDao`. `Clock`, not `SystemTimeProvider`.
- **Return domain types.** Never `sqlx::Row` or `serde_json::Value`.
- **Return domain errors.** Not `sqlx::Error`.
- **Keep them small.** One trait per responsibility. A trait with 20 methods is two traits.
- **`Send + Sync` for async.** Required if the port is used across `.await` points in shared state.

Full port + adapter + use case wiring: `references/generic-crud.md`.

## Implementing an adapter

```rust
pub struct PostgresUserRepository { pool: sqlx::PgPool }

#[async_trait::async_trait]
impl UserRepository for PostgresUserRepository {
    async fn find_by_id(&self, id: UserId) -> Result<Option<User>, DomainError> { /* sqlx call, .map_err(DomainError::from) */ }
}
```

- `sqlx` types stay inside the adapter crate. The trait signature returns `User` and `DomainError`.
- Map infra errors at the boundary via `impl From<sqlx::Error> for DomainError` (see Errors section).
- Reconstructing entities from DB rows uses an adapter-side `UserRow` struct and a `pub(crate)` constructor like `User::new_with_id`.

## Use cases (application services)

Use cases orchestrate ports. They are plain generic structs:

```rust
pub struct RegisterUser<R: UserRepository, C: Clock> { users: R, clock: C }

impl<R: UserRepository, C: Clock> RegisterUser<R, C> {
    pub async fn execute(&self, email: Email) -> Result<UserId, DomainError> { /* check uniqueness, build User, save */ }
}
```

- Fields are private; expose a `new(...)` constructor.
- No HTTP, no SQL, no filesystem. Pure orchestration of ports.
- Generic over the port traits (or take `Arc<dyn Trait>`), never over concrete adapter types.
- Trivially unit-testable with in-memory port impls.

## Errors: one type per layer

- **Domain** defines `DomainError` (a `thiserror` enum with business variants like `NotFound`, `EmailAlreadyTaken`, `Storage(String)`).
- **Driven adapters** convert their infra errors into `DomainError` via `impl From<sqlx::Error> for DomainError` (or `map_err`).
- **Driving adapters** convert `DomainError` into transport responses (`impl IntoResponse for DomainError`, or CLI exit codes).
- **`Storage(_)` variants must not leak detail to clients.** Log the inner error; return a generic message.
- Use `thiserror` in libraries (domain, adapters). Use `anyhow` only at the binary boundary (`main.rs`, integration tests).

Full error type + From impls + HTTP/CLI mapping: `references/generic-crud.md` and `references/http-service.md`.

## Idiomatic Rust rules (apply everywhere)

### Ownership and borrowing

- **Borrow by default.** Take `&T` or `&mut T`. Take ownership (`T`) only when you must store, move, or consume.
- **No `.clone()` to shut up the borrow checker.** Restructure instead. The exception: cheap reference-counted types (`Arc<T>`).
- **Prefer slices over `Vec`.** `&[T]` and `&str` for parameters. Owned `Vec<T>` / `String` only when storing or transforming.
- **Lifetimes are last resort.** If a function needs a complex lifetime annotation, consider owning the data instead.

### Errors

- **`Result<T, E>` for fallible operations.** Never panic on user input or external data.
- **`?` for propagation.** Don't manually `match` to re-wrap.
- **`thiserror` for libraries, `anyhow` for binaries.** Domain and adapters use `thiserror`; `main.rs` may use `anyhow`.
- **Encode statically guaranteed values in the type.** Use newtypes, enums, or `NonZero*` instead of unwrapping at the call site. (Iron rule 5 forbids `unwrap()` / `expect()` outside `main.rs` startup and tests.)

### Types

- **Newtype for domain values.** `pub struct UserId(uuid::Uuid);` — not raw `Uuid`.
- **Enums over booleans for state.** `enum AccountStatus { Active, Suspended, Closed }` — not `is_active: bool, is_suspended: bool`.
- **Make illegal states unrepresentable.** If two fields can never both be `Some`, that's an enum.

### Async

- **`Send + Sync` on port traits that cross tasks.**
- **Use `#[async_trait]` when you need `dyn Trait` for a port.** Native `async fn` in traits (stable since Rust 1.75) is fine when callers use generics (`impl Trait`); as of Rust 1.x it still has no built-in `dyn` dispatch, so reach for `#[async_trait]` or the `trait-variant` crate when a port must be stored behind `Arc<dyn Trait>`. Recheck this when bumping the toolchain.
- **Don't `block_on` inside async code.** Restructure.

### Testing

- **In-memory adapters for unit tests.** Implement the port trait with a `HashMap` or `Vec` and inject it.
- **`testcontainers` for integration tests.** Real Postgres in a container beats mocking SQL.
- **No `#[cfg(test)]` leakage in production code.** Test helpers live in `tests/` or `#[cfg(test)] mod tests` at the bottom of a file.

## Scaffolding a new slice (decision flow)

1. **What's the user-visible behavior?** Write it down in one sentence.
2. **What does the domain need?** List the ports — purely in business terms. Don't think about storage yet.
3. **Define entities and value objects.** Newtypes, enums, no infra deps.
4. **Define port traits in the domain.** One trait per responsibility.
5. **Write the use case.** Generic over the port traits. Unit-test it with in-memory port impls.
6. **Implement adapters.** Each adapter lives in its own module/crate and converts infra errors into domain errors.
7. **Wire it up in `lib.rs` (`build_app`).** Build concrete adapters, inject into the use case, expose via a driving adapter. Keep `main.rs` as a 5-line shim that calls `build_app()`.

If you're tempted to skip step 5 (the use case) because "it's just a CRUD pass-through," you still need it. The use case is where invariants live. A bare repository call is fine only when there are genuinely zero rules — and that's rarer than it looks.

As each piece grows past one concern or one named phase, decompose it as you write (see the `rust-decompose` skill) — don't let a use case, adapter, or module accrete into a god-file you'll split later.

## Review mode

When auditing an existing codebase, walk through `references/review-checklist.md` and cite file paths and line numbers for every finding. Report iron-rule violations first.

### Red flags (any one means stop and fix)

- A trait in an adapter crate that the domain implements (dependency inversion is upside down).
- A `sqlx::Error` or `reqwest::Error` bubbling up to an HTTP handler.
- A use case that takes a `PgPool` directly.
- A domain entity with a `pub fn save(&self, pool: &PgPool)` method (active record creeping in).
- A `Cargo.toml` in the domain crate that lists infrastructure dependencies.
- A test that mocks more than it asserts.

## Picking a worked example

Read one (or more) of these after this file:

- **`references/generic-crud.md`** — Start here if you're learning the pattern. UserRepository, Postgres adapter, in-memory adapter for tests.
- **`references/http-service.md`** — A realistic axum slice: handler → use case → port → DB adapter.
- **`references/cli-tool.md`** — A realistic clap slice: command → use case → port → filesystem/API adapter.
- **`references/openapi-utoipa.md`** — Same axum slice with utoipa annotations, an aggregated OpenAPI doc, and Swagger UI. All annotations live in the HTTP adapter; the domain stays clean.
- **`references/review-checklist.md`** — Full per-layer audit checklist for review mode.

Each example is fully wired, end-to-end, and follows the rules above.

## When NOT to use this skill

- Scripts under ~200 lines that won't outlive the week.
- Prototype crates whose only job is to validate a library API.
- Procedural macros and `build.rs` — they have their own structure.

For anything with persisted state, multiple external services, or a lifetime measured in months, use this skill.
