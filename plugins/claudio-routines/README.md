# claudio-routines

Manage claude.ai routines (scheduled cloud agents) as code:
- Render each routine's prompt from a template and private values.
- Show drift between git and the live routine.
- Push a rendered prompt after an explicit approval.
- Give routine runs a tested state engine for windows, item lifecycle and cursors.
- Collect each source with a script, through the provider's HTTPS API or a connector.
- Run a routine locally in a Claude Code session, with the same template, runtime and state as a cloud run.

## Components

| Part | Path | Role |
|---|---|---|
| `/routines` skill | `skills/routines/SKILL.md` | Export, diff, render, lint, sync, setup-script and run flows over Claude's `RemoteTrigger` tool |
| `routines.py` | `skills/routines/scripts/routines.py` | File side of every flow: snapshots, render, diff, lint, update body, setup script |
| Skeletons | `skills/routines/templates/` | Generic `prod-watch.md` prompt and `setup-env.sh` setup script, placeholders only |
| State engine | `runtime/state.py` | Run window, item lifecycle, blind spots, mutes and run records for routine runs |
| Collector | `runtime/collect.py` | Lists a routine's sources, checks the place's credentials and connectors, reads one source per command into a collection |
| Evaluator | `runtime/evaluate.py` | `features` computes the judgment features, `judge` checks the model's judgment and merges it into the facts, `annotate` adds the analysis of new and escalated items |
| Digest | `runtime/digest.py` | Renders the posted message as Markdown from the change summary, the next state, the run record and the base file; the model posts it unchanged |
| Features | `runtime/features.py` | Computes the features, base and rules files of one run; decides nothing |
| Judgment | `runtime/judgment.py` | Checks the judgment and the analysis against the features, and builds the facts |
| Roles | `runtime/roles.py` | Config and query pack checks, and the record schema of each role |
| Provider adapters | `runtime/providers/` | One module per vendor, each with an `api` and an `mcp` transport; see [the providers README](runtime/providers/README.md) |

The real templates and every value that names a company resource live in a private repository, never here.

## Prerequisites

- Python 3.10.12 or later: `lint --private` needs it to extract the pinned runtime safely.
- `git`.
- Claude Code with this plugin installed (`/plugin install claudio-routines`) and access to the `RemoteTrigger` tool.
- A private git repository for templates, config and snapshots, outside any other repository's working tree.
- For local runs:
  - The credential variables of every `api` source of the `local` place, in the shell that starts Claude Code.
  - The connector of every `mcp` source of the `local` place, in the Claude Code session.

## Setup

1. Create the private repository, for example `gh repo create <owner>/claudio-private --private --clone`.
2. Export its path in your shell profile: `export CLAUDIO_PRIVATE_DIR=<path to the clone>`.
3. Copy `config.example.json` to `$CLAUDIO_PRIVATE_DIR/config.json` and fill in the values.
4. Add your templates under `$CLAUDIO_PRIVATE_DIR/templates/<template>.md`. A routine without a private template renders from the public skeleton of the same name.
5. Run `/claudio-routines:routines export`, then `/claudio-routines:routines diff` until each configured routine prints `in sync`.
6. For local runs, run `/claudio-routines:routines setup-script --place local` and run its output.

## Usage

```text
/claudio-routines:routines export                                  snapshot every live routine into the private repository
/claudio-routines:routines diff [slug]                             export, then compare rendered prompt and cron with live
/claudio-routines:routines render <slug> [--place P] [--post]      print a routine's rendered prompt for a place, cloud by default
/claudio-routines:routines lint                                    lint the public skeletons, or the private templates
/claudio-routines:routines sync <slug>                             show the diff, wait for approval, push, export again, confirm in sync
/claudio-routines:routines setup-script [--place P]                print the setup script of a place, cloud by default
/claudio-routines:routines run <slug> [--since T] [--post]         run a routine in this session for the local place
```

Each flow is described step by step in [SKILL.md](skills/routines/SKILL.md).

Exit codes of `routines.py`, `state.py`, `collect.py`, `evaluate.py` and `digest.py`:
- 0: ok or in sync.
- 1: findings or drift; for `collect.py check-env`, a missing credential variable.
- 2: usage or input error, including an unreadable or invalid features, base, facts, preview, summary, record or state file; `digest.py` exits 2 for every refused input, naming the file.
- 3 (runtime scripts only): rejected state, facts, time or query pack; for `evaluate.py judge` and `annotate`, a rejected judgment or analysis, including a file that is not valid JSON.

## Config reference

`$CLAUDIO_PRIVATE_DIR/config.json`:

| Key | Meaning |
|---|---|
| `timezone` | IANA zone for windows and labels, for example `Europe/Paris`, matching `^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+)*$` |
| `runtime.repo` | HTTPS clone URL of this repository, with no user info, query or fragment |
| `runtime.tag` | Release tag the runs use |
| `runtime.sha` | Full commit hash of that tag (`git rev-parse <tag>^{commit}`), checked before any run uses the runtime |
| `places.<place>` | `cloud` or `local` |
| `places.<place>.runtime_dir` | Where the setup script installs the runtime in that place: absolute, at least two levels below the root, no `.` or `..` component, last component starting with `claudio-runtime` (for example `/opt/claudio-runtime`) |
| `places.<place>.state_dir` | Absolute path of the private repository checkout in that place |
| `providers.<name>` | One provider; sources point at it by `<name>` |
| `providers.<name>.adapter` | Module name of its adapter under `runtime/providers/` |
| `providers.<name>.api.base_url` | HTTPS base URL of the provider API, with no user info, query or fragment: the only host the adapter calls |
| `providers.<name>.api.credentials` | Name of the environment variable of each credential, never its value |
| `providers.<name>.mcp.connectors.<place>` | Name of the provider's connector in that place |
| `providers.<name>.links_base` | Optional HTTPS base of the provider's web UI, for record links; set it for a provider read only through a connector |
| `values` | Render-time values shared by every routine |
| `routines.<slug>` | One tracked routine; `<slug>` is the live routine name in lowercase with hyphens, as `export` prints it |
| `routines.<slug>.id` | Routine id, from the export |
| `routines.<slug>.template` | Template name, without `.md` |
| `routines.<slug>.cron` | Cron expression pushed by sync |
| `routines.<slug>.values` | Values of that routine only, applied over `values` |
| `routines.<slug>.sources.<source>` | One source of the routine; `<source>` matches `^[a-z][a-z0-9-]*$` and names its collection file |
| `routines.<slug>.sources.<source>.provider` | A key of `providers` |
| `routines.<slug>.sources.<source>.transport.cloud` | `api` or `mcp`: how cloud runs read the source |
| `routines.<slug>.sources.<source>.transport.local` | `api` or `mcp`: how local runs read the source |
| `routines.<slug>.query_pack` | Entries the evaluator turns into features, each with a prose rule (see below) |
| `routines.<slug>.rules` | Routine-wide judgment rules, for example flapping, discovered monitors and No Data: a list of texts of at most 500 characters |
| `routines.<slug>.models` | Model names of the run, copied into the facts |

A source also holds the options of its provider's role:

| Role | Option | Meaning |
|---|---|---|
| Observability tool | `kind` | `monitors` or `metrics` |
| Observability tool | `scope_filter` | Query of the alert event search of a `monitors` source, such as `source:alert env:prod`; a `metrics` source ignores it, since its pack queries carry their own scope |
| Observability tool | `discovery_query` | Optional monitor search query of a `monitors` source: the monitors it finds are judged under `monitor-<id>` even when the pack lacks them; without it nothing is discovered; a `metrics` source refuses it |
| Document store | `page_id` | The sources page that holds the mutes table: a top-level `Mutes` heading followed by a table with the columns `key` and `until` (or `silence until`, never both), never nested inside a toggle heading |
| Chat channel | `channels` | A non-empty list of channels |
| Code host | `repos` | A non-empty list of `owner/name` repositories |
| Code host | `query` | Optional search query; a source with a non-empty one is not read, since neither transport takes a search query |

Query pack entry fields:

| Field | Entry | Meaning |
|---|---|---|
| `key` | every entry | Unique; `monitor-<monitor>` for a monitor entry, never starting with `monitor-` for a metric entry |
| `source` | every entry | An observability source of the routine |
| `title`, `link` | every entry | Shown in the digest |
| `rule` | every entry | The judgment rule of this entry: a text of at most 500 characters, read by the model |
| `schedule` | every entry | `every_run`, or `daily` for the first run of each local day |
| `monitor` | monitor | The monitor id, digits only |
| `query` | metric | The query, in the provider's dialect |
| `read` | metric | `scalar`, `top` or `hourly` |
| `aggregator` | metric | The query's aggregator |
| `top` | metric with `read` `top` | Number of groups to read; each group is judged under its own key |
| `excluded_hours` | metric with `read` `hourly` | Optional list of local hours, 0 to 23, whose buckets never count toward the value |
| `lookback_days` | metric with `schedule` `daily` | Optional span of 1 to 31 days, ending at the window end, read as daily buckets or aggregated; not with `excluded_hours` |

Entries match this schema exactly: `severity`, `urgency` and `threshold` are rejected (`collect.py` and `evaluate.py` exit 3 naming the key path). The model sets severity and urgency per run, from the rules.

Config checks:
- `places.cloud` and `places.local` are both required.
- `places.<place>.runtime_dir` and `places.<place>.state_dir` match `^(/[A-Za-z0-9._-]+)+/?$`, with no `.` or `..` component, since the template uses them unquoted in shell commands.
- `timezone` matches `^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+)*$`, since the template uses it unquoted in shell commands.
- `runtime.dir`, a shared `values.state.dir` and a routine `values.state.dir` are refused; their values belong in `places.<place>.runtime_dir` and `places.<place>.state_dir`.
- A template name matches `^[a-z0-9-]+$`.
- Credential variable names match `^[A-Z][A-Z0-9_]*$`.
- A query pack key equal to a source name is an invalid pack (`collect.py` and `evaluate.py` exit 3): source names and pack keys share the blind spot keys.

Templates use `{{dotted.key}}` placeholders; `\{{` renders a literal `{{`. Render adds `runtime.*`, `timezone`, and for the rendered place:
- `runtime.dir` and `state.dir`, from `places.<place>`.
- `place`: `cloud` or `local`.
- `run.post`: `yes` for the cloud place, `yes` for the local place only with `--post`, `no` otherwise.

## Collectors

Each source has one transport per place, set in `routines.<slug>.sources.<source>.transport`:
- `api`: `collect.py fetch` calls the provider's HTTPS API from the place that runs the routine.
- `mcp`: a relay loop.
  - `collect.py plan` writes the next connector calls.
  - The model makes each call and saves each result unchanged.
  - `collect.py parse` turns the saved results into the collection.

Reads:
- Each source writes one collection, `<run>/collections/<source>.json`, in the record schema of its role.
- A source that cannot be read is marked not read, with a reason, and the other sources are still collected.
- A failed read never switches to the other transport.
- A relay loop ends after 20 pages of one query, a repeated cursor or 50 calls for one source; the source is then not read, with a reason starting `partial:`.

Credentials:
- Credentials live only in environment variables; the config names each variable, never its value.
- `local` reads them from the shell that starts Claude Code.
- `cloud` reads them from the cloud environment's variables at claude.ai.
- An adapter calls only the host of its `api.base_url`; the cloud environment must allow that host.
- [The providers README](runtime/providers/README.md) lists, per vendor, the credential variables, the read-only scope to create and the hosts to allow.

```text
python3 runtime/collect.py sources   --config C --routine R --place P
python3 runtime/collect.py check-env --config C --routine R --place P
python3 runtime/collect.py fetch     --config C --routine R --source NAME --place P --window W --state S --out COLLECTION
python3 runtime/collect.py plan      --config C --routine R --source NAME --place P --window W --state S --responses DIR --out PLAN
python3 runtime/collect.py parse     --config C --routine R --source NAME --place P --window W --state S --responses DIR --out COLLECTION
python3 runtime/evaluate.py features --config C --routine R --state S --window W --collections DIR --place P --runtime SHA --out FEATURES --base-out BASE --rules-out RULES
python3 runtime/evaluate.py judge    --features FEATURES --base BASE --judgment J --out F
python3 runtime/evaluate.py annotate --features FEATURES --facts F --analysis A --preview SUMMARY --out F
```

`collect.py` also reads one source outside any routine run, with a window from `state.py window --since` over a state from `state.py init`.

Discovery:
- A `monitors` source with a `discovery_query` also searches the monitors that match it.
- Each tracked `monitor-<id>` key is read by id until its item resolves, whether it came from the pack or from discovery.
- A failed or capped discovery, or a failed by-id read of an event-named monitor other than not found, adds the blind spot `discovery incomplete` and leaves the by-id reads counted as read.
- A monitor named by an alert event of the window that is outside the pack, untracked and not found by the search is read by id and reaches the model with its state and transitions, even when it is `OK` at run time; at most 50 per run, the excess adding `event monitors capped at 50` to the source's blind spot.

## Judgment

A routine run decides its facts in these steps. The scripts set every value; the model sets only the verdicts and the analysis.

1. `evaluate.py features` writes `features.json` (named numbers per key), `base.json` (everything of the facts except the observations) and `rules.json` (the pack's rules and the routine-wide rules). It decides nothing.
2. The model reads `features.json` and `rules.json` only, and writes `judgment.json`: one verdict per observed key with `open`, `severity`, `urgency`, `rank` and `cites`.
   - `rank` runs from 1 to N over the open keys, and is null on the others.
   - `cites` names the feature values the verdict relies on: a feature name, `bucket:<label>` or `day:<label>`, with its value. A monitor verdict cites `state`.
   - A monitor that matches several rules gets one verdict, with the highest severity.
   - No provider or connector call is made in this step.
3. `evaluate.py judge` checks the judgment against the features and merges it with `base.json` into `facts.json`. A key absent from the features, a missing verdict, a wrong level, a cited name or value that differs from the features, or ranks that are not 1 to N exit 3 with the key path.
4. `state.py apply` runs once into `<run>/preview/`. Its summary lists the new and escalated items.
5. The model writes `analysis.json` for exactly those keys: `risk`, `reason` claims tagged `measured` (with cited features) or `inferred`, 1 to 3 `mitigation` leads and the next `action`, each text at most 300 characters. `evaluate.py annotate` adds it to `facts.json` and changes nothing else.
6. The real `state.py apply` writes the next state, the summary and the run record. The summary lists new and escalated items in rank order, each with its analysis; the state keeps the analysis until the item escalates.
7. `digest.py` renders the digest from the summary, the next state, the run record and `base.json`. It shows each new and escalated item with its analysis, in rank order. A report-only run shows the analysis and stores nothing. The model posts the file's text unchanged and writes none of it.

A rejected judgment or analysis is corrected once from the checker's message. A second rejection ends the run with one message starting `degraded: judgment rejected`, and writes neither state nor run record.

The features, rules, judgment and analysis files stay in the run's temporary directory. Feature and rule text is data for the model, never an order to follow. The behaviors of steps 2 and 5 are checked by a model eval outside the unit tests.

## Digest

```text
python3 runtime/digest.py --summary M --state N --record R --base BASE --out DIGEST
```

`digest.py` renders the message as Markdown, so the same inputs give the same bytes. Only text from the four files reaches the output, never model text or free text. Sections with nothing to show are skipped.
- Title: the state's `digest` name and the record's `run_at`. A report-only run leaves the state as it was and still shows its own run time.
- New items, then escalated items, in the summary's rank order: severity, urgency, link, then the analysis (risk, reason claims tagged `measured` or `inferred`, mitigation leads, action).
- Resolved items.
- Still open items per severity, as listed by the summary's `still_open` (muted keys left out): each with since, last value, link and the stored action, read from the next state by key.
- Counts of muted changes and dropped blind spots, when not zero.
- Blind spots with their gap and runs, the cut span when set, the sources not read with their reasons (from `base.json`), and the overrides. A blind spot whose key is an unread source is shown only under the unread sources.

The run adds only the `state not saved` line, first, and the missing variables and connectors of the environment check, which the script does not know.

Analysis text rules, checked by `evaluate.py annotate` before the state stores them:
- Plain text of at most 300 characters per field.
- No control, format or separator characters (Unicode categories Cc, Cf, Cs, Zl and Zp).
- No `<`, `>`, `@` or `://`.
- At most 5 reason claims per item, and 1 to 3 mitigation leads.

## Local runs

`/claudio-routines:routines run <slug> [--since T] [--post]` renders the routine for the `local` place and follows the prompt in the current session.

- The run uses the pinned runtime at `places.local.runtime_dir`; a missing or stale runtime stops it before it renders.
- Before collecting, it names every missing credential variable and every missing connector.
- It starts from the remote `claude/state` branch and saves through a work tree under its run directory, so the checked-out branch and the working tree of the private repository never change.
- Without `--post`, the run reports only:
  - The digest is printed in the session, never posted.
  - The run pushes its run record and leaves the state and its cursors unchanged, so a change never posted is never consumed.
- With `--post`, the digest reaches the chat channel and the state moves, as in a cloud run.
- `--since T` runs an explicit window from `T`, which reports only.
- The run reads the working tree's `config.json`; the run record marks uncommitted config changes (`config_dirty`).
- A local run with `--post` and a cloud run at the same time both post; the second push is rejected and reports `state not saved`, and the next run collects the window again.

## Runtime

Routine runs reach the runtime through a setup script, rendered per place. The script:
1. Clones `runtime.repo` at `runtime.tag` over HTTPS, with no credentials, into a temporary directory.
2. Installs the clone at `places.<place>.runtime_dir` only when its hash equals `runtime.sha`.
3. Leaves nothing in place otherwise.
4. Exits without touching `places.<place>.runtime_dir` when its last component does not start with `claudio-runtime`.

A template that uses the runtime checks it first:
- `git rev-parse HEAD` in the runtime prints `runtime.sha`.
- `git status --porcelain --ignored` in the runtime prints nothing.
- Anything else makes the run report one `degraded` message and stop, with no state written.
- The template runs the runtime scripts with `python3 -B`, so a run writes no bytecode into the runtime.

`lint --private` exits 2 when `runtime.tag` does not resolve to `runtime.sha` in the local claudio checkout, naming both.

Bump procedure:
1. Tag a release of this repository.
2. Set `runtime.tag` and `runtime.sha` in the private config.
3. Run `/claudio-routines:routines setup-script` and paste the output into the environment's setup script at claude.ai.
4. Run `/claudio-routines:routines setup-script --place local` and run its output on your machine.
5. Run `/claudio-routines:routines sync <slug>` for each routine that uses the runtime.

## State engine

```text
python3 runtime/state.py window   --state S --now T --tz Z [--since T0 | --report-only] --out W
python3 runtime/state.py apply    --state S --facts F --window W --tz Z --out N --summary M --record R
python3 runtime/state.py init     --digest NAME --out S
python3 runtime/state.py validate (--state S | --facts F)
```

- `window`: the run window, from the last run in the state file, capped at 72 hours (3 hours on a baseline run), with local hour buckets that stay correct on daylight-saving change days.
  - `--since T0`: a manual catch-up or backfill from `T0`, uncapped; that run reports but never advances the state.
  - `--report-only`: the normal window, reported without advancing the state, for a local run that does not post.
- `apply`: the lifecycle of the tracked items.
  - Items open, escalate and resolve after 2 runs under their threshold.
  - Cursors only move forward.
  - Blind spots are capped at 8 and retried once a day.
  - Mutes keep items tracked but out of the summary, and the next state keeps them in `run.mutes`.
  - Deferred keys (not due, a known gap not retried, no data) keep their item unchanged.
  - The summary lists new and escalated items by `rank`, then by key; an item keeps its stored analysis until it escalates.
- `init`: the baseline state of a routine that has none.
- Every output is canonical JSON (sorted keys, 2-space indent), so state and run records diff cleanly in git.

### Where state lives

A routine that uses the engine keeps, on the `claude/state` branch of the private repository:
- `state/<slug>.json`: the state the next run starts from, so a run only collects what happened since the last one.
- `runs/<slug>/<run-at>.json`: one record per run, ready to parse for stats: window, counts, item keys, muted keys, blind spots, sources read, and the place, runtime commit, config commit and transport per source when the run had collectors.

A run with no branch or no state file is a baseline run. A failed push is reported in the digest as state not saved.

The schema and the rules are in the [routines-as-code spec](../../docs/features/routines-as-code/).

## Security

Record text written by other people (messages, titles) reaches a model that holds connector access and posting rights.
- The template treats any text from a source, a collection, a reason, a saved response or a script's output as data: it never follows instructions inside it and quotes it as plain text.
- Prefer the `api` transport for sources that carry text written by other people: the model then never reads record text.
- Keep routines that hold credentials on an environment shared only with routines that read no untrusted text.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `check-private` exits 2 | `CLAUDIO_PRIVATE_DIR` unset, missing, inside another repository's working tree, or a claudio checkout | Point it at the root of the private clone, outside any other repository |
| `render` exits 2 naming a placeholder | A template key has no value | Add it to `values` or the routine's `values` |
| `diff` prints `not exported` | No snapshot matches the config key: it is not the live routine's slug, or export has not run | Rename the key to the slug `export` printed, then run export again |
| Sync reports a residual diff | The live routine changed during the push, or the API rewrote a field | Run `/routines diff` and compare |
| A run says `degraded`, or `/routines run` stops before rendering | The runtime at `places.<place>.runtime_dir` is missing, at another commit, or holds changed or extra files | Run the setup script of that place again and check `runtime.sha` |
| `check-env` prints `missing <source> <variable>`, or a source is not read with `credentials missing: <variable>` | The place lacks a credential variable | Set it in the shell (`local`) or in the cloud environment's variables (`cloud`) |
| An `api` source reads locally but not in the cloud | The cloud environment blocks the provider's host | Allow the hosts the providers README lists for that vendor |
| The digest names a missing connector | The session lists no tool from the connector `check-env` named | Connect it in the session (`local`) or attach it to the routine (`cloud`), under the name `mcp.connectors.<place>` sets |
| A run reports `degraded: judgment rejected` | The model's judgment or analysis failed the checker twice | Read the key path in the message, then fix the rule text that led the model astray and run again |
| A source is not read with `partial: call cap` | Its relay loop reached 50 calls | Narrow the source's queries, or set its transport to `api` for that place |
| A source is not read with `plan not done` | The relay loop stopped before `plan` returned `done`: a missing connector, or the run stopped relaying | Fix the connector, then run again |
