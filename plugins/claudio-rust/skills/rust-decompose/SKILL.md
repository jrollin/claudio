---
name: rust-decompose
description: Structure Rust code into cohesive modules and functions. Use when writing new Rust feature code, adding a module or a non-trivial function, deciding how to organize a file, splitting a god-file into a directory module, breaking a long function into an orchestrator plus phase functions, keeping an owned resource (transaction, lock, accumulator) from leaking across boundaries, or reviewing module/function structure. Apply while writing, not only when refactoring. Architecture-agnostic — any Rust code, hexagonal or not.
---

# Rust Decomposition

This skill governs **internal structure**: how a module or function is split into smaller pieces. It is orthogonal to architecture — well-decomposed code can be hexagonal, a plain CLI, a parser, or a library. For where code goes across a domain/adapter boundary, use the separate `rust-hexagonal` skill; the two compose.

Two modes:

- **Scaffold** — write code already decomposed. A god-file or 300-line function is a defect at creation, not a cleanup task for later.
- **Review** — audit existing code for god-files, god-functions, and leaked invariants. Output cites file paths + line numbers (see `references/review-checklist.md`).

Worked example (the cartog `index_directory` split, real before/after): `references/decomposition.md`.

## The core idea

Each unit names one thing. A file names one concern; a function names one operation. When a unit has to say "and" to describe itself — "loads config AND converts it AND validates it", "walks AND parses AND stores AND resolves" — it is already telling you its split.

Decompose **as you write**, not in a later refactor. The cost of writing it split is near zero; the cost of splitting a god-file later (preserving every invariant, re-testing the seams) is high.

## The iron rules

1. **One file, one concern.** A file that mixes >1 concern AND is large enough that finding code is slow becomes a directory module. Not on line count alone.
2. **One function, one operation.** A function with distinct named sequential phases becomes an orchestrator + one function per phase.
3. **`mod.rs` / `lib.rs` carry no logic.** Aggregator files hold `mod` declarations + `pub use` re-exports + test wiring only.
4. **Owned resources stay in the orchestrator.** A transaction guard, lock, or `&mut` accumulator that spans the whole operation does NOT cross a function boundary. Phase functions take a `&` / `&mut` reference and operate within it.
5. **Moves preserve public names and signatures.** A move-only split changes no caller. A rename is a separate change.
6. **Test the seam.** When a split threads a shared resource across a boundary, the invariant that boundary could break gets a test.

Break any of these and the structure is wrong. Fix it before adding behavior.

## File → directory module

When a file grows a second concern, promote it to a directory before it sprawls:

```text
config.rs                        config/
                          →      ├── mod.rs        # mod schema; mod load; mod convert; pub use ...
                                 ├── schema.rs     # the config types
                                 ├── load.rs       # reading + parsing from disk
                                 ├── convert.rs    # runtime conversions
                                 └── tests/
                                     ├── mod.rs     # shared test helpers
                                     ├── load.rs
                                     └── convert.rs
```

- `mod.rs` stays tiny — declarations + re-exports + `#[cfg(test)] mod tests`. Never logic.

```rust
//! Configuration: schema types, runtime conversions, and file loading.
mod convert;
mod load;
mod schema;

pub use convert::*;
pub use load::*;
pub use schema::*;

#[cfg(test)]
mod tests;
```

- Re-export from the submodule; don't re-implement or re-export logic *through* `mod.rs`.
- Submodules pull the parent import surface with `use super::*;` at the top.
- Split tests by concern, one topic per file, under `tests/`. Shared helpers (temp-dir builders, fixtures) live in `tests/mod.rs`.
- The promotion is move-only: every `pub` name keeps its path so external `use` lines don't change.

## Function → orchestrator + phase functions

A long function with named phases is a thin orchestrator wearing the phases inline. Extract each phase; the original just sequences them.

```rust
// Before: one 300-line fn doing walk → parse → store → resolve inline.
// After: a thin orchestrator.
pub fn index_directory(db: &Database, root: &Path, /* ... */) -> Result<IndexResult> {
    let candidates = walk::walk_candidates(root, /* ... */);          // phase 1: pure, DB-free
    let parsed = pass::parse_candidates(&candidates, /* ... */);      // phase 2: pure, CPU-bound

    let tx = db.begin_indexing_tx()?;          // ── owned resource: stays HERE ──
    for item in parsed {
        pass::store_parsed_file(db, item, /* ... */)?;   // takes &Database, writes via *_in_tx
    }
    pass::resolve_and_finalize(db, /* ... */)?;          // joins the same tx
    tx.commit()?;                              // one all-or-nothing boundary
    Ok(result)
}
```

- **The transaction guard never crosses a function boundary.** Phase functions take `&Database` and call only `*_in_tx` helpers, so their writes join the orchestrator's transaction. A crash before `commit()` rolls back *every* phase atomically — the invariant holds by construction, not by discipline.
- The same rule covers any owned, operation-spanning resource: a `MutexGuard`, an open file, a `&mut HashSet` accumulator. Pass a reference in; keep ownership in the orchestrator.
- **Pure / CPU phases take immutable inputs and return owned data.** `walk_candidates` and `parse_candidates` touch no DB — that makes them unit-testable in isolation and safe to run on a worker pool.
- Document the invariant on the orchestrator and each phase (e.g. `// writes here join the caller's tx; a crash before commit rolls them all back`).

## Test the seam

A move-only split is not "just a move" once a shared resource crosses a new boundary — test the invariant that boundary could now break:

- A `&mut` accumulator threaded through a loop of phase calls: does it fold across **all** iterations, or get dropped/overwritten between calls? (Add a test with ≥2 items where each must contribute.)
- Partial-failure rollback: force a failure mid-pipeline and assert **every** phase rolled back, not only the first — including state written by a later phase (metadata, resolved edges), not just the obvious one.
- The existing suite must stay green with **no test edits**. Editing an assertion to make it pass means behavior changed — that is no longer a pure decomposition.

(Regression discipline mirrors normal testing: a bug exposed by a split starts with a failing test.)

## Scaffold mode (decision flow)

1. Name the unit in one sentence. If the sentence needs "and", that's your split line.
2. For a file: if it will hold >1 concern, start it as a directory module — don't wait for it to sprawl.
3. For a function: list its phases. >1 named phase → write an orchestrator + phase functions from the start.
4. Identify any resource that spans the whole operation (transaction, lock, accumulator). Decide it lives in the orchestrator before writing the phases.
5. Keep pure phases pure (immutable in, owned out); confine mutation to the orchestrator.

## Review mode

Walk `references/review-checklist.md`; cite file:line for every finding. Red flags (any one means stop and fix):

- A `mod.rs` / `lib.rs` carrying real logic instead of declarations + re-exports.
- A multi-hundred-line function with distinct named phases inlined.
- A transaction guard, lock, or `&mut` accumulator passed *into* a helper that owns it across the call (owner must stay in the orchestrator).
- A "refactor" commit that also edits test assertions (behavior changed under cover of a move).
- A move-only split that changed a public name or signature (caller churn that didn't need to happen).

## When NOT to use this skill

- Scripts under ~200 lines that won't outlive the week.
- A genuinely single-concern file or single-operation function — don't split for splitting's sake (no speculative decomposition).
- Generated code, `build.rs`, proc-macro internals.
