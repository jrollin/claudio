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
| Config tree | `runtime/config_tree.py` | Loads `config.json` and the routine files into one config, resolves each source's transport, and rejects secrets; the skill and the runtime share it |
| Example | `example/` | A private directory to copy: `config.json` and one routine file per routine, placeholders only |
| Skeletons | `skills/routines/templates/` | Generic `prod-watch.md`, `tribe-digest.md`, `chat-recap.md` and `weekly-status.md` prompts and the `setup-env.sh` setup script, placeholders only |
| State engine | `runtime/state.py` | Run window, item lifecycle, blind spots, mutes and run records for routine runs |
| Collector | `runtime/collect.py` | Lists a routine's sources, checks the place's credentials and connectors, reads one source per command into a collection, and rebuilds every collection of a run offline from its run folder |
| Relay capture | `runtime/relay_capture.py` | The `PostToolUse` hook command that saves each connector result byte-exact, the `take` function `collect.py plan` and `tribe.py publish-plan` use to pick the captures up, and the `mismatch` function they use to name how a near capture differs |
| Read store | `runtime/store.py` | Files each read of a store-backed source with its pages, records and `read.json`, writes the run manifest, serves the replay session and holds the `reparse` command (see Read store) |
| Evaluator | `runtime/evaluate.py` | `features` computes the judgment features, `judge` checks the model's judgment and merges it into the facts, `annotate` adds the analysis of new and escalated items |
| Digest | `runtime/digest.py` | Renders the posted message as Markdown from the change summary, the next state, the run record and the base file; the model posts it unchanged |
| Features | `runtime/features.py` | Computes the features, base and rules files of one run; decides nothing |
| Judgment | `runtime/judgment.py` | Checks the judgment and the analysis against the features, and builds the facts |
| Roles | `runtime/roles.py` | Config and query pack checks, and the record schema of each of the five roles: observability tool, document store, chat channel, code host and issue tracker |
| Tribe engine | `runtime/tribe.py` and its `tribe_*.py` modules | The engine of a routine whose `engine` is `tribe`: window, seed, features, judgment check, lifecycle, page render and structure check, page write plan and chat message |
| Recap engine | `runtime/recap.py` and its `recap_*.py` modules | The engine of a routine whose `engine` is `recap`: window, seed, features, judgment check, lifecycle and chat message |
| Weekly engine | `runtime/weekly.py` and its `weekly_*.py` modules | The engine of a routine whose `engine` is `weekly`: state, window, features, judgment check, state and run record, and chat message |
| Provider adapters | `runtime/providers/` | One module per vendor, each with an `api` and an `mcp` transport; see [the providers README](runtime/providers/README.md) |

The real templates and every value that names a company resource live in a private repository, never here.

## Templates

| Template | Kind | Runs |
|---|---|---|
| `prod-watch.md` | Routine prompt | Yes |
| `setup-env.sh` | Environment setup script, printed by `setup-script` | Yes |
| `tribe-digest.md` | Routine prompt | Yes |
| `chat-recap.md` | Routine prompt | Yes |
| `weekly-status.md` | Routine prompt | Yes |

A template is marked not runnable when its first line is exactly `<!-- not runnable -->`, in a public skeleton or a private template. A leading byte order mark and one trailing carriage return are ignored.
- `render` keeps the marker line and warns, naming the template.
- `render --runnable` and `body` refuse it with exit 2, and `sync` stops on it, so it is never pushed to a live routine. `/routines run` renders with `--runnable`.
- `diff` and `lint` treat it like any other template.
- `lint` reports a first line that is an HTML comment holding `not runnable` in another case or spacing as the finding `marker`, since it would leave the template runnable.

`lint --private` runs the role check of the runtime checkout on every routine file in `config/routines/`, for both places, and exits 2 naming the file and the key path of the first invalid value. Only a routine whose template calls the runtime (it holds `{{runtime.dir}}`) is checked: a prompt-only mirror and a template marked not runnable are not. `render` runs the key check of a recap routine before it renders, and fails a weekly routine without `recap` whose template uses `{{recap.slug}}`, naming `routines.<slug>.recap`.

A private `<name>-runtime.md` template is a byte copy of the public runnable template `<name>.md` at the pinned runtime commit. `lint --private` reports `runtime-copy-differs:<name>.md` at line 1 when the copy differs, and `runtime-copy-missing:<name>.md` when that commit has no such public template; copy the public template again after each release.

`lint --private` also prints two warnings on stderr, naming keys and never values, and leaves the exit code unchanged:
- `literal-value`: a template line holds, as case-sensitive text, a string value of 8 characters or more from the shared and own `values` of a routine that renders it. Use the placeholder.
- `repeated-value`: two routines set the same value key to the same value. Move it to the shared `values`.

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
3. Copy the contents of the plugin's `example/` directory into `$CLAUDIO_PRIVATE_DIR`: `config.json` and `config/routines/`. Fill in every `<placeholder>`.
   - Name each routine file after the live routine's slug, as `export` prints it, and set its `id`.
   - Delete the files of the routines you do not track.
4. Add `$CLAUDIO_PRIVATE_DIR/.claude/settings.json` with `permissions.deny` listing `PushNotification`, `Bash(sleep *)` and `Monitor`, and the relay capture hook (see Relay capture).
   - It applies to every routine.
   - `lint --private` reports `settings-missing`, `settings-invalid` or `deny-missing:<entry>` without it.
5. Add your templates under `$CLAUDIO_PRIVATE_DIR/templates/<template>.md`. A routine without a private template renders from the public skeleton of the same name.
6. Run `/claudio-routines:routines export`, then `/claudio-routines:routines diff` until each configured routine prints `in sync`.
7. For local runs, run `/claudio-routines:routines setup-script --place local` and run its output.

## Usage

```text
/claudio-routines:routines export                                  snapshot every live routine into the private repository
/claudio-routines:routines diff [slug]                             export, then compare rendered prompt and cron with live
/claudio-routines:routines render <slug> [--place P] [--post]      print a routine's rendered prompt for a place, cloud by default
/claudio-routines:routines lint                                    lint the public skeletons, or the private templates
/claudio-routines:routines sync <slug>                             show the diff, wait for approval, push, export again, confirm in sync
/claudio-routines:routines setup-script [--place P]                print the setup script of a place, cloud by default
/claudio-routines:routines run <slug> [--since T] [--post]         run a routine in this session for the local place
/claudio-routines:routines seed <slug>                             seed a tribe routine's state from its previous digest pages, or a recap routine's state from its stored state, push after approval
```

Each flow is described step by step in [SKILL.md](skills/routines/SKILL.md).

Exit codes of `routines.py`, `state.py`, `collect.py`, `store.py`, `evaluate.py`, `digest.py`, `tribe.py`, `recap.py` and `weekly.py`:
- 0: ok or in sync.
- 1: findings or drift; for `collect.py check-env`, a source with no usable transport and a missing credential variable.
- 2: usage or input error, including an unreadable or invalid features, base, facts, preview, summary, record or state file; `digest.py` exits 2 for every refused input, naming the file.
- 3 (runtime scripts only): rejected state, facts, time or query pack; for `evaluate.py judge` and `annotate`, a rejected judgment or analysis, including a file that is not valid JSON.
  - `tribe.py`: a rejected judgment, state, window or cursor (`judge`, `apply`), a page that fails its structure check (`render`, `publish-plan`), and a Run state field outside its allowed values (`seed`).
  - `recap.py`: a rejected judgment, state, window or stored unit (`judge`, `apply`, `window`, `seed`), naming its key path.
  - `weekly.py`: a rejected state, window, collection or recap file (`window`, `features`, `apply`) and a rejected judgment (`judge`), naming the file and key path.
  - `collect.py replay`: a read the run did not make, or a request that differs from its record.
  - `store.py reparse`: a read the parser rejects.

## Config reference

The private directory holds a shared file and one file per routine:

```text
$CLAUDIO_PRIVATE_DIR/
  config.json                  timezone, runtime, places, providers, values
  config/routines/<slug>.json  one routine
  templates/<template>.md      private templates
  routines/                    snapshots written by export
```

Routine files and routines inline under `routines` in `config.json` are both accepted, and the skill and the runtime read the same config from them.
- A routine file holds the keys of one routine, listed below, and never `timezone`, `runtime`, `places` or `providers`.
- A slug set both inline and in a routine file fails the load, and so do two routines with one `id`.
- A `.json` file of `config/routines/` whose name is not a slug (lowercase letters, digits and hyphens) fails the load; a file without the `.json` extension is ignored.
- A file that is not UTF-8 JSON, or not an object, fails the load.
- A runtime script reads `config.json` and the file of its own routine only, so another routine's broken file never stops a run.
- Error messages label a key of a routine file as `config/routines/<slug>.json: <path>`, and never print a config value.

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
| `places.<place>.runs_dir` | Optional. Absolute folder where a run of that place creates its run folder, `<runs_dir>/<slug>/<UTC start time>-<random>`; `/tmp` without it. Raw results hold source content, so keep it in a folder git ignores (for example `/srv/claudio-runs`) |
| `places.<place>.store_dir` | Optional. Absolute folder of the shared read store of that place, outside every git working tree or inside one that ignores it (for example `/srv/claudio-store`, or a `store-local/` folder listed in the private repository's `.gitignore`): the runs of the place file their chat reads under `<store_dir>/provider=<key>/` and reuse the fresh ones (see Shared store). Leave it unset on the cloud place |
| `places.<place>.injected_hosts` | Optional. List of plain host names (such as `api.example.test`) whose credentials the place's proxy adds, for example the cloud environment's network secrets. An `api` provider whose `api.base_url` host is listed is usable there without its credential variables, and the client sends no credential header. The code host's host is refused |
| `providers.<name>` | One provider; sources point at it by `<name>` |
| `providers.<name>.adapter` | Module name of its adapter under `runtime/providers/` |
| `providers.<name>.api.base_url` | HTTPS base URL of the provider API, with no user info, query or fragment: the only host the adapter calls |
| `providers.<name>.api.credentials` | Name of the environment variable of each credential, never its value |
| `providers.<name>.mcp.connectors.<place>` | Name of the provider's connector in that place; a provider read only through a connector sets no `api` block |
| `providers.<name>.links_base` | Optional HTTPS base of the provider's web UI, for record links; set it for a provider read only through a connector |
| `providers.<name>.transport.<place>` | Optional default transport of every source of the provider in that place: `api`, `mcp` or an ordered list of both, such as `["api", "mcp"]` |
| `values` | Render-time values shared by every routine, for example one chat channel used by several routines |
| `routines` | Optional object of inline routines, keyed by slug |

A routine is one file, `config/routines/<slug>.json`, or one entry `routines.<slug>` of `config.json`. `<slug>` is the live routine name in lowercase with hyphens, as `export` prints it. The keys below are relative to the routine:

| Key | Meaning |
|---|---|
| `id` | Routine id, from the export; unique among the routines |
| `template` | Template name, without `.md` |
| `cron` | Cron expression pushed by sync |
| `first_read_days` | Optional integer from 1 to 31: how many days before the window end a chat channel or an issue tracker filter with no stored cursor starts reading; without it, they start at the window start |
| `values` | Values of that routine only, applied over the shared `values` |
| `sources.<source>` | One source of the routine; `<source>` matches `^[a-z][a-z0-9-]*$` and names its collection file |
| `sources.<source>.provider` | A key of `providers` |
| `sources.<source>.transport.cloud` | Optional `api` or `mcp`, or an ordered list of both: how cloud runs read the source |
| `sources.<source>.transport.local` | Optional `api` or `mcp`, or an ordered list of both: how local runs read the source |
| `query_pack` | Entries the evaluator turns into features, each with a prose rule (see below) |
| `rules` | Routine-wide judgment rules, for example flapping, discovered monitors and No Data: a list of texts of at most 500 characters |
| `models` | Model names of the run, copied into the facts |

Provider default transport:
- A source takes the transport of its provider for each place: `providers.<name>.transport.<place>`.
- A source's own `transport.<place>` overrides the default for that place only, so a source that sets `transport.local: mcp` still takes the provider's `cloud` default.
- A transport is `api`, `mcp` or a list of them in order of preference. A single value is a list of one.
- A place that resolves to no transport, a place other than `cloud` or `local`, an empty list, a repeated transport and a value other than `api` or `mcp` fail the load, naming the key path.
- Every command past the loader reads the resolved list per source and place, and the first usable transport of it reads the source (see Collectors).

Secret guard:
- The loader scans `config.json` and each routine file it reads, and fails the load on a secret.
- Credentials and secret-named keys hold environment variable names. A key named `password`, `passwd`, `secret`, `token`, `api_key`, `apikey`, `app_key` or `private_key`, or ending in `_` and one of them once camelCase is split and dashes become underscores, holds a name matching `^[A-Z][A-Z0-9_]*$` (rule `secret-key`).
- A string or a key shaped like a known token or a private key header fails the load wherever it sits, in `values` and source options included (rule `token`).
- A message names the file, the key path and the rule, and never prints a value.

A source also holds the options of its provider's role:

| Role | Option | Meaning |
|---|---|---|
| Observability tool | `kind` | `monitors` or `metrics` |
| Observability tool | `scope_filter` | Query of the alert event search of a `monitors` source, such as `source:alert env:prod`; a `metrics` source ignores it, since its pack queries carry their own scope |
| Observability tool | `discovery_query` | Optional monitor search query of a `monitors` source: the monitors it finds are judged under `monitor-<id>` even when the pack lacks them; without it nothing is discovered; a `metrics` source refuses it |
| Document store | `page_id` | The sources page that holds the mutes table: a top-level `Mutes` heading followed by a table with the columns `key` and `until` (or `silence until`, never both), never nested inside a toggle heading; a source sets exactly one of `page_id`, `pages`, `page_from_state`, `edited_by` and `created_by` |
| Document store | `pages` | A non-empty list of page ids whose changes are collected: a page is read in full when its edit time moved, and its entry is `unchanged` or `not found or not shared` otherwise; keep it to about 10 pages, since a connector source fetches every listed page |
| Document store | `page_from_state` | `previous_page`, in place of `page_id` and `pages`, for a routine with the `tribe` engine: the source reads the previous digest page named by the state, and a run with no previous page leaves the source unread |
| Document store | `edited_by` | A user id, in place of `page_id` and `pages`: over `api`, the pages that user last edited in the window, newest first, up to `edited_cap` (1 to 20, default 10) |
| Document store | `created_by` | A user id (`me` for the connected user), in place of `page_id` and `pages`: over `mcp` only, the pages that user created in the window, without their blocks; `exclude_paths` drops pages whose path starts with one of its prefixes |
| Chat channel | `channels` | A non-empty list of channels; the replies of each thread whose root lies in the window are read too |
| Chat channel | `max_age` | Optional, 0 by default: the minutes before the window end within which a stored read is reused instead of fetched (see Shared store). An integer for every read kind, or an object with `default`, `history`, `thread`, `reactions` and `people` (members and user names), a missing kind taking `default`. Searches are always fetched |
| Chat channel | `closed_days` | Optional, false by default: with `true`, channel history and thread reads take the closed UTC days already filed in the day layer of the place's `store_dir`, whatever their fetch age, and fetch only the gaps (see Day layer) |
| Code host | `repos` | A non-empty list of `owner/name` repositories |
| Code host | `query` | Optional search query; a source with a non-empty one is not read, since neither transport takes a search query |
| Issue tracker | `filter` | The saved filter id, digits only; a source sets `filter` or `jql`, not both |
| Issue tracker | `jql` | A query in the tracker's query language, holding no ordering, read instead of a saved filter |
| Issue tracker | `query` | Optional text that narrows the filter or the `jql`, written in the tracker's query language and holding no ordering |
| Issue tracker | `open_sprints` | Optional boolean, with `filter` only: also read the filter's issues that sit in an open sprint, whatever their update time, and flag them `in_open_sprint` |

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
| `trend_days` | metric with `read` `scalar` or `hourly` | Optional span of 7 to 31 local days, the window end's day included: the query is read once more as an hourly series and kept as one value per local day, next to the window value; the aggregator is `max`, `min`, `sum`, `avg` or `last`, and the entry sets no `lookback_days`. A failed trend read leaves the window value and sets `trend_reason` |
| `empty` | metric with `read` `scalar` or `top` | Optional `gap` (default) or `zero`. With `gap`, a read that succeeds with no datapoint is a blind spot. With `zero`, it reads as a value of 0 (a `top` entry reads no group) with no blind spot, and a trend that succeeds with no datapoint reads as 0 for its window values with a null `growth_monthly`. A zero `top` read resolves its tracked groups and a tracked entry key as `group missing` in one run. A response whose value is not a finite number reads as no value, so with `zero` it reads as 0. A read that fails is a blind spot whatever `empty` says |

Entries match this schema exactly: `severity`, `urgency` and `threshold` are rejected (`collect.py` and `evaluate.py` exit 3 naming the key path). The model sets severity and urgency per run, from the rules.

Config checks:
- `places.cloud` and `places.local` are both required.
- `places.<place>.runtime_dir`, `places.<place>.state_dir` and, when present, `places.<place>.runs_dir` and `places.<place>.store_dir` match `^(/[A-Za-z0-9._-]+)+/?$`, with no `.` or `..` component, since the template uses them unquoted in shell commands.
- `places.<place>.runs_dir` and `places.<place>.store_dir` are strings: a relative path or another type fails the config check, naming the key.
- `collect.py sources` exits 2 naming `places.<place>.store_dir` when that folder is a link, belongs to another user or lies inside a git working tree that does not ignore it (`git check-ignore` on the folder path with a trailing `/`, so a `store-local/` pattern covers a folder not created yet).
- A chat source's `max_age` is a non-negative integer, or an object of the keys above with such values: anything else, or an unknown key, fails the load, naming the key path and never the value.
- A search named `.` or `..` fails the load, since its name becomes a store folder.
- `places.<place>.injected_hosts` is a list of plain host names matching `^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*$`: another type, a URL or a host with a port fails the config check, naming `places.<place>.injected_hosts`. A code host provider read over `api` at that place whose host is listed fails it too.
- `timezone` matches `^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+)*$`, since the template uses it unquoted in shell commands.
- `runtime.dir`, a shared `values.state.dir` and a routine `values.state.dir` are refused; their values belong in `places.<place>.runtime_dir` and `places.<place>.state_dir`.
- A template name matches `^[a-z0-9-]+$`.
- Credential variable names match `^[A-Z][A-Z0-9_]*$`.
- A query pack key equal to a source name is an invalid pack (`collect.py` and `evaluate.py` exit 3): source names and pack keys share the blind spot keys.

Templates use `{{dotted.key}}` placeholders; `\{{` renders a literal `{{`. Render adds `runtime.*`, `timezone`, and for the rendered place:
- `runtime.dir` and `state.dir`, from `places.<place>`.
- `runs.dir`, from `places.<place>.runs_dir`, or `/tmp` without it.
- `place`: `cloud` or `local`.
- `run.post`: `yes` for the cloud place, `yes` for the local place only with `--post`, `no` otherwise.

## Collectors

Each source has an ordered list of transports per place, from its own `transport` or its provider's default. The first usable one reads the source:
- `api`: `collect.py fetch` calls the provider's HTTPS API from the place that runs the routine, and records each HTTP call in the run folder.
- `mcp`: a relay loop.
  - `collect.py plan` saves the results a hook captured, then writes the next connector calls.
  - The model makes each call once; the hook captures the result byte-exact (see Relay capture).
  - The model saves a result by hand only for a call the plan lists again, as the fallback.
  - `collect.py parse` turns the saved results into the collection.

Transport choice:
- `api` is usable when every variable of `api.credentials` holds a value. A variable that is unset, empty or blank counts as missing.
- `mcp` is always usable, since only the session can tell whether its connector is there.
- `collect.py sources --out <run>/sources.json` writes, per source, its `role`, `provider`, the chosen `transport` (`null` when none is usable) and `skipped`, the transports passed over with their missing variables.
- `fetch`, `plan`, `parse` and `replay` take `--sources <run>/sources.json` and read through the chosen transport. A command that does not match it exits 2. Without the flag they choose from the environment.
- `check-env` prints a `fallback <source> <from> <to> <variable>` line per skipped transport and exits 0. It prints `missing <source> <variable>` lines only for a source with no usable transport, and `connector <source> <connector>` lines for a source read through `mcp`.
- `check-env` prints an `injected <source> <host>` line, instead of any `missing` line, for a source read through `api` whose provider host is in the place's `injected_hosts`. Its requests carry the adapter's static headers (an API version, a media type) and no credential header, and the run reads no variable for it.
- The collection and the run record keep the chosen transport and `skipped`.

Reads:
- Each source writes one collection, `<run>/collections/<source>.json`, in the record schema of its role.
- `fetch`, `plan` and `parse` take `--run <run>`, the run folder, and keep the raw results of each source in it:
  - A store-backed chat source files each read in the run store, `<run>/store`, one folder per read (see Read store), and keeps its relay files, `calls.json` and `planned.json`, in `<run>/relay/<source>/`.
  - Any other source keeps them in `<run>/raw/<role>/<source>/`, with `<role>` the role `collect.py sources` prints.
  - `mcp`: `calls.json` and one `<call id>.txt` per saved connector result.
  - `api`: one `<source>-<n>.json` per HTTP call, in call order, with the method, path, query, request body, status, `Link` header, decoded response and error. It holds no request header and no credential.
  - These folders hold source content and are never pushed to `claude/state`.
  - [The providers README](runtime/providers/README.md) gives the record format.
- A source that cannot be read is marked not read, with a reason, and the other sources are still collected.
- A failed read never switches to the other transport.
- A relay loop ends after 20 pages of one query, a repeated cursor or 50 calls for one source; the source is then not read, with a reason starting `partial:`. The 100-page cap applies to the `api` alert events read of a monitors source only; the relay reads those events through one `aggregate_events` call, capped at 1,000 monitors (`partial: group cap`).
- An observability source writes one entry per query pack entry, a document store `pages` source one per page, and a chat source one per failed channel: `ok`, `deferred` or `failed` with a reason, so one failed entry leaves the others read.

Where the collectors stand:
- A tribe digest routine lists chat, issue tracker, document store and observability sources, and collects each one by role, outside any run.
- A Prod watch state keeps no chat, issue tracker or document store cursor, so each chat and issue tracker collection starts at the first-read span (`first_read_days`), or at the window start without it, and a document store reads every listed page.
- A tribe state keeps the cursors of these sources under their source names, and `collect.py` reads them from there.
- The tribe engine computes the features of these sources and renders the digest page (see Tribe engine).

Credentials:
- Credentials live only in environment variables; the config names each variable, never its value.
- `local` reads them from the shell that starts Claude Code.
- `cloud` reads them from the cloud environment's variables at claude.ai.
- An adapter calls only the host of its `api.base_url`; the cloud environment must allow that host.
- [The providers README](runtime/providers/README.md) lists, per vendor, the credential variables, the read-only scope to create and the hosts to allow.

```text
python3 runtime/collect.py sources   --config C --routine R --place P [--out FILE]
python3 runtime/collect.py check-env --config C --routine R --place P
python3 runtime/collect.py fetch     --config C --routine R --source NAME --place P --window W --state S --run RUN [--sources FILE] --out COLLECTION
python3 runtime/collect.py plan      --config C --routine R --source NAME --place P [--sources FILE] --window W --state S --run RUN --out PLAN
python3 runtime/collect.py parse     --config C --routine R --source NAME --place P [--sources FILE] --window W --state S --run RUN --out COLLECTION
python3 runtime/collect.py replay    --config C --routine R --place P [--sources FILE] --window W --state S --run RUN --out DIR
python3 runtime/evaluate.py features --config C --routine R --state S --window W --collections DIR --place P --runtime SHA --out FEATURES --base-out BASE --rules-out RULES
python3 runtime/evaluate.py judge    --features FEATURES --base BASE --judgment J --out F
python3 runtime/evaluate.py annotate --features FEATURES --facts F --analysis A --preview SUMMARY --out F
```

`collect.py` also reads one source outside any routine run, with a window from `state.py window --since` over a state from `state.py init`.

`collect.py replay` rebuilds every source's collection of the run's place offline (see Offline replay):
- It writes `DIR/<source>.json` for each source of the routine.
- A store-backed source replays read by read from the run store, bound to `<run>/manifest.json`.
- Any other `mcp` source goes through `parse` of `<run>/raw/<role>/<source>`.
- Any other `api` source goes through the adapter's `fetch` against a replay client that serves the records of `<run>/raw/<role>/<source>`.
- A source the run skipped, or an `api` config the adapter refuses, gives the same not-read collection as the run.

Discovery:
- A `monitors` source with a `discovery_query` also searches the monitors that match it.
- Each tracked `monitor-<id>` key is read by id until its item resolves, whether it came from the pack or from discovery.
- A failed or capped discovery, or a failed by-id read of an event-named monitor other than not found, adds the blind spot `discovery incomplete` and leaves the by-id reads counted as read.
- A monitor named by an alert event of the window that is outside the pack, untracked and not found by the search is read by id and reaches the model with its state and transitions, even when it is `OK` at run time; at most 50 per run, the excess adding `event monitors capped at 50` to the source's blind spot.

### Relay capture

A Claude Code `PostToolUse` hook saves each connector result byte-exact, so the model never copies a result into a file. `collect.py plan` and `tribe.py publish-plan` pick the captures up.

Hook:
- `runtime/relay_capture.py` is the hook command. It reads the hook JSON on stdin, prints nothing and exits 0 whatever happens: it never fails or blocks a tool.
- It acts on a tool named `mcp__<connector>__<tool>` and saves the result text:
  - A result that is a list of text blocks is saved as the concatenation of its texts.
  - A result too large for the session, which the harness replaces with an error line naming the file it saved the result to, is read from that file. The file must be a regular file in a `tool-results` folder inside the session's folder, the folder of the transcript; any other path is skipped.
  - Any other shape of result is skipped, and so is a text over 10 MB.
- A failure adds one line to `errors.log` in the capture folder: the time, the error class and a message, never result text.

Capture folder:
- `$CLAUDIO_RELAY_DIR` when set and not blank, else `/tmp/claudio-relay`. The hook and `plan` both read the variable, so they share one folder when the session sets it once.
- The hook creates it with mode 0700. The hook and `plan` leave it alone when it is a link, is not a folder or belongs to another user.
- One file per result, written with mode 0600 as `<time in ns>-<tool use id>.json`, holding `tool_name`, `arguments`, `text` and `captured_at_ns`.
- A capture is deleted when `plan` takes it, and every capture is deleted after 24 hours.

Pick up:
- Each call `plan` prints carries `path`, the absolute file its result goes to: a page of its read in the run store for a store-backed source, `<id>.txt` in `<run>/raw/<role>/<source>/` for any other.
- `plan` records, per call id it printed, the time it first printed it, in `planned.json` of the source's relay folder: `<run>/relay/<source>/` for a store-backed source, `<run>/raw/<role>/<source>/` for any other.
- Before it prints a step, `plan` saves at its `path` the capture of each call it printed before: the same tool name (`mcp__<connector>__<tool>`, the connector being `mcp.connectors.<place>` of the provider), the same arguments (an exact match, key order aside) and a capture time at or after the first print. The newest capture wins, and every capture it matched is deleted.
- It then computes the step again, and repeats until nothing is picked up.
- `tribe.py publish-plan` does the same for `<run>/responses/publish/<id>.txt`.
- When the loop ends, `plan` checks each call it prints again, and prints one line on stderr when a capture of the same tool name, taken at or after the first print, has other arguments: `relay capture mismatch <id>: <path> <detail>; <path> <detail>`.
  - It names the closest capture: the fewest differing paths, the newest on a tie. It names at most 5 paths, then `; +N more`.
  - A path joins object keys with `.` and writes a list index as `[i]`, for example `pages[0].content`.
  - A detail is `missing` (planned, absent from the call), `extra` (in the call, not planned) or `changed`. A changed string adds the first differing character and both lengths, as in `changed at char 1234 (planned 28155, called 28140)`; when one string is a prefix of the other, the character is the shorter length. A changed type adds the type names, as in `changed (planned str, called int)`.
  - The line holds paths, kinds, indexes, lengths and type names only, never an argument value or a result text. Reporting a capture deletes none, so a capture that serves a later call stays; the 24 hour cleanup still applies.
  - One line per printed-again call per `plan` command, on stderr only. It changes neither the step nor the exit code.
  - With several sources relaying in parallel, a capture of another source can share the tool name. A line that names identity paths such as `channel_id` or `message_ts` usually points at that capture, not at a retyped call: a known false positive.

Model:
- The model makes each call of `calls` once and runs `plan` again.
- When `plan` prints again a call the model already made, the hook missed its result. The model then saves that result by hand at the call's `path`, unchanged, after creating its folder: it copies the file when the harness saved the result to one, else it writes the text with the Write tool, never in a shell command. It then runs `plan` again.
- A `relay capture mismatch` line in the error output of `plan` says how the call the model made differs from the printed one. It is a diagnostic only: the model never makes that call again, and saves its result by hand as above.

Hook settings, in `$CLAUDIO_PRIVATE_DIR/.claude/settings.json` beside `permissions.deny`. A cloud routine reads the file because the private repository is its only source:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "mcp__.*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 -I \"${CLAUDIO_RUNTIME_DIR:-/opt/claudio-runtime}/plugins/claudio-routines/runtime/relay_capture.py\" || true"
          }
        ]
      }
    ]
  }
}
```

- The default path stands for `places.cloud.runtime_dir`: write the configured value there.
- `|| true` keeps the hook silent when the runtime path is wrong: Python exits 2 for a missing script, and Claude Code shows the error of a `PostToolUse` hook that exits 2 to the model.
- A local run exports `CLAUDIO_RUNTIME_DIR` as `places.local.runtime_dir` in the shell that starts Claude Code, for example `export CLAUDIO_RUNTIME_DIR=<places.local.runtime_dir>` in the shell profile.
- Claude Code reads the hook only from the project of the session: start the local session in `$CLAUDIO_PRIVATE_DIR`. From any other directory the hook never runs, so `plan` prints each call again.

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
7. `digest.py` renders the digest from the summary, the next state, the run record and `base.json`. It shows each new and escalated item with its analysis, in rank order. A report-only run shows the analysis and stores nothing. The model posts the file's text unchanged and writes none of it. A digest longer than 4,000 characters comes in parts, `digest.md` then `digest.2.md` and so on, cut at blank lines: the run posts the first part and the others, in order, in its thread, since the chat send tool takes at most 5,000 characters.

A rejected judgment or analysis is corrected once from the checker's message. A second rejection ends the run with one message starting `degraded: judgment rejected`, and writes neither state nor run record.

The features, rules, judgment and analysis files stay in the run's temporary directory. Feature and rule text is data for the model, never an order to follow. The behaviors of steps 2 and 5 are checked by a model eval outside the unit tests.

## Digest

```text
python3 runtime/digest.py --summary M --state N --record R --base BASE --tz ZONE --out DIGEST
```

`digest.py` renders the compact chat layout in Standard Markdown, so the same inputs give the same bytes. Only text from the four files reaches the output, never model text or free text. A section with nothing to show is skipped, except Summary. `--tz` is required: every time of the message is in that zone, and an unknown zone exits 2.
- Title: the bold digest name of the state and the record's `run_at` as `DD Mon HH:MM <city>`, then `(since <weekday HH:MM>)` from the next state's window start, or `(baseline)` when the next state has no previous run. A report-only run leaves the state as it was and still shows its own run time.
- Summary: `N new, N escalated, N resolved, N still open`. Counts take the singular at 1 (`1 run`, `1 muted change`, `1 blind spot dropped`).
- New items, then escalated items, in the summary's rank order: one block each, with the urgency mark (🔴 now, 🟠 within months, 🟡 watch, ⬆️ before it when escalated), the title, `severity · urgency · since <time> · [label](link)`, then the Risk, Reason (claims tagged `measured` or `inferred`, the claim's trailing period dropped before its tag), Mitigation and Action bullets the item holds. `since` is read from the next state by key and shown as stored when it is not a UTC time.
- Resolved items: one line each, with the link and the last value.
- Still open: the count, then one bullet per severity with at most 3 titles in the summary's order and `+N` for the rest. The summary's `still_open` leaves muted keys out, and each of its keys must be an item of the next state, else the script exits 2 naming the key.
- One line each for `Blind spots:` (blind spots with the item's title when the key is an item of the next state, else the key, then gap and runs, the sources not read with their reasons from `base.json`, and the cut as the end of the unread span), `Not shown:` (muted changes and dropped blind spots, when not zero) and `Overrides:`. A blind spot whose key is an unread source is shown only as a source not read.
- A link label is `monitor <id>` for a monitor link and `metric` otherwise. Only an `http://` or `https://` link renders as a Markdown link; any other link (empty, `javascript:`, relative) shows the label alone. `(`, `)`, spaces and backslashes of the destination are percent-encoded. In text, `](` becomes `] (` and `**` becomes `* *`, so a value cannot make a link or close a bold span. No item key appears in the message.

The run adds only the `state not saved` line, first, and the missing variables and connectors of the environment check, which the script does not know.

Analysis text rules, checked by `evaluate.py annotate` before the state stores them:
- Plain text of at most 300 characters per field.
- No control, format or separator characters (Unicode categories Cc, Cf, Cs, Zl and Zp).
- No `<`, `>`, `@` or `://`.
- At most 5 reason claims per item, and 1 to 3 mitigation leads.

## Tribe engine

A routine file with `engine: tribe` runs the `tribe-digest` template, which needs the routine values `digest.slug` (the state file name) and `digest.name` (the digest name in the state and the prompt). The state is `state/<slug>.json` on the `claude/state` branch, schema `tribe-1`, and changes only through `tribe.py apply` and `publish-parse`.

Commands, in run order:

```text
python3 runtime/tribe.py init          --digest NAME --out STATE
python3 runtime/tribe.py window        --state S --now T --tz Z [--since T0 | --report-only] --out W
python3 runtime/collect.py ...         (one collection per source, as above)
python3 runtime/tribe.py features      --config C --routine R --state S --window W --collections DIR --place P --out FEATURES --base-out BASE --rules-out RULES
python3 runtime/tribe.py judge         --features FEATURES --judgment J
python3 runtime/tribe.py apply         --state S --features FEATURES --base BASE --judgment J --window W --out applied.json --summary SUMMARY --record RECORD
python3 runtime/tribe.py render        --config C --routine R --place P --summary SUMMARY --out PAGE
python3 runtime/tribe.py publish-plan  --config C --routine R --place P --summary SUMMARY --state applied.json --page PAGE --responses DIR --out PLAN
python3 runtime/tribe.py publish-parse --config C --routine R --place P --summary SUMMARY --state applied.json --responses DIR --now T --out next.json --result RESULT
python3 runtime/tribe.py message       --summary SUMMARY --result RESULT --config C --routine R --place P --out MESSAGE
python3 runtime/tribe.py message       --degraded {judgment|structure} --out MESSAGE
python3 runtime/tribe.py seed          --page FETCHED [--page FETCHED ...] --routine R --config C --out STATE
```

- The model writes only `judgment.json`, from `features.json` and `rules.json`. `judge` rejects a cite that the features do not hold (exit 3, with the key path).
- `apply` merges the judgment and the edits made on the previous page into the next state, the summary and the run record. A report-only run (`--since` or `--report-only`) leaves the state byte-identical.
- `render` writes the page and runs its structure check; a failed check exits 3 and no page is written.
- `publish-plan` prints one connector call at a time: on the first run of an ISO week the weekly heading, then the page create and one poll per plan step (at most 20). The model makes each call once and runs `publish-plan` again: the captured result is saved as `DIR/<id>.txt` (see Relay capture), and the model saves it by hand only for a call the plan prints again. `publish-parse` reads the results into the page id and the week of the state, and writes `RESULT` with the status `created`, `failed` or `report-only`; a failed create leaves the state as it was.
- `message` writes the chat message with the page link, or one `degraded:` line for a rejected judgment, a failed structure check or a failed page create.
- The judgment may carry an optional `coverage_notes` list of at most 10 `{source, text}`: `source` is a label of at most 60 characters, no two notes share a source, and a note holds no cite. The notes show under Blind spots of the page and name their sources in the blind spots line of the message for that run only; they are stored in no state and change no warning, check or blind spot count.
- A document store source with `page_from_state: previous_page` reads the previous page named by the state; its blocks give the status edits and the ticked checks that `features` hands to the judgment.

Routine keys of the engine, validated at config load. A routine with `engine: tribe` must set `page` and `publish`:

| Key | Content |
|---|---|
| `engine` | `watch` (the default), `tribe`, `recap` or `weekly` |
| `page` | `how_built` and `key_callout` (lists of lines), `state_path`, `link` (a URL template holding `{{id}}`) and `title` (a template holding `{{date}}` only, the title of the page and of the chat message), every key required |
| `publish` | `provider` (a key of `providers`), `parent` (page id), optional `week_start_format` (a `strftime` format, default `%Y-%m-%d`), `create`, `poll` and `heading` as `{tool, arguments}`, and `results`: the dotted paths `task`, `status`, `page` and `heading`, and the non-empty status lists `done` and `failed` |

- `arguments` hold the placeholders `{{parent}}`, `{{title}}`, `{{content}}`, `{{date}}`, `{{week}}` and `{{week_start}}`, and `{{task}}` in `poll` only. Tool names come from this key, never from code or the template.
- The `publish` provider needs an `mcp` connector for the place that runs the routine.

Seed:
- `/routines seed <slug>` turns the Run state of the newest digest pages into a tribe state in a scratch file, shows its summary and waits for the owner's approval before it pushes `state/<slug>.json`.
- `tribe.py seed` skips a page with no valid run state, naming it, and exits 2 when no page holds one.
- It exits 3 when a field is outside its allowed values, a warning `status` excepted.
- A warning `status` other than `open`, `in progress`, `mitigated`, `decided` or `dropped` is read as the one it starts with, else as `open`. Each reading is printed on stderr with the key and the original status.

## Recap engine

A routine file with `engine: recap` runs the `chat-recap` template, which needs the routine values `digest.slug` (the state file name) and `digest.name` (the digest name in the state and the prompt). The state is `state/<slug>.json` on the `claude/state` branch, and changes only through `recap.py apply`. The routine reads chat sources only and posts one chat message with no page.

Commands, in run order:

```text
python3 runtime/recap.py init          --digest NAME --out STATE
python3 runtime/recap.py window        --state S --now T --tz Z --lookback-working-days N [--since T0 | --report-only] --out W
python3 runtime/collect.py ...         (one collection per source, as above)
python3 runtime/recap.py features      --config C --routine R --state S --window W --collections DIR --place P --out FEATURES --base-out BASE --rules-out RULES
python3 runtime/recap.py judge         --features FEATURES --judgment J
python3 runtime/recap.py apply         --state S --features FEATURES --base BASE --judgment J --window W --tz Z [--late-after-working-days N] [--drop-after-days N] --out applied.json --summary SUMMARY --record RECORD
python3 runtime/recap.py message       --summary SUMMARY --config C --routine R --place P --tz Z --out MESSAGE
python3 runtime/recap.py message       --degraded judgment --out MESSAGE
python3 runtime/recap.py seed          --from STORED --digest NAME --out STATE
```

- The model writes only `judgment.json`, from `features.json` and `rules.json`. `judge` rejects a judgment the features do not allow (exit 3, with the key path).
- `apply` writes the next state, the summary and the run record. A report-only run (`--since` or `--report-only`) leaves the state byte-identical. The state and the record hold no message text.
- `message` writes a message longer than 4,000 characters in parts, `MESSAGE` then `<stem>.2<ext>` and so on, cut at blank lines; the run posts the first part and the others, in order, in its thread.
- The template saves the state on the `claude/state` branch before it renders the message.
- `message` posts only when `post` is true in the summary.

Routine keys of the engine, validated at config load and by `routines.py lint --private`, which names the key path of an invalid value. Nested mappings reject unexpected keys.

| Key | Content |
|---|---|
| `owner` | The chat user id of the owner; each chat source sets the same `owner` |
| `workspace` | The chat host name that builds the message links |
| `groups` | List of `{id, label, lands_in}`, `lands_in` being `waiting` or `good_to_know` |
| `announcement` | Optional `channels` and `topics`: the channels read for announcements and the topics kept |
| `window` | `lookback_working_days`, 1 to 365: the working days a baseline run or a run after a long gap reads; each search carries its own look-back |
| `exclude` | Optional `authors`, `channels` and `keep_bots` (the bot ids kept) |
| `history` | Optional `late_after_working_days` (0 to 365) and `drop_after_days` (1 to 365); the engine defaults apply when left out |
| `rules` | Non-empty list of the ask rules the judgment follows |
| `thread_reads` | Optional `full` (default) or `since`; see Thread reads |

Thread reads:
- `full`, or no key: every thread unit is read whole, as before.
- `since`: a thread unit already in the state with an `owner_last_ts` key is read from its `last_ts` minus the re-read margin, so a long thread stops going through the relay in full. A new unit, or a stored unit without the key, is read whole.
- `owner_last_ts` is the time of the owner's latest message or reaction in the unit, or null when the owner has none. Every unit read in a run gets it, whatever the mode, so `since` can be turned on at any time; a seeded unit has no key until it is read.
- With `since` only, the facts of a thread unit merge the stored `owner_last_ts` with the messages read: a stored value counts as an answer and as the owner taking part, a reaction included. Facts that look back (a direct mention, a group ask and its replies) see only the messages read. With `full`, the facts use the messages read only, as before.

Seed:
- `/routines seed <slug>` turns the state a live recap routine kept in the document store into a recap state in a scratch file, shows its summary and waits for the owner's approval before it pushes `state/<slug>.json`.
- `routines.py seed <slug> --from <stored state>` runs `recap.py seed` for a routine whose engine is `recap`; `--page` is refused for it, and `--from` for a tribe routine.
- `recap.py seed` drops the permalinks, maps the statuses, cuts titles to 8 words and exits 3 naming the key path of a unit it cannot map.

Settings:
- The private repository holds `.claude/settings.json` with `permissions.deny` listing `PushNotification`, `Bash(sleep *)` and `Monitor`, and the `PostToolUse` hook of the relay capture. A cloud routine reads it because the private repository is its only source.
- `routines.py lint --private` fails with `settings-missing`, `settings-invalid` or `deny-missing:<entry>` when the file or an entry is absent.

## Weekly engine

A routine with `engine: weekly` summarises the owner's week from issue tracker, code host, chat and document store sources. The state is `state/<slug>.json`, schema `weekly-1`: `digest`, and `last_run` (`run_at`, `week_start`) or null. It holds no message, comment or page text.

```
python3 runtime/weekly.py init     --digest SLUG --out STATE
python3 runtime/weekly.py window   --state S --now T --tz Z [--report-only] --out W
python3 runtime/weekly.py features --config C --routine R --window W --collections DIR [--recap RECAP_DIR] --out FEATURES
python3 runtime/weekly.py judge    --features FEATURES --judgment JUDGMENT --out SUMMARY
python3 runtime/weekly.py apply    --state S --summary SUMMARY --window W --out NEXT --record RECORD
python3 runtime/weekly.py message  --summary SUMMARY --features FEATURES --out MESSAGE
```

- `window` starts at Monday 00:00 of the week of `--now` in `--tz`, across a clock change, and ends at `--now`, which must be a UTC time ending in `Z`. It writes `from_ts`, `to_ts`, `week_start` and `report_only`; the window keeps no cursor, so `--report-only` only marks it.
- `features` reads the collection of each source in `DIR/<source>.json` and writes one item per issue, pull request, chat thread or direct message and page with activity in the window. An item holds `source`, `role`, `kind`, `title`, `status`, `link`, `when`, `people`, `excerpts` (`by`, `at`, `text`), `channel_name` (the chat channel's name, else null) and `waiting_on`.
  - Keys: `issue:<key>`, `pr:<repo>#<number>`, `chat:<recap unit key>`, `page:<id>`.
  - `waiting_on` says who waits: on a recap item, `owner` for the status `waiting` or `promise`, the person's name for `waiting_on_others` (null without a person) and `team` for `team_ask`, else null. An issue, a pull request, a page and a direct-only chat item keep null. The `weekly-status` template sets an open item's `owner` from it when it names another person.
  - Excerpts: pull request activity up to 10 and chat messages up to 15, each text cut to 500 characters, newest first; a page gives its first 1000 characters as one excerpt.
  - `--recap` is the folder of the recap routine's `state.json` and `runs/` records. A recap unit first seen or last written in the week makes a chat item with its title, status and link (a thread's root message, or the conversation); the week's records give `recap_counts` (`new`, `resolved`, `handled`). A direct chat source adds its messages to the item of the same key, or makes its own.
  - Chat units in `exclude.channels` are dropped from the items and the counts.
  - `sources` lists each source with `read` and `reason`, and `reads` when its collection holds them; a source with no collection file is not read, with the reason `no collection`.
- `judge` checks the model's judgment, `{"schema": 1, "accomplishments": [{"text", "cites"}], "decisions": [{"text", "cites"}], "open": [{"text", "owner", "cites"}]}`, and writes the summary: the judgment with the features' `window`, `week_start`, `recap_counts` and `sources`.
  - Counts: accomplishments 1 to 6, or none when the features hold no item; decisions 0 to 6; open 0 to 8.
  - `text`: 1 to 200 characters, with no URL (`http://`, `https://`, `www.`), no line break and no other control character; all texts hold at most 220 words together.
  - `owner`: null, or a non-blank name of at most 60 characters.
  - `cites`: a non-empty list of item keys of the features, none repeated within a bullet.
  - An unknown key, a missing key or another schema is rejected too; the rejection names the key path, such as `open[0].cites[1]`.
- `apply` writes the next state and the run record.
  - The next state keeps the digest and sets `last_run` to the window's end (`run_at`) and its `week_start`; a `report_only` window leaves the state as it was.
  - The record holds `schema`, `run_at`, `window`, `week_start`, `report_only`, `counts` (cited items per role, bullets per section), `cited` (the sorted item keys) and `sources` (`source`, `read`, `reason`, and `reads` when present). It holds no bullet text, title or owner name.
- `message` renders the summary as the chat message, with the links of each bullet taken from its cited items:
  - Title `**Weekly status, week of Mon 12 Oct**`, then `**Key accomplishments**`, `**Decisions**` and `**Still open / next week**`; an empty section shows `- None`, or `- None recorded` for decisions.
  - A bullet reads `- <text> (owner: <name>) ([<label>](<link>), ...)`; the owner shows on open bullets that have one.
  - Labels: the issue key, `<repo name>#<number>` for a pull request, `thread in #<channel>` (or `thread` without a channel name) or `DM` for chat, the first 6 words of a page title.
  - `_Sources checked: <roles read>._` lists issue tracker, code host, chat and document store in that order, chat included when the recap fed items; one `Not read: <source> (<reason>)` line follows per source not read.
  - The title date is the Monday of the summary's `week_start`, which `window` already computed in the routine's zone: `message` takes no `--tz`.
- Exit codes: 2 for an unreadable input, a features or summary file that fails its checks, a cite missing from the features or a `--now` that is not UTC; 3 for a state, window, collection or judgment that fails its checks, naming the file and key path.

Routine keys of the engine, validated at config load and by `routines.py lint --private`:

| Key | Content |
|---|---|
| `owner` | The chat user id of the owner, non-blank; a chat source sets the same `owner` |
| `workspace` | The chat host name that builds the chat links |
| `recap` | Optional: the slug of the chat recap routine whose state feeds the chat items; the `weekly-status` template needs it, as its render value `recap.slug` |
| `exclude` | Optional `channels`: the chat channels dropped, such as the routine's own digest channel |
| `sources` | Issue tracker, code host, chat and document store sources only; a chat source sets `searches` |

### Weekly template

The `weekly-status` template needs the routine values `digest.slug` (the state file name) and `digest.name`, and the routine key `recap`. It follows the chat recap's save, raw folder, run folder and fallback rules, and runs these steps:

1. Check the runtime: the pinned commit and a clean checkout, else `degraded: runtime missing, at another commit or modified`.
2. Load the state from the `claude/state` branch, or `weekly.py init` on a baseline run. Then read the recap routine's `state/<recap>.json` and `runs/<recap>/` records into `<run>/recap/` with `git show` and `git archive | tar -x --strip-components=2`, so the records land in `<run>/recap/runs/*.json`. When that fails, the run goes on without `--recap` and the report names the recap as not read.
3. `weekly.py window`, with `--report-only` when the post setting is `no`.
4. `collect.py check-env`: a missing variable or connector ends that source not read, named in the report.
5. `collect.py sources`, then one `fetch`, or one `plan` and `parse` relay loop, per source, with the raw results in the run folder (see Collectors).
6. `weekly.py features`, with `--recap <run>/recap` when step 2 read it.
7. The model reads `features.json` only and writes `judgment.json`; `weekly.py judge` checks it. One correction is allowed, a second rejection is the degraded run `degraded: judgment rejected, no weekly status this run`, reported like the message (posted when the post setting is `yes`), with no state written.
8. `weekly.py apply` writes `next.json` and `record.json`.
9. Save `next.json` to `state/<slug>.json` and `record.json` to `runs/<slug>/<run-at>.json` through a work tree, after a `cmp` check that no other run saved meanwhile, with one retry on a moved branch. A report-only run commits the run record only.
10. `weekly.py message` writes `message.md`.
11. Post `message.md` unchanged to the digest channel when the post setting is `yes`, else print it. A failed save adds the line `state not saved` first.

## Local runs

`/claudio-routines:routines run <slug> [--since T] [--post]` renders the routine for the `local` place and follows the prompt in the current session.

- The run uses the pinned runtime at `places.local.runtime_dir`; a missing or stale runtime stops it before it renders.
- The relay capture hook finds the runtime through `CLAUDIO_RUNTIME_DIR` (see Relay capture). Without it no result is captured, `plan` prints each call again and the model saves each result by hand.
- The run creates its folder at `<runs_dir>/<slug>/<UTC start time>-<random>`, with `runs_dir` from `places.local.runs_dir`, or `/tmp` without it.
- The run folder keeps the raw results of every source, its run store and its manifest, and stays after the run.
- Before collecting, it names every missing credential variable and every missing connector.
- It starts from the remote `claude/state` branch and saves through a work tree under its run directory, so the checked-out branch and the working tree of the private repository never change.
- Without `--post`, the run reports only:
  - The digest is printed in the session, never posted.
  - The run pushes its run record and leaves the state and its cursors unchanged, so a change never posted is never consumed.
- With `--post`, the digest reaches the chat channel and the state moves, as in a cloud run.
- `--since T` runs an explicit window from `T`, which reports only.
- The run reads the working tree's `config.json` and the routine's file `config/routines/<slug>.json`.
- `config_dirty` in the run record covers both files: it is true when either holds uncommitted changes, an untracked routine file included.
- A local run with `--post` and a cloud run at the same time both post; the second save finds the routine's state file changed since it started, stops and reports `state not saved`, and the next run collects the window again.

## Read store

A store-backed adapter (the chat adapter) files every read of a run in the run store, `<run>/store`, so a run selects, reparses and replays one read at a time. The [provider-store spec](../../docs/features/provider-store/) holds the rules.

Layout, in hive-style `key=value` folders:

```text
<run>/store/provider=<key>/
  kind=history/channel=<channel>/read=<from>_<to>-<fetch id>/
  kind=thread/channel=<channel>/root=<root ts>/read=<from>_<to>-<fetch id>/
  kind=reactions/channel=<channel>/message=<message ts>/read=<fetch id>/
  kind=members/channel=<channel>/read=<fetch id>/
  kind=users/user=<user id>/read=<fetch id>/
  kind=search/search=<search name>/read=<from>_<to>-<fetch id>/
```

- `<key>` is the provider's config key.
- `<from>` and `<to>` are the read's span: its `oldest` argument (the root ts for a whole thread) and its `latest` argument, or the window end of the run for a connector thread read.
- `<fetch id>` is `<run id>.<source>`, so two sources of one run never share a read.
- A search name is percent-encoded, and an id from tool text that is not a chat id or ts fails its read with `invalid entity id`.

Each read folder:
- `page-001.txt`, `page-002.txt`, and so on: the connector pages, byte-exact.
- `page-001.json`, and so on: the HTTP records of an `api` read, in the format of [the providers README](runtime/providers/README.md).
- `records.jsonl`: the parsed records, one compact JSON object per line, without the values the path holds.
- `read.json`: the kind, entity, span, transport, run, source, fetch time, page requests, outcome (`complete`, `failed` or `partial`, with its reason) and the runtime commit that parsed the records.
- `read.json` is written last: a folder without it is an unfinished read, which no listing shows.
- Folders are created with mode 0700 and files with 0600.

`<run>/manifest.json` lists, per store-backed source, the reads its collection used and how many the run fetched.

### Shared store

With `places.<place>.store_dir` set, the runs of that place share their reads:
- A run still writes each read in `<run>/store`, then publishes it under `<store_dir>/provider=<key>/`. Its files are linked into `.incoming/`, then the folder is renamed into place, so no reader sees a partial read. A link falls back to a copy across file systems.
- A source with `max_age` above 0 reuses a stored read when all of these hold:
  - same provider key
  - outcome `complete`
  - kind other than `search`
  - fetched at most `max_age` minutes before the window end
  - fetched before the window end, unless by another source of the same run
  - not one of the source's own reads in this run
  - trust rule: an `api` source reuses `api` reads only, an `mcp` source reuses both
- A channel history fetches only the gaps of its span that the reused reads leave, one read per gap. A thread is read from the end of its covered part.
- Messages merge by ts, the newest fetch winning, then keep the needed span.
- Reactions, members and user names reuse the newest fresh read whole.
- A reused read is linked into `<run>/store` and listed in the manifest, so the run folder replays alone.
- A reused read spends no call of `call_cap` or of the page caps.
- Records that another runtime commit parsed are reparsed from their pages before use, with no network.
- With `max_age` above 0 for some kind, the collection, the run record (`collected.<source>.reads`) and the weekly record's source rows hold `reads`: `{"fetched": N, "reused": M}`. Without it they are unchanged.

Reparse:

```text
python3 runtime/store.py reparse --root ROOT [--provider P] [--channel C] [--thread C:TS] [--kind K] [--from UTC_TIME] [--to UTC_TIME]
```

- `ROOT` is a store root, such as `<run>/store`.
- Each filter repeats, and the filters combine with AND; `--from` and `--to` select the reads whose span overlaps.
- Only complete reads are reparsed, from their saved pages, with no network and no environment variable.
- It rewrites `records.jsonl`, then `read.json` when the records or the runtime commit changed.
- It prints `same`, `changed` or `rejected <read>: <reason>` per read, then the counts.
- A read the parser rejects stays as it was, and the command exits 3.
- Filters that match no read exit 2, naming them.

Prune:

```text
python3 runtime/store.py prune --root STORE_DIR --older-than-days N [--dry-run]
```

- It deletes, whole, each read folder fetched more than N days ago.
- A folder without `read.json`, and a `.incoming/` leftover, go by their modification time.
- It prints `<provider> deleted <N> kept <M>` per provider key; `--dry-run` prints the same and deletes nothing.
- Nothing else deletes a read. A run folder keeps the reads it linked, so it still replays after a prune.
- An age that is not a positive whole number exits 2, and so does a root that is not a folder.

Query the store with an outside tool, with no runtime code. DuckDB example:

```sql
SELECT channel, root, ts, author, text
FROM read_json('<run>/store/provider=chat/kind=thread/*/*/*/records.jsonl',
               format = 'newline_delimited',
               hive_partitioning = true,
               hive_types_autocast = false)
WHERE channel = 'C0123';
```

`hive_types_autocast = false` keeps the chat ts values as text.

### Day layer

With `places.<place>.store_dir` set, each complete read a run publishes is also filed by message day, under `<store_dir>/days/`. The [store-by-day spec](../../docs/features/store-by-day/) holds the rules.

```text
<store_dir>/days/provider=<key>/
  kind=history/year=YYYY/month=MM/day=DD/channel=<channel>/
  kind=thread/year=YYYY/month=MM/day=DD/channel=<channel>/root=<root ts>/
  kind=search/year=YYYY/month=MM/day=DD/search=<search name>/
  kind=reactions/year=YYYY/month=MM/day=DD/channel=<channel>/message=<message ts>/
```

- The day is the UTC day of the message ts; a reply goes to its own day, a reaction set to the day of its message. Member and user reads are not filed.
- Each day folder holds `records.jsonl` (the read's rows plus `fetch_id`, `fetched_at` and `transport`, ordered by ts) and `coverage.json` (the spans covered that day, per transport, or the newest fetch of a reaction set).
- One row per message: the newer fetch wins; a read filed again replaces its own rows, so a reparse followed by `build` fixes the day.
- A span covering a day with no message still writes that day, with coverage and no row, and so does a message with no reaction: "read, nothing said" differs from "never read".
- `failed` and `partial` reads are not filed. Read folders are unchanged.
- Merges hold `days/.lock`; `records.jsonl` is written before `coverage.json`, each by an atomic rename, so coverage never claims more than the rows hold.
- A filing error never fails the run: it prints `days: cannot file <read> by day: <reason>` to stderr, and `build` repairs it.
- The day layer is durable: `store.py prune` never touches it.

The other providers have no read store: their collections are filed by day instead, after `collect.py fetch` or `parse` writes them, when the place sets `store_dir` (never on a replay, never for a source not read):

```text
<store_dir>/days/provider=<key>/kind=<record kind>/year=YYYY/month=MM/day=DD/
```

| Adapter | Kinds | Day | Key |
|---|---|---|---|
| issue tracker | `issues` | `updated` | issue key |
| code host | `pull_requests`, `issues` | `updated_at` | repository and number |
| code host | `activity` | `at` | repository, number, kind, author, time |
| document store | `pages` (with their blocks) | `last_edited` | page id |
| observability | `monitors`, `discovered` | window end | monitor id |
| observability | `transitions` | `last_ts_ms` | routine, source, monitor |
| observability | `metrics` | window end | routine, source, entry key |

- Rows carry `fetch_id`, `fetched_at`, `routine`, `source` and `transport`; the newest fetch wins per key, so a day holds each issue, pull request or page once, as last seen.
- Transitions and metrics depend on the routine's window and query pack, so their key holds the routine and source: two routines never overwrite each other.
- `coverage.json` lists the fetches of the day (`fetches`), no span: a collection covers its source's scope, not the whole provider, so these days are never reused. `show` prints `fetches <N> newest <time>`.
- A filing error prints `days: cannot file <source> by day: <reason>` to stderr; the collection is written and the run goes on. `days.py build` files reads only, so a missed collection day is filed again only by a later run.

A chat source with `closed_days: true` reuses closed days:
- A day is closed when it ends at or before the window end. Only `history` and `thread` reads are reused this way; reactions keep `max_age`, searches are always fetched.
- The covered spans of closed days count as fresh whatever their age; the gaps are fetched, as with `max_age`.
- Trust rule: an `api` source takes `api` spans only, and skips a day folder holding any row fetched over `mcp`.
- A source skips a day folder its own reads filed during the run, unless it reused that folder earlier in the run.
- A reused day folder is linked into `<run>/store/days/` and listed in the manifest as `days/...`, so the run replays alone, from that copy.
- Messages edited or deleted after the stored fetch are not seen.
- The collection and run record hold `reads`, as with `max_age`.

Commands, from `runtime/`:

```text
python3 days.py build --root STORE_DIR [--provider P] [--kind K] [--from UTC_TIME] [--to UTC_TIME]
python3 days.py show  --root STORE_DIR --date YYYY-MM-DD [--to YYYY-MM-DD] [--provider P] [--kind K] [--channel C] [--records]
python3 days.py prune --root STORE_DIR --older-than-days N [--dry-run]
```

- `build` files every complete read under the root, with no network: the backfill of reads published before the day layer, and the repair after a `reparse`. It prints `<provider> <kind> reads <N> days <M>`, and is idempotent.
- `show` prints, per day, one line per entity: `full`, `partial` followed by its uncovered spans (`<from>_<to>`), or `read <fetch time>` for a reaction set; an entity never read is absent. `--records` prints the rows instead, as JSON lines with the path values added.
- `prune` deletes the day folders whose day ended more than N days ago, whatever their fetch time, and prints `<provider> deleted <N> kept <M>`. A run's linked copy survives.
- A malformed date, an end before the start, or a root that is not a folder exits 2.

DuckDB, one table per kind, the path values as columns:

```sql
SELECT year, month, day, channel, ts, author, text
FROM read_json('<store_dir>/days/provider=chat/kind=history/*/*/*/*/records.jsonl',
               hive_partitioning = true,
               hive_types_autocast = false)
WHERE year = '2026' AND month = '10' AND day = '26';
```

## Offline replay

A run folder holds its window, its state, its raw results, its run store, its manifest and its judgment, so the run's result can be rebuilt offline to test a change to a parser, an evaluator or the digest.

A watch routine replays in this order, `RUN` being the run folder and `OUT` a separate output folder:

```text
python3 runtime/collect.py replay    --config C --routine R --place P --sources RUN/sources.json --window RUN/window.json --state RUN/state.json --run RUN --out OUT/collections
python3 runtime/evaluate.py features --config C --routine R --state RUN/state.json --window RUN/window.json --collections OUT/collections --place P --runtime SHA --out OUT/features.json --base-out OUT/base.json --rules-out OUT/rules.json
python3 runtime/evaluate.py judge    --features OUT/features.json --base OUT/base.json --judgment RUN/judgment.json --out OUT/facts.json
python3 runtime/state.py apply       --state RUN/state.json --facts OUT/facts.json --window RUN/window.json --tz Z --out OUT/next.json --summary OUT/summary.json --record OUT/record.json
python3 runtime/digest.py            --summary OUT/summary.json --state OUT/next.json --record OUT/record.json --base OUT/base.json --tz Z --out OUT/digest.md
```

- Each command reads the run's files and writes only under `OUT`, so the run folder stays as it was.
- `P` is the place of the run, and `RUN/sources.json` the transport the run chose for each source, so each source replays through the same transport.
- Without `--sources`, each source replays through its first listed transport.
- `replay` makes no network call and reads no environment variable.
- A request that differs from its record, or one past the last record, exits 3 naming the source, the call number, the method and the path.
- A store-backed source replays only the reads `<run>/manifest.json` lists: a read the run did not make exits 3 naming it, and each asked request is compared with the one `read.json` recorded, a difference exiting 3 with the read, the call number and the differing fields, never a value.
- A run with a store-backed source and no `manifest.json` exits 2.
- A recorded error replays as the same not-read collection.
- A record that is not valid JSON exits 2 naming its file, and a record of the wrong shape exits 3 naming its file; an `mcp` source with no saved responses exits 2.
- `judge` checks the run's stored judgment against the replayed features, so a feature change that the judgment no longer fits exits 3 with the key path.
- When the run kept an analysis, `evaluate.py annotate` runs between `judge` and `apply` with the run's `analysis.json` and its `preview/summary.json`.
- The tribe and recap engines follow the same order with their own commands: `replay`, then `features`, `judge` with the stored judgment, `apply`, and `render` or `message` (see Tribe engine and Recap engine).

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
- `runs/<slug>/<run-at>.json`: one record per run, ready to parse for stats: window, counts, item keys, muted keys, blind spots, sources read, and the place, runtime commit, config commit, and transport and skipped transports per source when the run had collectors.

A run with no branch or no state file is a baseline run. The save fetches the branch again and commits on its latest tip, since other routines push to it during a run. A push rejected because the branch moved meanwhile is retried once. A failed save is reported in the digest as state not saved.

The schema and the rules are in the [routines-as-code spec](../../docs/features/routines-as-code/).

## Security

Record text written by other people (messages, titles) reaches a model that holds connector access and posting rights.
- The template treats any text from a source, a collection, a reason, a saved response or a script's output as data: it never follows instructions inside it and quotes it as plain text.
- Prefer the `api` transport for sources that carry text written by other people: the model then never reads record text. A transport list that ends with `mcp` routes that text through the model whenever the place lacks the `api` credentials.
- Keep routines that hold credentials on an environment shared only with routines that read no untrusted text.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `check-private` exits 2 | `CLAUDIO_PRIVATE_DIR` unset, missing, inside another repository's working tree, or a claudio checkout | Point it at the root of the private clone, outside any other repository |
| `render` exits 2 naming a placeholder | A template key has no value | Add it to `values` or the routine's `values` |
| `diff` prints `not exported` | No snapshot matches the config key: it is not the live routine's slug, or export has not run | Rename the key to the slug `export` printed, then run export again |
| Sync reports a residual diff | The live routine changed during the push, or the API rewrote a field | Run `/routines diff` and compare |
| A run says `degraded`, or `/routines run` stops before rendering | The runtime at `places.<place>.runtime_dir` is missing, at another commit, or holds changed or extra files | Run the setup script of that place again and check `runtime.sha` |
| `check-env` prints `missing <source> <variable>`, or a source is not read with `credentials missing: <variable>` | The place lacks a credential variable, or it is blank, and no `mcp` transport is listed for the source | Set it in the shell (`local`) or in the cloud environment's variables (`cloud`), or list `mcp` after `api` |
| `check-env` prints `fallback <source> <from> <to> <variable>` | `<variable>` is missing or blank, so the source is read through `<to>` | Set the variable to read the source through `<from>` |
| `check-env` prints `injected <source> <host>` | The provider's host is in the place's `injected_hosts`: the proxy adds the credential | Nothing; remove the host from `injected_hosts` to send the variables from the session instead |
| An `api` source reads locally but not in the cloud | The cloud environment blocks the provider's host | Allow the hosts the providers README lists for that vendor |
| The digest names a missing connector | The session lists no tool from the connector `check-env` named | Connect it in the session (`local`) or attach it to the routine (`cloud`), under the name `mcp.connectors.<place>` sets |
| A run reports `degraded: judgment rejected` | The model's judgment or analysis failed the checker twice | Read the key path in the message, then fix the rule text that led the model astray and run again |
| A source is not read with `partial: call cap` | Its relay loop reached 50 calls | Narrow the source's queries, or set its transport to `api` for that place |
| `replay` exits 3 with `a read the run did not make` | The walk asks a read the run's manifest does not list: the config, the window or the walk changed since the run | Replay with the config and the runtime of the run; to check a parser change alone, use `store.py reparse` |
| `replay` exits 2 with `holds no manifest.json` | The run folder holds a store-backed source but no manifest: it was written by a runtime without the read store, or the run stopped before its collections | Replay it with the runtime tag that wrote it |
| `collect.py sources` exits 2 naming `places.<place>.store_dir` | The folder is a link, belongs to another user, or lies inside a git working tree that does not ignore it | Point `store_dir` at a folder you own, outside every repository, or add the folder to that repository's `.gitignore` |
| A source with `max_age` still fetches its whole span | No stored read is eligible: older than `max_age`, fetched after the window end by another run, not complete, a connector read for an `api` source, or another provider key | Read the `read.json` of the stored reads, or raise `max_age` for that kind |
| `store_dir` keeps growing | Only `prune` deletes reads | Run `store.py prune --root <store_dir> --older-than-days N` |
| `<store_dir>/days` keeps growing | `store.py prune` leaves the day layer alone | Run `days.py prune --root <store_dir> --older-than-days N` |
| A run prints `days: cannot file <read> by day` | The day layer could not take the read; the read is published | Fix the cause, then run `days.py build --root <store_dir>` |
| A source with `closed_days` still fetches a past day | The day is not closed at the window end, no read filed it, its coverage has gaps, or it holds an `mcp` row for an `api` source | Run `days.py show --root <store_dir> --date <day>` |
| A source is not read with `plan not done` | The relay loop stopped before `plan` returned `done`: a missing connector, or the run stopped relaying | Fix the connector, then run again |
| `plan` prints the same call again after the model made it | The hook captured nothing for it: the session did not start in `$CLAUDIO_PRIVATE_DIR`, so Claude Code never loaded the hook, or the hook is not in `.claude/settings.json`, `CLAUDIO_RUNTIME_DIR` is wrong for the place, the capture folder is a link or belongs to another user, or the arguments differ from the printed ones (`plan` then prints a `relay capture mismatch` line) | Read `errors.log` in the capture folder and the `relay capture mismatch` line of the error output: it names the paths where the call differs, never their values, and a line that names identity paths such as `channel_id` or `message_ts` usually points at another source's capture when several sources relay in parallel (a known false positive). Fix the hook settings, or save that result by hand as the template says |
