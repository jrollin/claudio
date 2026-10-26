---
name: routines
description: Manage claude.ai routines (scheduled cloud agents) as code. Export the live routines into a private repository, render their prompts from templates, show drift between git and live, lint templates, push a rendered prompt after an explicit approval, seed a tribe routine's state from its previous digest pages or a recap routine's state from its stored state, and run a routine locally in this session. Use for "/routines", "export my routines", "is my routine in sync", "diff routines", "sync the routine", "push the routine prompt", "seed the tribe state", "render the routine", "lint routine templates", "print the environment setup script", "run prod watch locally", "run the routine here". NOT for creating or deleting routines, and NOT for reading a routine's run logs.
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
/claudio-routines:routines seed <slug>
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

- `--place` picks the place whose `runtime_dir`, `state_dir` and `runs_dir` fill the prompt, `cloud` by default.
- `runs_dir` is optional; without it the prompt creates its run folder under `/tmp`.
- The rendered prompt posts its digest for the cloud place, and for the local place only with `--post`.
- Exit 2 names the unresolved placeholder and its template.
- Warnings name values the routine's template does not use.
- A template whose first line is exactly `<!-- not runnable -->` is marked not runnable. Render keeps that line and warns, naming the template. `--runnable` exits 2 on it, with nothing on stdout and no `--out` file written.

## Lint

- Public skeletons: `R lint --public`.
  - It checks every `state.py`, `collect.py`, `evaluate.py`, `digest.py`, `tribe.py` and `recap.py` command and flag against this checkout's runtime.
  - It fails a provider name (`provider-name`: a module name under `runtime/providers/`) in the skeletons, the plugin README and this file.
- Private templates: `R lint --private <path> [--claudio <checkout>]`. It checks every `state.py`, `collect.py`, `evaluate.py`, `digest.py`, `tribe.py` and `recap.py` command and flag against the runtime at the pinned tag, so the tag must exist in a local claudio checkout. Pass `--claudio` when the plugin runs from the plugin cache.
- Each finding prints `path:line:rule`.
- `lint --private` runs the role check of this checkout's runtime on every routine file, for both places. It exits 2 naming the file and the key path of the first invalid value, and skips a routine whose template does not call the runtime (no `{{runtime.dir}}`): a prompt-only mirror or a template marked not runnable.
- `lint --private` also checks `.claude/settings.json` of the private repository, the file the cloud session reads. It reports at line 1 of that file:
  - `settings-missing`: the file does not exist.
  - `settings-invalid`: the file is not a JSON object.
  - `deny-missing:<entry>`: `permissions.deny` lacks `<entry>`, one finding for each of `PushNotification`, `Bash(sleep *)` and `Monitor`.
- `lint --private` compares each private `<name>-runtime.md` template with the public runnable template `<name>.md` at the pinned runtime commit, and reports at line 1:
  - `runtime-copy-differs:<name>.md`: the copy differs; copy the public template again.
  - `runtime-copy-missing:<name>.md`: the pinned commit has no such public template.
- `marker`: the first line is an HTML comment holding `not runnable` but is not exactly `<!-- not runnable -->`, so the template would stay runnable. Both lints report it at line 1.
- `lint --private` also prints warnings on stderr, naming keys and never values. They leave the exit code unchanged:
  - `literal-value`: a template holds the value of a routine key as literal text. Use the placeholder.
  - `repeated-value`: two routines set the same key to the same value. Move it to the shared values.

## Sync

Pushes one routine's rendered prompt and cron. Never push without the owner's explicit approval of the diff shown in this session.

1. Make a directory with `mktemp -d`, outside any repository, and run `R render <slug> --runnable --out <dir>/prompt.md`. Exit 2 stops the sync with its message, before any API call: the template is marked not runnable, or the render failed.
2. Run Export, then `R diff <slug>`.
   - Exit 0: report `in sync` and stop.
3. Generate one UUID (`python3 -c "import uuid; print(uuid.uuid4())"`) and run `R body <slug> --uuid <uuid> > <dir>/before.json`, in the same directory. It prints `{"trigger_id": ..., "body": ...}`, built from the fresh snapshot, so connectors, environment and tools stay as they are live.
   - `body` exits 2 on a template marked not runnable: stop the sync with its message.
4. Show the full diff and ask the owner to approve the push for this routine. Wait for an explicit approval. Anything else stops the sync with nothing pushed.
5. After the approval, run `R body <slug> --uuid <uuid> > <dir>/after.json` with the same UUID and compare the body built before and after approval with `cmp <dir>/before.json <dir>/after.json`.
   - Different: a template, the config or the snapshot changed during the wait. Stop with nothing pushed and run Sync again.
6. Call `RemoteTrigger` with `action: "update"`, the `trigger_id` and the `body` of `after.json`, unchanged.
   - An HTTP error stops the sync for this routine and leaves the others untouched. Report the status.
7. Run Export again, then `R diff <slug>`.
   - Exit 0: the sync succeeded.
   - Exit 1: the sync failed. Show the residual diff.
8. Report the routine link from the update result and the next run time.

## Setup script

1. Run `R setup-script [--place cloud|local]`. It renders the setup script from `runtime.repo`, `runtime.tag`, `runtime.sha` and `places.<place>.runtime_dir`, `cloud` by default. Exit 2 names an invalid value.
2. Show the script.
   - `cloud`: the owner pastes it into the setup script of the cloud environment at claude.ai; no API sets it.
   - `local`: the owner runs it once on this machine, after each runtime bump.
3. For a runtime bump, follow the bump procedure in the plugin README, then run Sync for each routine that uses the runtime.

## Run

Runs one routine in this session for the local place, with the same template, state branch and runtime as a cloud run. Without `--post`, the run reports only: it pushes its run record, leaves the state unchanged and prints the digest.

1. Run `R check-private`. On exit 2, stop and show its message.
   - The session must start in `CLAUDIO_PRIVATE_DIR`: Claude Code reads the relay hook from that repository's `.claude/settings.json` only in a session started there. In any other session, stop and tell the owner to restart it in the private repository.
   - The shell that starts the session must export `CLAUDIO_RUNTIME_DIR` as `places.local.runtime_dir`, or the relay hook captures nothing.
2. Read `places.local.runtime_dir`, `places.local.state_dir` and `runtime.sha` from the private `config.json` (a routine may sit in `config/routines/<slug>.json` beside it), then run `git -C <runtime_dir> rev-parse HEAD` and `git -C <runtime_dir> status --porcelain --ignored`.
   - `rev-parse` fails or prints another hash than `runtime.sha`, or `status` prints anything: tell the owner to run `R setup-script --place local` and run its output, then stop.
   - `places.local.state_dir` does not resolve to the private repository path of the Preconditions (compare the `realpath` of both): tell the owner to set `places.local.state_dir` to that path, then stop.
3. Render the local place into a file of a `mktemp -d` directory outside any repository: `R render <slug> --place local --runnable --out <dir>/prompt.md`, with `--post` added only when the owner passed it.
   - Exit 2 names the problem, including a template marked not runnable: stop and report it.
4. Run `python3 -B <runtime_dir>/plugins/claudio-routines/runtime/collect.py check-env --config <state_dir>/config.json --routine <slug> --place local`.
   - Each `missing <source> <variable>` line: tell the owner which variable is missing and which source it leaves not read.
   - Each `connector <source> <connector>` line: check that this session lists a tool from that connector, and name the missing ones.
   - Each `fallback <source> <from> <to> <variable>` line: the source is read through `<to>`; report nothing for it.
   - Each `injected <source> <host>` line: the place's proxy adds that source's credential; report nothing for it.
   - Exit 2 or 3: show the error and stop.
5. Follow the rendered prompt in this session, step by step. With `--since T`, give it `T` as the run's start time, in UTC (`YYYY-MM-DDTHH:MM:SSZ`).
   - The prompt creates the run folder under `places.local.runs_dir` (`/tmp` without it) and keeps it, raw results included.

Never post to the chat channel without `--post`: the rendered prompt then prints the digest in this session.

## Seed

Seeds the state of a routine whose engine is `tribe` from its previous digest pages, or whose engine is `recap` from the state its live routine kept in the document store, so the first runtime run continues their keys. The seeded state stays in a scratch directory until the owner approves it. Never push the state without the owner's explicit approval of the summary shown in this session.

`<private>` below is the private repository path of the Preconditions.

1. Run `R check-private`. On exit 2, stop and show its message.
2. Ask the owner for the previous digest pages of the routine, newest first, as page ids or links. Make a directory `<dir>` with `mktemp -d`, outside any repository, and fetch each page with the document store connector.
   - When the result says it was saved to a file, copy that file to `<dir>/page-<n>.json`. Otherwise write the full result, first line included, to that path. `<n>` counts from 1, newest first.
   - A `recap` routine takes no digest pages: ask for the page that holds the stored state, fetch it the same way, and write the JSON of its state to `<dir>/source.json`.
3. Run `R seed <slug> --page <dir>/page-1.json [--page <dir>/page-2.json ...] --out <dir>/state.json`, the pages newest first. It runs the seed command of the runtime checked out at `runtime.sha` in `places.local.runtime_dir`, so the state matches the version that reads it.
   - A `recap` routine runs `R seed <slug> --from <dir>/source.json --out <dir>/state.json` instead: the state is named after the routine's `values.digest.name`, else its slug, and each unit keeps its kind, channel, status, waiting runs and lateness with its title cut to 8 words; links, blind spots and run bookkeeping are dropped.
   - The runtime directory is missing, at another commit or not clean: tell the owner to run `R setup-script --place local` and run its output, then stop.
   - Exit 2 or 3 stops the seed with its message and nothing written: the routine's engine is not `tribe` or `recap`, the input flag does not fit the engine (`--page` for `tribe`, `--from` for `recap`), the config is invalid, no page holds a valid run state (each page read is named), a run state holds a field outside the allowed values, a warning `status` excepted (its key path is named), or a stored `recap` unit cannot be mapped (its key path `units.<key>.<field>` is named).
   - A page without a valid run state is named on stderr with its reason and skipped; the next page seeds the state.
   - A warning `status` other than `open`, `in progress`, `mitigated`, `decided` or `dropped` is read as the one it starts with, else as `open`. Each reading is printed on stderr: show those lines with the summary of step 5.
4. Run `git -C <private> fetch origin +claude/state:refs/remotes/origin/claude/state`, then `git -C <private> cat-file -e origin/claude/state:state/<slug>.json`.
   - The fetch fails or finds no `claude/state` branch: stop the seed with nothing pushed, and tell the owner the branch does not exist.
   - `cat-file` exits 0: the push replaces the stored state of the routine. Say so.
5. Show the summary printed by step 3 and where the state goes, `state/<slug>.json` on `claude/state`. Ask the owner to approve the push for this routine. Wait for an explicit approval. Anything else ends the seed with nothing pushed.
6. After the approval, save the state with a fast-forward push through a work tree under `<dir>`, `git -C <dir>/store push origin HEAD:refs/heads/claude/state`, as one command:

   ```bash
   git -C <private> worktree add --detach <dir>/store origin/claude/state && \
     mkdir -p <dir>/store/state && \
     cp <dir>/state.json <dir>/store/state/<slug>.json && \
     git -C <dir>/store add state && \
     git -C <dir>/store commit -q -m "seed <slug>" && \
     git -C <dir>/store push origin HEAD:refs/heads/claude/state
   ```

   - A rejected push means the branch moved: report that the state is not saved and run Seed again. Never force the push.
   - Whatever the command exited with, run `git -C <private> worktree remove --force <dir>/store`.
7. Run the fetch of step 4 again, then `git -C <private> show origin/claude/state:state/<slug>.json | cmp - <dir>/state.json`.
   - Exit 0: report the routine seeded.
   - Exit 1: report the state not saved.

## After any command

The private repository changed when Export ran. Offer to commit it there; never commit in this repository on its behalf.
