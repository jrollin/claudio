# Routines as Code: Tasks

---
feature: routines-as-code
spec_version: 1
total_tasks: 59
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
5. Seed `state/prod-watch.json` on the `claude/state` branch from the current state page, with its provider-named cursor key renamed to `cursors.observability`.
6. Run `/routines run prod-watch` without `--post`: the record reaches `claude/state`, the state does not change, the digest is printed.
7. Switch `routines.prod-watch.template` to `prod-watch-runtime`.
8. Run `/routines sync prod-watch`.
- **Refs**: US-8, US-11, TD-12, TD-15
- **Files**: none in this repository; the private repository's `config.json` changes
- **Verify**: `python3 plugins/claudio-routines/skills/routines/scripts/routines.py lint --private "$CLAUDIO_PRIVATE_DIR" && python3 plugins/claudio-routines/skills/routines/scripts/routines.py diff prod-watch`
- **Blocked by**: T-15, T-17, T-18, T-31, T-43
- **Rules**: BR-6, BR-7, BR-15, BR-23, BR-25
- **Status**: Not Started

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
- **Status**: In Progress (config shape migrated locally, live prompt still in sync; the local runtime remains)

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
- **Status**: In Progress (all 5 routines split into routine files and mirrored, `diff` in sync for all 5, `check-env` exit 0 in both places; `lint --private` waits for the runtime pin of T-31)

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
