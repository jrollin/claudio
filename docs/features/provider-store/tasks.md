# Provider Store: Tasks

---
feature: provider-store
spec_version: 1
total_tasks: 18
phases:
  - name: "Entity layout in the run folder"
    tasks: [T-1, T-2, T-3, T-4, T-5, T-6, T-7, T-8, T-9, T-10]
  - name: "Shared local store"
    tasks: [T-11, T-12, T-13, T-14, T-15, T-16, T-17, T-18]
depends_on: [routines-as-code]
---

Paths are under `plugins/claudio-routines/` unless they start with `docs/` or `scripts/`. Verify commands run from the repository root. Phase 1 ships as its own release before phase 2 starts (T-11 waits on T-10).

## Phase 1: Entity layout in the run folder

### T-1: Create the run store and the read folder format
- **Scope**:
  - `ReadSession` over a run store root: `open`, `page`, `finish`, hive folder names from kind, entity keys and span (TD-2, TD-13)
  - `finish` writes `records.jsonl`, then `read.json`, each by an atomic rename; folders 0700, files 0600
  - Folders without `read.json` are skipped by every listing; `<run>/manifest.json` merges one source at a time
  - Tests: a read interrupted before `read.json`, two sources asking the same read get two folders, canonical JSON and JSON lines bytes
- **Refs**: US-1, US-2, US-3, TD-1, TD-2, TD-4, TD-13
- **Files**: `runtime/store.py` (new), `runtime/test_store.py` (new)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_store.py'`
- **Rules**: BR-1, BR-2, BR-3
- **Status**: Complete
- **Result**: `store.py` with `ReadSession`, `ReadHandle`, read listing and `write_manifest`; 38 passing tests, full runtime suite (5497) green

### T-2: Make the Slack page parsers depend on the read alone
- **Scope**:
  - Move-only refactor: page parsers take the read's arguments and `to`, never the window (TD-3)
  - `_in_window` and the hit `_within` filter move to collection assembly in `slack.py`
  - No test file changes: the existing suites prove the move
- **Refs**: US-2, TD-3
- **Files**: `runtime/providers/_slack_read.py` (modify), `runtime/providers/_slack_search.py` (modify), `runtime/providers/slack.py` (modify)
- **Verify**: `git diff --quiet -- plugins/claudio-routines/runtime/providers/test_slack.py plugins/claudio-routines/runtime/providers/test_slack_search.py && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_slack*.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_*pipeline.py'`
- **Rules**: BR-4
- **Status**: Complete
- **Result**: page parsers and read filters take the read's span (`_in_span`, `to`), the walk keeps deriving start, `to` and the cited oldest from the window; `slack.py` needed no change; 383 Slack tests and 56 pipeline tests green with no test file edited

### T-3: Define the Slack read kinds and `parse_read`
- **Scope**:
  - The 6 kinds of BR-1 with their entity keys, spans and record fields; records drop the values their path holds and loading adds them back
  - Entity id and ts patterns before any path part; a search name percent-encoded with no safe character
  - `parse_read(kind, read, pages)` over the T-2 page parsers, reading pages in order with read-scoped state
  - Tests: forged ids from tool text refused (`invalid entity id`), a search name holding `/`, thread pages newest first, a parser rejection marks the read failed
- **Refs**: US-1, US-2, TD-2, TD-3, TD-13
- **Files**: `runtime/providers/_slack_reads.py` (new), `runtime/providers/test_slack_reads.py` (new)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_slack_reads.py'`
- **Blocked by**: T-1, T-2
- **Rules**: BR-1, BR-2
- **Status**: Complete
- **Result**: `_slack_reads.py` with read keys, id checks, JSON lines rows and `parse_read` for both transports; the API page parsers of `_slack_read.py` and `_slack_search.py` extracted move-only; 48 passing tests, Slack and pipeline suites unchanged and green

### T-4: Route the Slack channel reads through the session
- **Scope**:
  - `slack.py` declares `STORE = True` and exposes `parse_read`; `fetch`, `plan` and `parse` take a session
  - Channel history, root replies and cited threads open one read each; collections assemble from records
  - `slack_support.py` gains an in-memory session that serves the existing fixture pages by read
  - Tests: the same fixtures give byte-identical collections, failed channels and cited threads keep their failed entries, call caps unchanged
- **Refs**: US-1, US-3, TD-4
- **Files**: `runtime/providers/_slack_read.py` (modify), `runtime/providers/slack.py` (modify), `runtime/providers/slack_support.py` (modify), `runtime/providers/test_slack.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_slack.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_*pipeline.py'`
- **Blocked by**: T-3
- **Rules**: BR-4, BR-5
- **Status**: Complete
- **Result**: one `_channel_read` walk over `RelayReads` and `ApiReads` (search conversations included), each history, root-replies and cited-thread read filed and finished in the session; `slack.py` declares `STORE` and `parse_read`, and wraps a responses dict or HTTP client in `CallOrderSession` or `LiveSession` until `collect.py` passes sessions (T-6); 18 new store-backed tests, the 236 existing Slack tests unedited and green, full runtime suite (5564) green

### T-5: Route the Slack search reads through the session
- **Scope**:
  - Searches, conversations, threads, members, user lookups and reactions each open one read
  - Rereads and known threads keep their read starts (US-59 of routines-as-code)
  - Conformance: a store-backed adapter exposes `parse_read`
  - Tests: byte-identical units on the existing fixtures, failed reactions and missing threads keep their keys, `call_cap` counts unchanged
- **Refs**: US-1, US-3, TD-4
- **Files**: `runtime/providers/_slack_search.py` (modify), `runtime/providers/test_slack_search.py` (modify), `runtime/providers/test_conformance.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_slack_search.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_conformance.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_*pipeline.py'`
- **Blocked by**: T-4
- **Rules**: BR-4
- **Status**: Complete
- **Result**: searches, unit threads, members, user lookups and reactions each open one read through `RelayReads` or `ApiReads`, the readers keep the window and channel-type filters, and an id that fails its check fails only its read (`invalid entity id`); the old relay and API pagers are removed; 15 new tests, the 116 existing search tests unedited and green, full runtime suite (5579) green

### T-6: Wire the read sessions into `collect.py`
- **Scope**:
  - `--run` replaces `--responses` on `fetch`, `plan` and `parse`; other adapters derive `<run>/raw/<role>/<source>/` from it
  - Store-backed adapters get a session on `<run>/store`; relay files move to `<run>/relay/<source>/`
  - Each planned call carries its absolute `path`; the capture pick-up writes there; the `relay capture mismatch` line stays
  - The collection's reads are added to `<run>/manifest.json`
  - `slack.py` drops the bridge that wraps a responses dict or HTTP client; `CallOrderSession` and `LiveSession` move to `slack_support.py` (owner, 2026-10-20)
  - Tests: a missed capture saved by hand at `path`, a plan not done, a call cap reached, a non-Slack source unchanged
- **Refs**: US-1, US-3, TD-4, TD-5
- **Files**: `runtime/collect.py` (modify), `runtime/test_collect.py` (modify), `runtime/providers/slack.py` (modify), `runtime/providers/_slack_reads.py` (modify), `runtime/providers/slack_support.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_collect.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_relay_capture.py'`
- **Blocked by**: T-5
- **Rules**: BR-3, BR-4
- **Status**: Complete
- **Result**: `fetch`, `plan` and `parse` take `--run`; store-backed adapters get a `ReadSession` on `<run>/store` with relay files in `<run>/relay/<source>/`, the others keep `<run>/raw/<role>/<source>/`; every planned call carries its absolute `path`, the pick-up writes there, the mismatch line stays, and each store-backed collection writes its reads to `manifest.json`; the store reads pages with the response guards (no link, regular file, 10 MB cap); the `slack.py` bridge is gone and the call-order and live sessions live in `slack_support.py`; 11 new collect tests and 5 new store tests, full runtime suite (5595) green

### T-7: Replay a run read by read
- **Scope**:
  - `replay --run` builds a replay session on `<run>/store`, bound to the manifest, with no network and no shared store
  - `api` reads serve their pages through `ReplayClient`; connector reads compare each asked request with `read.json`
  - Tests: byte-identical collections, a read missing from the manifest (exit 3), a changed request (exit 3), no manifest (exit 2), other roles unchanged
- **Refs**: US-5, TD-12
- **Files**: `runtime/collect.py` (modify), `runtime/test_collect.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_collect.py'`
- **Blocked by**: T-6
- **Rules**: BR-2
- **Status**: Complete
- **Result**: `replay` takes `--run`; a store-backed source replays through a `ReplaySession` bound to the manifest that serves the run's pages, compares every asked request with `read.json` (exit 3 naming the read, call number and differing fields, never a value) and writes nothing into the run; the manifest is required only when a store-backed source is replayed (exit 2 without it); 8 new store tests and 6 new collect tests, full runtime suite (5619) green

### T-8: Add the reparse command
- **Scope**:
  - `store.py reparse --root` with provider, channel, thread, kind and time range filters, combined with AND
  - Loads the adapter named in `read.json`; rewrites `records.jsonl` then `read.json`; prints `changed` or `same` per read
  - Tests: an unchanged parser changes no byte, a rejected read exits 3 and the others still reparse, no match exits 2, no network and no environment read
- **Refs**: US-4, TD-11
- **Files**: `runtime/store.py` (modify), `runtime/test_store.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_store.py'`
- **Blocked by**: T-1, T-4
- **Rules**: BR-2, BR-3
- **Status**: Complete
- **Result**: `store.py reparse --root` with `--provider`, `--channel`, `--thread`, `--kind`, `--from` and `--to` combined with AND over complete reads; it rewrites `records.jsonl`, then `read.json` when the records or the runtime commit changed, prints `same`, `changed` or `rejected` per read and the counts, leaves a rejected read untouched and exits 3, and exits 2 on no match; `runtime_commit` moves to `store.py` and `slack.py` exposes `to_rows`; 16 new tests, full runtime suite green

### T-9: Switch the templates to `--run` and the call's save path
- **Scope**:
  - Every `collect.py` command takes `--run <run>`
  - The hand-save fallback saves a missed capture at the call's `path`
  - `tribe.py publish-plan` keeps its own `--responses`
- **Refs**: US-1, TD-5
- **Files**: `skills/routines/templates/prod-watch.md` (modify), `skills/routines/templates/tribe-digest.md` (modify), `skills/routines/templates/chat-recap.md` (modify), `skills/routines/templates/weekly-status.md` (modify)
- **Verify**: `! grep -rnE 'collect\.py (fetch|plan|parse|replay).*--responses' plugins/claudio-routines/skills/routines/templates && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public`
- **Blocked by**: T-6
- **Status**: Complete
- **Result**: the 4 templates pass `--run <run>` to `fetch`, `plan` and `parse`, the hook and the hand-save fallback save at the call's `path` (creating its folder first, Write tool rule kept), and the `<role>` substitution is gone; `tribe.py publish-*` keep `--responses`; the template text tests of `test_routines.py` follow; 782 routines tests and `lint --public` green

### T-10: Document the entity layout
- **Scope**:
  - Plugin README: the store layout, `--run`, the save path, read-by-read replay, the reparse command, the DuckDB query
  - Providers README: saved responses, recorded and replayed calls per read, the Slack read layout
  - routines-as-code AC-51.1 and AC-51.4 point to this spec for chat sources
- **Refs**: US-1, US-4, US-5, TD-5, TD-13
- **Files**: `README.md` (modify), `runtime/providers/README.md` (modify), `docs/features/routines-as-code/requirements.md` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_conformance.py' && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-7, T-8, T-9
- **Status**: Not Started

## Phase 2: Shared local store

### T-11: Add `store_dir` and `max_age` to the config
- **Scope**:
  - `places.<place>.store_dir` with the path rules of `runs_dir`, in the runtime config check and in `routines.py`
  - Chat source `max_age`: an integer of minutes or the TD-9 object; a search named `.` or `..` fails the load
  - Collection schema accepts an optional `reads`
  - Tests: negative and non-integer `max_age`, an unknown kind key, a relative `store_dir`, error messages naming the key path and never a value
- **Refs**: US-6, US-7, TD-9, TD-10
- **Files**: `runtime/roles.py` (modify), `runtime/test_roles.py` (modify), `skills/routines/scripts/routines.py` (modify), `skills/routines/scripts/test_routines.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_roles.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts`
- **Blocked by**: T-10
- **Rules**: BR-6, BR-11
- **Status**: Not Started

### T-12: Share reads through `store_dir`
- **Scope**:
  - The session links reused reads into `<run>/store` and publishes new ones through `.incoming/` and a rename (TD-6), copying on `EXDEV` or `EPERM`
  - `collect.py sources` refuses a `store_dir` inside a git working tree, a link, or another user's folder (exit 2)
  - Tests: two sessions publishing at once, a partial `.incoming/` folder never listed, a prune-like deletion after linking leaves the run store intact, provider keys isolated
- **Refs**: US-6, TD-6
- **Files**: `runtime/store.py` (modify), `runtime/test_store.py` (modify), `runtime/collect.py` (modify), `runtime/test_collect.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_store.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_collect.py'`
- **Blocked by**: T-7, T-8, T-11
- **Rules**: BR-3, BR-6, BR-12
- **Status**: Not Started

### T-13: Reuse fresh reads and fetch only the gaps
- **Scope**:
  - `session.eligible` applies TD-7; interval gaps on decimal ts (TD-8); records merge by ts, newest fetch winning
  - The Slack history and thread helpers fill gaps; reactions, members and users reuse by kind; searches never reuse
  - A read whose `parsed_by` differs is reparsed from its pages before use
  - Tests: a read fetched after the window end by another run is ignored, an `api` source skips a connector read, failed and partial reads refetched, `max_age` 0 gives phase 1 bytes, a source never reuses its own reads, adjacent and overlapping spans
- **Refs**: US-7, TD-7, TD-8
- **Files**: `runtime/store.py` (modify), `runtime/test_store.py` (modify), `runtime/providers/_slack_reads.py` (modify), `runtime/providers/test_slack_reads.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_store.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_slack*.py'`
- **Blocked by**: T-12
- **Rules**: BR-5, BR-7, BR-8, BR-9, BR-11, BR-12, BR-13
- **Status**: Not Started

### T-14: Count fetched and reused reads in collections
- **Scope**:
  - `collect.py` adds `reads` from the session's counts when the source's `max_age` is above 0 for some kind (TD-10)
  - Reused reads spend no call against `call_cap`, `search_page_cap` or the page caps
  - Tests: no `reads` key with `max_age` unset or 0, counts after a full reuse, a partial reuse and none
- **Refs**: US-7, TD-10
- **Files**: `runtime/collect.py` (modify), `runtime/test_collect.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_collect.py'`
- **Blocked by**: T-13
- **Rules**: BR-13
- **Status**: Not Started

### T-15: Carry the reuse counts into run records
- **Scope**:
  - `evaluate.run_context` copies `reads` into `collected.<source>`; the run context spec accepts it as optional
  - Tests: a record with and without `reads`, a state file never storing the run context
- **Refs**: US-7, TD-10
- **Files**: `runtime/evaluate.py` (modify), `runtime/state.py` (modify), `runtime/test_evaluate.py` (modify), `runtime/test_state.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_evaluate.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_state.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_*pipeline.py'`
- **Blocked by**: T-14
- **Status**: Not Started

### T-16: Carry the reuse counts into the weekly record
- **Scope**:
  - Weekly source rows and the weekly run record keep `reads` when the collection has it
  - Tests: a weekly record with and without `reads`, a source with no collection
- **Refs**: US-7, TD-10
- **Files**: `runtime/weekly_features.py` (modify), `runtime/weekly.py` (modify), `runtime/test_weekly.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_weekly*.py'`
- **Blocked by**: T-14
- **Status**: Not Started

### T-17: Add the prune command
- **Scope**:
  - `store.py prune --root --older-than-days N [--dry-run]` deletes whole read folders by `fetched_at`, and `.incoming/` leftovers by age
  - Tests: a run store keeping its linked reads after a prune, `--dry-run` deleting nothing, an age of 0 or a non-integer exiting 2, counts per provider
- **Refs**: US-8, TD-6
- **Files**: `runtime/store.py` (modify), `runtime/test_store.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime -p 'test_store.py'`
- **Blocked by**: T-13
- **Rules**: BR-10
- **Status**: Not Started

### T-18: Document the shared store
- **Scope**:
  - Plugin README: `store_dir`, `max_age`, reuse and the trust rule, `prune`, the reuse counts in records, Troubleshooting rows
  - Providers README: reuse of Slack reads per kind
  - Example config: `store_dir` on the local place, a `max_age` object on the recap routine
- **Refs**: US-6, US-7, US-8, TD-7, TD-9
- **Files**: `README.md` (modify), `runtime/providers/README.md` (modify), `example/config.json` (modify), `example/config/routines/chat-recap.json` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-15, T-16, T-17
- **Status**: Not Started

## Related Features

- **routines-as-code**: this spec changes how its collectors file and replay chat sources.
  - **Shared state**: the raw layout `<run>/raw/<role>/<source>/`, the relay protocol (`calls.json`, `planned.json`, `<source>-<n>` ids), the capture pick-up (US-60) and the replay of US-51.
  - **Risk**: a relay change for Slack that leaks into the other adapters' ids or folders; T-6 keeps their tests unchanged.
- **Private repository templates**: the `<name>-runtime.md` copies must equal the public templates at the pinned runtime commit.
  - **Shared state**: the `collect.py` flags in the 4 templates (T-9).
  - **Risk**: a routine synced with a template that still passes `--responses` fails against a runtime past T-6; bump the runtime tag, copy the templates and sync each routine together, per the plugin README bump procedure.
- **Live tribe and recap states**: their cursors, threads and units feed the Slack walk.
  - **Shared state**: `cursors.<source>`, `threads`, `units.*.last_ts`, `owner_last_ts`.
  - **Risk**: none while BR-4 holds; a collection that differs by one byte moves a cursor or a unit status on the next posting run.
