# Routines as Code: Design

## Architecture Overview

Four parts, one new plugin, one private repository.

- **Leak guard**, at the repository root:
  - `scripts/leak_check.py` scans staged changes, the tree, or the history, and prints `path:line:rule`.
  - The pre-commit hook runs it on staged changes; CI runs it on the tree.
  - CI also runs the unit tests and the template lint.
- **Routine tooling**, in the new plugin `plugins/claudio-routines`:
  - The `/routines` skill drives the routines API through Claude's `RemoteTrigger` tool, the only client that holds the OAuth token.
  - `routines.py` does every file operation: normalize an API listing into snapshots, render templates, diff, lint, and build the update body.
  - Public skeletons sit in the plugin; real templates and render-time values sit in the private repository.
- **State engine**, in `plugins/claudio-routines/runtime/state.py`:
  - Computes the run window and the item lifecycle from the previous state and the facts the evaluator writes.
  - Cloud runs get it from a setup script on the default environment, which clones this repository at a pinned tag.
  - Each run reads and writes its state as a JSON file on the `claude/state` branch of the private repository, with one run record per run for stats.
- **Collectors**, in `plugins/claudio-routines/runtime/`:
  - `collect.py` reads one source of a routine for a window and writes a collection file in the schema of the source's role.
  - The `api` transport calls the provider's HTTPS API with credentials from environment variables.
  - The `mcp` transport writes a plan that the model relays through a claude.ai connector, then parses the saved responses.
  - The private config picks the transport per source and per place (`cloud`, `local`).
  - `providers/` holds one adapter module per vendor.
  - `evaluate.py` computes Prod watch's features from the collections, the query pack and the state, checks the model's judgment and analysis against them, and writes the facts `state.py` takes.
  - The routine's model judges the features against the routine's prose rules: it writes the verdicts (`open`, `severity`, `urgency`, `rank`, `cites`) and the analysis of new and escalated items, and sets no fact value.
  - A routine runs in the cloud on its schedule, or locally through `/routines run`, from the same template and the same pinned runtime.

The private repository (`$CLAUDIO_PRIVATE_DIR`) holds `config.json`, `templates/` and `routines/` snapshots on its main branch, and the run state on `claude/state`. CI never reads it, and no script writes it into this repository.

The routines name roles, not providers: an observability tool (monitors, metrics, alert events), a chat channel (the digest, and messages to read), a document store (the sources page with the mutes) and a code host (pull requests and issues). Which product fills each role is a private configuration choice: a source's `provider` in `config.json` picks the adapter.

## Usage Flow

```mermaid
flowchart TD
    A[Owner runs /routines diff or sync] --> B{CLAUDIO_PRIVATE_DIR set, outside this repo?}
    B -->|No| X[Stop: name the path problem]
    B -->|Yes| C[RemoteTrigger list]
    C --> D{API ok?}
    D -->|No| Y[Stop: name the HTTP status, write nothing]
    D -->|Yes| E[routines.py export: snapshots]
    E --> F[routines.py render: prompt per routine]
    F --> G{Placeholders resolved?}
    G -->|No| Z[Stop: name placeholder and template]
    G -->|Yes| H[routines.py diff]
    H --> I{Drift in prompt or cron?}
    I -->|No| J[in sync]
    I -->|Yes, diff only| K[Show diff]
    I -->|Yes, sync| L[Show diff, wait for approval]
    L -->|Declined| K
    L -->|Approved| M[routines.py body, RemoteTrigger update]
    M --> N[Export again, diff]
    N -->|Empty| O[Sync ok]
    N -->|Not empty| P[Sync failed, show residual diff]
```

A routine run, in the cloud on its schedule or locally through `/routines run`:

```mermaid
flowchart TD
    A[Cloud schedule, or owner runs /routines run] --> B[Prompt rendered for the place]
    B --> C{Pinned runtime hash ok?}
    C -->|No| X[Post degraded, stop, write no state]
    C -->|Yes| D[Load state from claude/state, or init a baseline]
    D --> E[state.py window, report-only for a local run without the post flag]
    E --> F[collect.py check-env and sources]
    F -->|Invalid config or query pack| Y[Post the error, stop, write no state]
    F --> G{Transport}
    G -->|api| H[collect.py fetch: HTTPS, env credentials]
    G -->|mcp| I[collect.py plan, model relays the calls, saves the responses]
    I --> J{Plan done?}
    J -->|No| I
    J -->|Yes| K[collect.py parse]
    H --> L[Collections]
    K --> L
    L --> M[evaluate.py features: values, features, rules]
    M --> M1[Model writes the judgment]
    M1 --> M2{evaluate.py judge}
    M2 -->|Rejected twice| W[Report degraded, stop, write no state]
    M2 --> M3[state.py apply into a preview]
    M3 --> M4[Model writes the analysis of new and escalated items]
    M4 --> M5{evaluate.py annotate}
    M5 -->|Rejected twice| W
    M5 --> N[state.py apply]
    N -->|Exit 3| Z[Post the rejection, stop, write no state]
    N --> O[Commit state and record to claude/state, push without force]
    O --> P{Post allowed for this run?}
    P -->|Cloud, or local with the post flag| Q[Post the digest to the chat channel]
    P -->|Local without the post flag| R[Print the digest]
```

## Component Diagram

```mermaid
graph LR
    subgraph public[This repository, public]
        LC[scripts/leak_check.py]
        HK[.githooks/pre-commit]
        CI[.github/workflows/ci.yml]
        SK[/routines skill/]
        RP[routines.py]
        SKEL[templates: skeletons, setup-env.sh]
        subgraph runtime[runtime, cloned at the pinned tag]
            ST[state.py]
            COL[collect.py]
            PRV[providers: one adapter per vendor]
        RL[roles.py: role schemas, config and pack validation]
            EV[evaluate.py]
            FT[features.py]
            JG[judgment.py]
        end
    end
    subgraph private[Private repository]
        CFG[(config.json: places, providers, sources, query packs)]
        TPL[(templates)]
        SNAP[(routines snapshots)]
        STATE[(claude/state: state and run records)]
    end
    subgraph cloud[claude.ai]
        API([Routines API])
        ENV[Default environment setup script]
        RUN[Routine run]
        CONN([Connectors])
    end
    LOCAL[Local session: /routines run]
    PAPI([Provider HTTPS APIs])
    HK --> LC
    CI --> LC
    CI --> RP
    SK -->|RemoteTrigger| API
    SK --> RP
    SK -->|run| LOCAL
    RP --> CFG
    RP --> TPL
    RP --> SKEL
    RP --> SNAP
    RP -->|lint flag contracts| runtime
    ENV -->|git clone tag| runtime
    RUN --> runtime
    LOCAL --> runtime
    COL --> CFG
    EV --> CFG
    COL --> PRV
    COL --> RL
    EV --> RL
    EV --> FT
    EV --> JG
    PRV -->|api| PAPI
    RUN -->|mcp relay, digest post| CONN
    LOCAL -->|mcp relay, digest post| CONN
    RUN --> STATE
    LOCAL --> STATE
```

## Technical Decisions

### TD-1: One stdlib scanner for hook, CI and history

**Choice**: `scripts/leak_check.py` with five modes:
- `--staged`: the lines added in the staged diff, and the staged paths.
- `--tree`: every line and every path of the text files that git tracks or would track (`git ls-files --cached --others --exclude-standard`).
- `--history`: the lines added by every commit reachable from all branches, the paths each commit adds or renames (both sides of a rename), and every commit message.
- `--range A..B`: the same as `--history`, for the commits of one range; CI scans the pushed or pull request commits with it.
- `--message FILE`: one commit message, for the commit-msg hook.

Files holding a NUL byte are scanned too, decoded as UTF-16 when they start with a BOM and as latin-1 otherwise; git diffs run with `--text`.

Removed lines are never scanned, so the commit that deletes a leak passes.

**Alternatives considered**:
- gitleaks: rejected, an external binary on every machine, and its reports print the match unless redaction is set everywhere.
- detect-secrets: rejected, a pip dependency, and it targets secrets, not deny-words or ids.

**Rationale**: zero dependencies, one rule set for all three modes, and full control of the output (BR-2).

### TD-2: Rules and output

**Choice**: named rules and three output shapes, exit 0 clean, 1 findings, 2 cannot run:
- `path:line:rule` for a line, `path:0:rule` for a path finding.
- `commit:path:line:rule` in history mode, and `commit:<message>:line:rule` for a commit message.
- Any part of a printed path that matches a rule is replaced by `<redacted>`.

| Rule | Pattern |
|---|---|
| `slack-id` | `(?<![A-Za-z0-9])[A-Z][A-Z0-9]{8,11}(?![A-Za-z0-9])` with at least 2 digits after the first character |
| `notion-id` | 32 hex characters of either case bounded by `(?<![0-9A-Za-z])` and `(?![0-9A-Za-z])`, or a case-insensitive UUID bounded by `(?<![0-9a-f-])` and `(?![0-9a-f-])` |
| `aws-account` | `(?<![0-9A-Za-z])(?<![0-9a-f]{4}-)[0-9]{12}(?![0-9A-Za-z])`, or the dashed form `dddd-dddd-dddd` with the same anchoring |
| `atlassian-account` | `[0-9]{6}:[0-9a-f-]{36}`, or 24 lowercase hex characters bounded like `notion-id` |
| `token` | `gh[pousr]_[A-Za-z0-9]{36}`, `github_pat_[A-Za-z0-9_]{22,}`, `xox[abprs]-[A-Za-z0-9-]{10,}`, `AKIA[0-9A-Z]{16}`, `sk-ant-[A-Za-z0-9_-]{20,}`, `-----BEGIN [A-Z ]*PRIVATE KEY-----` |
| `home-path` | `(?<![\w.])/(Users\|home)/[A-Za-z0-9._-]+`, `Users` matched case-insensitively |
| `deny-word` | each entry `re.escape`d, matched case-insensitively as a substring; an entry starting with `=` matches only between non-alphanumeric characters (AC-1.9) |

Bounded hex rules skip 40-character commit hashes, since a 32-hex match inside them has hex neighbours.

**Alternatives considered**:
- Printing a masked match: rejected, a masked company name still leaks its length and first letters.
- Exit 1 for "cannot run": rejected, CI could not tell a leak from a broken job.

**Rationale**: exit code 2 lets the hook and CI fail closed (BR-17) with a distinct message.

### TD-3: Deny-words sources

**Choice**:
- Local: the file named by `CLAUDIO_DENY_WORDS_FILE`, default `~/.config/claudio/deny-words.txt`, one entry per line, `#` comments.
- CI: the `LEAK_DENY_WORDS` environment variable, one entry per line, set from a repository secret in the leak-check step's `env` only.
- With `--require-deny-words`, the scanner exits 2 when the source is unset, empty, or has no entry once blank and `#` lines are dropped. CI passes the flag; the hook does not (AC-1.5).
- A fork guard step runs first when `github.event.pull_request.head.repo.full_name != github.repository`: it prints that the secret is not available to forks and exits 1 (AC-2.6).
- The workflow never uses `pull_request_target`.
- On a push, CI scans `before..after`; when `before` is not in the fetched history (a force push) or is all zeros (a new branch), it scans the full history instead.

**Alternatives considered**:
- A deny-words file committed encrypted: rejected, the key would still need a secret, for no gain.

**Rationale**: the words never touch the repository, and CI fails closed when the secret is absent.

### TD-4: Allowlist

**Choice**: `scripts/leak-allow.txt`, one entry per line: `path:<glob> <rule>` or `commit:<short-hash> <rule>`.
Initial entries:
- `path:plugins/claudio-rust/skills/rust-hexagonal/references/openapi-utoipa.md notion-id` (an RFC example UUID).
- `commit:174491e deny-word`, the onboarding commit whose examples were made generic later.

Commit entries need at least 7 hex characters and apply only in history mode; path entries never apply to commit messages.

**Alternatives considered**:
- Inline `leak-allow` comments: rejected, they need editing the flagged file and do not cover commits.

**Rationale**: covers examples and acknowledged commits (AC-3.4) without ever storing the match (BR-3).

### TD-5: Hook installation and branch protection

**Choice**:
- `scripts/install-hooks.sh` sets `core.hooksPath` to `.githooks`; running it twice is a no-op (AC-1.7).
- `commit-msg` scans only the message git keeps: it cuts the file at the scissors line and strips comment lines (`core.commentChar` aware) before `--message`.
- `scripts/check_protection.py` reads the protection of main through `gh api`. It exits 0 only when main requires a pull request, the `leak-check` status and enforcement for admins; 1 otherwise; 2 when `gh` fails (AC-2.5).
- The README documents the one-time `gh api` call that sets that protection.

**Alternatives considered**:
- Setting protection from CI: rejected, it needs an admin token in Actions.

**Rationale**: protection is a one-time owner action, and the check script makes its state verifiable.

### TD-6: A new plugin

**Choice**: `plugins/claudio-routines`, version 0.1.0, listed in the marketplace.
**Alternatives considered**:
- A skill inside `claudio-tools`: rejected, it ships runtime scripts that cloud runs pin by tag, which would couple their release to unrelated skills.

**Rationale**: an independent plugin and version, and a stable path for the runtime.

### TD-7: Template syntax

**Choice**: `{{dotted.key}}` placeholders, `\{{` for a literal marker, rendered by a stdlib regex.
**Alternatives considered**:
- `string.Template` (`$key`): rejected, prompts contain shell commands with `$`.
- Jinja2: rejected, a dependency, and loops or conditionals would move logic into templates.

**Rationale**: no logic in templates, unambiguous next to shell and JSON text.

### TD-8: Private repository location

**Choice**: the `CLAUDIO_PRIVATE_DIR` environment variable; `--private` overrides it. The script refuses a private path that lies inside another git working tree: the private directory must be the root of its own repository, or outside git, and its parent directory must not be inside a working tree (AC-4.7). It also refuses a claudio checkout given as the private directory.
**Alternatives considered**:
- A default path under the home directory: rejected, it would put a personal path into public code.

`routines.py check-private` runs the same checks alone, so the skill calls it before any API call (AC-4.4, AC-4.7).

**Rationale**: no personal path in this repository, and no way for an export to land in a tree that another repository could commit, whether the script runs from a checkout or from the plugin cache.

### TD-9: Snapshots as two files per routine

**Choice**:
- `routines/<slug>.json` holds id, name, cron, enabled flag, environment id, model, tools, the full `session_context` and the connector names, with sorted keys.
- `routines/<slug>.prompt.md` holds the prompt text.
- The slug comes from the routine name; two routines with the same slug stop the export.
- Every file is written to a temporary name first, and the renames happen only after all writes succeed (AC-4.6).

**Alternatives considered**:
- One JSON per routine: rejected, a prompt change becomes one long escaped line in the git diff.

**Rationale**: readable git diffs and stable output (AC-4.2).

### TD-10: Export input from the RemoteTrigger listing

**Choice**: the skill calls `RemoteTrigger list`. When the harness saved the result to a file, the skill passes that path to `routines.py export --input`; otherwise it writes the result to a scratch file first. The script accepts an optional `HTTP <status>` first line and stops on any status other than 200 (AC-4.8). A listing that carries a next-page marker stops the export before any write, since removing snapshots of routines on later pages would lose them.
**Alternatives considered**:
- One `get` per routine: rejected, more calls and the same data.

**Rationale**: the model never retypes the listing when the harness already saved it.

### TD-11: Private configuration shape

**Choice**: `config.json` in the private repository:
- `timezone`
- `runtime`: `repo` (HTTPS clone URL with no user info, query or fragment), `tag` (must match `^[A-Za-z0-9._-]+$`), `sha` (the commit hash of the tag, `git rev-parse <tag>^{commit}`, must match `^[0-9a-f]{40}$`)
- `places.<place>`, for `cloud` and `local`:
  - `runtime_dir`: where the setup script installs the runtime in that place; absolute, at least two levels below the root, characters `[A-Za-z0-9._-]` only, no `.` or `..` component, last component starting with `claudio-runtime`, since the setup script replaces that directory.
  - `state_dir`: the absolute path of the private repository checkout in that place, with the same character rule, since the template uses it unquoted in shell commands.
- `runtime.dir`, a shared `values.state.dir` and a routine `values.state.dir` are refused (exit 2), naming `places.<place>.runtime_dir` or `places.<place>.state_dir` as the replacement.
- `providers.<name>` (TD-19)
- `values`: shared render-time values (ids, channel, page ids)
- `routines.<slug>`: `id`, `template`, `cron`, its own `values`, `sources` (TD-19), `query_pack` (TD-23) and `models`

The render context merges `values`, then the routine's `values`, then `runtime.*`, `timezone`, and the rendered place: `runtime.dir`, `state.dir`, `place` and `run.post` (TD-24). `{{runtime.dir}}` and `{{state.dir}}` come only from `places`. Render refuses a `runtime.repo` not starting with `https://`, a `runtime.tag` or `runtime.sha` that does not match its pattern, and a `runtime_dir` that breaks its rule.

**Alternatives considered**:
- One config file per routine: rejected, shared ids would be duplicated.

**Rationale**: one place per value. Switching Prod watch to the runtime is a one-line change of `template` (BR-15, AC-11.4).

### TD-12: Update body built by the script

**Choice**: `routines.py body <slug> [--uuid U]` reads the fresh snapshot and the rendered prompt and prints the `RemoteTrigger update` body:
- `cron_expression` from the config.
- `job_config.ccr`: `environment_id` and `session_context` copied from the snapshot.
- One user event with the given or a new UUID and the rendered prompt.

**Alternatives considered**:
- The model assembles the body: rejected, it dropped and renamed fields in earlier manual updates.

**Rationale**: fields absent from the template stay as they are live (AC-8.2), and `--uuid` keeps tests deterministic (NFR-2).

### TD-13: State engine interface

**Choice**: `runtime/state.py` subcommands, each reading and writing JSON files:
- `window --state S --now T --tz Z [--since T0 | --report-only] --out W`: window, hour buckets, `retry_known_gaps`, cut span. Exit 3 when `--now` is before the previous run.
  - Without `--since`, the window starts at the last run in the state file (capped), or covers the baseline span when the state has none.
  - `--since T0` starts the window at `T0`, uncapped, and marks it `explicit` for a manual catch-up or backfill.
  - `--report-only` keeps the normal start and marks the window `explicit`, for a local run without `--post` (AC-10.8, BR-22).
- `apply --state S --facts F --window W --tz Z --out N --summary M --record R`: next state, change summary and run record. `run.at` is set to the window end, so events collected after the window was computed are read again by the next run.
  - With an `explicit` window, the summary and the record are written, the next state is byte-identical to the previous one, and the cursor regression check is skipped, since no cursor moves (BR-22, AC-9.4).
  - A key in the facts' `deferred` list keeps its item unchanged and is not required in `observations` (AC-9.14, BR-32).
  - The facts' `mutes` are kept in `run.mutes` (AC-9.15); a state without `run.mutes` reads as an empty list.
  - The facts' `run_context` is copied into the record, never into the state (TD-24).
- `init --digest NAME --out S`: the baseline state (schema 2, `run.at` null, no cursors, items or blind spots), written when `claude/state` has no state file for the routine.
- `validate (--state S | --facts F)`.
- The state is written as canonical JSON (2-space indent, sorted keys, trailing newline), so its git diffs are line-based.

**Alternatives considered**:
- One combined command: rejected, the window must exist before collection, the lifecycle only after.

**Rationale**: each step is a pure file-to-file function the model calls, so nothing in the lifecycle is decided in prose.

### TD-14: Time handling

**Choice**: compute in UTC. The first bucket starts at the local hour of `--tz` that contains the window start; buckets then step one real hour at a time and are labelled with `zoneinfo` local time plus the UTC offset (`Sun 02:00+02:00`, `Sun 02:00+01:00`), which also holds for zones with half-hour offsets.
**Alternatives considered**:
- `dateutil`: rejected, a dependency.
- Local-time arithmetic: rejected, it double counts or skips an hour on change days.

**Rationale**: correct on both daylight-saving change days (AC-10.3).

### TD-15: Runtime delivery

**Choice**: a setup script on the default environment, rendered from `skills/routines/templates/setup-env.sh`:
1. Clone this repository with `git -c credential.helper= clone --depth 1 --branch <tag>` over HTTPS into a `mktemp -d` directory.
2. Compare `git rev-parse HEAD` with the pinned hash.
3. On a match, replace the place's `runtime_dir` with the clone; on a mismatch, delete the temporary directory and leave nothing in place.

The prompt checks the same hash, and that `git status --porcelain --ignored` in the runtime directory is empty, before using the engine, and runs degraded otherwise (AC-11.3). The local place keeps its runtime between runs, so an edited or planted file there fails the check. Every runtime call runs `python3 -B`, so a run leaves no bytecode there.

Bump procedure, documented in the plugin README:
1. Tag a release.
2. Set `runtime.tag` and `runtime.sha` in the private config.
3. Run `routines.py setup-script` and paste its output into the environment settings.
4. Run `routines.py setup-script --place local` and run its output on the owner's machine.
5. Run `/routines sync`.

**Alternatives considered**:
- Attaching the repository as a routine source: rejected, no ref pinning, and the code host app the routines use can push to it.
- Fetching raw files with curl: rejected, one request per file and no single integrity check.

**Rationale**: a read-only, pinned, verifiable runtime with one documented place to bump.

### TD-16: Lint contract and rules

**Choice**:
- Public skeleton rules (AC-7.1, AC-7.2):
  - `literal-number`: 5 or more consecutive digits.
  - `channel-name`: `#` followed by a lowercase word.
  - `host`: a URL host, or a bare host name ending in `.com`, `.net`, `.io`, `.eu`, `.ai` or `.org`, other than `claude.ai` and `github.com`.
  - The setup script skeleton gets only the `host`, `literal-number` and `provider-name` rules.
  - `threshold`: a number followed by `%`, `ms`, `s`, `min`, `h`, `MB` or `GB`; or `above`, `below`, `over` or `under` followed by a number.
- Flag contract (AC-7.3), for each runtime script (`state.py`, `collect.py`, `evaluate.py`):
  - `lint --public` loads the checkout's script with `importlib`.
  - `lint --private` first requires `runtime.tag` to resolve to `runtime.sha` in the local checkout, then extracts the pinned `plugins/claudio-routines/runtime/` tree of `runtime.sha` from the local checkout (`git archive`) into a temporary directory, since the scripts import their siblings, loads each script from there, and exits 2 when the commit is missing.
  - The in-repo paths `plugins/claudio-routines` and `plugins/claudio-routines/runtime` are fixed strings, so the lint and the private-dir guard work from the plugin cache too.
  - Both read `build_parser()` subcommands and options, and check every `<script> <command> --flag` in a template against them; a call that names no subcommand of a script with subcommands fails as an unknown command.
- `provider-name` (AC-7.5, BR-30): its words are the module names under `providers/`; it checks the public skeletons (the setup script included), the plugin README and SKILL.md.

**Alternatives considered**:
- Parsing `--help` text: rejected, fragile.

**Rationale**: a template cannot call a command or flag that the engine it will run lacks.

### TD-17: State store on a private repository branch

**Choice**: the run state and the run records are JSON files on the `claude/state` branch of the private repository, which the routine attaches as a source:
- `state/<slug>.json`: the state the next run starts from.
- `runs/<slug>/<run-at>.json`: one record per run (window, counts, keys new, escalated and resolved, muted keys, blind spots, sources read), kept for stats.
- At the start of a run, the model fetches `claude/state`. A missing branch or file means a baseline run.
- At the end, it commits both files and pushes to `claude/state`. A failed push is reported in the digest as state not saved.
- The public repository is never attached to a routine.

**Alternatives considered**:
- A page in the document store: rejected, the model retypes the JSON on every write, and the page keeps no history for stats.
- A token in the environment variables, pushing to main: rejected, the token is visible to every routine on the environment.

**Rationale**: no secret, a full history of states and runs in git, and the routines' write access is limited to `claude/` branches of a private repository.

### TD-18: Collector contract

**Choice**: `collect.py` writes one collection per source, `<run>/collections/<source>.json`, as canonical JSON (AC-13.6):
- `schema` (1), `source`, `role`, `provider`, `transport`, `place`, `window` (`from_ts`, `to_ts`).
- `read`, and `reason` (null when read).
- `cursor`: the newest position reached, in the role's cursor shape. The state stores the observability cursors only (`cursors.observability`); a source of another role reads from the window start.
- `records`: in the role's record schema (Data Model), shared by every provider of the role (AC-13.7).
- `entries`: per query pack entry of the source, `ok`, `deferred` or `failed` with a reason, so the evaluator can defer one entry without dropping the source.

A source not read still gets a collection, with `read` false, a reason (control characters replaced by spaces, at most 200 characters) and empty records, and the command exits 0: a source not read is data for the run, not an error (AC-13.3). A partial read (page cap, size cap, partial response) sets `read` false with a reason starting `partial:` (AC-13.4, BR-28). An entry that fails on its own is `failed` in `entries`, and the source stays read (BR-32).

**Alternatives considered**:
- Collectors write facts: rejected, facts are Prod watch's lifecycle input, and the chat channel and code host feed other routines.
- One collection file per run: rejected, a source not read would hide the others.

**Rationale**: one contract per role lets a routine switch vendors by config, and keeps a routine unaware of the transport.

### TD-19: Transport per source and place

**Choice**: the private config holds (AC-13.1):
- `providers.<name>`: `adapter` (the vendor module name), `api.base_url`, `api.credentials` (each credential's environment variable name, never a value, AC-14.1, BR-25), `mcp.connectors.<place>` (the connector's name in that place, since a cloud session and a local session can name one vendor's connector differently).
- `providers.<name>.links_base` (optional): the HTTPS base of the vendor's web UI, for record links. Without it, an adapter derives the UI host from `api.base_url`; a provider read only through a connector sets it, since a connector does not reveal its host.
- `routines.<slug>.sources.<source>`: `provider`, `transport.cloud` and `transport.local` (`api` or `mcp`), and the role's source options.

Config load checks every source before any provider call, and exits 2 naming the key: an `api` transport needs an `api` block, an `mcp` transport needs `mcp.connectors.<place>`.

`collect.py` reads the config from the private repository checkout of the place. `fetch` on an `mcp` source, or `plan` and `parse` on an `api` source, exits 2: the transport never changes at run time, and a failed read never falls back (AC-13.5, BR-24).

`check-env` prints, for the place, every `api` source whose variables are missing and every `mcp` source with its connector name, and exits 1 when a variable is missing; the skill and the template confirm that the session lists a tool from each named connector (AC-16.6).

The digest post stays a model call to the chat channel's connector in both places.

**Alternatives considered**:
- Pick the transport by the credentials present: rejected, the transport would depend on the environment, not on git.
- One transport per place for every source: rejected, a provider with no connector, or no key in that place, would block the whole place.

**Rationale**: git decides how each source is read in each place, and a missing credential is a reported blind spot, not a silent switch.

### TD-20: API transport

**Choice**: one stdlib HTTPS client, `runtime/providers/_http.py`, used by every adapter:
- Host pinning (AC-14.3, BR-29):
  - `api.base_url` must use `https`, with no user info, query or fragment, checked at config load.
  - Each request is the base URL plus a path.
  - A pagination URL from a response is followed only when its scheme and host equal the base URL's.
  - Redirects are refused, so no credential header reaches another host.
- Credentials (AC-14.1, AC-14.2, BR-25):
  - Read from `os.environ` by variable name, at request time.
  - A missing variable marks the source not read, with reason `credentials missing: <VAR>` (AC-13.3).
  - Error messages carry the method, the path and the status only, never headers, values or response bodies.
- Limits:
  - 30 s timeout per socket operation, and a 30 s deadline for reading the whole response body; the status line and headers are bounded by the per-operation timeout only.
  - One retry on 429 and 5xx, after `Retry-After` capped at 30 s; other 4xx are not retried (AC-14.4).
  - 20 pages per query and 10 MB per response; reaching either marks the source partial (AC-14.5). A document store source also stops at 50 requests (page, block pages, table rows), as a partial read.
- TLS uses the default verified context.
- Tests inject a fake opener, so no test opens a connection (NFR-3, NFR-7).

**Alternatives considered**:
- `requests` or vendor SDKs: rejected, NFR-1 (standard library only), and cloud runs have no install step for them.

**Rationale**: host pinning, limits and redaction sit in one tested place for every vendor.

### TD-21: MCP transport: plan, relay, parse

**Choice**: three steps, each a file:
1. `collect.py plan --responses DIR --out PLAN` writes the next calls, given the responses saved so far: `{"done": false, "partial": null, "calls": [{"id", "connector", "tool", "arguments"}]}`, or `done` true with no calls.
2. The model calls each tool on the named connector with the arguments as given, and saves each result unchanged as `DIR/<id>.txt`: it copies the file when the harness saved the result to one, and writes the result text as is otherwise (AC-15.3).
3. `collect.py parse --responses DIR --out COLLECTION` reads the saved responses and writes the collection.

Loop termination (AC-15.6):
- Call ids are `<source>-<n>`, a running count over every call of the source (pages, channels, repositories), and `plan` never lists an id that has a saved response.
- The adapter ends the loop with `partial: "page cap"` after 20 pages of one query (a channel, a repository list, an event stream), and with `partial: "cursor repeated"` when a page returns the cursor of an earlier page; `parse` then marks the source partial.
- `collect.py` ends the loop with `partial: "call cap"` after 50 relayed calls for one source, a ceiling on model turns whatever the number of queries.
- An unreadable response ends the loop; `parse` marks the source not read, naming the tool (AC-15.5).

Two kinds of calls:
- A connector that runs code gets one script per plan step (AC-15.1). The script runs the source's queries, follows pagination inside the connector up to the page cap, and returns `{"payload": "<JSON text>", "checksum": "<hex>", "digest": "<hex>"}` (AC-15.4):
  - The payload is ASCII only: the script escapes every non-ASCII character as `\uXXXX`, so its UTF-16 code units equal its bytes.
  - `checksum` is FNV-1a 32-bit over the payload (offset `2166136261`, multiply with `Math.imul(h, 16777619) >>> 0`), as 8 lowercase hex digits. `parse` rejects a payload that is not ASCII or whose checksum differs.
  - The script embeds its parameters as one JSON text (`json.dumps` with sorted keys, ASCII only), parsed inside the script, never by string concatenation, so a query text cannot change the script.
  - `digest` is the same hash over that parameter text as embedded; `parse` compares it with the plan's `digest`, so edited parameters are rejected. Hashing the text, not a re-serialized object, keeps key order and number formats identical in both languages.
  - The payload carries the raw per-call data; `parse` normalizes it with the functions of the `api` transport, so both transports give the same records (AC-13.2).
  - Test vectors include an emoji and an escaped lone surrogate.
- A connector without code execution gets plain tool calls (AC-15.2). `parse` reads the response format that fixture tests pin.

**Alternatives considered**:
- The model writes the collection: rejected, that transcription is what the scripts replace.
- One static plan with every page: rejected, a cursor is known only after its page.

**Rationale**: the model only moves bytes between a connector and a file; the checksum and the digest catch a result or parameters changed in transcription, and parsing stays in tested code. They do not stop a hostile relay, which could compute both.

### TD-22: Provider adapters

**Choice**: `runtime/providers/` is a package:
- One module per vendor, named after the vendor, declaring `ROLE` and implementing `api_client(provider)`, `fetch(source, window, cursor, entries, http)`, `plan(source, window, cursor, entries, responses, connector)` and `parse(source, window, cursor, entries, responses, digests)`. `source` carries the source options, its `name` and its `provider_config`; `entries` are the query pack entries selected for this run (observability only, empty for the other roles).
- `providers/__init__.py` finds an adapter by module name, so no role-level code lists a vendor (BR-30).
- Adapters ship for the four roles, each with both transports (AC-13.8).
- Fixtures sit in `providers/fixtures/<vendor>/`, one set per transport for the same data; a test checks that both transports give the same records and cursor (AC-13.2). Id-shaped values are filled at test time (NFR-3).
- `providers/README.md` lists, per vendor, the credential variables, the read-only scope to create, the hosts the cloud environment must allow, and where each place reads the variables from (AC-14.6).
- `unittest discover -s plugins/claudio-routines/runtime` also runs the package's tests; `scripts/test_ci.py` counts a test directory inside a package of a listed directory as covered.
- The public lint gets the `provider-name` rule (TD-16, AC-7.5). The leak rules keep their id-format names and token patterns, which name an id shape; this repository's own git host and its CLI are tooling, not routine providers.

**Alternatives considered**:
- Adapters in the private repository: rejected by the owner, they would run unpinned and untested in CI.
- One module per role with vendor branches: rejected, a new vendor would edit shared code.

**Rationale**: a vendor change adds one module and changes config lines; the query pack's queries and monitor ids stay in the vendor's dialect and change with it.

### TD-23: Query pack and evaluator

**Choice**: `routines.<slug>.query_pack` in the private config (AC-17.1, BR-31), a list of entries:
- Every entry: `key` (unique), `source` (a configured observability source; its `kind`, `monitors` or `metrics`, is the engine source of the entry's observation), `title`, `link`, `schedule` (`every_run` or `daily`), and the fields of TD-31.
- Source names match `^[a-z][a-z0-9-]*$`, since they name collection files.
- Monitor entry: `monitor` (the monitor id, digits only); its key is `monitor-<monitor>`, since the engine derives the source from the prefix and a monitor has one key (TD-29). The accepted states are `OK`, `Alert`, `Warn`, `No Data`, `Skipped`, `Unknown` and `Ignored`; any other state fails the entry.
- Metric entry: `query`, `read` (`scalar`, `top` or `hourly`), `aggregator`, `top` (N, for `top`); its key never starts with `monitor-`.

`roles.py` holds the pack validation, called by `collect.py` and `evaluate.py` before any provider call; an invalid pack exits 3 naming the key path (AC-17.2). A pack key never equals a source name, since blind spots key both in one namespace.

`collect.py` decides which entries to read:
- A daily entry is read only when `run.daily_metrics_on` differs from the local date of the window end (AC-17.7).
- When the window's `retry_known_gaps` is false, an entry whose key is a known gap in the state is not read (AC-17.9, BR-19).
- Every other entry is read; skipped entries are `deferred` in the collection's `entries`.

`evaluate.py` builds the facts:
- One observation per key with a verdict: `value` comes from the features (TD-26); `over`, severity, urgency and rank come from the checked judgment (TD-27, AC-17.3, BR-38).
- `deferred` (BR-32, AC-9.14) lists the keys of:
  - entries not due (daily) or known gaps not retried, which stay out of `blind_spots`;
  - entries that failed on their own, and entries with no datapoints or a monitor absent from the collection, which are also blind spots (AC-17.8).
  - tracked metric keys of a read kind that are neither a pack key nor a group key of a pack top entry, which are also blind spots with the gap `not in the query pack` (AC-17.10); tracked monitor keys are read by id instead (BR-36). `roles.py` rejects a pack key that starts with a top entry's key followed by `-`, so a group key never matches another entry. Their items never resolve and, after 3 runs, their gap is known and keeps a blind spot slot: the owner re-adds the entry or edits the state.
- `sources.<s>.read` comes from the collections; a source not read gives no observation (AC-17.4).
- `daily_metrics_on` becomes the window end's local date only when the daily entries were read.
- Known gaps: with `retry_known_gaps` true, `blind_spots_retried` lists the known gaps attempted this run; with it false, it is empty.
- Cursors come from the collections; a source not read keeps its stored cursor (AC-9.13).
- Mutes come from the mutes table of the sources page (Data Model), and `sources_last_edited` from the page; when the page was not read, both come from the state (AC-17.6). A read page whose mutes table lacks the `key` column, or has no `until` column or both `until` and `silence until`, keeps the stored mutes and adds the blind spot `mutes table unreadable` on the document store source; rows with an empty key or an `until` that is not a date are skipped.
- `resolved_queries` comes from the state, `models` from the config, and `run_context` from the arguments and the collections (TD-24).
- The same records, cursors, state, pack and judgment give byte-identical facts, apart from `run_context` (AC-17.5).

**Alternatives considered**:
- The query pack on the sources page: rejected by the owner; the page keeps the mutes only.
- Thresholds in the query pack, decided by the evaluator: the first choice, replaced by prose rules the model judges (TD-25).
- A failed entry marks its whole source not read: rejected, one known gap would keep the source unread on every run, and no item of it would ever resolve.

**Rationale**: a local run and a cloud run over the same data agree, and a missing datapoint never resolves an item.

### TD-24: Places, local runs and the run context

**Choice**:
- `places.cloud` and `places.local` (TD-11) each set `runtime_dir` and `state_dir`.
- `routines.py render SLUG --place P [--post]` fills `{{runtime.dir}}`, `{{state.dir}}`, `{{place}}` and `{{run.post}}`. `run.post` is `yes` for the cloud place, and `yes` for the local place only with `--post`; with `no`, the digest is printed in the session (AC-16.4, BR-26). `diff`, `sync` and `body` render the cloud place.
- With `run.post` `no`, the template runs `state.py window --report-only`, so the run pushes its record and leaves the state unchanged (AC-16.8, BR-22): a change never reported in the chat channel is never consumed.
- `routines.py setup-script --place local` renders the same setup script for `places.local.runtime_dir`; the owner runs it once per runtime bump, so local runs use the pinned runtime and pass the same hash check (AC-16.7).
- `/routines run <slug> [--since T] [--post]`:
  1. Runs `check-private`, checks that the local runtime is at `runtime.sha`, and checks that `places.local.state_dir` is the private directory.
  2. Renders the local place.
  3. Runs `collect.py check-env`, names the missing variables, and checks the session lists a tool from each `mcp` connector (AC-16.6).
  4. Follows the rendered prompt in the session, with the start time when given (AC-16.3).
- The run starts from the remote `claude/state` (AC-16.1). The template saves the state from a worktree under the run directory, so the checked-out branch of the private repository never changes (AC-16.2), and pushes without force (AC-16.5, BR-27).
- Facts carry an optional `run_context`: `place`, `runtime` (the pinned commit), `config` (the private repository commit) and `config_dirty` (uncommitted config changes), and `collected.<source>` (`role`, `transport`, `read`, `reason`). `state.py` validates its shape and copies it into the run record; the state never stores it (AC-13.10, AC-13.11).

Accepted risks:
- Clock skew: a cloud run that starts within the skew after a local run exits 3 on `window` (AC-10.4), posts the rejection and writes nothing; the next run recovers.
- A local run with `--post` and a cloud run at the same time both post; the second push is rejected and reports `state not saved`, and the next run collects the window again.
- A local run reads the working tree's `config.json`, which can hold uncommitted changes; `config_dirty` marks those runs in the record.

**Alternatives considered**:
- The installed plugin's engine for local runs: rejected, its version can differ from the pinned tag, so local and cloud facts could differ.
- A separate local template: rejected, two prompts drift.
- A local run that saves the state without posting: rejected, it consumes new and resolved items that never reach the chat channel (BR-11).
- Headless `claude -p` runs: deferred, on-demand runs in a session come first.
- `state.py` reading the collections: rejected, the engine stays unaware of roles.

**Rationale**: one template, one runtime and one state branch for both places.

### TD-25: Judgment pipeline

**Choice**:
- `evaluate.py features` writes `features.json`, `base.json` and `rules.json` (TD-26). It decides nothing (AC-18.6).
- The routine's own model reads both files and writes `judgment.json`, one verdict per key that needs one (TD-27, AC-20.2).
- `evaluate.py judge` checks the judgment against the features and merges it with `base.json` into `facts.json`, the input `state.py apply` already takes (AC-21.8).
- A rejection exits 3 and names the key path; the template lets the model correct once, then reports `degraded: judgment rejected` and writes neither state nor record (AC-21.6, AC-21.7).
- The engine keeps the lifecycle (BR-9 to BR-12, BR-39); its only change is the rank order (TD-32).
- The judging model is the routine's model: the cloud routine's, or the local session's. No subagent.
- AC-20.6, AC-20.7 and AC-22.1 are model behavior: the template states them, and a model eval over saved features and rules checks them, outside the unit tests.

**Alternatives considered**:
- Thresholds in the pack, decided by `evaluate.py`: the first choice; a replay of one live window matched 10 of 24 live items.
- The model writes the facts: rejected, its values would be unchecked (BR-38).
- A smaller subagent judges: rejected, one more hop over the same data, and the routine's model already reads the rules.
- `state.py` checks the judgment: rejected, the engine stays unaware of features and roles.

**Rationale**: scripts keep every value and the lifecycle; the model judges what fixed thresholds missed, and every number it cites is checked.

### TD-26: Features, base and rules files

**Choice**: `evaluate.py features` writes three files:
- `features.json`, the model's input: compact JSON, floats rounded to 4 significant digits.
  - `bucket_labels`: the window's hour buckets, once per file, as local ISO times with date and offset, so a long `--since` window never repeats a label.
  - `keys.<key>`, for each pack entry read with data (except top entries, which give their groups), each group of a top entry, each discovered monitor and each tracked monitor key:
    - `kind` (`monitor`, `metric` or `group`), `entry` (the pack key, or null for a discovered monitor), `source`, `title`, `link`.
    - `values`, a flat map of named features:
      - monitor: `state`, `priority`, `transitions`, `first_transition`, `last_transition`, `transitions_per_hour` (AC-18.1);
      - metric and group: `value`, `window_max`, `window_max_at`, `latest`, `previous`, `change`, `change_percent` (AC-18.2), and for a group `groups_complete` (AC-18.4).
    - `buckets`, for an hourly entry: its values aligned with `bucket_labels`, and `excluded`, the indexes its excluded hours cover (AC-18.3); `value` and `window_max` skip excluded buckets, so a spike in an excluded hour never escalates (BR-10).
    - `days`, for a lookback entry: `[{label, value}]` daily buckets labelled with their UTC date, the last one marked `partial` (AC-18.5); its `value` and `window_max` are the largest daily value, partial day included, `window_max_at` that day's label, and `latest` the last daily value.
    - `tracked`: null, or the stored item's `severity`, `when`, `since`, `runs_under_threshold` and whether it holds an analysis; these anchor escalation (BR-10), and they are the only severity and urgency in the features (AC-18.6).
  - `auto.<key>`: keys that need no verdict, as `{reason, title, link, severity, when}` taken from the stored item, with the reason `not found` (AC-19.5), `group missing` (AC-21.10) or `replaced by groups` (AC-21.12); only keys of read sources (AC-17.4).
- `base.json`, read only by `judge`: every field of the facts except `observations` (sources, cursors, blind spots, retried gaps, mutes, deferred keys, `sources_last_edited`, `daily_metrics_on`, `resolved_queries`, `models`, `run_context`).
- `rules.json`: the pack's rule per entry key and the routine-wide rules.

Feature rules:
- `previous` comes from the stored state's `cursors.observability.metrics`, so `change` compares with the key's last collection; a daily entry compares with its last daily read.
- `base.json` cursors hold the features' `value` of this read, groups included, so `change` compares like with like; they drop the untracked group keys absent from a read entry, and keep the stored groups of an entry not read this run.
- `transitions` counts the monitor's alert events in the window; `transitions_per_hour` divides it by the hours between the first and the last event.
- A rate or a percent with fewer than 2 events, first and last events at the same time, no stored value, or a stored value of 0 is null (AC-18.9).
- A discovered monitor's name is cleaned like a collector reason (control characters to spaces), `@`, `<` and `>` replaced so a posted title mentions no one, and cut to 300 characters.
- A discovered monitor's link comes from the provider's `links_base`.
- Keys are sorted, so the same inputs give byte-identical features (AC-18.7).

**Alternatives considered**:
- The collections given to the model: rejected for size; the live tribe digest's observability collector alone read 294k tokens in one run.
- One file for the model and the merge: rejected, cursors and run context would cost model input for nothing (NFR-9).
- Features chosen per rule: rejected, the rules are prose.

**Rationale**: the model gets compact, named numbers it can cite, and the checker can verify every citation.

### TD-27: Judgment and analysis files, and their checks

**Choice**:
- `judgment.json`: `{"schema": 1, "verdicts": {<key>: {"open", "severity", "urgency", "rank", "cites"}}}`.
  - `cites` maps a name of the key's `values`, `bucket:<label>` for an hourly bucket, or `day:<label>` for a lookback day, to the value the verdict relies on (AC-20.3); a monitor verdict cites `state` (AC-20.5).
  - `rank` is an integer for open keys, 1 to N, each once, and null otherwise (AC-20.4, AC-21.5).
- `judge` rejects, with exit 3 and the key path, a `judgment.json` that is not valid JSON, and:
  - a verdict for a key absent from `keys`, deferred or auto (AC-21.1);
  - a key of `keys` with no verdict (AC-21.2);
  - a severity or urgency outside the allowed values (AC-21.3);
  - empty `cites` (AC-20.3), or a monitor verdict that does not cite `state` (AC-20.5);
  - a cited name the key lacks, a cited excluded bucket, or a cited value that differs from the feature (AC-21.4): values compare after parsing, numbers as numbers, booleans only with booleans, text exactly;
  - ranks that are not 1 to N over the open keys (AC-21.5).
- `judge` merges each verdict into an observation (`source`, `over`, `value`, `severity`, `when`, `title`, `link`, `last_value`, `rank`); an auto key becomes an observation not over that keeps its stored severity and urgency.
- `analysis.json`: `{"schema": 1, "items": {<key>: {"risk", "reason": [{"tag", "claim", "cites"}], "mitigation", "action"}}}`.
  - Its keys equal the new and escalated keys of the preview summary (TD-28, AC-22.4).
  - Each text is at most 300 characters, with no control, format or separator characters (Unicode Cc, Cf, Zl, Zp), and no `<`, `>`, `@` or `://`, so no mention or link reaches the posted digest; `reason` holds at most 5 claims and `mitigation` 1 to 3 texts (AC-22.3).
  - `tag` is `measured` or `inferred`; a measured claim has non-empty `cites`, checked like a verdict's (AC-22.2).
  - `evaluate.py annotate` adds it to the pass-1 `facts.json`, as the optional `risk`, `reason` (the list without `cites`), `mitigation` and `action` of those observations, and changes nothing else (TD-28).
  - A rejected analysis is corrected and reported like a judgment, with the same `degraded: judgment rejected` message (AC-22.4, AC-21.7).
- The engine types those item fields (labels, and `reason` as a list of `{tag, claim}`), so a tampered state cannot carry long or multi-line text. States written by the engine never held a text `reason`, since `evaluate.py` wrote no analysis before.

**Alternatives considered**:
- Free-text verdicts parsed by a script: rejected, fragile.
- Numbers matched inside the analysis prose: rejected, false rejections; claims cite structured values instead.

**Rationale**: every verdict and every measured claim is traceable to a feature, and a bad judgment fails loudly, once corrected, never silently.

### TD-28: Two-pass apply for the analysis

**Choice**:
1. `state.py apply` writes into `<run>/preview/`; the template reads only its summary, to list the new and escalated keys.
2. When there are any, the model writes `analysis.json` for exactly those keys.
3. `evaluate.py annotate --features FEATURES --facts F --analysis A --preview SUMMARY` adds the analysis to the pass-1 facts and changes nothing else, so an edited `judgment.json` cannot slip in.
4. `state.py apply` writes the real next state, summary and record. Facts that differ only in the analysis fields give the same lifecycle, so both passes agree.

- A report-only run keeps the state byte-identical (BR-22), and its summary still shows the analysis (AC-22.6).
- Muted keys are left out of the summary, so they get no analysis (BR-37).
- A still-open item keeps its stored analysis, since an observation without those fields leaves them unchanged (AC-22.5).

**Alternatives considered**:
- `evaluate.py` derives new and escalated keys: rejected, it would duplicate the engine's escalation rule (BR-10).
- An analysis for every open key at judgment time: rejected for cost, and against BR-37.

**Rationale**: the engine stays the only place that decides what changed.

### TD-29: Discovery and tracked monitors

**Choice**:
- A monitors source takes an optional `discovery_query`; without it, nothing is discovered (AC-19.1).
- Per run, the collector reads by id the pack's monitors and every tracked `monitor-<id>` key of the state (AC-19.4, BR-36), then runs the discovery search, following the provider's pagination up to the page cap (AC-19.6).
- Monitor records gain `priority` (integer or null); the collection's records gain `discovered` `[{id, name, state, priority, link}]` (search results and event-named monitors) and `discovery` `{read, reason, event_monitors_capped?}`; a discovered monitor is featured under `monitor-<id>` (AC-19.2).
- A by-id read the provider answers with not found gets the new entry status `missing`. For a tracked key, the evaluator turns it into the auto key `not found` (AC-19.5); for an untracked pack monitor, it adds the blind spot `not found` on the entry key and no observation.
- A failed or capped discovery sets `discovery.read` false with a reason, and the source stays read; `discovery` is null in a collection whose source was not read; the evaluator adds the blind spot `discovery incomplete` on the source and still features the monitors found (AC-19.7, BR-40). A discovered monitor with a state outside the accepted ones is left out of the features; the source keeps one blind spot that joins `discovery incomplete` and `monitor state not recognised: <ids>`, cut to 300 characters.
- After the events read, a failed by-id read of an event-named monitor other than not found marks the discovery not read, and an unknown state keeps the monitor for the features step to flag.
- After the events read, the collector reads by id every monitor the window's alert events name that is not in the pack, not tracked and not found by the search, at most 50 per run (the excess adds `event monitors capped at 50` to the source's blind spot), and lists them with the discovered monitors (AC-19.8).
- An untracked discovered monitor in state `OK` gets no key unless the window's alert events name it, so a monitor that flapped and recovered still reaches the model; at most 100 discovered monitors get a key, lowest ids first; the excess adds `discovery capped at 100 monitors` to the source's blind spot.
- A monitor found both by id and by discovery is featured once, under `monitor-<id>` (BR-35); `roles.py` requires pack monitor keys to equal `monitor-<monitor>` (AC-19.3).
- The adapter reads the discovery search over both transports; `providers/README.md` names the endpoint per vendor.

**Alternatives considered**:
- Discovery from the alert events only: rejected, a monitor stuck in Alert has no event in the window.
- Discovering every monitor, OK ones included: rejected for size; an OK monitor opens nothing.

**Rationale**: a monitor outside the pack reaches the model, and a tracked one is followed until it resolves.

### TD-30: Groups as keys

**Choice**:
- Each group of a top entry gets its own key (BR-34), `<entry key>-<slug>`: the group's tag values joined by `-`, lowercased, every run of other characters turned into `-`, trimmed, the whole key at most 120 characters.
- A slug that is empty, was cut, or equals another group's slug of the same entry ends with `-<fnv1a32>` of the raw group values, so case or punctuation never makes two groups collide on every run.
- A remaining collision within an entry, across entries, with a pack key or with a source name fails the entries involved, with a reason naming the key (AC-18.8).
- `groups_complete` is true when the read returned fewer groups than `top` (AC-18.4); a read with no group at all is the gap `no datapoints`, so tracked groups never resolve on empty data (AC-17.8).
- A tracked group key missing from a complete read becomes the auto key `group missing` (AC-21.10); missing from a capped read, it is deferred, and the entry key gets one blind spot `outside the top <N>` for all its missing groups, so groups never flood the cap of BR-12 (AC-21.11).
- The tracked group keys of a deferred or failed top entry are deferred with it.
- Known-gap retries count every key of `keys`, tracked monitor and group keys included, as attempted (BR-21).
- A tracked key equal to a top entry's key, from before its groups were tracked, becomes the auto key `replaced by groups` (AC-21.12).
- `features.py` expands a mute on a top entry key to that entry's group keys found in the features or the state (BR-41), so the engine's mute rule is unchanged.
- Group values are stored per group key in `cursors.observability.metrics`, which gives each group its `previous`.

**Alternatives considered**:
- One item per entry, judged on the top group: the first choice; a second queue growing behind the first was never seen.

**Rationale**: each queue or function gets its own lifecycle, and a group that drops out of the top N never resolves on missing data.

### TD-31: Query pack with prose rules

**Choice**:
- Every entry adds `rule`, a text of at most 500 characters (AC-20.1, BR-33).
- A metric entry adds optional `excluded_hours` (local hours 0 to 23, hourly entries only) and optional `lookback_days` (1 to 31, daily entries only, AC-18.5).
- A lookback entry reads over `lookback_days` ending at the window end: an hourly read becomes daily buckets, and scalar and top reads aggregate over the span.
- `routines.<slug>.rules` lists the routine-wide rules, for example flapping, discovered monitors and No Data, each at most 500 characters.
- `severity`, `urgency` and `threshold` leave the pack; entries must match their schema exactly, so a pack that still carries one fails with exit 3 and the key path (AC-17.2).

**Alternatives considered**:
- Structured rule fields (operators, durations, per-state maps): rejected by the owner, the model judges prose rules.

**Rationale**: the rules read like the live sources page, and each stays next to its query.

### TD-32: Rank order in the summary

**Choice**: observations carry an optional `rank`; the summary's new and escalated lists sort by rank, then by key, and each summary entry carries its rank (AC-21.9). The template's digest lists them in that order, each with its analysis (AC-22.7).

**Alternatives considered**:
- The model reorders the digest text: rejected, the order would be unchecked.

**Rationale**: the model sets the priority, a script keeps it.

### TD-33: Digest rendered by a script

**Choice**:
- A dedicated script, `digest.py --summary M --state N --record R --base BASE --out DIGEST`, renders the message as Markdown from the change summary, the next state, the run record and the base file. The title line takes the state's `digest` name and the record's `run_at`, so a report-only run shows its own time, so each routine's message carries its own title. The summary gives: new then escalated items in rank order, each with severity, urgency, link and analysis (risk, the reason's claims with their tags, mitigation leads, action); resolved items; still open items per severity: the keys of the summary's `still_open` lists, which leave muted keys out, each with its `since`, last value, link and stored action read from the next state by key; muted changes and dropped blind spots as counts; the blind spots with their gaps; the cut span; the unread sources and their reasons from `base.json` `run_context.collected`, whose blind spots are not listed twice; the overrides.
- The template posts the file's text unchanged with the chat tool, or prints it on a report-only run (BR-42); it adds only the `state not saved` line and the missing variables and connectors of the environment check, which the run knows before the digest.
- Every rendered value comes from the summary, the next state or the base file, whose text fields are labels or cleaned text, so no model-composed sentence reaches the channel.

**Alternatives considered**:
- The model composes the digest from the summary: rejected by the owner after the security review; source or model text could steer what is posted.

**Rationale**: the same run gives the same message, and the posted text is checked text only. Like `collect.py` for collecting, rendering has its own script, so `state.py` stays the lifecycle engine.

## Implementation Considerations

### Data Model

State schema 2, stored as `state/<slug>.json`:

| Key | Content |
|---|---|
| `schema`, `digest` | `2`, routine name |
| `run` | `at`, `previous_at` (UTC `Z`), `sources_last_edited`, `window` (`from_ts`, `to_ts`, Unix seconds), `daily_metrics_on`, `models`, `posted`, `mutes` (absent reads as empty) |
| `cursors.observability` | `events_ts_ms`, `monitors` (state by id), `metrics` (last value by key) |
| `items.<key>` | `title`, `topic`, `severity`, `when`, `status`, `confidence`, `since`, `opened_value`, `runs_under_threshold`, `last_value`, `link`, optional `risk` and `action` (labels), `reason` (list of `{tag, claim}`), `mitigation` (1 to 3 labels) |
| `resolved_queries` | object |
| `blind_spots` | list of `{key, gap, runs}` |

The engine adds `opened_value`; an existing item without it gets its current `value` on its next observation over its threshold.

Facts, written by `evaluate.py` from the collections and the query pack (TD-23):

| Key | Content |
|---|---|
| `sources.<name>.read` | boolean, per source (`monitors`, `metrics`) |
| `observations.<key>` | `source`, `over`, `value` (number or null), `severity`, `when` (the urgency), `title`, `link`, `last_value`, optional `rank`; optional `risk`, `reason`, `mitigation`, `action` from the analysis (TD-27), and optional `confidence` |
| `cursors` | the new `cursors.observability` values; a source not read keeps its stored cursor |
| `blind_spots` | list of `{key, gap}` seen this run |
| `blind_spots_retried` | keys of the known gaps retried this run |
| `mutes` | list of `{key, until}` (`until` as `YYYY-MM-DD`) from the mutes table of the sources page, or the stored `run.mutes` when the page was not read or its mutes table is unreadable |
| `deferred` | keys whose item is held unchanged this run (BR-32) |
| `overrides` | optional: monitor keys whose state is not OK while the judgment keeps them not open; copied into the run record, and into the summary as `{key, title, state}` without muted keys |
| `sources_last_edited`, `daily_metrics_on`, `resolved_queries`, `models` | copied into `run` and state |
| `run_context` | optional: `place`, `runtime`, `config`, `config_dirty`, `collected.<source>` (`role`, `transport`, `read`, `reason`); copied into the run record, never into the state |

Severity order: Low, Medium, High. Urgency order: watch, within months, now.

Run record, written by `apply --record` as `runs/<slug>/<run-at>.json`:

| Key | Content |
|---|---|
| `schema`, `digest` | `1`, routine name |
| `run_at`, `window` | the window end, and `from_ts`, `to_ts`, `explicit`, `cut` |
| `counts` | new, escalated, resolved, still open, tracked, muted changes; muted changes count in every bucket |
| `new`, `escalated`, `resolved` | item keys, muted keys included |
| `muted` | keys whose change this run was left out of the summary (BR-18) |
| `blind_spots`, `blind_spots_dropped` | gap keys and their runs after the cap, and the count the cap dropped (BR-12) |
| `sources_read` | source names read this run |
| `place`, `runtime`, `config`, `config_dirty`, `collected` | from the facts' `run_context`, when present |

The summary drives the digest and leaves muted changes out. It lists `still_open` per severity, each `{key, title}` in key order without muted keys, so the digest shows no muted item. It also lists `blind_spots` after the cap, each `{key, gap, runs}`, so the digest names each gap the cap kept and counts the dropped ones; the record drives stats and keeps every change.

Private config additions (TD-19, TD-23, TD-24):

| Key | Content |
|---|---|
| `providers.<name>` | `adapter`, `api.base_url`, `api.credentials.<credential>` (environment variable name), `mcp.connectors.<place>` (connector name in that place), optional `links_base` |
| `places.<place>` | `runtime_dir`, `state_dir`, for `cloud` and `local` |
| `routines.<slug>.sources.<source>` | `provider`, `transport.cloud`, `transport.local`, and the role's options |
| `routines.<slug>.query_pack` | list of entries (TD-23, TD-31) |
| `routines.<slug>.rules` | routine-wide rule texts (TD-31) |
| `routines.<slug>.sources.<monitors source>.discovery_query` | optional monitor search query (TD-29) |
| `routines.<slug>.models` | copied into the facts |

Role record schemas, shared by every provider of a role (AC-13.7):

| Role | Source options | Records | Cursor |
|---|---|---|---|
| observability | `kind` (`monitors` or `metrics`), `scope_filter` (the alert event search query of a `monitors` source; ignored by a `metrics` source), `discovery_query` (`monitors` only) | `monitors` kind: `monitors` `{id, name, state, priority, link}`, alert `events` `{ts_ms, link, monitor}` after the cursor (no title: the features use only the monitor and the time), `discovered` `{id, name, state, priority, link}` (search results and event-named monitors) and `discovery` `{read, reason}` with an optional `event_monitors_capped`; `metrics` kind: `metrics` `{key, value, hourly [{ts, value}], daily [{ts, value}], groups [{group, value}]}`, `daily` for lookback entries only | `events_ts_ms` and `monitors` for `monitors`, `metrics` for `metrics` |
| document store | `page_id` (`^[A-Za-z0-9-]+$`) | `pages`: `{id, title, last_edited, blocks [{type, text, rows}]}` | `last_edited` |
| chat channel | `channels` | `messages`: `{channel, ts, author, text, link}` | newest `ts` per channel |
| code host | `repos`, `query` (a non-empty `query` makes the source not read: neither transport supports it) | `pull_requests`: `{repo, number, title, author, state, draft, created_at, updated_at, merged_at, link}`; `issues`: `{repo, number, title, author, state, created_at, updated_at, link}` | newest `updated_at` |

A role's records hold only the fields both transports return, so `api` and `mcp` give the same records (AC-13.2): the chat connector's history has no thread fields, and the code host connector's issue list has no closing time.

The mutes table is the first table block under a heading whose text is `Mutes`, with the columns `key` and `until`; a `silence until` column stands for `until`, and a table with both is unreadable. Both sit at the top level of the page: neither transport reads the children of a toggle heading, so a table nested inside one is not found.

Entry statuses in a collection's `entries`: `ok`, `deferred`, `failed`, and `missing` when the provider reports the entry's object as not found (TD-29).

Features, base, rules, judgment and analysis files: TD-26 and TD-27. They stay in the run's temporary directory (NFR-8).

Plan file (TD-21): `{"done", "partial", "calls": [{"id", "connector", "tool", "arguments"}]}`. Per responses directory, `calls.json` keeps `{"calls": {id: digest or null}, "done", "partial"}` across plan steps, so `parse` knows every planned call, its expected digest, and whether the loop ended. A code script's result is `{"payload", "checksum", "digest"}`. Each source has its own responses directory.

### API / Interface

```text
python3 scripts/leak_check.py (--staged | --tree | --history | --range A..B | --message FILE) [--require-deny-words] [--allow FILE]
python3 .../routines.py check-private [--private DIR]
python3 .../routines.py export --input LISTING [--private DIR]
python3 .../routines.py render SLUG [--private DIR] [--place cloud|local] [--post] [--out FILE]
python3 .../routines.py diff [SLUG] [--private DIR]
python3 .../routines.py lint (--public | --private DIR [--claudio CHECKOUT])
python3 .../routines.py body SLUG [--private DIR] [--uuid U]
python3 .../routines.py setup-script [--private DIR] [--place cloud|local]
python3 .../runtime/state.py window --state S --now T --tz Z [--since T0 | --report-only] --out W
python3 .../runtime/state.py apply --state S --facts F --window W --tz Z --out N --summary M --record R
python3 .../runtime/state.py init --digest NAME --out S
python3 .../runtime/digest.py --summary M --state N --record R --base BASE --out DIGEST
python3 .../runtime/state.py validate (--state S | --facts F)
python3 .../runtime/collect.py sources   --config C --routine R --place P
python3 .../runtime/collect.py check-env --config C --routine R --place P
python3 .../runtime/collect.py fetch     --config C --routine R --source NAME --place P --window W --state S --out COLLECTION
python3 .../runtime/collect.py plan      --config C --routine R --source NAME --place P --window W --state S --responses DIR --out PLAN
python3 .../runtime/collect.py parse     --config C --routine R --source NAME --place P --window W --state S --responses DIR --out COLLECTION
python3 .../runtime/evaluate.py features --config C --routine R --state S --window W --collections DIR --place P --runtime SHA --out FEATURES --base-out BASE --rules-out RULES
python3 .../runtime/evaluate.py judge    --features FEATURES --base BASE --judgment J --out F
python3 .../runtime/evaluate.py annotate --features FEATURES --facts F --analysis A --preview SUMMARY --out F2
```

`collect.py` runs one source outside any routine with a window from `state.py window --since` over a state from `state.py init` (AC-13.9). `collect.py check-env` exits 1 when a variable is missing; `collect.py` and `evaluate.py` exit 3 on an invalid query pack; `evaluate.py judge` and `annotate` exit 3 on a rejected judgment or analysis.

Exit codes:
- 0: ok or in sync.
- 1: findings or drift.
- 2: usage error, input error, or a scan that cannot run.
- 3: rejected state, facts, time, query pack, judgment or analysis.

### Lifecycle Algorithm

For each key in the previous items or in the observations:
1. Its source is `monitors` for a `monitor-` key, else `metrics`; an `observations.<key>.source` that differs rejects the facts with exit 3.
2. Source not read: a tracked item is unchanged; an over-threshold observation of an untracked key rejects the facts with exit 3.
3. Source read and the previous key absent from `observations`: reject the facts with exit 3 and the key path (AC-9.10).
4. Observed over threshold:
   - Not in state: a new item, `opened_value` set from `value`.
   - In state: `runs_under_threshold` back to 0.
   - Escalated when severity or urgency moved up, or `value` is above 1.5 times `opened_value` (BR-10). The value test is skipped when either value is null or `opened_value` is 0 or less.
   - On escalation, `opened_value` becomes the current `value`, so one escalation is reported once.
   - Still open otherwise.
5. Observed not over: `runs_under_threshold` + 1. At 2 the item resolves (BR-9), appears in the summary and leaves the state (BR-11).
6. Mutes: a key muted until a date later than the window end's local date goes through steps 1 to 5, and is left out of the summary lists; the summary counts muted changes (BR-18).
7. The summary's new and escalated lists sort by `rank`, then by key; a key without a rank sorts last (TD-32).

Blind spots:
1. Each gap in the facts gets `runs` = previous `runs` + 1, or 1 if new.
2. A gap at 3 runs or more is known (BR-19).
3. A previous known gap absent from the facts is dropped only when its key is in `blind_spots_retried`, and carried unchanged otherwise (BR-21).
4. A previous gap that is not known and absent from the facts is dropped.
5. Known gaps sort first, then the list is cut to 8, and the summary counts the dropped entries (BR-12).

`window` sets `retry_known_gaps` to true when the previous run's local date differs from the current local date, or when there is no previous run.

### Performance

- `leak_check.py --tree` reads only the tracked and untracked non-ignored files; binary files are decoded rather than skipped, which keeps the scan under the NFR-4 budget at this repository's size.
- `--history` uses one `git log -p --all --no-color` stream, not one process per commit.
- `state.py` is linear in items, at about 50 items today.

### Security

- No scanner output echoes matched text (BR-2).
- `routines.py` refuses a private directory inside this working tree (AC-4.7), and prints config values only inside a rendered prompt the owner asked for.
- The setup script uses HTTPS with credential helpers disabled, clones into a temporary directory, and installs only a clone whose hash matches (AC-11.1, AC-11.2).
- The CI workflow sets `permissions: contents: read`, never runs on `pull_request_target`, and exposes the deny-words secret only to the leak-check step.
- Collectors:
  - Credentials live only in environment variables (BR-25): the local shell for the local place, the environment's variables at claude.ai for the cloud place, where every routine on that environment can read them, so each is a read-only key.
  - The HTTPS client pins the host, refuses redirects, and never prints headers, credential values or response bodies (TD-20).
  - A code script gets its parameters as one JSON literal (TD-21).
  - Collections, plans and responses stay in the run's temporary directory; only the state and the run record are committed (NFR-8).
  - Text from sources is untrusted and reaches a model that holds connector access and posting rights: record text, collection reasons, saved responses and script output. The template treats all of it as data, quoted as plain text, never as instructions.
  - The model judges `features.json` and `rules.json`: feature text such as a discovered monitor's name comes from a source and is data. The judgment and the analysis are model output; `judge` accepts only schema-valid, capped text whose cited values match the features.
  - Facts take titles and links from the query pack or, for a discovered monitor, from the typed features; the engine types and caps stored titles, links, analysis fields and blind spot gaps, and the collector caps reasons, so a tampered state or response cannot carry long or multi-line text.
  - Over the connector, the model reads the raw record text; over the `api` transport it never does. A source that carries text written by other people prefers the `api` transport.
  - Source text reaching the features goes through one cleaner: NFKC, control, format and separator characters turned into spaces, `@`, `<` and `>` replaced, cut to the label cap. Lone surrogates are replaced at collection, so no run stops on an unencodable character.
  - Accepted risk: the run directory, `features.json` and `base.json` included, is writable by the model, which also runs Bash. The checks catch a model's mistakes and keep source text inert; they do not contain a hijacked model, which the template's data rules and the single posting channel limit instead.
  - The chat connector's text format cannot mark message boundaries reliably: a message body that imitates a header can split or forge a message over the connector; the `api` transport is not affected.
  - The cloud environment's network settings must allow each `api` provider host; `providers/README.md` lists the hosts per vendor. A blocked host marks the source not read, naming the host.

## Sequence Diagrams

### Sync one routine

```mermaid
sequenceDiagram
    participant O as Owner
    participant S as /routines skill
    participant R as RemoteTrigger
    participant P as routines.py
    O->>S: /routines sync prod-watch
    S->>R: list
    R-->>S: listing or HTTP error
    alt HTTP error
        S-->>O: stop, name the status
    end
    S->>P: export --input listing
    P-->>S: fresh snapshots
    S->>P: diff prod-watch
    P-->>S: diff, exit 1
    S-->>O: full diff, ask for approval
    O->>S: approved
    S->>P: body prod-watch
    P-->>S: update body
    S->>R: update trigger id, body
    R-->>S: updated or HTTP error
    S->>R: list
    S->>P: export, then diff prod-watch
    alt diff empty
        S-->>O: sync ok
    else residual diff
        S-->>O: sync failed, residual diff
    end
```

### Prod watch run with collectors

```mermaid
sequenceDiagram
    participant M as Model, cloud or local session
    participant G as Private repo checkout
    participant St as state.py
    participant Co as collect.py
    participant P as Provider API
    participant Cn as Connector
    participant Ev as evaluate.py
    M->>M: check the pinned runtime hash
    alt hash mismatch or missing
        M->>M: post degraded, stop
    end
    M->>G: fetch claude/state, read state/<slug>.json
    alt branch or file missing
        M->>St: init
    end
    M->>St: window --state --now --tz [--since or --report-only]
    St-->>M: window, buckets, retry_known_gaps
    M->>Co: check-env, then sources --place
    alt invalid config or query pack
        Co-->>M: exit 2 or 3, key path
        M->>M: post the error, stop
    end
    Co-->>M: transport per source
    loop each api source
        M->>Co: fetch
        Co->>P: HTTPS requests, env credentials
        P-->>Co: pages
        Co-->>M: collection
    end
    loop each mcp source, until the plan is done
        M->>Co: plan --responses
        Co-->>M: calls, or done
        M->>Cn: each call, arguments as given
        Cn-->>M: result
        M->>M: save the result unchanged
    end
    M->>Co: parse --responses
    Co-->>M: collection
    M->>Ev: features, judgment, analysis (next diagram)
    alt evaluate fails, or judgment or analysis rejected twice
        Ev-->>M: exit 2 or 3, key path
        M->>M: post the error, stop
    end
    Ev-->>M: facts with run_context
    M->>St: apply --state --facts --window --tz --record
    alt rejected
        St-->>M: exit 3, key path
        M->>M: post the rejection, stop
    end
    St-->>M: next state, change summary, run record
    M->>G: worktree on claude/state, commit, push without force
    M->>M: post or print the digest, per run.post
```

### Judgment and analysis

```mermaid
sequenceDiagram
    participant M as Model, cloud or local session
    participant Ev as evaluate.py
    participant St as state.py
    M->>Ev: features --collections --state --window
    Ev-->>M: features.json, base.json, rules.json
    M->>M: write judgment.json from the features and rules
    M->>Ev: judge --features --base --judgment
    alt rejected
        Ev-->>M: exit 3, key path
        M->>M: correct judgment.json once
        M->>Ev: judge again
        alt rejected again
            Ev-->>M: exit 3
            M->>M: report degraded: judgment rejected, stop, write nothing
        end
    end
    Ev-->>M: facts.json
    M->>St: apply into the preview directory
    St-->>M: preview summary with the new and escalated keys
    opt new or escalated keys
        M->>M: write analysis.json for exactly those keys
        M->>Ev: annotate --facts --analysis --preview
        alt rejected twice
            M->>M: report degraded: judgment rejected, stop, write nothing
        end
        Ev-->>M: facts.json with the analysis
    end
    M->>St: apply --record
    St-->>M: next state, summary in rank order, run record
```

## File Inventory

| File | Action | Purpose |
|------|--------|---------|
| `scripts/leak_check.py` | new | Leak scanner: staged, tree and history modes, rules, deny-words, allowlist, `path:line:rule` output |
| `scripts/test_leak_check.py` | new | Unit tests for rules, deny-words, allowlist, modes and exit codes, with fixtures built at runtime |
| `scripts/leak-allow.txt` | new | Allowlist entries for examples and acknowledged commits |
| `scripts/install-hooks.sh` | new | Idempotent `core.hooksPath` setup |
| `scripts/check_protection.py` | new | Exit 0 only when main requires a pull request, the leak-check status and admin enforcement |
| `scripts/test_hooks.py` | new | Tests for the three hooks, install-hooks idempotency and check_protection against a stubbed `gh` |
| `.githooks/pre-commit` | new | Runs the scanner on staged changes |
| `.githooks/pre-merge-commit` | new | Runs the same check on automatic merge commits |
| `.githooks/commit-msg` | new | Scans the commit message with `--message` |
| `.github/workflows/ci.yml` | new | Fork guard, leak check on the tree, template lint, unit tests per directory, on pushes and pull requests to main |
| `scripts/test_ci.py` | new | Static assertions on `ci.yml`: `leak-check` job id, no `pull_request_target`, fork guard first, secret only in the leak-check step, one unittest run per test directory, a test package counted under its parent |
| `.gitignore` | modify | Ignore `__pycache__/` |
| `plugins/claudio-routines/.claude-plugin/plugin.json` | new | Plugin manifest, version 0.1.0 |
| `plugins/claudio-routines/README.md` | new | Setup (private directory, environment), usage, bump procedure, config reference |
| `plugins/claudio-routines/config.example.json` | new | Private config shape with placeholders such as `<chat-channel-id>` and `<40-hex-sha>` |
| `plugins/claudio-routines/skills/routines/SKILL.md` | new | Export, diff, render, lint, sync, setup-script and run flows, with the approval gate |
| `plugins/claudio-routines/skills/routines/scripts/routines.py` | new | check-private, export, render (per place), diff, lint, body and setup-script (per place) commands |
| `plugins/claudio-routines/skills/routines/scripts/lint.py` | new | Lint rule constants and pure rule functions, flag contracts of state.py, collect.py and evaluate.py, `provider-name` rule |
| `plugins/claudio-routines/skills/routines/scripts/test_routines.py` | new | Unit tests for every routines.py command |
| `plugins/claudio-routines/skills/routines/templates/prod-watch.md` | new | Public skeleton of Prod watch using the state engine, placeholders only |
| `plugins/claudio-routines/skills/routines/templates/setup-env.sh` | new | Environment setup script skeleton: temp clone, hash check, install |
| `plugins/claudio-routines/runtime/state.py` | new | State engine: window (with `--since`), apply (state, summary, run record with `run_context`), init, validate |
| `plugins/claudio-routines/runtime/test_state.py` | new | Unit tests for the lifecycle, blind spots, mutes, cursors and daylight-saving windows |
| `plugins/claudio-routines/runtime/collect.py` | new | Collector CLI: sources, check-env, fetch, plan, parse; config and transport rules |
| `plugins/claudio-routines/runtime/roles.py` | new | Collection and record schemas per role, and their validation |
| `plugins/claudio-routines/runtime/evaluate.py` | new | Query pack validation and Prod watch facts from the collections |
| `plugins/claudio-routines/runtime/test_roles.py` | new | Tests for role record, collector config and query pack validation, checksum and digest vectors |
| `plugins/claudio-routines/runtime/test_collect.py` | new | Tests for the collector CLI, config validation and transport rules |
| `plugins/claudio-routines/runtime/test_evaluate.py` | new | Tests for read modes, thresholds, daily entries, known gaps, mutes and `run_context` |
| `plugins/claudio-routines/runtime/providers/__init__.py` | new | Adapter lookup by module name |
| `plugins/claudio-routines/runtime/providers/_http.py` | new | HTTPS client: host pinning, no redirects, timeout, retry, caps, redaction |
| `plugins/claudio-routines/runtime/providers/test_http.py` | new | Tests for the HTTPS client against a fake opener |
| `plugins/claudio-routines/runtime/providers/<vendor>.py` | new | One adapter per vendor, for the observability, document store, chat channel and code host roles |
| `plugins/claudio-routines/runtime/providers/test_<vendor>.py` | new | Per adapter: both transports give the same collection, errors mark the source not read |
| `plugins/claudio-routines/runtime/providers/fixtures/` | new | API and connector responses per vendor and transport |
| `plugins/claudio-routines/runtime/providers/README.md` | new | Per vendor: credential variables, read-only scope, where each place reads them |
| `.claude-plugin/marketplace.json` | modify | Add `claudio-routines`, bump the marketplace version |
| `README.md` | modify | Plugin table, leak guard setup and contributing steps |
| `plugins/claudio-routines/runtime/features.py` | new | Judgment: features per key from the collections, the pack and the state: transitions, deltas, buckets, groups, discovered and tracked monitors, auto keys |
| `plugins/claudio-routines/runtime/judgment.py` | new | Judgment: judgment and analysis schemas, cite and rank checks, merge into facts, analysis added to facts |
| `plugins/claudio-routines/runtime/test_features.py` | new | Judgment: tests for every feature, group keys, collisions, auto keys, mute expansion and determinism |
| `plugins/claudio-routines/runtime/test_judgment.py` | new | Judgment: tests for every rejection, the merge, ranks and the analysis checks |
| `plugins/claudio-routines/runtime/evaluate.py` | modify | Judgment: `features`, `judge` and `annotate` subcommands |
| `plugins/claudio-routines/runtime/roles.py` | modify | Judgment: pack entries with prose rules, routine rules, `discovery_query`, `missing` status, monitor records with `priority`, `discovered` and `discovery` |
| `plugins/claudio-routines/runtime/collect.py` | modify | Judgment: tracked monitor ids read by id, lookback spans |
| `plugins/claudio-routines/runtime/state.py` | modify | Judgment: rank order in the summary, typed analysis fields |
| `plugins/claudio-routines/runtime/providers/<vendor>.py` | modify | Judgment, observability adapter: discovery search, priority, not found, lookback reads, over both transports |
| `plugins/claudio-routines/skills/routines/scripts/lint.py` | modify | Judgment: a call without a subcommand to a script with subcommands fails |
| `plugins/claudio-routines/runtime/digest.py` | new | Digest: renders the posted message from the summary, the next state and the base file (TD-33) |
| `plugins/claudio-routines/runtime/test_digest.py` | new | Digest: each section, empty sections skipped, rank order, report-only output, only summary, state and base text rendered |
| `plugins/claudio-routines/runtime/support.py`, `evaluate_support.py`, `providers/datadog_support.py` | new | Test support: shared state, evaluator and adapter fixtures, so no test module imports another |
| `plugins/claudio-routines/runtime/test_pipeline.py` | new | Judgment: one fixture run through `features`, `judge`, a preview apply, `annotate` and `apply`, checking rank order and the stored analysis |
| `plugins/claudio-routines/skills/routines/templates/prod-watch.md` | modify | Judgment: features, judgment, preview apply, analysis and rank-ordered digest steps |
| `plugins/claudio-routines/config.example.json` | modify | Judgment: pack entries with prose rules, routine rules, `discovery_query` |
| `plugins/claudio-routines/README.md` | modify | Judgment: pack fields, rules, discovery, judgment steps |
| `plugins/claudio-routines/runtime/test_roles.py`, `test_collect.py`, `test_evaluate.py`, `test_state.py` | modify | Judgment: tests for pack entries with prose rules, the new collection fields, tracked monitor reads, lookback spans, the subcommands, rank order and typed analysis |
| `plugins/claudio-routines/runtime/providers/test_<vendor>.py`, `test_<vendor>_relay.py`, `fixtures/<vendor>/`, `README.md` | modify | Judgment, observability adapter: discovery, priority, not found and lookback fixtures over both transports, and the discovery endpoint per vendor |
| `plugins/claudio-routines/skills/routines/scripts/test_routines.py` | modify | Judgment: template steps and flag contracts of the `evaluate.py` subcommands |

A task creates the private repository files (`config.json`, `templates/prod-watch.md`, `templates/prod-watch-runtime.md`, `routines/*`) outside this repository; this inventory never lists their content.

## Non-Functional Requirements

- **NFR-1** (Compatibility): Python 3.10.12 or later (`lint --private` needs the tar extraction filter), standard library only, on macOS and Linux; `git` and `gh` are the only external commands.
- **NFR-2** (Determinism): every script takes its time and random inputs as arguments where they matter (`--now`, `--uuid`), and the same inputs give byte-identical outputs.
- **NFR-3** (Testability): tests run offline with `python3 -m unittest discover -s <dir>`, one run per directory holding tests, and build every id-shaped fixture at runtime.
- **NFR-4** (Performance): `leak_check.py --tree` under 5 s and `--staged` under 1 s on this repository; `state.py apply` under 1 s for 200 items.
- **NFR-5** (Security): no script prints a leak match, a secret or a config value outside a requested render.
- **NFR-6** (Portability): no absolute home path, user name or private identifier in this repository; the `home-path`, id and deny-word rules enforce it on paths and lines at commit and CI time, and on commit messages through the history scan.
- **NFR-7** (Network): only `api` collectors open connections, to the configured hosts, within the TD-20 limits; no test opens one.
- **NFR-8** (Privacy): collections, plans and responses stay in the run's temporary directory and are never committed; a run commits only its state and its record.
- **NFR-9** (Model input): `features.json` and `rules.json` together stay under 150 kB for 50 keys with 72 hourly buckets each, 500-character rules and values of up to 15 digits; the live Prod watch pack measures under 100 kB.
- **NFR-10** (Performance): `evaluate.py features` and `evaluate.py judge` each run under 1 s for 50 keys.
