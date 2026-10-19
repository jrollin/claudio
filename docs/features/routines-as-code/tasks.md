# Routines as Code: Tasks

---
feature: routines-as-code
spec_version: 1
total_tasks: 74
phases:
  - name: "Leak guard"
    tasks: [T-1, T-2, T-3]
  - name: "State engine"
    tasks: [T-4, T-5, T-6]
  - name: "Routine tooling"
    tasks: [T-7, T-8, T-9, T-10, T-11, T-12]
  - name: "Integration and rollout"
    tasks: [T-13, T-14, T-15, T-16]
  - name: "State store and neutral roles"
    tasks: [T-17, T-18]
  - name: "Collectors over provider APIs"
    tasks: [T-19, T-20, T-21, T-22, T-23, T-24, T-25, T-26]
  - name: "Relay through connectors"
    tasks: [T-27, T-28, T-29]
  - name: "Local runs and the Prod watch template"
    tasks: [T-30, T-31]
  - name: "Chat channel and code host adapters"
    tasks: [T-32, T-33]
  - name: "Model judgment"
    tasks: [T-34, T-35, T-36, T-37, T-38, T-39, T-40, T-41, T-42, T-43, T-44, T-45]
  - name: "Config split and mirrors"
    tasks: [T-46, T-47, T-48, T-49, T-50, T-51, T-52]
  - name: "Tribe digest collectors"
    tasks: [T-53, T-54, T-55, T-56, T-57, T-58, T-59]
  - name: "Tribe judgment"
    tasks: [T-60, T-61, T-62, T-63, T-64, T-65, T-66, T-67, T-68, T-69]
  - name: "Empty reads as zero"
    tasks: [T-70]
  - name: "Monitor event aggregates"
    tasks: [T-71]
  - name: "Monitor priority and seed fixes"
    tasks: [T-72, T-73, T-74]
depends_on: []
---

## Phase 1: Leak guard

### T-1: Create the leak scanner with tree and staged modes
- **Refs**: US-1, US-2, TD-1, TD-2, TD-3
- **Files**: `scripts/leak_check.py` (new), `scripts/test_leak_check.py` (new)
- **Verify**: `python3 -m unittest discover -s scripts -p 'test_leak_check.py'`
- **Rules**: BR-1, BR-2, BR-17
- **Status**: Complete

### T-2: Add the history mode and the allowlist
- **Refs**: US-1, US-3, TD-1, TD-4
- **Files**: `scripts/leak_check.py` (modify), `scripts/test_leak_check.py` (modify), `scripts/leak-allow.txt` (new)
- **Verify**: `python3 -m unittest discover -s scripts -p 'test_leak_check.py' && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-1
- **Rules**: BR-2, BR-3
- **Status**: Complete

### T-3: Add the pre-commit hook, the hook installer and the protection check
- **Refs**: US-1, US-2, TD-5
- **Files**: `.githooks/pre-commit` (new), `.githooks/pre-merge-commit` (new), `.githooks/commit-msg` (new), `scripts/install-hooks.sh` (new), `scripts/check_protection.py` (new), `scripts/test_hooks.py` (new)
- **Verify**: `python3 -m unittest discover -s scripts -p 'test_hooks.py'`
- **Blocked by**: T-1
- **Rules**: BR-4, BR-17
- **Status**: Complete

## Phase 2: State engine

### T-4: Compute the run window and hour buckets
- **Refs**: US-10, TD-13, TD-14, TD-16
- **Files**: `plugins/claudio-routines/runtime/state.py` (new), `plugins/claudio-routines/runtime/test_state.py` (new)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Rules**: BR-13, BR-20, BR-21
- **Status**: Complete

### T-5: Validate state and facts, and apply the item lifecycle
- **Refs**: US-9, TD-13
- **Files**: `plugins/claudio-routines/runtime/state.py` (modify), `plugins/claudio-routines/runtime/test_state.py` (modify)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-4
- **Rules**: BR-9, BR-10, BR-11, BR-14, BR-16
- **Status**: Complete

### T-6: Apply blind spots and mutes
- **Refs**: US-9, TD-13
- **Files**: `plugins/claudio-routines/runtime/state.py` (modify), `plugins/claudio-routines/runtime/test_state.py` (modify)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-5
- **Rules**: BR-12, BR-18, BR-19, BR-21
- **Status**: Complete

## Phase 3: Routine tooling

### T-7: Create the plugin scaffold, the config example and the marketplace entry
- **Refs**: US-5, TD-6, TD-11
- **Files**: `plugins/claudio-routines/.claude-plugin/plugin.json` (new), `plugins/claudio-routines/config.example.json` (new), `.claude-plugin/marketplace.json` (modify)
- **Verify**: `python3 -c "import json; d=json.load(open('.claude-plugin/marketplace.json')); assert any(p['name']=='claudio-routines' for p in d['plugins']); json.load(open('plugins/claudio-routines/config.example.json'))" && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-2
- **Rules**: BR-1
- **Status**: Complete

### T-8: Check the private path and export live routines into snapshots
- **Refs**: US-4, TD-8, TD-9, TD-10
- **Files**: `plugins/claudio-routines/skills/routines/scripts/routines.py` (new), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (new)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts`
- **Blocked by**: T-7
- **Rules**: BR-1
- **Status**: Complete

### T-9: Render templates and the environment setup script
- **Refs**: US-5, US-11, TD-7, TD-11, TD-15
- **Files**: `plugins/claudio-routines/skills/routines/scripts/routines.py` (modify), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify), `plugins/claudio-routines/skills/routines/templates/setup-env.sh` (new)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts`
- **Blocked by**: T-8
- **Rules**: BR-15
- **Status**: Complete

### T-10: Diff rendered routines against snapshots and build the update body
- **Refs**: US-6, US-8, TD-12
- **Files**: `plugins/claudio-routines/skills/routines/scripts/routines.py` (modify), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts`
- **Blocked by**: T-9
- **Rules**: BR-5, BR-7
- **Status**: Complete

### T-11: Lint templates and write the public Prod watch skeleton
- **Refs**: US-7, TD-16
- **Files**: `plugins/claudio-routines/skills/routines/scripts/routines.py` (modify), `plugins/claudio-routines/skills/routines/scripts/lint.py` (new), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify), `plugins/claudio-routines/skills/routines/templates/prod-watch.md` (new)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public`
- **Blocked by**: T-6, T-10
- **Rules**: BR-8
- **Status**: Complete

### T-12: Write the /routines skill
- **Refs**: US-4, US-5, US-6, US-7, US-8, TD-8, TD-10, TD-12
- **Files**: `plugins/claudio-routines/skills/routines/SKILL.md` (new)
- **Verify**: `python3 scripts/leak_check.py --tree && grep -q 'explicit approval' plugins/claudio-routines/skills/routines/SKILL.md && grep -q 'RemoteTrigger' plugins/claudio-routines/skills/routines/SKILL.md && grep -q 'check-private' plugins/claudio-routines/skills/routines/SKILL.md`
- **Blocked by**: T-10, T-11
- **Rules**: BR-6, BR-7
- **Status**: Complete

## Phase 4: Integration and rollout

### T-13: Add the CI workflow and ignore Python caches
- **Refs**: US-2, US-7, TD-3
- **Files**: `.github/workflows/ci.yml` (new), `scripts/test_ci.py` (new), `.gitignore` (modify)
- **Verify**: `python3 -m unittest discover -s scripts -p 'test_ci.py'`
- **Blocked by**: T-3, T-6, T-11
- **Rules**: BR-4, BR-17
- **Status**: Complete

### T-14: Document setup, usage and the runtime bump procedure
- **Refs**: US-1, US-2, US-11, TD-5, TD-8, TD-11, TD-15
- **Files**: `plugins/claudio-routines/README.md` (new), `README.md` (modify)
- **Verify**: `python3 scripts/leak_check.py --tree`
- **Blocked by**: T-12, T-13
- **Rules**: BR-1, BR-4, BR-15
- **Status**: Complete

### T-15: Scaffold the private repository and prove Prod watch renders in sync
Run `/routines export` first, with `CLAUDIO_PRIVATE_DIR` pointing at the private repository. The private template reproduces the live prompt, so the diff proves the render pipeline without changing the routine.
- **Refs**: US-4, US-5, US-6, TD-8, TD-11
- **Files**: none in this repository; the private repository gets `config.json`, `templates/prod-watch.md`, `templates/prod-watch-runtime.md` and `routines/` snapshots
- **Verify**: `python3 plugins/claudio-routines/skills/routines/scripts/routines.py diff prod-watch`
- **Blocked by**: T-11, T-14
- **Rules**: BR-5
- **Status**: Complete

### T-16: Roll out the runtime to Prod watch
Owner-gated: needs the merged pull request, a release tag, the setup script pasted into the default environment, and an approved sync.
1. Set `runtime.tag` and `runtime.sha` in the private config.
2. Paste the `setup-script` output into the default environment.
3. Attach the private repository to the Prod watch routine as a source, and set `places.cloud.state_dir` to its checkout path in the run session.
4. For each `api` source of the cloud place, set its credential variables in the environment's settings, and allow its hosts in the environment's network settings (`providers/README.md`).
5. Seed `state/prod-watch.json` on the `claude/state` branch from the current state page: rename its provider-named cursor key to `cursors.observability`, drop the free-text `reason` of items (the runtime stores a list of tagged claims) and the blind spots without a key, then check it with `state.py validate`.
6. Switch `routines.prod-watch.template` to `prod-watch-runtime`; the live routine changes only at the sync.
7. Run `/routines run prod-watch` without `--post`, right after a live run with `--since` its window start, so both read the same window: the record reaches `claude/state`, the state does not change, the digest is printed. Compare it with the live run, and repeat over a few days.
8. Run `/routines sync prod-watch`.
- **Refs**: US-8, US-11, TD-12, TD-15
- **Files**: none in this repository; the private repository's `config.json` changes
- **Verify**: `python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --private "$CLAUDIO_PRIVATE_DIR" && python3 plugins/claudio-routines/skills/routines/scripts/routines.py diff prod-watch`
- **Blocked by**: T-15, T-17, T-18, T-31, T-43
- **Rules**: BR-6, BR-7, BR-15, BR-23, BR-25
- **Status**: In Progress (synced to the runtime on 2026-10-19 after an aligned shadow run: 22 of 26 live items matched, the other 4 explained by timing and by the runtime keeping an open item's severity; first runtime runs to check)

## Phase 5: State store and neutral roles

### T-17: Add the explicit window and the run record to the state engine
- **Refs**: US-9, US-10, US-12, TD-13, TD-14, TD-17
- **Files**: `plugins/claudio-routines/runtime/state.py` (modify), `plugins/claudio-routines/runtime/test_state.py` (modify)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-6
- **Rules**: BR-14, BR-22, BR-23
- **Status**: Complete

### T-18: Store state on the private branch and name roles, not providers
- **Refs**: US-4, US-5, US-7, US-12, TD-8, TD-10, TD-11, TD-16, TD-17
- **Files**: `plugins/claudio-routines/skills/routines/scripts/routines.py` (modify), `plugins/claudio-routines/skills/routines/scripts/lint.py` (modify), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify), `plugins/claudio-routines/skills/routines/templates/prod-watch.md` (modify), `plugins/claudio-routines/config.example.json` (modify), `plugins/claudio-routines/runtime/state.py` (modify: `init`), `plugins/claudio-routines/runtime/test_state.py` (modify)
- **Verify**: `python3 -m unittest discover -s plugins/claudio-routines/runtime && python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public`
- **Blocked by**: T-17
- **Rules**: BR-1, BR-8, BR-23
- **Status**: Complete

## Phase 6: Collectors over provider APIs

### T-19: Hold deferred keys, keep mutes, add the report-only window and the run context
- **Refs**: US-9, US-10, US-13, US-16, TD-13, TD-24
- **Files**: `plugins/claudio-routines/runtime/state.py` (modify), `plugins/claudio-routines/runtime/test_state.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-18
- **Rules**: BR-14, BR-22, BR-32
- **Status**: Complete

### T-20: Validate role records, the collector config and the query pack
- **Refs**: US-13, US-14, US-17, TD-18, TD-19, TD-23
- **Files**: `plugins/claudio-routines/runtime/roles.py` (new), `plugins/claudio-routines/runtime/test_roles.py` (new)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Rules**: BR-24, BR-25, BR-29, BR-31
- **Status**: Complete

### T-21: Add the HTTPS client and the adapter lookup
- **Refs**: US-14, TD-20, TD-22
- **Files**: `plugins/claudio-routines/runtime/providers/__init__.py` (new), `plugins/claudio-routines/runtime/providers/_http.py` (new), `plugins/claudio-routines/runtime/providers/test_http.py` (new)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Rules**: BR-25, BR-29
- **Status**: Complete

### T-22: Collect a source over the API transport
- **Refs**: US-13, US-14, US-17, TD-18, TD-19, TD-23
- **Files**: `plugins/claudio-routines/runtime/collect.py` (new), `plugins/claudio-routines/runtime/test_collect.py` (new)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-20, T-21
- **Rules**: BR-19, BR-24, BR-28, BR-32
- **Status**: Complete

### T-23: Read the observability tool over its API
- **Refs**: US-13, US-14, TD-18, TD-20, TD-22
- **Files**: `plugins/claudio-routines/runtime/providers/<observability vendor>.py` (new), `plugins/claudio-routines/runtime/providers/test_<observability vendor>.py` (new), `plugins/claudio-routines/runtime/providers/fixtures/<observability vendor>/` (new), `plugins/claudio-routines/runtime/providers/README.md` (new)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-20, T-21
- **Rules**: BR-25, BR-28, BR-29
- **Status**: Complete

### T-24: Read the document store over its API
- **Refs**: US-13, US-14, TD-18, TD-20, TD-22
- **Files**: `plugins/claudio-routines/runtime/providers/<document store vendor>.py` (new), `plugins/claudio-routines/runtime/providers/test_<document store vendor>.py` (new), `plugins/claudio-routines/runtime/providers/fixtures/<document store vendor>/` (new), `plugins/claudio-routines/runtime/providers/README.md` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-20, T-21
- **Rules**: BR-25, BR-28, BR-29
- **Status**: Complete

### T-25: Evaluate Prod watch facts from the collections and the query pack
- **Refs**: US-17, US-13, TD-23, TD-24
- **Files**: `plugins/claudio-routines/runtime/evaluate.py` (new), `plugins/claudio-routines/runtime/test_evaluate.py` (new)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-19, T-20
- **Rules**: BR-16, BR-19, BR-21, BR-28, BR-31, BR-32
- **Status**: Complete

### T-26: Render per place, extend the lint contracts and the config example
- **Refs**: US-5, US-7, US-16, TD-11, TD-15, TD-16, TD-22, TD-24
- **Files**: `plugins/claudio-routines/skills/routines/scripts/routines.py` (modify), `plugins/claudio-routines/skills/routines/scripts/lint.py` (modify), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify), `plugins/claudio-routines/config.example.json` (modify), `scripts/test_ci.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 -m unittest discover -s scripts -p 'test_ci.py'`
- **Blocked by**: T-22, T-25
- **Rules**: BR-15, BR-26, BR-30
- **Status**: Complete

## Phase 7: Relay through connectors

### T-27: Plan, relay and parse connector calls
- **Refs**: US-15, TD-21
- **Files**: `plugins/claudio-routines/runtime/collect.py` (modify), `plugins/claudio-routines/runtime/test_collect.py` (modify), `plugins/claudio-routines/runtime/roles.py` (modify: checksum and digest helpers), `plugins/claudio-routines/runtime/test_roles.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-22
- **Rules**: BR-24, BR-28
- **Status**: Complete

### T-28: Relay the observability tool through its code connector
- **Refs**: US-13, US-15, TD-21, TD-22
- **Files**: `plugins/claudio-routines/runtime/providers/<observability vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/test_<observability vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/fixtures/<observability vendor>/` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-23, T-27
- **Rules**: BR-24, BR-28
- **Status**: Complete

### T-29: Relay the document store through its connector
- **Refs**: US-13, US-15, TD-21, TD-22
- **Files**: `plugins/claudio-routines/runtime/providers/<document store vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/test_<document store vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/fixtures/<document store vendor>/` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-24, T-27
- **Rules**: BR-24, BR-28
- **Status**: Complete

## Phase 8: Local runs and the Prod watch template

### T-30: Run Prod watch on collectors, in the cloud and locally
Carries the T-18 review minors: delete the throwaway branch only on the orphan path, test that delete, add "report any other failure the same way" to the window step, and reword the explicit-run note for a baseline run.
- **Refs**: US-11, US-12, US-16, TD-15, TD-21, TD-24
- **Files**: `plugins/claudio-routines/skills/routines/templates/prod-watch.md` (modify), `plugins/claudio-routines/skills/routines/SKILL.md` (modify), `plugins/claudio-routines/README.md` (modify), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-26, T-28, T-29
- **Rules**: BR-22, BR-24, BR-26, BR-27, BR-30
- **Status**: Complete

### T-31: Migrate the private repository and prove a local run
Owner-gated: needs the private repository on the remote and the local credential variables of every `api` source of the local place.
1. Move the private `config.json` to the new shape: `places`, `providers` and `sources`; the query pack comes in T-43.
2. Rename the private templates' placeholders to the neutral keys, and check `/routines diff prod-watch` still prints `in sync`.
3. Run `routines.py setup-script --place local` and run its output.
- **Refs**: US-13, US-16, US-17, TD-23, TD-24
- **Files**: none in this repository; the private repository's `config.json` and `templates/` change
- **Verify**: `python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --private "$CLAUDIO_PRIVATE_DIR" && python3 plugins/claudio-routines/skills/routines/scripts/routines.py diff prod-watch`
- **Blocked by**: T-30
- **Rules**: BR-22, BR-25, BR-31
- **Status**: Complete

## Phase 9: Chat channel and code host adapters

### T-32: Read the chat channel over both transports
- **Refs**: US-13, US-14, US-15, TD-18, TD-20, TD-21, TD-22
- **Files**: `plugins/claudio-routines/runtime/providers/<chat vendor>.py` (new), `plugins/claudio-routines/runtime/providers/test_<chat vendor>.py` (new), `plugins/claudio-routines/runtime/providers/fixtures/<chat vendor>/` (new), `plugins/claudio-routines/runtime/providers/README.md` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-27
- **Rules**: BR-24, BR-25, BR-28, BR-29
- **Status**: Complete

### T-33: Read the code host over both transports
- **Refs**: US-13, US-14, US-15, TD-18, TD-20, TD-21, TD-22
- **Files**: `plugins/claudio-routines/runtime/providers/<code host vendor>.py` (new), `plugins/claudio-routines/runtime/providers/test_<code host vendor>.py` (new), `plugins/claudio-routines/runtime/providers/fixtures/<code host vendor>/` (new), `plugins/claudio-routines/runtime/providers/README.md` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-27
- **Rules**: BR-24, BR-25, BR-28, BR-29
- **Status**: Complete

## Phase 10: Model judgment

Phase 10 lands as one pull request: from T-39 to T-42, the template still calls the removed `evaluate.py` form.

### T-34: Validate the query pack v2 and the new collection fields
- Pack entries match their schema exactly: `rule` on every entry, optional `excluded_hours` (hourly entries only) and `lookback_days` (daily entries only, 1 to 31); `severity`, `urgency` and `threshold` are rejected.
- A monitors entry's key equals `monitor-<monitor>`, and a pack key that starts with a top entry's key followed by `-` is rejected.
- `routines.<slug>.rules` (texts of at most 500 characters) and the monitors source option `discovery_query`.
- Collections: the entry status `missing`, monitor records with `priority`, `discovered` records, `discovery` (`{read, reason}`, null when the source was not read), and metric records with `daily [{ts, value}]` for lookback entries.
- **Refs**: US-17, US-18, US-19, US-20, TD-23, TD-29, TD-31
- **Files**: `plugins/claudio-routines/runtime/roles.py` (modify), `plugins/claudio-routines/runtime/test_roles.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Rules**: BR-31, BR-33, BR-35
- **Status**: Complete

### T-35: Hand tracked monitors and lookback spans to the adapters
- `collect.py` adds every tracked `monitor-<id>` key of the state to the monitors entries, so they are read by id.
- It attaches a `span` to each lookback entry: `lookback_days` ending at the window end. Every other entry has no `span` and is read over the run window the adapter receives.
- **Refs**: US-18, US-19, TD-18, TD-29, TD-31
- **Files**: `plugins/claudio-routines/runtime/collect.py` (modify), `plugins/claudio-routines/runtime/test_collect.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-34
- **Rules**: BR-36
- **Status**: Complete

### T-36: Read discovery, priority, not found and lookbacks over the API
- The observability adapter's `api` transport: the discovery search with pagination up to the page cap, the monitor priority, `missing` on a not-found by-id read, `daily` buckets or span aggregates for lookback entries.
- A failed or capped discovery sets `discovery.read` false with a reason, and leaves the source read.
- The providers README names the discovery endpoint per vendor.
- **Refs**: US-14, US-18, US-19, TD-20, TD-22, TD-29, TD-31
- **Files**: `plugins/claudio-routines/runtime/providers/<observability vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/test_<observability vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/fixtures/<observability vendor>/` (modify), `plugins/claudio-routines/runtime/providers/README.md` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-35
- **Rules**: BR-28, BR-29, BR-40
- **Status**: Complete

### T-37: Read the same through the connector's code script
- The code script reads the discovery search, the priority, not found and lookback spans, with the ids, the discovery query and the spans inside its digested parameters (AC-15.4).
- The relay parse gives the same collection as the `api` transport for the same provider data.
- Monitors collections then require `priority`, `discovered` and `discovery`, which T-34 left omittable until both transports write them.
- **Refs**: US-15, US-18, US-19, TD-21, TD-22, TD-29
- **Files**: `plugins/claudio-routines/runtime/providers/<observability vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/test_<observability vendor>_relay.py` (modify), `plugins/claudio-routines/runtime/providers/fixtures/<observability vendor>/` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-36
- **Rules**: BR-24, BR-40
- **Status**: Complete

### T-38: Compute the features and rules files
- `evaluate.py features` writes `features.json` and `rules.json` (TD-26).
- Monitor values, with transitions from the alert events; metric values, with `previous` from the stored cursor; a rate or percent null when undefined (AC-18.9).
- Hourly buckets aligned with `bucket_labels`, their excluded indexes skipped by `value` and `window_max`; lookback `days` from the `daily` records, the last one marked partial; `tracked`.
- Group keys with slugs, `-<fnv1a32>` suffixes and collisions (TD-30), `groups_complete` (AC-18.4); top entries give only their groups.
- Discovered names cleaned, without `@`, `<` and `>`, cut to 300 characters.
- Byte-identical output for the same inputs, and a size test: 50 keys with 72 buckets each, 500-character rules and 15-digit values stay under 150 kB with the rules.
- **Refs**: US-18, US-19, TD-26, TD-30
- **Files**: `plugins/claudio-routines/runtime/features.py` (new), `plugins/claudio-routines/runtime/test_features.py` (new), `plugins/claudio-routines/runtime/evaluate.py` (modify), `plugins/claudio-routines/runtime/test_evaluate.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-34
- **Rules**: BR-34, BR-35
- **Status**: Complete

### T-39: Compute the base file, auto keys and blind spots
- `evaluate.py features` also writes `base.json`: every facts field except `observations`, with cursors holding this read's values, groups included.
- Auto keys `not found`, `group missing` and `replaced by groups`, on read sources only; group keys of a deferred or failed top entry deferred with it.
- Blind spots `discovery incomplete`, `not found` on an untracked entry key, and one `outside the top <N>` per entry.
- The orphan rule for metric keys only; mutes expanded to group keys; retried gaps counting every key of `keys`.
- Removes the threshold path of `evaluate.py` and its tests.
- **Refs**: US-17, US-18, US-19, US-21, TD-23, TD-26, TD-29, TD-30
- **Files**: `plugins/claudio-routines/runtime/features.py` (modify), `plugins/claudio-routines/runtime/test_features.py` (modify), `plugins/claudio-routines/runtime/evaluate.py` (modify), `plugins/claudio-routines/runtime/test_evaluate.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-38
- **Rules**: BR-12, BR-21, BR-32, BR-36, BR-40, BR-41
- **Status**: Complete

### T-40: Check and merge the judgment, add the analysis
- `evaluate.py judge` validates `judgment.json` against `features.json`: every rejection of TD-27 exits 3 with the key path; strict value comparison; ranks 1 to N over the open keys.
- It merges the verdicts and the auto keys with `base.json` into `facts.json`: observations carry `rank`, and a monitor's value is null (AC-21.8); the same inputs give byte-identical facts (AC-17.5).
- `evaluate.py annotate` validates `analysis.json` (keys equal to the preview summary's new and escalated keys, 300-character texts without control characters, 1 to 3 leads, `measured` claims with checked cites) and adds it to the pass-1 facts, changing nothing else.
- **Refs**: US-17, US-20, US-21, US-22, TD-25, TD-27, TD-28
- **Files**: `plugins/claudio-routines/runtime/judgment.py` (new), `plugins/claudio-routines/runtime/test_judgment.py` (new), `plugins/claudio-routines/runtime/evaluate.py` (modify), `plugins/claudio-routines/runtime/test_evaluate.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-39
- **Rules**: BR-37, BR-38, BR-39
- **Status**: Complete

### T-41: Rank order and typed analysis in the state engine
- Observations accept an optional `rank`; the summary's new and escalated lists sort by rank, then key, keys without a rank last, and each summary entry carries its rank.
- Items and observations type `risk` and `action` as labels, `reason` as a list of `{tag, claim}` with `tag` `measured` or `inferred`, and `mitigation` as 1 to 3 labels.
- Tests: a still-open item keeps its stored analysis; an explicit window keeps the state byte-identical while the summary carries the analysis.
- **Refs**: US-21, US-22, TD-27, TD-28, TD-32
- **Files**: `plugins/claudio-routines/runtime/state.py` (modify), `plugins/claudio-routines/runtime/test_state.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Rules**: BR-22, BR-37
- **Status**: Complete

### T-42: Run the judgment steps from the Prod watch template
- The skeleton: `features`, the model writes `judgment.json` from `features.json` and `rules.json`, `judge` with one correction, a preview apply, the model writes `analysis.json` for the preview's new and escalated keys, `annotate` with one correction, the real apply, and the digest in rank order with each analysis.
- The skeleton states the model behavior of AC-20.6, AC-20.7 and AC-22.1, treats feature text as data, and reports `degraded: judgment rejected` after a second rejection, writing neither state nor record; `test_routines.py` asserts that text.
- The lint fails a call that names no subcommand of a script with subcommands.
- `test_pipeline.py` runs one fixture run through `features`, a fixed judgment, `judge`, a preview apply, a fixed analysis, `annotate` and `apply`, and checks the rank order and the stored analysis.
- `config.example.json` with pack version 2, routine rules and `discovery_query`; the plugin README (pack fields, rules, discovery, judgment steps).
- **Refs**: US-16, US-20, US-21, US-22, TD-16, TD-24, TD-25, TD-28, TD-31, TD-32
- **Files**: `plugins/claudio-routines/skills/routines/templates/prod-watch.md` (modify), `plugins/claudio-routines/skills/routines/scripts/lint.py` (modify), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify), `plugins/claudio-routines/runtime/test_pipeline.py` (new), `plugins/claudio-routines/config.example.json` (modify), `plugins/claudio-routines/README.md` (modify), `README.md` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-37, T-40, T-41
- **Rules**: BR-8, BR-22, BR-30, BR-33, BR-38
- **Status**: Complete

### T-43: Write the private pack v2 and replay a live window
Runs in a local session with the observability and document store connectors; nothing is posted, and the run stops before the save step, since the private repository has no remote yet.
1. Write the private query pack version 2 from the sources page: one prose rule per entry, the routine-wide rules (flapping, discovered monitors, No Data, the highest severity wins), `excluded_hours`, `lookback_days`, and the monitors `discovery_query`.
2. Replay the 2026-10-16 15:46Z to 16:46Z window with `--since`, following the template's steps up to the digest.
3. Write `compare.py` in the replay directory: it lists every item of that run's live state with a match or a cause, and exits 1 when one has neither.
4. Check AC-20.6, AC-20.7 and AC-22.1 on the saved judgment and analysis (model eval).
- **Refs**: US-17, US-18, US-19, US-20, US-21, US-22, TD-25, TD-31
- **Files**: none in this repository; the private repository's `config.json` changes, and the replay outputs stay in a temporary directory
- **Verify**: `R=<replay dir>; python3 -B plugins/claudio-routines/runtime/evaluate.py judge --features "$R/features.json" --base "$R/base.json" --judgment "$R/judgment.json" --out "$R/facts.json" && python3 -B plugins/claudio-routines/runtime/evaluate.py annotate --features "$R/features.json" --facts "$R/facts.json" --analysis "$R/analysis.json" --preview "$R/preview/summary.json" --out "$R/facts-annotated.json" && python3 "$R/compare.py"`
- **Blocked by**: T-31, T-44
- **Rules**: BR-22, BR-31, BR-33
- **Status**: Complete (replay on the routine's model: 7 of 24 live items match, 0 unexplained, 0 replay-only items; findings: the sustained-Alert rule wording, fixed in the private config, and untracked monitors named only by alert events)

### T-44: Render the digest in a dedicated script
- New `digest.py --summary M --state N --record R --base BASE --out DIGEST` renders the message from the change summary, the next state, the run record and the base file (TD-33): the title from the state's `digest` name and the record's `run_at`, items in rank order with their analysis, resolved items, still open items from the summary's `still_open` keys (muted keys left out), with since, last value, link and stored action from the next state, blind spots, cut span, unread sources, overrides.
- The template's digest step runs it, then posts or prints that text unchanged, adding only the `state not saved` line and the environment check's missing variables and connectors.
- The lint checks `digest.py` calls like the other runtime scripts; the plugin and root READMEs list it, with the analysis text rules (no control, format or separator characters, no `<`, `>`, `@` or `://`, at most 5 claims).
- Tests: rendering of each section, empty sections skipped, rank order, report-only output, no text outside the summary, state and base fields.
- **Refs**: US-12, US-16, US-22, TD-16, TD-24, TD-32, TD-33
- **Files**: `plugins/claudio-routines/runtime/digest.py` (new), `plugins/claudio-routines/runtime/test_digest.py` (new), `plugins/claudio-routines/skills/routines/templates/prod-watch.md` (modify), `plugins/claudio-routines/skills/routines/scripts/lint.py` (modify), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify), `plugins/claudio-routines/README.md` (modify), `README.md` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-42
- **Rules**: BR-22, BR-26, BR-42
- **Status**: Complete

### T-45: Read the monitors named by the window's alert events
- Both transports, after the events read: every monitor id named by an alert event of the window that is not in the pack, not tracked and not returned by the discovery search is read by id, at most 50 per run, and added to `discovered`; the excess adds `event monitors capped at 50` to the monitors source's blind spot.
- The code script does it inside the same plan step, with the cap in its digested parameters.
- `features.py` keeps an untracked discovered monitor in state `OK` when the window's alert events name it, so its transitions reach the model.
- Tests: an event-named monitor that is OK at run time gets a key with its transitions, over both transports; the cap and its blind spot; parity between the api and relay collections.
- **Refs**: US-18, US-19, TD-21, TD-26, TD-29
- **Files**: `plugins/claudio-routines/runtime/providers/<observability vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/test_<observability vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/test_<observability vendor>_relay.py` (modify), `plugins/claudio-routines/runtime/providers/<observability vendor>_support.py` (modify), `plugins/claudio-routines/runtime/providers/fixtures/<observability vendor>/` (modify), `plugins/claudio-routines/runtime/providers/README.md` (modify), `plugins/claudio-routines/runtime/features.py` (modify), `plugins/claudio-routines/runtime/test_features.py` (modify), `plugins/claudio-routines/runtime/roles.py` (modify), `plugins/claudio-routines/runtime/test_roles.py` (modify), `plugins/claudio-routines/README.md` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-43
- **Rules**: BR-36, BR-40
- **Status**: Complete (replay 2: 13 of 24 live items match, 0 unexplained, 0 replay-only items)

## Phase 11: Config split and mirrors

The private config moves to routine files (T-51) only after both loaders read them (T-47, T-48).

### T-46: Load and merge the config tree
- `runtime/config_tree.py`, standard library and `roles.py` only:
  - `load(path)`: `config.json` plus every `.json` file of `config/routines/`, merged into `routines`.
  - `load(path, routine=SLUG)`: `config.json` plus `config/routines/SLUG.json` only; a `SLUG` that does not match `^[a-z0-9-]+$` reads no routine file.
  - Rejects, as `roles.ConfigError`: a `.json` name that does not match `^[a-z0-9-]+\.json$`, a file that is not UTF-8 JSON or not an object, a routine file holding `timezone`, `runtime`, `places` or `providers`, a slug both inline and in a file (both paths named), and, in a full load, two routines with one `id` (both paths named, no value printed).
  - Ignores files that do not end in `.json`; a config with neither `routines` nor routine files has no routine.
  - Resolves each source's transport per place, for every routine in a full load and for `SLUG` only in a one-routine load: the source's value, else `providers.<name>.transport`; rejects an unknown place, a value other than `api` or `mcp`, and a place left unresolved, naming the key path; leaves malformed shapes for `roles.validate_config`.
  - `label(directory, slug)` and `locate(message, directory)`: every `routines.<slug>.` key path of a routine kept in a file reads `config/routines/<slug>.json: <path inside the file>`, whatever the message's prefix.
  - Re-exports `roles.ConfigError` as `config_tree.ConfigError`.
- Tests: each rejection with its message, inline and file forms giving the same merged config, a one-routine load that ignores another routine's broken file, a path-like slug rejected before any read, per-place override of a provider default, the unchanged single-file form, labels and `locate` on matching and non-matching messages.
- **Refs**: US-23, US-24, TD-34, TD-35
- **Files**: `plugins/claudio-routines/runtime/config_tree.py` (new), `plugins/claudio-routines/runtime/test_config_tree.py` (new)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Rules**: BR-24, BR-43, BR-44, BR-47
- **Status**: Complete

### T-47: Read the config tree in the runtime
- `config.read_routine` loads through `config_tree.load(path, routine=...)`, so every `collect.py` and `evaluate.py` command sees the merged routine and the resolved transports.
- `roles.validate_config` rejects an absent or empty `sources`, exit 2.
- `collect.py` and `evaluate.py` print `ConfigError` and `PackError` messages through `config_tree.locate`.
- `run_context` runs `git status --porcelain -- config.json config/routines/<slug>.json`, so `config_dirty` is true for a modified or untracked routine file.
- Tests: `sources`, `check-env` and `fetch` on a routine kept in a file, with a provider default transport; another routine's broken file does not stop them; a pack error located to the routine file; `config_dirty` for a modified, an untracked and an absent routine file; empty `sources` rejected; the existing inline fixtures unchanged.
- **Refs**: US-23, US-24, US-25, TD-34, TD-35, TD-36
- **Files**: `plugins/claudio-routines/runtime/config.py` (modify), `plugins/claudio-routines/runtime/roles.py` (modify), `plugins/claudio-routines/runtime/collect.py` (modify), `plugins/claudio-routines/runtime/evaluate.py` (modify), `plugins/claudio-routines/runtime/test_collect.py` (modify), `plugins/claudio-routines/runtime/test_evaluate.py` (modify), `plugins/claudio-routines/runtime/test_roles.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-46
- **Rules**: BR-24, BR-43, BR-44
- **Status**: Complete

### T-48: Read the config tree in the skill
- `routines.py load_config` imports `config_tree` from its plugin's runtime through `runtime_imports`, converts `config_tree.ConfigError` to a usage error, and runs its own checks on the merged config with `config_tree.label` in every routine message; a `routines` that is not an object fails.
- `routines` in `config.json` is optional; `render`, `diff`, `lint`, `body` and `sync` see inline and file routines alike, and an invalid routine file fails them.
- `diff` reports `untracked` for a live routine with neither a routine file nor a `routines` entry; `export` writes only under `routines/`.
- `lint --private` adds the `literal-value` and `repeated-value` warnings (TD-36), naming keys, never values; the pure line check sits in `lint.py`.
- Tests: render and diff of a routine kept in a file, a routine value overriding a shared one, a slug clash and an id clash failing with both paths, an invalid file failing every command, `untracked` and `not exported` over the merged set, `export` leaving `config/` untouched, each warning and its absence.
- **Refs**: US-23, US-25, TD-34, TD-36
- **Files**: `plugins/claudio-routines/skills/routines/scripts/routines.py` (modify), `plugins/claudio-routines/skills/routines/scripts/lint.py` (modify), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts`
- **Blocked by**: T-46
- **Rules**: BR-43, BR-45, BR-47
- **Status**: Complete

### T-49: Mark templates not runnable and ship the skeletons
- `lint.py` detects the marker: a first line that is exactly `<!-- not runnable -->`, ignoring a leading byte order mark and one trailing carriage return; a near-miss first line (an HTML comment holding `not runnable` in another case or spacing) is the lint finding `marker`.
- `render` keeps the line, and the `render` command warns, naming the template, while `diff` and `lint` render silently; `render --runnable` exits 2; `body` exits 2 before printing a body.
- Three public skeletons, each starting with the marker, with the sections Purpose, Sources (by role), Steps and Outputs, placeholders only and no runtime command: `tribe-digest.md`, `chat-recap.md`, `weekly-status.md`.
- SKILL.md: `/routines run` renders with `--runnable`, and `sync` runs `render --runnable` before its export, then stops when `body` refuses.
- README: each template and whether it runs.
- Tests: the marker on the first line only, with a byte order mark or a carriage return, the near-miss finding, render's warning, `--runnable` and `body` refusals before any output, `diff` and `lint` silent on a marked template, the three skeletons in `lint --public`.
- **Refs**: US-26, TD-37
- **Files**: `plugins/claudio-routines/skills/routines/scripts/routines.py` (modify), `plugins/claudio-routines/skills/routines/scripts/lint.py` (modify), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify), `plugins/claudio-routines/skills/routines/templates/tribe-digest.md` (new), `plugins/claudio-routines/skills/routines/templates/chat-recap.md` (new), `plugins/claudio-routines/skills/routines/templates/weekly-status.md` (new), `plugins/claudio-routines/skills/routines/SKILL.md` (modify), `plugins/claudio-routines/README.md` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-48
- **Rules**: BR-8, BR-30, BR-46
- **Status**: Complete

### T-50: Ship the example private directory
- `example/config.json`: timezone, runtime pin, places, providers with a default transport, shared values, all placeholders.
- `example/config/routines/prod-watch.json`: the Prod watch routine of `config.example.json`, its sources without transport blocks.
- `example/config/routines/tribe-digest.json`, `chat-recap.json`, `weekly-status.json`: id, template, cron and values for the skeletons, no sources.
- Each example routine has its own id placeholder, so the example passes the id clash check.
- `config.example.json` is deleted; the example tests load `example/` through `config_tree`: Prod watch passes `validate_config` in both places and the pack check, and every skeleton renders with no placeholder left.
- README: setup copies `example/` into the private directory; the config reference shows the split layout and the provider default transport.
- Plugin and marketplace versions bumped.
- **Refs**: US-23, US-24, US-26, TD-34, TD-35, TD-37
- **Files**: `plugins/claudio-routines/example/config.json` (new), `plugins/claudio-routines/example/config/routines/prod-watch.json` (new), `plugins/claudio-routines/example/config/routines/tribe-digest.json` (new), `plugins/claudio-routines/example/config/routines/chat-recap.json` (new), `plugins/claudio-routines/example/config/routines/weekly-status.json` (new), `plugins/claudio-routines/config.example.json` (delete), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify), `plugins/claudio-routines/README.md` (modify), `plugins/claudio-routines/.claude-plugin/plugin.json` (modify), `.claude-plugin/marketplace.json` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-47, T-49
- **Rules**: BR-8, BR-44
- **Status**: Complete

### T-51: Split the private config and mirror the 4 live routines
Runs in a local session; nothing is pushed to a live routine, and the private repository is committed only on the owner's word.
1. Export the live routines (`RemoteTrigger list`, then `/routines export`).
2. Move Prod watch to `config/routines/prod-watch.json`, set each provider's default transport, and drop the sources' transport blocks.
3. Merge the duplicated digest channel values into one shared key, and update the Prod watch templates' placeholder.
4. Write the routine files of the 4 other routines (id, template, cron, values) and the mirrors `tribe-digest.md`, `chat-recap.md` and `weekly-status.md`, with every id, channel, page, user id, login, organization and owner identity as a value.
5. Check that each render equals its exported prompt, and that `diff` prints `in sync` for all 5.
6. Once T-31 pins the runtime, run `lint --private`: no finding, and no `unused`, `literal-value` or `repeated-value` warning.
- **Refs**: US-23, US-24, US-25, TD-34, TD-35, TD-36
- **Files**: none in this repository; the private repository's `config.json`, `config/routines/` and `templates/` change
- **Verify**: `S=plugins/claudio-routines/skills/routines/scripts/routines.py; R=plugins/claudio-routines/runtime/collect.py; python3 $S diff && python3 -B $R check-env --config "$CLAUDIO_PRIVATE_DIR/config.json" --routine prod-watch --place local && python3 -B $R check-env --config "$CLAUDIO_PRIVATE_DIR/config.json" --routine prod-watch --place cloud`
- **Blocked by**: T-47, T-48
- **Rules**: BR-43, BR-44, BR-45
- **Status**: Complete

### T-52: Reject secrets in the private config
- `config_tree` scans `config.json` and each routine file it reads, before the merge:
  - `secret-key`: a key named `password`, `passwd`, `secret`, `token`, `api_key`, `apikey`, `app_key` or `private_key`, or ending in `_` and one of them once camelCase is split and dashes become underscores, holds an environment variable name, else the load fails; the keys of `routines`, `providers` and `sources` are names, never secret names.
  - `token`: a string or a key anywhere matching the leak guard's `token` rule fails the load.
  - Messages name the file, the key path and the rule, never the value.
- Tests: each rule in `config.json`, in a routine file, in `values`, in a source option and in `api`; credential variable names and `max_tokens`-like keys pass; a one-routine load ignores another routine's file; an `mcp`-only provider with no `api` block loads; no value in any message.
- `providers/README.md`: credentials hold variable names and the loader rejects secrets; a connector-only provider sets no `api` block.
- **Refs**: US-14, US-23, TD-34, TD-38
- **Files**: `plugins/claudio-routines/runtime/config_tree.py` (modify), `plugins/claudio-routines/runtime/test_config_tree.py` (modify), `plugins/claudio-routines/runtime/providers/README.md` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-46
- **Rules**: BR-25
- **Status**: Complete

## Phase 12: Tribe digest collectors

T-53 lands first: it sets the record, cursor and option contracts the adapters of T-54 to T-57 fill, which run in parallel on separate files.

### T-53: Contracts for the tribe collectors
- `roles.py`:
  - the `issue_tracker` options (`filter`, optional `query` and `open_sprints`), records and cursor, outside `ROLES` until T-54 adds the role with its adapter;
  - chat records with `thread_ts`;
  - document store `pages` option (exclusive with `page_id`), page `link`, cursor `{pages: {id: edit time}}`;
  - metric records with omittable `trend` and `trend_reason`;
  - pack entries with `trend_days` (7 to 31, `scalar` or `hourly`, never with `lookback_days`, aggregator `max`, `min`, `sum`, `avg` or `last`).
- `collect.py`:
  - `EMPTY_RECORDS` for the issue tracker;
  - the routine's `first_read_days` (1 to 31) adds `first_read_from_ts` to the window handed to adapters, the window start without it;
  - entry spans for `trend_days`, over the last local days of the config timezone;
  - `timezone` in the window handed to adapters, and adapter entries passed through for chat and document store sources;
  - one read start helper in `providers/_common.py`: a stored cursor later than `first_read_from_ts`, else `first_read_from_ts`.
- `evaluate.py` takes the sources page only from a source that sets `page_id`.
- Existing adapters keep passing their tests: the chat adapter emits `thread_ts: null`, the document store adapter emits `link` and the new cursor; the evaluator's sources page facts read the new page record.
- Tests: every new rejection with its key path, `first_read_from_ts` with and without the key, the unchanged Prod watch collections, the sources page facts.
- **Refs**: US-27, US-28, US-29, US-30, US-31, TD-39, TD-40, TD-41, TD-42, TD-43
- **Files**: `plugins/claudio-routines/runtime/roles.py` (modify), `plugins/claudio-routines/runtime/collect.py` (modify), `plugins/claudio-routines/runtime/evaluate.py` (modify), `plugins/claudio-routines/runtime/providers/_common.py` (modify), `plugins/claudio-routines/runtime/providers/test_common.py` (new), `plugins/claudio-routines/runtime/providers/<chat vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/<document store vendor>.py` (modify), `plugins/claudio-routines/runtime/test_roles.py` (modify), `plugins/claudio-routines/runtime/test_collect.py` (modify), `plugins/claudio-routines/runtime/evaluate_support.py` (modify), `plugins/claudio-routines/runtime/test_evaluate.py` (modify), provider tests and fixtures as the record changes need
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Rules**: BR-50, BR-52, BR-53
- **Status**: Complete

### T-54: Read the issue tracker over both transports
- `issue_tracker` added to `ROLES`, `EMPTY_RECORDS` and the test role maps, with the adapter module for the issue tracker vendor (TD-39): updated read with the 1-hour overlap, the 24-hour query margin and the exact bound filter, open-sprint read, merge by key, page cap, connector plan in the full view with the site from `links_base`, response parser shared by both transports, UTC times, links, not-found filter as source not read.
- `providers/README.md`: the adapter's section (calls, connector, credentials, read-only scope, hosts, where each place reads the variables), as the conformance test requires.
- Tests: fixtures for both transports from one data set, transport equality, overlap and bound, zone mismatch over-read, open sprints with none and several, newest update wins, no person field, page cap, a filter not found, the conformance test.
- **Refs**: US-27, TD-39
- **Files**: `plugins/claudio-routines/runtime/providers/<issue tracker vendor>.py` (new), `plugins/claudio-routines/runtime/providers/test_<issue tracker vendor>.py` (new), `plugins/claudio-routines/runtime/providers/fixtures/<issue tracker vendor>/` (new), `plugins/claudio-routines/runtime/providers/README.md` (modify), `plugins/claudio-routines/runtime/test_roles.py` (modify), `plugins/claudio-routines/runtime/evaluate_support.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-53
- **Rules**: BR-24, BR-28, BR-49, BR-50, BR-52
- **Status**: Complete

### T-55: Read chat thread replies
- Chat adapter (TD-40): roots from the history read (reply count over the API, the thread marker line over the connector, removed from the text), replies of roots in the window up to the window end, thread text parser with the history guards, one record per channel and ts with the thread copy winning, one budget of 50 history pages and thread reads, per-channel failed entries for not found, archived and not joined, cursor at the window end for an empty channel, first-read start for a channel with no cursor.
- Tests: both transports from one data set, broadcast reply deduplication, a root older than the window, a reply after the window end, a forged reply header, a failed channel next to read ones, another error failing the source, the empty channel cursor, the first-read start.
- **Refs**: US-28, TD-40
- **Files**: `plugins/claudio-routines/runtime/providers/<chat vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/test_<chat vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/fixtures/<chat vendor>/` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-53
- **Rules**: BR-14, BR-48, BR-50, BR-52
- **Status**: Complete

### T-56: Read changed documents
- Document store adapter (TD-41): a `pages` source reads each page's edit time over the API and fetches each page over the connector, keeps only pages whose edit minute differs from the cursor, per-page entries (`ok`, `deferred` unchanged, `failed` not found or not shared), cursor per page, page links, request and call caps.
- Tests: both transports from one data set, the minute tie, a page with no cursor, a missing page next to read ones, the cap, the sources page unchanged.
- **Refs**: US-29, TD-41
- **Files**: `plugins/claudio-routines/runtime/providers/<document store vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/test_<document store vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/fixtures/<document store vendor>/` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-53
- **Rules**: BR-28, BR-51
- **Status**: Complete

### T-57: Read trend windows
- Observability adapter (TD-42): one guarded hourly read per entry with `trend_days` (HTTP errors other than 401 and 403 set `trend_reason`), from the local day start of the span to the window end, local-day buckets with the entry's aggregator, absent days, clock-change days, `trend_reason` on failure, both transports, the connector script and its golden fixture.
- Tests: both transports from one data set, each aggregator, a spring-forward and a fall-back day, an empty day, a failed trend next to a read window value, the script parameters digest.
- **Refs**: US-30, TD-42
- **Files**: `plugins/claudio-routines/runtime/providers/<observability vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/test_<observability vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/test_<observability vendor>_relay.py` (modify), `plugins/claudio-routines/runtime/providers/<observability vendor>_support.py` (modify), `plugins/claudio-routines/runtime/providers/fixtures/<observability vendor>/` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-53
- **Rules**: BR-32, BR-53
- **Status**: Complete

### T-58: Example, docs and version
- `example/config.json` with the chat and issue tracker providers; `example/config/routines/tribe-digest.json` with sources by role, `first_read_days` and a trend entry, placeholders only.
- `providers/README.md`: thread reads, page lists and their connector cost, trend reads. Plugin README: the issue tracker role, the new source options, `first_read_days`.
- Plugin 0.3.0, marketplace 2.15.0.
- Tests: the example loads and validates for every source of the tribe routine, its skeleton still renders.
- **Refs**: US-31, TD-43
- **Files**: `plugins/claudio-routines/example/config.json` (modify), `plugins/claudio-routines/example/config/routines/tribe-digest.json` (modify), `plugins/claudio-routines/runtime/providers/README.md` (modify), `plugins/claudio-routines/README.md` (modify), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify), `plugins/claudio-routines/.claude-plugin/plugin.json` (modify), `.claude-plugin/marketplace.json` (modify)
- **Verify**: `for d in scripts plugins/claudio-routines/runtime plugins/claudio-routines/skills/routines/scripts; do PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s $d; done && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-54, T-55, T-56, T-57
- **Status**: Complete

### T-59: Configure the tribe sources and replay the reference windows
Runs in a local session with the chat, issue tracker, document store and observability connectors; nothing is posted or written to any tool.
1. Add the chat and issue tracker providers to the private `config.json`, and the sources, `first_read_days` and trend entries to the two tribe routine files, from their sources pages.
2. Check that both renders still equal their live prompts.
3. Collect every source of each tribe routine over its reference window (`plan`, saved responses, `parse`).
4. Write the compare script and, after checking each unmatched record, the reasons file.
- **Refs**: US-31, TD-43, TD-44
- **Files**: none in this repository; the private repository's `config.json`, two routine files and `reference/` change, and the collections stay in a temporary directory
- **Verify**: `python3 plugins/claudio-routines/skills/routines/scripts/routines.py diff && python3 "$CLAUDIO_PRIVATE_DIR/reference/compare_collections.py" --digest connect --collections <replay dir>/connect && python3 "$CLAUDIO_PRIVATE_DIR/reference/compare_collections.py" --digest scheduling --collections <replay dir>/scheduling`
- **Blocked by**: T-58
- **Rules**: BR-48, BR-50
- **Status**: Complete (both reference windows covered, 0 unexplained: connect issues 8/12, pages 1/10, channels 4/7 found; scheduling issues 44/48, pages 0/7, channels 9/11 found; every other cited record has a verified reason. The replay found and fixed: thread pagination wording, newest-first thread pages, trailing message metadata, exclusive bounds, truncated listed pages, a listed database, the open-sprint query scope and harness-saved results)

## Phase 13: Tribe judgment

T-60, T-61, T-62 and T-64 run in parallel on separate files; T-63 needs T-60 and T-62; T-65 needs T-60 and T-64; T-66 needs T-62 and T-65.

### T-60: Tribe state, window and seed
- `tribe_state.py`: schema `tribe-1` (TD-46), load and check with key paths, atomic write.
- `tribe.py`:
  - `init`;
  - `window`, using `state.compute_window` over `run.at`;
  - `seed`: newest valid Run state, BR-54 checks with a `status` read as its leading BR-54 word, else `open`, cursors matched to the routine's sources, `previous_page`, skipped pages named, exit 2 with none (TD-47).
- Routine key `engine` (`watch` default, `tribe`), validated in the config loaders. `collect.py` checks `--state` with the engine's checker and reads no tracked items for a tribe state.
- Tests: every schema rejection, baseline init, window over a tribe state, an unknown `engine`, seed from a valid page, a skipped newer page, no valid page, a value outside BR-54, a status read as its BR-54 word, `collect.py` reading a tribe state.
- **Refs**: US-32, US-33, TD-45, TD-46, TD-47
- **Files**: `plugins/claudio-routines/runtime/tribe.py` (new), `plugins/claudio-routines/runtime/tribe_state.py` (new), `plugins/claudio-routines/runtime/tribe_seed.py` (new), `plugins/claudio-routines/runtime/test_tribe_seed.py` (new), `plugins/claudio-routines/runtime/test_tribe_state.py` (new), `plugins/claudio-routines/runtime/tribe_support.py` (new), `plugins/claudio-routines/runtime/collect.py` (modify), `plugins/claudio-routines/runtime/roles.py` (modify), `plugins/claudio-routines/runtime/config_tree.py` (modify), `plugins/claudio-routines/runtime/test_collect.py` (modify), `plugins/claudio-routines/runtime/test_roles.py` (modify), `plugins/claudio-routines/runtime/test_config_tree.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Rules**: BR-14, BR-22, BR-23, BR-27, BR-54, BR-55
- **Status**: Complete

### T-61: Collector additions for the tribe judgment
- Chat: `source["threads"]` (from the tribe state) reads each cited thread's replies newer than the previous window end; a thread the tool reports as not found is a failed entry keyed `<channel>:<root ts>`, both transports.
- Document store: list blocks carry `checked` (true, false or null) on both transports; the source option `page_from_state: previous_page` takes its page id from the state, filled by `collect.py`; a run with no previous page skips the source.
- Tests: both transports from one data set for cited threads and checked to-dos, a deleted thread next to read ones, `page_from_state` with and without a previous page.
- **Refs**: US-32, US-35, TD-46, TD-49
- **Files**: `plugins/claudio-routines/runtime/providers/<chat vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/test_<chat vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/<document store vendor>.py` (modify), `plugins/claudio-routines/runtime/providers/test_<document store vendor>.py` (modify), provider fixtures, `plugins/claudio-routines/runtime/roles.py` (modify), `plugins/claudio-routines/runtime/collect.py` (modify), `plugins/claudio-routines/runtime/test_collect.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-60 (shares `collect.py` and `roles.py`; start once T-60's edits to them land)
- **Rules**: BR-28, BR-50, BR-52
- **Status**: Complete

### T-62: Page render, structure check and edit parsing
- `tribe_page.py`: render layout version 1 from a summary and a state (TD-52), key markers on warning rows and to-dos, the structure check in Python, and the parser of a fetched page's warning rows and to-dos into edits (TD-49).
- Tests: a full render matches a golden page, each structure rule failing on a broken page, the parser reading ticks, statuses and key markers, ignored edits listed, a render-then-parse round trip.
- **Refs**: US-35, US-39, TD-49, TD-52
- **Files**: `plugins/claudio-routines/runtime/tribe_page.py` (new), `plugins/claudio-routines/runtime/test_tribe_page.py` (new), `plugins/claudio-routines/runtime/fixtures/tribe/` (new)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Rules**: BR-55, BR-60, BR-61, BR-62
- **Status**: Complete

### T-63: Tribe features and rules
- `tribe_features.py` and `tribe.py features` (TD-48): record documents with source and link, monitor and metric documents, trend documents with `growth_monthly`, `previous`, `edits` (through `tribe_page`'s parser), `deferred`, `rules.json` from the routine's prose rules, `state.clean_text` on source text.
- Tests: byte-identical features, each trend value and its null cases, deferred warnings from unread sources, edits after `written_at` only, no threshold in the features.
- **Refs**: US-34, US-35, TD-48, TD-49
- **Files**: `plugins/claudio-routines/runtime/tribe_features.py` (new), `plugins/claudio-routines/runtime/test_tribe_features.py` (new), `plugins/claudio-routines/runtime/tribe.py` (modify), `plugins/claudio-routines/runtime/tribe_support.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-60, T-62
- **Rules**: BR-33, BR-38, BR-51, BR-61, BR-63
- **Status**: Complete

### T-64: Tribe judgment checks
- `tribe_judgment.py` (TD-50, the CLI command lands in T-65): the judgment schema, every rejection with its key path and exit 3, author ids from the collections, the correction loop's messages.
- Tests: one test per rejection, a valid judgment passing, replaces and deferred keys, title matches against stored and retired titles.
- **Refs**: US-36, US-37, TD-50
- **Files**: `plugins/claudio-routines/runtime/tribe_judgment.py` (new), `plugins/claudio-routines/runtime/test_tribe_judgment.py` (new)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Rules**: BR-52, BR-54, BR-56, BR-59, BR-62
- **Status**: Complete

### T-65: Tribe lifecycle
- `tribe.py judge` (TD-50), wiring `tribe_judgment.py` into the CLI.
- `tribe.py apply` (TD-51): the judgment then the edits into the next state, the summary and the run record, every resolution rule, `retired` with titles, `threads` rebuilt, forward-only cursors, report-only byte-identity.
- Tests: each lifecycle rule, an edit winning over the judgment, a deferred warning held, a metric-less warning resolving by status only, once-only summary entries, report-only.
- **Refs**: US-38, TD-51
- **Files**: `plugins/claudio-routines/runtime/tribe.py` (modify), `plugins/claudio-routines/runtime/tribe_lifecycle.py` (new), `plugins/claudio-routines/runtime/tribe_state.py` (modify), `plugins/claudio-routines/runtime/test_tribe_lifecycle.py` (new)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-60, T-64
- **Rules**: BR-12, BR-14, BR-22, BR-57, BR-58, BR-63
- **Status**: Complete

### T-66: Publish and message
- `tribe_publish.py`, `tribe.py render`, `publish-plan`, `publish-parse` and `message` (TD-52, TD-53): the iterative write plan (create, polls, weekly heading), the page id and week from the results, a failed create or heading, report-only, the message and the degraded messages.
- `roles.py` validates `page` and `publish` at config load for a routine with the tribe engine: every key required, `publish.provider` naming a configured provider (TD-52).
- Tests: the plan for each step, a successful and a failed create, a failed heading kept for the next run, report-only plans no write, each message section, `page` and `publish` validation at config load.
- **Refs**: US-39, US-40, TD-52, TD-53
- **Files**: `plugins/claudio-routines/runtime/tribe_publish.py` (new), `plugins/claudio-routines/runtime/test_tribe_publish.py` (new), `plugins/claudio-routines/runtime/tribe_message.py` (new), `plugins/claudio-routines/runtime/test_tribe_message.py` (new), `plugins/claudio-routines/runtime/roles.py` (modify), `plugins/claudio-routines/runtime/test_roles.py` (modify), `plugins/claudio-routines/runtime/tribe_page.py` (modify), `plugins/claudio-routines/runtime/tribe.py` (modify)
- **Verify**: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s plugins/claudio-routines/runtime`
- **Blocked by**: T-62, T-65
- **Rules**: BR-22, BR-26, BR-42, BR-60
- **Status**: Complete

### T-67: Template, skill, docs and version
- The runnable `tribe-digest.md` template (TD-54), `/routines seed <slug>` in SKILL.md with the approval gate, `lint --private` failing without the settings deny list, the template contract tests, an end-to-end pipeline test over fixtures (features, judge, apply, render, publish-plan and publish-parse, message), the plugin, providers and root READMEs, the example, plugin 0.4.0 and marketplace 2.16.0.
- **Refs**: US-39, US-40, US-41, TD-45, TD-54
- **Files**: `plugins/claudio-routines/skills/routines/templates/tribe-digest.md` (modify), `plugins/claudio-routines/skills/routines/SKILL.md` (modify), `plugins/claudio-routines/skills/routines/scripts/routines.py` (modify), `plugins/claudio-routines/skills/routines/scripts/lint.py` (modify), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify), `plugins/claudio-routines/runtime/test_tribe_pipeline.py` (new), `plugins/claudio-routines/README.md` (modify), `README.md` (modify), `plugins/claudio-routines/runtime/providers/README.md` (modify), `plugins/claudio-routines/example/` (modify), `plugins/claudio-routines/.claude-plugin/plugin.json` (modify), `.claude-plugin/marketplace.json` (modify)
- **Verify**: `for d in scripts plugins/claudio-routines/runtime plugins/claudio-routines/skills/routines/scripts; do PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s $d; done && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-61, T-63, T-66
- **Rules**: BR-6, BR-8, BR-30, BR-42
- **Status**: Complete

### T-68: Seed and replay the next live digests
Runs in a local session with the chat, issue tracker, document store and observability connectors; nothing is posted or written to any tool.
1. Private: `.claude/settings.json` with the deny list, the tribe routine files with `engine: tribe`, the `previous-digest` source and the prose rules, the private runtime template.
2. Fetch the 2026-10-16 tribe digests into `reference/`.
3. Seed each tribe state from its 2026-10-15 digest (in a scratch state, not pushed).
4. Replay the full pipeline report-only over each 2026-10-16 window, write the key map and the reasons after checking each difference, and run `reference/compare_judgment.py`.
- **Refs**: US-33, US-42, TD-47, TD-55
- **Files**: none in this repository; the private repository's `.claude/settings.json`, routine files, templates and `reference/` change, and the replay stays in a temporary directory
- **Verify**: `python3 "$CLAUDIO_PRIVATE_DIR/reference/compare_judgment.py" --digest connect --replay <replay dir>/connect && python3 "$CLAUDIO_PRIVATE_DIR/reference/compare_judgment.py" --digest scheduling --replay <replay dir>/scheduling`
- **Blocked by**: T-67
- **Rules**: BR-22, BR-27
- **Status**: Complete (Connect explained in full; Scheduling keeps one line as a known limit: its main page reads truncated over the document store connector, reported as a blind spot every run, and only the api transport would read it whole)

### T-69: Coverage notes
- `coverage_notes` in the judgment (TD-50): schema and checks in `tribe_judgment.py`, carried into the summary by `apply` (TD-51, not the state), rendered after the collector gaps under Blind spots as `source: text` (TD-52), and named in the message's blind spots line (TD-53); template Step 7 describes the field and its limits.
- Tests: a valid note passing, each rejection (over 10 notes, a repeated source, a source over 60 characters, a text failing the text rules), notes absent from the next state, the render and structure check with notes, the message line, the pipeline with notes.
- **Refs**: US-36, TD-50, TD-51, TD-52, TD-53
- **Files**: `plugins/claudio-routines/runtime/tribe_judgment.py` (modify), `plugins/claudio-routines/runtime/test_tribe_judgment.py` (modify), `plugins/claudio-routines/runtime/tribe_lifecycle.py` (modify), `plugins/claudio-routines/runtime/test_tribe_lifecycle.py` (modify), `plugins/claudio-routines/runtime/tribe_page.py` (modify), `plugins/claudio-routines/runtime/test_tribe_page.py` (modify), `plugins/claudio-routines/runtime/tribe_message.py` (modify), `plugins/claudio-routines/runtime/test_tribe_message.py` (modify), `plugins/claudio-routines/runtime/test_tribe_pipeline.py` (modify), `plugins/claudio-routines/runtime/tribe_state.py` (modify), `plugins/claudio-routines/runtime/tribe_support.py` (modify), `plugins/claudio-routines/runtime/test_tribe_seed.py` (modify), `plugins/claudio-routines/README.md` (modify), `plugins/claudio-routines/runtime/fixtures/tribe/` (modify), `plugins/claudio-routines/skills/routines/templates/tribe-digest.md` (modify), `plugins/claudio-routines/skills/routines/scripts/test_routines.py` (modify)
- **Verify**: `for d in scripts plugins/claudio-routines/runtime plugins/claudio-routines/skills/routines/scripts; do PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s $d; done && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 scripts/leak_check.py --tree`
- **Blocked by**: T-67
- **Rules**: BR-60, BR-61, BR-64
- **Status**: Complete

## Phase 14: Empty reads as zero

### T-70: Read an empty count as zero
- `empty` (`gap` or `zero`) on `scalar` and `top` pack entries (TD-56): validation in `roles.py`, the zero mapping of window values and the zero cursor in `features.py`, shared by the watch and tribe engines, and of trends in `tribe_features.py`; READMEs.
- Tests: each rejection with its key path, a `scalar` and a `top` entry read as 0, a trend read as zeros with a null growth, a failed read still a gap, an entry without the option unchanged, the tribe features with no blind spot for such an entry.
- **Refs**: US-43, US-30, TD-56, TD-42
- **Files**: `plugins/claudio-routines/runtime/roles.py` (modify), `plugins/claudio-routines/runtime/test_roles.py` (modify), `plugins/claudio-routines/runtime/features.py` (modify), `plugins/claudio-routines/runtime/test_features.py` (modify), `plugins/claudio-routines/runtime/tribe_features.py` (modify), `plugins/claudio-routines/runtime/test_tribe_features.py` (modify), `plugins/claudio-routines/runtime/providers/README.md` (modify), `plugins/claudio-routines/README.md` (modify)
- **Verify**: `for d in scripts plugins/claudio-routines/runtime plugins/claudio-routines/skills/routines/scripts; do PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s $d; done && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 scripts/leak_check.py --tree`
- **Rules**: BR-53, BR-65
- **Status**: Complete

## Phase 15: Monitor event aggregates

### T-71: Aggregate the alert events where they are read
- The monitors read aggregates the alert events per numeric monitor id where it reads them (TD-29): the adapter for `api`, the connector tool `aggregate_events` for `mcp`, whose plan has that call first and the `execute_code` script second (monitors, discovery and by-id reads, the monitors the aggregate names included). `records.transitions` `{monitor, count, first_ts_ms, last_ts_ms}` over the events inside the window replaces `records.events`; the cursor keeps the newest event time. The `api` events read takes 100 pages of 100 events; the `mcp` aggregate takes 1,000 groups (`partial: group cap`); the search keeps 20 pages.
- Tests: the aggregate per monitor, the window bounds, events without a monitor, a numeric id or a time, the cursor on events outside the window, the `api` page cap at 100 pages and a read past 20 pages, the aggregate call arguments and the two-step plan, the table parse (fixture, sorting, cursor, non-numeric group, group cap, each malformed table, repeated monitor, row count), the script payload checks, the `api` collection equal to the one parsed from a table built from the same events, the script under node, the schema, and the features values equal to those computed from the raw event list.
- **Refs**: US-19, AC-19.8, AC-14.5, AC-15.2, TD-20, TD-21, TD-26, TD-29
- **Files**: `.claude-plugin/marketplace.json` (modify), `docs/features/routines-as-code/design.md` (modify), `docs/features/routines-as-code/tasks.md` (modify), `plugins/claudio-routines/.claude-plugin/plugin.json` (modify), `plugins/claudio-routines/README.md` (modify), `plugins/claudio-routines/runtime/collect.py` (modify), `plugins/claudio-routines/runtime/evaluate.py` (modify), `plugins/claudio-routines/runtime/evaluate_support.py` (modify), `plugins/claudio-routines/runtime/features.py` (modify), `plugins/claudio-routines/runtime/fixtures/tribe/pipeline_collections.json` (modify), `plugins/claudio-routines/runtime/providers/README.md` (modify), `plugins/claudio-routines/runtime/providers/_errors.py` (modify), `plugins/claudio-routines/runtime/providers/datadog.py` (modify), `plugins/claudio-routines/runtime/providers/datadog_support.py` (modify), `plugins/claudio-routines/runtime/providers/fixtures/datadog/aggregate_events.txt` (create), `plugins/claudio-routines/runtime/providers/fixtures/datadog/relay_discovery.json` (modify), `plugins/claudio-routines/runtime/providers/fixtures/datadog/relay_monitor_errors.json` (modify), `plugins/claudio-routines/runtime/providers/fixtures/datadog/relay_monitors.json` (modify), `plugins/claudio-routines/runtime/providers/fixtures/datadog/script_template.js` (modify), `plugins/claudio-routines/runtime/providers/test_datadog.py` (modify), `plugins/claudio-routines/runtime/providers/test_datadog_relay.py` (modify), `plugins/claudio-routines/runtime/roles.py` (modify), `plugins/claudio-routines/runtime/test_collect.py` (modify), `plugins/claudio-routines/runtime/test_evaluate.py` (modify), `plugins/claudio-routines/runtime/test_features.py` (modify), `plugins/claudio-routines/runtime/test_roles.py` (modify), `plugins/claudio-routines/runtime/tribe_support.py` (modify)
- **Verify**: `for d in scripts plugins/claudio-routines/runtime plugins/claudio-routines/skills/routines/scripts; do PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s $d; done && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 scripts/leak_check.py --tree`
- **Rules**: BR-28
- **Status**: Complete (live check over a 63-hour window: 28 monitors, 3,748 events, aggregate call 7 s, monitors script 26 s)

## Phase 16: Monitor priority and seed fixes

### T-72: Take a null monitor priority from the name
- A monitor whose record priority is null takes the digit 1 to 5 of a leading `[P<n>]` in its name (case-insensitive, exact brackets, only at the start of the name); a record priority always wins, and a name without the prefix keeps a null priority. In `features.py`, shared by the watch and tribe engines; the discovery search returns no priority, so the discovered monitors rely on it.
- Tests: the prefix read as 1 to 5, a lower-case prefix, an API priority kept over the name, no priority for `[P6]`, `[P0]`, `[P12]`, `[P2`, `[P 2]`, a prefix after other text, a leading space or a trailing prefix, and the values of a monitor without the prefix unchanged.
- **Refs**: US-18, US-19, AC-18.1, AC-19.2, TD-26
- **Files**: `.claude-plugin/marketplace.json` (modify), `docs/features/routines-as-code/design.md` (modify), `docs/features/routines-as-code/tasks.md` (modify), `plugins/claudio-routines/.claude-plugin/plugin.json` (modify), `plugins/claudio-routines/runtime/features.py` (modify), `plugins/claudio-routines/runtime/providers/README.md` (modify), `plugins/claudio-routines/runtime/test_features.py` (modify)
- **Verify**: `for d in scripts plugins/claudio-routines/runtime plugins/claudio-routines/skills/routines/scripts; do PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s $d; done && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 scripts/leak_check.py --tree`
- **Status**: Complete

### T-73: Seed the blind spot runs from a map
- `tribe.py seed` reads `blind_spot_runs` from the top level of the Run state, else from `run.blind_spot_runs`, as a list of `{key, gap, runs}` or a map `{<gap key>: <runs>}`. A map entry becomes `{key, gap, runs}` with the key cleaned and cut to 60 characters, also used as the gap; an entry with an empty key or runs that is not an integer of at least 1 is skipped with one stderr line `seed: blind_spot_runs.<key> skipped: <reason>`; a value of another type is rejected with its key path. The seeded state passes `check_state`.
- Tests: a map at the top level and under `run`, the top level winning over `run`, a list at either place, an empty map, a key cleaned and cut, entries skipped with their stderr line next to a kept one, a value that is neither a list nor a map rejected with its path, the seeded state accepted by `check_state`.
- **Refs**: US-33, TD-47
- **Files**: `docs/features/routines-as-code/design.md` (modify), `docs/features/routines-as-code/tasks.md` (modify), `plugins/claudio-routines/runtime/test_tribe_seed.py` (modify), `plugins/claudio-routines/runtime/tribe_seed.py` (modify)
- **Verify**: `for d in scripts plugins/claudio-routines/runtime plugins/claudio-routines/skills/routines/scripts; do PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s $d; done && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 scripts/leak_check.py --tree`
- **Status**: Complete

### T-74: Date the month-end check group on the page
- `tribe.py render` titles the second check group `Before the <YYYY-MM-DD> month-end`, the last day of the month of `run_at` in the config timezone (TD-52); `tribe_page.render` takes that zone. The stored group value stays `Before the month-end`. The structure check accepts the dated heading when its date is the last day of a month, and the undated heading of pages already written; any other heading still fails. `parse_edits` and `page_markdown` read to-dos under either heading.
- Tests: the heading of a run on 2026-10-19 in Paris, a run late on the last day in UTC that is the next month in Paris, the same run in UTC, a leap and a common February, the other groups unchanged, the check on a dated page, an undated page, a leap-day date, a date that is not a month end, a date that does not exist, another ending and a malformed date, the to-dos read under either heading in `parse_edits` and in the collection blocks, the render command in the config timezone, the golden page.
- **Refs**: US-39, TD-52
- **Files**: `docs/features/routines-as-code/design.md` (modify), `docs/features/routines-as-code/tasks.md` (modify), `plugins/claudio-routines/runtime/fixtures/tribe/page_golden.md` (modify), `plugins/claudio-routines/runtime/test_tribe_features.py` (modify), `plugins/claudio-routines/runtime/test_tribe_lifecycle.py` (modify), `plugins/claudio-routines/runtime/test_tribe_page.py` (modify), `plugins/claudio-routines/runtime/test_tribe_publish.py` (modify), `plugins/claudio-routines/runtime/tribe_page.py` (modify), `plugins/claudio-routines/runtime/tribe_publish.py` (modify), `plugins/claudio-routines/runtime/tribe_state.py` (modify)
- **Verify**: `for d in scripts plugins/claudio-routines/runtime plugins/claudio-routines/skills/routines/scripts; do PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s $d; done && python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --public && python3 scripts/leak_check.py --tree`
- **Status**: Complete

## Related Features

- **onboarding (claudio-spec skill)**: its examples are made generic in a separate commit that lands before this feature.
  - **Shared state**: the allowlist entry `commit:174491e deny-word` in `scripts/leak-allow.txt`, and the marketplace version, bumped to 2.12.1 by that commit and to 2.13.0 by this feature.
  - **Risk**: the history scan fails if that commit is rewritten or the entry is removed.
- **Live claude.ai routines**: Prod watch's stored prompt and the default environment's setup script.
  - **Shared state**: the state schema 2, seeded from the current state page into `state/prod-watch.json`, and the sources page of the document store.
  - **Risk**: syncing `prod-watch-runtime` before the tag, the setup script and the seeded state exist makes every run degraded or baseline.
- **Private repository config**: the shape changes in T-26 (`places` replaces `runtime.dir` and `values.state.dir`) and gains `providers`, `sources` and the query pack.
  - **Shared state**: the sources page's metrics and thresholds move into the query pack; the page keeps the mutes table.
  - **Risk**: a sync rendered from the old shape fails at render, and a query pack that drifts from the page's last thresholds changes which items open.
  - **Shared state, model judgment**: the query pack version 2 replaces thresholds, severities and urgencies with prose rules (T-34, T-43).
  - **Risk**: a pack written before T-34 fails validation with exit 3 until it moves to version 2; the live routine is unaffected until a sync.
  - **Shared state, config split**: Prod watch moves to `config/routines/prod-watch.json`, and the sources take their providers' default transport (T-51).
  - **Risk**: a runtime pinned before T-47 finds no routine in a split config and exits 2, so T-31 pins a tag that holds T-47.
- **Mirrored live routines**: the 4 other routines' stored prompts and crons.
  - **Shared state**: their snapshots in the private repository, compared with the mirrors' renders.
  - **Risk**: a sync from a mirror that is not byte-identical changes a live prompt, so `diff` must print `in sync` for each before any sync.
