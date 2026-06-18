# Decomposition Review Checklist

Use this in **review mode** to audit existing Rust code for structure. For every finding, cite a file path and line number. Group findings by category. Report iron-rule violations first, then idiomatic-structure issues.

## File / module structure

- [ ] No `mod.rs` / `lib.rs` carries logic — only `mod` declarations, `pub use` re-exports, and test wiring.
- [ ] Each file holds one concern; a file mixing several large concerns is a directory module instead.
- [ ] A directory module's submodules are split by concern, not by arbitrary size.
- [ ] Re-exports come from the submodule that owns the item; the aggregator file does not re-implement.
- [ ] Tests are split by concern under `tests/`, one topic per file; shared helpers in `tests/mod.rs`.

## Function structure

- [ ] No multi-hundred-line function with distinct named phases inlined — phases are extracted.
- [ ] The original is a thin orchestrator that sequences phase functions; it holds no phase logic itself.
- [ ] Pure / CPU phases take immutable inputs and return owned data (no DB / I/O handle threaded in).
- [ ] Each phase function has a single responsibility reflected in its name.

## Owned resources (the invariant rule)

- [ ] A transaction guard, lock, or `&mut` accumulator that spans the operation lives in the orchestrator.
- [ ] No such resource is passed *into* a helper that owns it across the call — helpers take `&` / `&mut` references only.
- [ ] The all-or-nothing boundary (e.g. one transaction) is documented on the orchestrator and each phase.
- [ ] Helpers that write inside a caller's transaction use `*_in_tx`-style methods, not their own transaction.

## Move-only discipline

- [ ] A split that claims to be move-only changed no public name or signature (no caller churn).
- [ ] A "refactor" change did not edit any test assertion (edited assertions mean behavior changed).
- [ ] A rename, if needed, is a separate change from the move.

## Seam tests

- [ ] A `&mut` accumulator threaded through a loop has a test proving it folds across all iterations.
- [ ] A pipeline with rollback has a test proving a mid-pipeline failure rolls back every phase, not just the first.
- [ ] An invariant newly exposed by a split has a regression test (failing-test-first if it was a bug).

## Reporting format

For each finding:

```text
[<category>] <file>:<line>
  Rule: <quote iron rule or checklist item>
  Finding: <what the code does>
  Fix: <smallest change that resolves it>
```

Group by category in the order above. Iron-rule violations first, then structure issues, then missing seam tests.
