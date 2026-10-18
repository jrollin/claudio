---
name: routines
description: Manage claude.ai routines (scheduled cloud agents) as code. Export the live routines into a private repository, render their prompts from templates, show drift between git and live, lint templates, push a rendered prompt after an explicit approval, and run a routine locally in this session. Use for "/routines", "export my routines", "is my routine in sync", "diff routines", "sync the routine", "push the routine prompt", "render the routine", "lint routine templates", "print the environment setup script", "run prod watch locally", "run the routine here". NOT for creating or deleting routines, and NOT for reading a routine's run logs.
---

# Routines

Git is the source of truth for routine prompts. The real templates and values live in a private repository; this plugin ships the scripts and generic skeletons.

```text
/claudio-routines:routines export
/claudio-routines:routines diff [slug]
/claudio-routines:routines render <slug> [--place cloud|local] [--post]
/claudio-routines:routines lint
/claudio-routines:routines sync <slug>
/claudio-routines:routines setup-script [--place cloud|local]
/claudio-routines:routines run <slug> [--since T] [--post]
```

`R` below is `python3 ${CLAUDE_PLUGIN_ROOT}/skills/routines/scripts/routines.py`.

## Preconditions

1. The private repository path comes from `CLAUDIO_PRIVATE_DIR`. When it is unset, ask the owner for the path and pass it as `--private <path>` to every command.
2. Run `R check-private` before any `RemoteTrigger` call. On exit 2, stop and show its message: the path is missing, or it sits inside another repository's working tree.
3. Load the `RemoteTrigger` tool with ToolSearch (`select:RemoteTrigger`) when it is deferred.

## Export

1. Call `RemoteTrigger` with `action: "list"`.
2. When the result says it was saved to a file, use that path. Otherwise write the full result, first line included, to a file in a directory made with `mktemp -d`, outside any repository.
3. Run `R export --input <file>`.
   - Exit 2 names the HTTP status, the routine or the path that failed; stop and report it. Nothing was written.
4. Report the exported slugs. The snapshots are `routines/<slug>.json` and `routines/<slug>.prompt.md` in the private repository.

## Diff

1. Run Export first, so the comparison is against live, never against an old snapshot.
2. Run `R diff [slug]`.
   - Exit 0: every compared routine prints `in sync`; `untracked` lines are live routines with no template, for information.
   - Exit 1: show the diff of each drifting field (prompt, cron) and the `not exported` routines.
   - Connectors, model and tools print as information lines, never as drift.

## Render

Run `R render <slug> [--place cloud|local] [--post]`.

- `--place` picks the place whose `runtime_dir` and `state_dir` fill the prompt, `cloud` by default.
- The rendered prompt posts its digest for the cloud place, and for the local place only with `--post`.
- Exit 2 names the unresolved placeholder and its template.
- Warnings name values the routine's template does not use.

## Lint

- Public skeletons: `R lint --public`.
  - It checks every `state.py`, `collect.py`, `evaluate.py` and `digest.py` command and flag against this checkout's runtime.
  - It fails a provider name (`provider-name`: a module name under `runtime/providers/`) in the skeletons, the plugin README and this file.
- Private templates: `R lint --private <path> [--claudio <checkout>]`. It checks every `state.py`, `collect.py`, `evaluate.py` and `digest.py` command and flag against the runtime at the pinned tag, so the tag must exist in a local claudio checkout. Pass `--claudio` when the plugin runs from the plugin cache.
- Each finding prints `path:line:rule`.

## Sync

Pushes one routine's rendered prompt and cron. Never push without the owner's explicit approval of the diff shown in this session.

1. Run Export, then `R diff <slug>`.
   - Exit 0: report `in sync` and stop.
2. Generate one UUID (`python3 -c "import uuid; print(uuid.uuid4())"`) and run `R body <slug> --uuid <uuid> > <dir>/before.json`, in a `mktemp -d` directory outside any repository. It prints `{"trigger_id": ..., "body": ...}`, built from the fresh snapshot, so connectors, environment and tools stay as they are live.
3. Show the full diff and ask the owner to approve the push for this routine. Wait for an explicit approval. Anything else stops the sync with nothing pushed.
4. After the approval, run `R body <slug> --uuid <uuid> > <dir>/after.json` with the same UUID and compare the body built before and after approval with `cmp <dir>/before.json <dir>/after.json`.
   - Different: a template, the config or the snapshot changed during the wait. Stop with nothing pushed and run Sync again.
5. Call `RemoteTrigger` with `action: "update"`, the `trigger_id` and the `body` of `after.json`, unchanged.
   - An HTTP error stops the sync for this routine and leaves the others untouched. Report the status.
6. Run Export again, then `R diff <slug>`.
   - Exit 0: the sync succeeded.
   - Exit 1: the sync failed. Show the residual diff.
7. Report the routine link from the update result and the next run time.

## Setup script

1. Run `R setup-script [--place cloud|local]`. It renders the setup script from `runtime.repo`, `runtime.tag`, `runtime.sha` and `places.<place>.runtime_dir`, `cloud` by default. Exit 2 names an invalid value.
2. Show the script.
   - `cloud`: the owner pastes it into the setup script of the cloud environment at claude.ai; no API sets it.
   - `local`: the owner runs it once on this machine, after each runtime bump.
3. For a runtime bump, follow the bump procedure in the plugin README, then run Sync for each routine that uses the runtime.

## Run

Runs one routine in this session for the local place, with the same template, state branch and runtime as a cloud run. Without `--post`, the run reports only: it pushes its run record, leaves the state unchanged and prints the digest.

1. Run `R check-private`. On exit 2, stop and show its message.
2. Read `places.local.runtime_dir`, `places.local.state_dir` and `runtime.sha` from the private `config.json`, then run `git -C <runtime_dir> rev-parse HEAD` and `git -C <runtime_dir> status --porcelain --ignored`.
   - `rev-parse` fails or prints another hash than `runtime.sha`, or `status` prints anything: tell the owner to run `R setup-script --place local` and run its output, then stop.
   - `places.local.state_dir` does not resolve to the private repository path of the Preconditions (compare the `realpath` of both): tell the owner to set `places.local.state_dir` to that path, then stop.
3. Render the local place into a file of a `mktemp -d` directory outside any repository: `R render <slug> --place local --out <dir>/prompt.md`, with `--post` added only when the owner passed it.
   - Exit 2 names the problem: stop and report it.
4. Run `python3 -B <runtime_dir>/plugins/claudio-routines/runtime/collect.py check-env --config <state_dir>/config.json --routine <slug> --place local`.
   - Each `missing <source> <variable>` line: tell the owner which variable is missing and which source it leaves not read.
   - Each `connector <source> <connector>` line: check that this session lists a tool from that connector, and name the missing ones.
   - Exit 2 or 3: show the error and stop.
5. Follow the rendered prompt in this session, step by step. With `--since T`, give it `T` as the run's start time, in UTC (`YYYY-MM-DDTHH:MM:SSZ`).

Never post to the chat channel without `--post`: the rendered prompt then prints the digest in this session.

## After any command

The private repository changed when Export ran. Offer to commit it there; never commit in this repository on its behalf.
