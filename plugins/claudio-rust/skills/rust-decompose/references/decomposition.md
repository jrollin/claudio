# Worked example: decomposing an indexer pass

A real before/after from a code-graph indexer. It shows both decomposition axes at once — a god-file split into a directory module, and a god-function split into an orchestrator + phase functions — and the one rule that makes the function split safe: **the transaction stays in the orchestrator.**

## The starting point

A single `lib.rs` held a 540-line `index_directory` function that walked a directory, parsed every file in parallel, wrote symbols to SQLite, then resolved cross-file edges — all inline, inside one open transaction. The function was correct but unreviewable: the transaction's all-or-nothing guarantee was implicit in the fact that everything happened in one scope.

Two problems:
- **File**: `lib.rs` mixed the public API, the walk filter, the parse logic, and the store/resolve logic.
- **Function**: `index_directory` named four phases (walk → parse → store → resolve) but inlined all of them.

## Step 1 — file → directory concerns

Move each concern to its own module. The crate root keeps the public surface; phases move out.

```text
crates/cartog-indexer/src/
├── lib.rs        # public API + the thin index_directory orchestrator
├── walk.rs       # WalkFilter + walk_candidates (phase 1)
├── pass.rs       # parse_candidates, store_parsed_file, resolve_and_finalize (phases 2–4)
└── tests/
    ├── mod.rs        # shared helpers (visible_dir, ...)
    ├── incremental.rs
    ├── walk_filter.rs
    └── ...           # one file per concern
```

`walk.rs` and `pass.rs` start with `use super::*;` to inherit the crate's import surface. No public name moved — external callers of `index_directory` were untouched. This is the move-only discipline: the split is invisible from outside.

## Step 2 — function → orchestrator + phase functions

Each phase becomes a named function. The four signatures, by responsibility:

```rust
// walk.rs — phase 1: pure, single-threaded, DB-free.
pub(crate) fn walk_candidates(
    root: &Path,
    force: bool,
    filter: &WalkFilter,
    changed_files: Option<&HashSet<String>>,
    stored_hashes: &HashMap<String, String>,
    result: &mut IndexResult,
) -> Candidates { /* walk + filter + git/hash skip */ }

// pass.rs — phase 2: pure, CPU-bound, runs on a rayon pool.
pub(crate) fn parse_candidates(
    candidates: &[(PathBuf, String, &'static str)],
    force: bool,
    redact: RedactionConfig,
    stored_hashes: &HashMap<String, String>,
    jobs: usize,
    emit: &(dyn Fn(ProgressUpdate) + Send + Sync),
) -> Vec<ParseOutput> { /* parse + extract, no DB writes */ }

// pass.rs — phase 3 (per file): writes inside the caller's transaction.
pub(crate) fn store_parsed_file(
    db: &Database,                       // <- borrow, not an owned tx
    /* ... */
    dirty_files: &mut HashSet<String>,   // <- accumulator owned by the orchestrator
    added_symbol_names: &mut HashSet<String>,
    result: &mut IndexResult,
) -> Result<()> { /* Merkle-diff + *_in_tx writes */ }

// pass.rs — phase 4: edge resolution + LSP + metadata, same transaction.
pub(crate) fn resolve_and_finalize(db: &Database, /* ... */) -> Result<()> { ... }
```

The orchestrator in `lib.rs` sequences them:

```rust
pub fn index_directory(db: &Database, root: &Path, /* ... */) -> Result<IndexResult> {
    let mut result = IndexResult::default();
    let candidates = walk::walk_candidates(root, force, filter, /* ... */, &mut result);
    let parsed = pass::parse_candidates(&candidates, force, redact, /* ... */, &emit);

    let tx = db.begin_indexing_tx()?;        // ── the owned resource lives HERE ──
    let mut dirty_files = HashSet::new();
    let mut added_symbol_names = HashSet::new();
    for item in parsed {
        pass::store_parsed_file(db, item, /* ... */, &mut dirty_files,
                                &mut added_symbol_names, &mut result)?;
    }
    pass::resolve_and_finalize(db, &dirty_files, /* ... */)?;
    tx.commit()?;                            // one atomic boundary for phases 3–4
    Ok(result)
}
```

## The rule that makes it safe

The transaction guard `tx` is created in the orchestrator and **never passed into a phase function**. Phases 3 and 4 take `&Database` and call only `*_in_tx` helpers, so every write joins the orchestrator's open transaction. A crash before `tx.commit()` rolls back *all* of phases 3 and 4 together.

If `store_parsed_file` had instead taken ownership of the transaction (or opened its own), the atomicity guarantee would have shattered into per-call transactions — a partial index could commit. Keeping the owned resource in the orchestrator preserves the invariant **by construction**, so no reviewer has to reason about it.

The same shape applies to the `&mut dirty_files` / `&mut added_symbol_names` accumulators: owned by the orchestrator, threaded into each `store_parsed_file` call by reference, so they fold across every iteration of the loop.

## The seam tests this split required

The decomposition was move-only, but two invariants now crossed function boundaries, so two tests were added:

1. **Accumulator folds across files.** Two new files added in one pass, each defining a symbol a distinct pending edge was waiting on — assert *both* edges reopen. This proves `&mut added_symbol_names` accumulates across the per-file loop and isn't dropped between calls.

2. **Rollback spans every phase.** Force a disk-full failure mid-store, then assert not only that symbol writes rolled back, but that **phase-4 state** (metadata, the seed file's symbol count) is byte-identical to before the failed run. This proves the transaction still wraps phases 3 *and* 4 as one unit after the split — the exact invariant the function boundary could have broken.

Both tests pass against the pre-split behavior too (they describe the invariant, not the new structure), and the rest of the suite stayed green with no edits — confirming the split changed structure, not behavior.
