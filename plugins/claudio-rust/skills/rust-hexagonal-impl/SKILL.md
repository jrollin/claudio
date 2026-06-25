---
name: rust-hexagonal-impl
description: Orchestrate implementation of one hexagonal Rust slice by dispatching agents in the correct order — build the domain core (model + use case + ports) first, then fan out the driven and driving adapters in parallel, then wire bootstrap serially. Use when you want to implement a ports-and-adapters slice with parallel adapter work that does not interfere. Trigger for "implement this slice hexagonally", "build the domain then the adapters in parallel", "scaffold a ports-and-adapters feature end to end". For the layering RULES themselves use rust-hexagonal; this skill is the DISPATCH recipe.
---

# Rust Hexagonal Implementation (orchestrator)

This skill is a **dispatch recipe**, not a rule set. It sequences the claudio-rust hexagonal agents to implement one slice end to end. The architecture rules live in `claudio-rust:rust-hexagonal`; the decomposition rules in `claudio-rust:rust-decompose`. Do not restate them here — the agents load them.

The whole point: the **port-and-adapter pattern lets the two adapters be built in parallel**, because they share only a frozen, read-only contract. This skill enforces the ordering that makes that safe.

## When to use

- You have a slice to implement and the rust-hexagonal layout (workspace crates or single-crate modules) is chosen.
- You want the driven adapter (repository/client/sender) and the driving adapter (HTTP/CLI/gRPC) built concurrently.

If the slice is a sub-200-line script or a prototype, skip this — implement it directly (see rust-hexagonal "When NOT to use").

## Preconditions (verify before phase 1)

- The user-visible behavior is stated in one sentence. If not, ask.
- The crate/module layout exists or is decided.
- The slice is **one cohesive use case**. If it is several, run this skill once per slice; do not widen the parallel phase.

## The three phases

### Phase 1 — Domain core (serial, blocking)

Dispatch **one** `hexagonal-core-builder` agent. It produces and freezes the contract: port traits, use-case signatures, `DomainError`. It writes only `domain/**` and emits a **contract summary**.

Phase 2 cannot start until this agent returns its contract summary and the domain compiles + tests green. The contract is the synchronization point.

### Phase 2 — Adapters (parallel, non-blocking between the two)

Dispatch **both** adapter agents in a **single message with two Agent tool calls** so they run concurrently:

- `hexagonal-driven-adapter` — implements one port. Writes only `driven/<adapter>/**`.
- `hexagonal-driving-adapter` — calls one use case. Writes only `driving/<adapter>/**`.

Both read `domain/**` read-only. Their write sets are disjoint, so they cannot conflict.

Pass each agent the contract summary from phase 1 verbatim, plus which single port / which single driving surface it owns. If the slice needs N driven adapters and M driving adapters, dispatch all N+M in the same message — they are all mutually non-overlapping.

**The interference guard:** neither adapter may edit `domain/**`, the other adapter's dir, or `bootstrap`/`build_app()`/`main.rs`. If an adapter reports the contract must change, that is a Phase 1 redo (re-dispatch core-builder), not an in-place edit — because the other adapter is compiling against the same frozen contract concurrently.

### Phase 3 — Bootstrap wiring (serial, fan-in)

After **both** adapter agents return, do the wiring yourself (or dispatch a focused agent). This is the one file both adapters would otherwise touch, which is why it is deferred to here:

- In `lib.rs` / `bootstrap`, write `build_app(...)`: construct each driven adapter (its `new(...)`), construct the use case injecting the driven adapter(s), then build the driving surface by passing the use case into the driving adapter's build seam (`routes(uc)` / `command(uc)`).
- Keep `main.rs` a thin shim: parse env, call `build_app()`, serve.
- Build + test the whole slice. Integration tests in `bootstrap/tests/` call `build_app()` directly.

### Phase 4 — Review (optional)

Dispatch `hexagonal-review` (read-only) to audit the finished slice against the iron rules before you call it done.

## Dispatch summary

```text
phase 1  [serial]    hexagonal-core-builder        -> freezes contract (ports, use cases, DomainError)
                          |  (contract summary + green domain)
phase 2  [parallel]  hexagonal-driven-adapter   ─┐  read domain/** ; write driven/<a>/** only
                     hexagonal-driving-adapter  ─┘  read domain/** ; write driving/<a>/** only
                          |  (both return constructor + build-seam signatures)
phase 3  [serial]    you / wiring step             -> build_app() in lib.rs/bootstrap, main.rs shim
                          |
phase 4  [optional]  hexagonal-review              -> read-only iron-rule audit
```

## Non-interference invariant (why parallel is safe)

| Path | Phase 1 | Phase 2 driven | Phase 2 driving | Phase 3 |
| --- | --- | --- | --- | --- |
| `domain/**` | write | read-only | read-only | read-only |
| `driven/<a>/**` | — | **write** | — | read-only |
| `driving/<a>/**` | — | — | **write** | read-only |
| `bootstrap` / `build_app()` / `main.rs` | — | — | — | **write** |

Disjoint write sets in phase 2 are the guarantee. The shared `build_app()` file is the only contention point, so it is serialized into phase 3. If you ever let an adapter write `build_app()`, you lose the guarantee.

## Failure handling

- **Contract change requested by an adapter** → stop phase 2, re-run phase 1 with the change, re-dispatch both adapters against the new contract. Never patch the domain from inside an adapter agent.
- **One adapter fails, the other succeeds** → re-dispatch only the failed one; the succeeded one's files are untouched.
- **Phase 3 wiring fails to compile** → the mismatch is between a constructor/build-seam signature and what wiring assumed; reconcile in `build_app()`, not by editing an adapter's internals.

## Conventions

- English only. No em-dash in prose. Concise, bullet-driven.
- One slice per run. Re-invoke per slice rather than widening the fan-out across unrelated use cases.
- Defer all architecture and idiom rules to `claudio-rust:rust-hexagonal` and `claudio-rust:rust-decompose`.
