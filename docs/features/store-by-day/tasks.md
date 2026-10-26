# Store By Day: Tasks

---
feature: store-by-day
spec_version: 1
total_tasks: 8
phases:
  - name: "Day layer"
    tasks: [T-1, T-2, T-3, T-4]
  - name: "Lookup and prune"
    tasks: [T-5, T-6]
  - name: "Closed-day reuse"
    tasks: [T-7, T-8]
depends_on: [provider-store]
---

Paths are under `plugins/claudio-routines/` unless they start with `docs/`. Verify commands run from the repository root.

## Phase 1: Day layer

### T-1: Slack day hooks
- **Scope**:
  - `DAY_KINDS` and `day_row` in `_slack_reads`, exposed by `slack.py`
  - Conformance: an adapter with one hook has both
- **Refs**: US-1, TD-10
- **Files**: `runtime/providers/_slack_reads.py` (modify), `runtime/providers/slack.py` (modify), `runtime/providers/test_conformance.py` (modify)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime/providers -p 'test_conformance.py'`
- **Rules**: BR-1, BR-3
- **Status**: Complete

### T-2: Merge a read into its day folders
- **Scope**:
  - `DayLayer.merge(folder, document)`: day of each row in UTC, same-fetch drop, newest wins per key, snapshot replace, rows ordered
  - Coverage per transport, clipped and merged; coverage-only days for spanned kinds
  - Lock, records then coverage, folders 0700, files 0600
  - Tests: day boundary, two overlapping reads, older fetch dropped, same fetch replaces, publish order independence, partial and failed ignored, members and users ignored
- **Refs**: US-1, US-2, US-3, TD-1, TD-2, TD-3, TD-4, TD-5
- **Files**: `runtime/days.py` (new), `runtime/test_days.py` (new)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_days.py'`
- **Blocked by**: T-1
- **Rules**: BR-1, BR-2, BR-3, BR-4, BR-9
- **Status**: Complete

### T-3: Publish hook
- **Scope**:
  - `ReadSession(..., days=None)`; `publish` hands complete reads to `days.merge`; a merge failure prints to stderr and never fails the read
  - `collect.py` builds the `DayLayer` when `store_dir` is set
  - Tests: publish merges, no `store_dir` writes no `days/`, read folders unchanged
- **Refs**: US-1, TD-3
- **Files**: `runtime/store.py` (modify), `runtime/test_store.py` (modify), `runtime/collect.py` (modify), `runtime/test_collect.py` (modify)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_store.py'`
- **Blocked by**: T-2
- **Rules**: BR-4, BR-10
- **Status**: Complete

### T-4: `days.py build`
- **Scope**:
  - Walk complete reads under the root, filtered as `reparse` filters, merge each; print counts per provider and kind
  - Tests: backfill, idempotent bytes, after a reparse, bad root exits 2
- **Refs**: US-4, TD-8
- **Files**: `runtime/days.py` (modify), `runtime/test_days.py` (modify)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_days.py'`
- **Blocked by**: T-2
- **Rules**: BR-4
- **Status**: Complete

## Phase 2: Lookup and prune

### T-5: `days.py show`
- **Scope**:
  - Coverage per provider, kind and entity for a date or an inclusive range: `full`, `partial` with gaps, snapshot time
  - `--provider`, `--kind`, `--channel`, `--records`
  - Tests: full, partial gaps, never read absent, range, bad dates exit 2
- **Refs**: US-5, TD-8
- **Files**: `runtime/days.py` (modify), `runtime/test_days.py` (modify)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_days.py'`
- **Blocked by**: T-2
- **Rules**: BR-1
- **Status**: Complete

### T-6: `days.py prune`
- **Scope**:
  - Delete day folders whose day ended more than N days ago; `--dry-run`; empty parents removed
  - Tests: age by folder day, dry run, `store.py prune` leaves `days/` alone, linked run copy survives
- **Refs**: US-7, TD-8
- **Files**: `runtime/days.py` (modify), `runtime/test_days.py` (modify)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_days.py'`
- **Blocked by**: T-2
- **Rules**: BR-8
- **Status**: Complete

## Phase 3: Closed-day reuse

### T-7: `closed_days` config key
- **Scope**:
  - `roles.py` chat key, boolean; `Freshness.closed_days`; `counted` reports reads when on
  - Tests: accepted, non-boolean fails naming the path
- **Refs**: US-6, TD-9
- **Files**: `runtime/roles.py` (modify), `runtime/test_roles.py` (modify), `runtime/collect.py` (modify), `runtime/providers/slack.py` (modify)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_roles.py'`
- **Status**: Complete

### T-8: Reuse closed days in the gap fill, replayable
- **Scope**:
  - `DayLayer.reuses`, `ReadSession.closed_days` linking into the run store, `ReplaySession.closed_days` from recorded copies
  - `Reuse.spans`; `_Reads._reused` adds day reuses for `history` and `thread`
  - Tests: fully covered closed day makes no call, partial fetches gaps, current day keeps `max_age`, `api` source skips `mcp` rows, replay of a run that reused days, docs updated
- **Refs**: US-6, TD-6, TD-7
- **Files**: `runtime/days.py` (modify), `runtime/store.py` (modify), `runtime/providers/_slack_reads.py` (modify), `runtime/providers/test_slack_reads.py` (modify), `README.md` (modify), `runtime/providers/README.md` (modify)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-3, T-7
- **Rules**: BR-5, BR-6, BR-7
- **Status**: Complete

## Related Features

- **provider-store**: the read folders, `ReadSession`, `publish`, `eligible`, replay and `prune`
  - **Shared state**: `<store_dir>`, `<run>/store`, `<run>/manifest.json` `reads` list, `Reuse`
  - **Risk**: a change of the read layout or of `publish` breaks the merge hook; a manifest reader that expects only `provider=` paths sees `days/` entries
- **routines-as-code**: chat source config keys and the run record `reads` counts
  - **Shared state**: `roles.py` chat schema, `collected.<source>.reads`
  - **Risk**: a schema change dropping unknown keys would silently disable `closed_days`
