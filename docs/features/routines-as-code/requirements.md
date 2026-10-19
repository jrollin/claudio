# Routines as Code: Requirements

## Overview

Puts the owner's claude.ai routines (scheduled cloud agents) under version control and moves their deterministic logic into tested scripts. Prod watch is the first routine moved.

- A public plugin in this repository ships the render and diff scripts, generic prompt skeletons, a runtime state engine and a leak guard.
- A private repository holds the real prompt templates and the render-time values that name company resources.
- The private config holds the shared settings once, in `config.json`, and the routines, one file each.
- A skill renders, diffs and pushes routine prompts.
- The state engine computes the lifecycle of the items a routine run tracks.
- Collectors read each source through the provider's API or through a claude.ai connector, chosen per source and per place, so a routine runs the same way locally and in the cloud.
- Scripts compute the values and features of each run; the model judges them against the routine's rules, and a script checks each judgment before the engine applies it.

## Problem Statement

**Who** is affected: the owner of this repository, who maintains claude.ai routines and publishes this repository publicly.
**What** problem they face:
- Routine prompts live in the claude.ai UI and in hand-made copies, with no history or review.
- Each run re-derives its deterministic logic in prose: state diffs, time windows, cursor updates.
- Private identifiers can reach a public repository, and git history keeps them.
- Data collection is prose that tells the model which connector tools to call, so a routine runs only inside a cloud session.
- Fixed thresholds miss what the model catches: a replay of one live Prod watch window matched 10 of its 24 open items, missing flapping monitors, monitors outside the pack and growth-based rules.
- One config file holds every routine, and each source repeats its provider's transport.
- Only Prod watch has a template: the other 4 live prompts have no history, diff or lint.
- The tribe digests collect through 4 model subagents per run.
- Each of those subagents costs 150k to 300k tokens.
- The model rebuilds about 16 kB of run state JSON by hand on each digest run, inside the page it writes.
- Their logs show truncated reads and wrong default aggregators.
**Why** it matters:
- Drift between copies makes routines skip steps.
- Re-derived logic costs tokens on every run.
- Re-derived logic gives different results from run to run.
- A leaked identifier stays in public git history.
**How** success is measured:
- Every live routine prompt equals its rendered template.
- No private identifier reaches the public repository.
- Prod watch item lifecycle comes from a tested script, not from the model.
- For the same window and the same provider data, a Prod watch run gives the same features locally and in the cloud.
- A replay of a live Prod watch window opens the same items as the live routine, apart from states that changed between the two reads.
- Every value of a digest item, and every value a measured claim cites, traces to a feature.
- A provider's settings appear once in the private config, whatever the number of routines that read it.
- A replay collection holds every issue key, document page and chat channel a reference tribe digest cites, or gives the reason it does not.
- A replay seeded from one live tribe digest matches the next one's warnings, checks and decisions, or gives the reason it does not.

## User Stories

### Block leaks at commit time {#US-1}

WHEN the owner commits to this repository
THE pre-commit hook scans the staged changes with the generic leak patterns and the local deny-words, and blocks the commit on a match

**Acceptance Criteria:**
- [ ] A staged line with a Slack id, Notion id, 12-digit AWS account id, Atlassian account id, token or absolute home path blocks the commit with exit code 1, per BR-1 *(AC-1.1)*
- [ ] A staged line with a word from the local deny-words file blocks the commit *(AC-1.2)*
- [ ] Each finding prints `path:line:rule`, never the matched text, per BR-2 *(AC-1.3)*
- [ ] A finding covered by an allowlist entry does not block, per BR-3 *(AC-1.4)*
- [ ] With no local deny-words file, the hook runs the generic patterns and prints one notice that deny-words were skipped *(AC-1.5)*
- [ ] A staged binary file is scanned as text, and a deleted file is skipped without error *(AC-1.6)*
- [ ] A documented command installs the hook, and running it again changes nothing *(AC-1.7)*
- [ ] A scanner that cannot run exits 2 and blocks the commit, per BR-17 *(AC-1.8)*
- [ ] Deny-words match case-insensitively as substrings: `acme` matches `Acme`, `acme-api` and `AcmeApp`; an entry prefixed `=` matches whole words only *(AC-1.9)*
- [ ] A commit message with a leak-shaped token or a deny-word is blocked by the commit-msg hook *(AC-1.10)*

### Block leaks before merge {#US-2}

WHEN a branch is pushed or a pull request is opened
THE CI job scans the whole tree with the generic patterns and the deny-words held in a repository secret, and fails the leak-check status on any finding

**Acceptance Criteria:**
- [ ] A push or pull request adding a generic-pattern match fails the leak-check status *(AC-2.1)*
- [ ] A push or pull request adding a deny-word fails the status, and the job log shows only `path:line:rule` *(AC-2.2)*
- [ ] A missing deny-words secret fails the job with a message naming the secret, per BR-17 *(AC-2.3)*
- [ ] The CI job fails when the unit tests or the template lint fail *(AC-2.4)*
- [ ] A documented setup step protects main, per BR-4, and a check command exits 0 only when main requires a pull request, the `leak-check` status and enforcement for admins, 1 otherwise, and 2 when it cannot read the settings *(AC-2.5)*
- [ ] A pull request from a fork fails the deny-words step, per BR-17, and the log says the secret is not available to forks *(AC-2.6)*
- [ ] A leak added and removed again inside the pushed or pull request commits fails the status: CI scans the lines and messages of those commits, not only the final tree *(AC-2.7)*

### Scan past commits {#US-3}

WHEN the owner runs the history scan
THE script scans the lines added by every commit reachable from all branches, and every commit message, with the generic patterns and the local deny-words, and reports each finding with its commit, path, line and rule, without changing history

**Acceptance Criteria:**
- [ ] A finding present only in an old commit is reported with that commit's short hash *(AC-3.1)*
- [ ] The scan prints a count per rule *(AC-3.2)*
- [ ] The scan never runs a command that rewrites history *(AC-3.3)*
- [ ] The scan exits 1 when a finding exists that no allowlist entry acknowledges, per BR-3 *(AC-3.4)*

### Export live routines {#US-4}

WHEN the owner runs `/routines export`
THE skill reads every live routine through the routines API, and the script writes one normalized snapshot per routine into the private repository

**Acceptance Criteria:**
- [ ] Each snapshot holds name, id, cron expression, enabled flag, environment id, model, tools, connector names and prompt *(AC-4.1)*
- [ ] Snapshots use a stable key order, so re-exporting an unchanged routine produces no git diff *(AC-4.2)*
- [ ] Run history, timestamps and run sessions are not written *(AC-4.3)*
- [ ] A missing or unconfigured private repository path stops the export before any API call, naming the path *(AC-4.4)*
- [ ] A malformed API response stops the export, naming the routine id that failed *(AC-4.5)*
- [ ] A failed export leaves no partially written snapshot *(AC-4.6)*
- [ ] A private repository path inside this repository's working tree stops the export before any API call, naming the path, per BR-1 *(AC-4.7)*
- [ ] An unreachable or unauthorized routines API stops the export before any write, naming the HTTP status *(AC-4.8)*

### Render a routine prompt {#US-5}

WHEN the owner renders a routine
THE script fills the routine's private template, or the public skeleton when no private template exists, with the render-time values of the private repository

**Acceptance Criteria:**
- [ ] The rendered prompt contains no unresolved placeholder *(AC-5.1)*
- [ ] A placeholder with no value fails the render, naming the placeholder and the template *(AC-5.2)*
- [ ] A value that no template uses is reported as a warning *(AC-5.3)*
- [ ] The private template wins over the public skeleton of the same routine *(AC-5.4)*
- [ ] Rendering twice with the same inputs gives byte-identical output *(AC-5.5)*
- [ ] An escaped marker `\{{` renders as a literal `{{` *(AC-5.6)*

### Show drift between git and live {#US-6}

WHEN the owner runs `/routines diff`
THE skill exports every live routine, then the script compares each rendered routine with its fresh snapshot and prints a unified diff per field (prompt, cron)

**Acceptance Criteria:**
- [ ] A routine whose rendered prompt equals its fresh snapshot prints `in sync` *(AC-6.1)*
- [ ] Any difference sets exit code 1 and names the routine and the field, per BR-5 *(AC-6.2)*
- [ ] A routine with a template but no live routine is reported as `not exported` *(AC-6.3)*
- [ ] A live routine with no template is reported as `untracked` *(AC-6.4)*
- [ ] Connectors, model and tools are printed as information, never counted as drift *(AC-6.5)*

### Lint templates {#US-7}

WHEN templates are linted, in CI for the public skeletons or locally for the private templates
THE linter rejects content that breaks the template contract

**Acceptance Criteria:**
- [ ] A public skeleton with a literal number of 5 or more digits fails the lint, per BR-8 *(AC-7.1)*
- [ ] A public skeleton with a `#channel` name, a URL host not on the allowlist or a threshold pattern fails the lint, per BR-8 *(AC-7.2)*
- [ ] A template referencing a command or flag of `state.py`, `collect.py`, `evaluate.py`, `digest.py` or `tribe.py` that does not exist fails the lint *(AC-7.3)*
- [ ] Each lint failure prints `path:line:rule` *(AC-7.4)*
- [ ] A public skeleton, the plugin README or SKILL.md naming a vendor that has a module under `providers/` fails the lint, per BR-30 *(AC-7.5)*

### Push a rendered routine {#US-8}

WHEN the owner approves the diff shown by `/routines sync` for a routine
THE skill pushes the rendered prompt and cron through the routines API, exports the routine again and confirms that the diff is empty

**Acceptance Criteria:**
- [ ] The skill shows the full diff and waits for an explicit approval before any push, per BR-6 *(AC-8.1)*
- [ ] Fields absent from the template stay as they are live: environment and tools are sent unchanged from a snapshot exported at the start of the sync, and connectors are not sent *(AC-8.2)*
- [ ] A non-empty diff after the push is reported as a failed sync, with the residual diff, per BR-7 *(AC-8.3)*
- [ ] An API error stops the sync for that routine and leaves the other routines untouched *(AC-8.4)*

### Compute a run's item lifecycle {#US-9}

WHEN a Prod watch run passes its previous state and the facts collected in this run to the state engine
THE engine validates the state, applies the lifecycle rules, and writes the next state and a change summary for the message

**Acceptance Criteria:**
- [ ] A previous state with a wrong schema version or a missing required key is rejected with the key path, and nothing is written *(AC-9.1)*
- [ ] Items are classified as new, escalated, resolved or still open per BR-9, BR-10 and BR-11 *(AC-9.2)*
- [ ] A resolved item appears once in the change summary and is absent from the next state *(AC-9.3)*
- [ ] In a run that advances the state, a cursor in the facts older than the stored cursor is rejected, and the stored cursor is kept, per BR-14 *(AC-9.4)*
- [ ] Blind spots keep their run count across runs and follow BR-12, BR-19 and BR-21 *(AC-9.5)*
- [ ] A muted item follows BR-18 *(AC-9.6)*
- [ ] Facts that read every source and observe every tracked key as not over only increment `runs_under_threshold`, and resolve the items reaching 2 *(AC-9.7)*
- [ ] The facts declare, per observed key, its source, whether it is open (`over`), its value, its severity and its urgency; per source, whether it was read; and the known gaps retried this run, per BR-16 *(AC-9.8)*
- [ ] A facts file missing one of those fields is rejected with exit code 3 and the key path, and nothing is written *(AC-9.9)*
- [ ] A tracked key absent from the observations while its source was read rejects the facts with exit code 3 and the key path *(AC-9.10)*
- [ ] Each run writes a run record with its window, its counts, the keys new, escalated and resolved, its blind spots and the sources it read *(AC-9.11)*
- [ ] With an explicit window, the summary and the run record are written, and the next state is byte-identical to the previous one, per BR-22 *(AC-9.12)*
- [ ] A source not read keeps its stored cursor, per BR-14 *(AC-9.13)*
- [ ] A key listed as deferred in the facts keeps its item unchanged, and its absence from the observations is not rejected, per BR-32 *(AC-9.14)*
- [ ] The next state keeps the facts' mutes in `run.mutes` *(AC-9.15)*

### Compute the run window {#US-10}

WHEN a run starts
THE engine computes the run window and the local hour buckets from the previous run time and the current time

**Acceptance Criteria:**
- [ ] The window starts at the previous run time, capped per BR-13, and ends at the current time *(AC-10.1)*
- [ ] A baseline run (no previous run time) covers the span of BR-20 *(AC-10.2)*
- [ ] Hour buckets are labelled in the configured timezone: on spring-forward day the skipped hour has no bucket, and on fall-back day the repeated hour has two distinct buckets *(AC-10.3)*
- [ ] A current time earlier than the previous run time is rejected with exit code 3 *(AC-10.4)*
- [ ] When the cap cut the window, the result names the span that was not read *(AC-10.5)*
- [ ] An explicit start time (`--since`) starts the window there, without the cap, and marks it explicit *(AC-10.6)*
- [ ] The first bucket is the local hour of the configured timezone that contains the window start, including zones with half-hour offsets *(AC-10.7)*
- [ ] `--report-only` keeps the normal start and marks the window explicit, per BR-22 *(AC-10.8)*

### Make the scripts available to cloud runs {#US-11}

WHEN a routine session starts on the cloud environment
THE environment's setup script fetches this repository at the pinned release tag, read-only, so the routine can run the state engine

**Acceptance Criteria:**
- [ ] The setup script clones the configured tag only, over HTTPS, without credentials, per BR-15 *(AC-11.1)*
- [ ] The setup script checks the tag's commit hash against the configured hash, and leaves no scripts in place on a mismatch *(AC-11.2)*
- [ ] A routine whose runtime is missing, or at another commit than its prompt expects, posts one message that says `degraded`, and stops with no state written *(AC-11.3)*
- [ ] The tag and its hash are set once in the private repository and rendered into both the setup script and the prompts *(AC-11.4)*

### Keep state between cloud runs {#US-12}

WHEN a Prod watch run finishes
THE routine commits the next state and the run record to the `claude/state` branch of the private repository and pushes it, so the next run starts from the last run without collecting everything again

**Acceptance Criteria:**
- [ ] A run with no `claude/state` branch or no state file is a baseline run *(AC-12.1)*
- [ ] The state is `state/<slug>.json` and the record `runs/<slug>/<run-at>.json` on that branch, per BR-23 *(AC-12.2)*
- [ ] A failed push is reported in the digest as state not saved *(AC-12.3)*
- [ ] A run with an explicit start time pushes its run record and leaves the state file unchanged, per BR-22 *(AC-12.4)*

### Collect a source with a script {#US-13}

WHEN a run collects one of its sources
THE collector reads the source for the run window, through the transport the private config sets for that source and place, and writes one collection file in the schema of the source's role

**Acceptance Criteria:**
- [ ] The private config sets, per source of a routine, its role, its provider and one transport (`api` or `mcp`) for each place (`local`, `cloud`), on the source or through its provider's default, per BR-24 *(AC-13.1)*
- [ ] The two transports of one provider give byte-identical records and cursor from the same provider data *(AC-13.2)*
- [ ] A source that cannot be read is marked not read, with a reason naming the missing variable, the HTTP status, the host or the tool, and the other sources are still collected *(AC-13.3)*
- [ ] A source read only in part is marked not read, per BR-28 *(AC-13.4)*
- [ ] A failed read never switches to the other transport, per BR-24 *(AC-13.5)*
- [ ] A collection names its role, provider, transport and window, whether the source was read and why not, the cursor reached, and its records *(AC-13.6)*
- [ ] All providers of one role write the same record schema, so a routine never depends on the provider *(AC-13.7)*
- [ ] Adapters ship for the observability tool, the document store, the chat channel, the code host and the issue tracker (US-27), each with both transports and fixture tests *(AC-13.8)*
- [ ] `collect` runs one configured source of a routine for a given window, outside a routine run, and writes its collection *(AC-13.9)*
- [ ] The run record names the place and, per source, the transport and the reason it was not read *(AC-13.10)*
- [ ] The run record names the commit of the private config and whether the config had uncommitted changes *(AC-13.11)*

### Call a provider API {#US-14}

WHEN a source's transport is `api`
THE provider adapter calls the provider's HTTPS API with the credentials held in the environment variables the private config names

**Acceptance Criteria:**
- [ ] The config names the credential variables, never their values, per BR-25 *(AC-14.1)*
- [ ] No output, error message, facts file, run record or state contains a credential value *(AC-14.2)*
- [ ] Requests go only to the host the config sets for the provider, per BR-29: a base URL that is not HTTPS, or that carries user info, a query or a fragment, is rejected before any request *(AC-14.3)*
- [ ] Each request has a bounded timeout, and a rate-limit or server error is retried once, after the delay the provider asks for, within a cap *(AC-14.4)*
- [ ] A paginated read follows the provider's cursor up to a page cap, and reaching the cap marks the source partial *(AC-14.5)*
- [ ] The providers README lists, per provider, the credential variables, the read-only scope to create, and where each place reads the variables from *(AC-14.6)*
- [ ] A config key named like a secret (`password`, `secret`, `token`, `api_key`, `app_key`, `private_key`, in any case, camelCase or dashed form) that holds anything but an environment variable name fails the load, naming the key path and never the value, per BR-25 *(AC-14.7)*
- [ ] A config string or key shaped like a known token or private key fails the load, naming the key path and the rule and never the value, per BR-25 *(AC-14.8)*
- [ ] A source reads through `api` with credentials named by environment variables, or through `mcp` with no `api` settings at all, per place *(AC-14.9)*

### Relay a source through a connector {#US-15}

WHEN a source's transport is `mcp`
THE collector writes a request plan, the model executes the plan through the connector and saves the raw responses, and the collector parses the responses into facts

**Acceptance Criteria:**
- [ ] For a provider whose connector runs code, each plan step is one script for that tool, which reads up to the page cap inside the connector and returns a compact result *(AC-15.1)*
- [ ] For a provider without code execution, the plan lists the connector tool calls and their arguments *(AC-15.2)*
- [ ] The model saves each response unchanged, with no edit, summary or filter before the parser reads it; a script result proves it per AC-15.4 *(AC-15.3)*
- [ ] A script result carries a checksum of its payload and a digest of the plan it ran, both computed inside the connector; a saved result whose checksum or plan digest does not match is rejected, with the source marked not read *(AC-15.4)*
- [ ] A response the parser cannot read marks the source not read, naming the tool *(AC-15.5)*
- [ ] The plan loop ends within the page cap: reaching the cap, or a cursor that repeats, ends it and marks the source partial *(AC-15.6)*

### Run a routine locally {#US-16}

WHEN the owner runs `/routines run <slug>`
THE skill renders the routine for the local place and runs it in the current Claude Code session, with the same template, state branch and state engine as a cloud run

**Acceptance Criteria:**
- [ ] The run starts from the latest state on the remote `claude/state` branch of the private repository, and pushes its state and run record there *(AC-16.1)*
- [ ] The run never changes the checked-out branch or the working tree of the private repository *(AC-16.2)*
- [ ] `--since T` runs an explicit window, per BR-22 *(AC-16.3)*
- [ ] The digest is printed in the session, and reaches the chat channel only with `--post`, per BR-26 *(AC-16.4)*
- [ ] A save whose own state file moved since the run started, or whose push is rejected twice, is reported as state not saved, per BR-27 *(AC-16.5)*
- [ ] Before collecting, the run names every `api` source whose credential variables are missing, and every `mcp` source whose connector the session lacks *(AC-16.6)*
- [ ] The run uses the pinned runtime, installed locally by the setup script, and the run record names its commit *(AC-16.7)*
- [ ] Without `--post`, the run reports only: it pushes its run record and leaves the state unchanged, per BR-22 *(AC-16.8)*

### Evaluate Prod watch observations {#US-17}

WHEN Prod watch has collected its sources
THE evaluator reads the observability collection with the routine's query pack, and, once the judgment is checked, writes the facts the state engine takes

**Acceptance Criteria:**
- [ ] The query pack sits in the private config, per routine: each entry's key, source, query, read mode, top limit, excluded hours, lookback, rule, title, link and schedule, per BR-31 *(AC-17.1)*
- [ ] An invalid query pack stops the run before any provider call, naming the key path *(AC-17.2)*
- [ ] The value of every observation comes from the collection, never from the model; its over flag, severity and urgency come from the checked judgment of US-21, except for the keys of AC-19.5, AC-21.10 and AC-21.12, per BR-38 *(AC-17.3)*
- [ ] A source not read gives no observation for its keys, and the facts mark that source not read *(AC-17.4)*
- [ ] The same records, cursors, state, query pack and judgment give byte-identical facts, apart from `run_context` *(AC-17.5)*
- [ ] The mutes come from the mutes table of the sources page, through the document store collection; when the page was not read, or its mutes table lacks the `key` column, or has no `until` column or both `until` and `silence until`, the stored mutes apply *(AC-17.6)*
- [ ] A daily entry is collected once per local day, and a tracked key not due this run is deferred, per BR-32 *(AC-17.7)*
- [ ] An entry with no datapoints, or a monitor absent from the collection, is deferred and reported as a blind spot, never observed as not open, per BR-32 *(AC-17.8)*
- [ ] On a run where known gaps are not retried, their entries are not collected, are deferred, and stay out of the blind spots, per BR-19 *(AC-17.9)*
- [ ] A tracked metric key whose entry left the query pack is deferred and reported as a blind spot `not in the query pack` until the entry returns or the state is edited, per BR-32 *(AC-17.10)*

### Compute judgment features {#US-18}

WHEN Prod watch has collected its sources
THE evaluator writes, per pack entry, per discovered monitor and per tracked monitor key, the observed values and the features the model needs to judge them, and decides no threshold

**Acceptance Criteria:**
- [ ] A monitor lists its state, its priority (from the observability tool, or else from a leading `[P1]` to `[P5]` in its name), and, from the alert events of the window, its transition count, its first and last transition times, and its transitions per hour between them *(AC-18.1)*
- [ ] A metric entry lists its value for its read mode, its window maximum with that hour, its latest value, the value stored at its previous collection, and the change since that value, in units and in percent *(AC-18.2)*
- [ ] An hourly entry lists every hour bucket of the window with its local label and its value, and marks the buckets its excluded hours cover *(AC-18.3)*
- [ ] A top entry lists every group the read returned, each under its own key, per BR-34, and says whether the read returned fewer groups than its limit *(AC-18.4)*
- [ ] A daily entry with a lookback is read over that span, ending at the window end, at a daily rollup; a lookback on any other entry is invalid, per AC-17.2 *(AC-18.5)*
- [ ] The features hold no threshold or rule, and no severity or urgency other than a tracked item's stored ones *(AC-18.6)*
- [ ] The same records, cursors, state and query pack give byte-identical features, apart from `run_context` *(AC-18.7)*
- [ ] Two groups that map to the same key, in one entry or across entries, or a group key equal to a pack key, mark the entries failed, with a reason naming the key *(AC-18.8)*
- [ ] A rate or a percent that is undefined is null: fewer than 2 transitions, first and last transitions at the same time, no stored value, or a stored value of 0 *(AC-18.9)*

### Discover monitors that are not OK {#US-19}

WHEN the monitors source is read
THE collector also lists the in-scope monitors that are not OK, with the discovery query of the private config, so a monitor missing from the pack still reaches the model

**Acceptance Criteria:**
- [ ] The private config sets the discovery query per monitors source; with no query, nothing is discovered *(AC-19.1)*
- [ ] A discovered monitor carries its id, name, state, priority and link, under the key `monitor-<id>` *(AC-19.2)*
- [ ] A monitors entry of the pack has the key `monitor-<id>` of its monitor, so a monitor has one key whether listed or discovered, per BR-35 *(AC-19.3)*
- [ ] A tracked monitor key is read by id on every run until its item resolves, whether the pack lists it or not, per BR-36 *(AC-19.4)*
- [ ] A tracked monitor that the observability tool reports as not found needs no verdict: it counts as observed and not open, so its item resolves after 2 runs *(AC-19.5)*
- [ ] The discovery read follows the provider's pagination up to the page cap *(AC-19.6)*
- [ ] A discovery read that fails or reaches its page cap adds a blind spot to the monitors source; the monitors it returned are still judged, and the by-id reads still count as read, per BR-40 *(AC-19.7)*
- [ ] A monitor named by an alert event of the window, outside the pack, untracked and not found by the discovery search, is read by id and reaches the model with its state and transitions, even when it is OK at run time; at most 50 such reads per run, the excess being a blind spot of the monitors source *(AC-19.8)*

### Judge observations with the model {#US-20}

WHEN the features are written
THE model judges every observed key against the routine's rules and writes one judgment: whether the key is open, its severity, its urgency, the feature values it relies on, and its rank in the digest

**Acceptance Criteria:**
- [ ] The rules are prose in the private config: one rule per pack entry, and routine-wide rules for monitors, per BR-33 *(AC-20.1)*
- [ ] The judgment holds one verdict per observed key, except deferred keys and the keys of AC-19.5, AC-21.10 and AC-21.12 *(AC-20.2)*
- [ ] Each verdict names the feature values it relies on, by feature name and value *(AC-20.3)*
- [ ] Each open key carries a rank, 1 for the most urgent *(AC-20.4)*
- [ ] A monitor verdict cites the monitor's state, so a severity set per state traces to it *(AC-20.5)*
- [ ] A monitor that matches several rules gets one verdict, with the highest of their severities, per BR-35 (model eval) *(AC-20.6)*
- [ ] The model judges from the features and the rules only, and makes no provider call in this step (model eval) *(AC-20.7)*

### Check the judgment {#US-21}

WHEN the model has written its judgment
THE checker validates it against the features, then merges it into the facts the state engine takes

**Acceptance Criteria:**
- [ ] A verdict for a key absent from the features, or for a deferred key, is rejected with its key path *(AC-21.1)*
- [ ] An observed key with no verdict is rejected with its key path *(AC-21.2)*
- [ ] A severity or urgency outside the allowed values is rejected with its key path *(AC-21.3)*
- [ ] A cited feature name that the key lacks, or a cited value that differs from the features of that key, is rejected with its key path, per BR-38 *(AC-21.4)*
- [ ] Ranks that are not 1 to N over the open keys, each used once, are rejected *(AC-21.5)*
- [ ] On a first rejection, the model corrects the judgment from the checker's message *(AC-21.6)*
- [ ] A second rejection ends the run with no state and no run record written, and one message that starts with `degraded: judgment rejected` *(AC-21.7)*
- [ ] The merged facts take the over flag, severity, urgency and rank from the judgment and the value from the features, in the facts schema of US-9; a monitor's value is null, so a monitor escalates only by severity or urgency, per BR-10 *(AC-21.8)*
- [ ] The change summary lists the new and escalated items in rank order *(AC-21.9)*
- [ ] A tracked group key missing from a read that returned fewer groups than its limit needs no verdict: it counts as observed and not open, and keeps its item's severity and urgency, per BR-34 *(AC-21.10)*
- [ ] A tracked group key missing from a read that reached its limit is deferred, with the blind spot `outside the top <N>`, per BR-34 *(AC-21.11)*
- [ ] A tracked key of a top entry from before its groups were tracked needs no verdict: it counts as observed and not open, so it resolves after 2 runs while its groups open their own items *(AC-21.12)*

### Write the analysis of new and escalated items {#US-22}

WHEN the change summary lists a new or escalated item
THE model writes its risk, reason, mitigation leads and next action, and the engine stores them in the item

**Acceptance Criteria:**
- [ ] The analysis holds the risk (what happens if it continues, and who is affected), the reason (the likely cause, each claim tagged measured or inferred), 1 to 3 mitigation leads and the next action, leads and action verb first (model eval) *(AC-22.1)*
- [ ] Each claim tagged measured lists the feature values it relies on, by name and value, checked like a verdict's, per AC-21.4 *(AC-22.2)*
- [ ] Each analysis field is plain text of at most 300 characters, with no control characters *(AC-22.3)*
- [ ] An analysis for a key the summary does not list as new or escalated, or a listed key with no analysis, is rejected with its key path, and corrected per AC-21.6 and AC-21.7 *(AC-22.4)*
- [ ] The engine stores the analysis in the item, and later runs reuse it until the item escalates, per BR-37 *(AC-22.5)*
- [ ] On a report-only run, the analysis is shown in the digest and not stored, per BR-22 *(AC-22.6)*
- [ ] The digest shows the analysis of each new and escalated item, rendered by a script, per BR-42 *(AC-22.7)*

### Split the private config per routine {#US-23}

WHEN a script loads the private config
THE loader reads the shared `config.json` and the routine files under `config/routines/`, and merges them into one config

**Acceptance Criteria:**
- [ ] `config.json` holds the timezone, the runtime pin, the places, the providers and the shared values, per BR-44 *(AC-23.1)*
- [ ] `config/routines/<slug>.json` holds one routine, and its file name is the slug *(AC-23.2)*
- [ ] `config.json` may also hold routines under `routines`, and both forms load the same way *(AC-23.3)*
- [ ] A config with neither `routines` nor a routine file has no routine *(AC-23.4)*
- [ ] `diff` reports `untracked` for a live routine with neither a routine file nor a `routines` entry *(AC-23.5)*
- [ ] A slug defined both under `routines` and as a routine file fails the load, per BR-43 *(AC-23.6)*
- [ ] Two routines with the same `id` fail the skill's load, per BR-47 *(AC-23.7)*
- [ ] A routine file holding `timezone`, `runtime`, `places` or `providers` fails the load, per BR-44 *(AC-23.8)*
- [ ] A routine file that is not JSON, or not an object, fails the load *(AC-23.9)*
- [ ] A file of `config/routines/` ending in `.json` whose name does not match `^[a-z0-9-]+\.json$` fails the load *(AC-23.10)*
- [ ] Files of `config/routines/` that do not end in `.json` are ignored *(AC-23.11)*
- [ ] Every load error names the file and the key path inside it, and a clash names both paths *(AC-23.12)*
- [ ] `--config` keeps naming `config.json`, and the runtime reads the routine files from the `config/routines/` directory of the folder that holds `config.json` *(AC-23.13)*
- [ ] The skill's `render`, `diff`, `lint`, `body` and `sync` load every routine file, and an invalid file fails them *(AC-23.14)*
- [ ] A runtime command for one routine reads `config.json` and that routine's file only: an invalid file of another routine does not stop it *(AC-23.15)*
- [ ] The skill and the runtime give the same merged routine from the same files *(AC-23.16)*
- [ ] A routine's values override the shared values of the same key *(AC-23.17)*
- [ ] `config_dirty` is true when `config.json` or the routine's file has uncommitted changes, an untracked file included *(AC-23.18)*
- [ ] `export` writes only under `routines/`, never under `config/` *(AC-23.19)*
- [ ] The plugin's example config ships the split layout: a shared `config.json` and one routine file *(AC-23.20)*

### Default a source's transport to its provider's {#US-24}

WHEN a source sets no transport for a place
THE loader resolves it to the default transport its provider sets for that place

**Acceptance Criteria:**
- [ ] A provider may set `transport`, with one value per place *(AC-24.1)*
- [ ] A transport value other than `api` or `mcp`, or a place other than `local` or `cloud`, fails the load with its key path, on a provider as on a source *(AC-24.2)*
- [ ] A source's own transport for a place wins over its provider's default, per BR-24 *(AC-24.3)*
- [ ] A source may set the transport of one place and take its provider's default for the other *(AC-24.4)*
- [ ] A source that resolves no transport for a place fails the load, naming the source's key path *(AC-24.5)*
- [ ] A resolved transport needs what US-13 and US-14 require: the provider's `api` settings for `api`, a connector for that place for `mcp` *(AC-24.6)*
- [ ] Every command, collection and run record sees the resolved transport only *(AC-24.7)*

### Mirror every live routine {#US-25}

WHEN the owner renders, diffs, lints or syncs any of the 5 live routines
THE skill renders it from its private template and routine file, and the result equals the live prompt and cron

**Acceptance Criteria:**
- [ ] Each live routine has a routine file and a private template *(AC-25.1)*
- [ ] After an export, `/routines diff` prints `in sync` for all 5, prompt and cron *(AC-25.2)*
- [ ] Ids, channels, pages, user ids, logins, organizations and the owner's identity in the 4 new templates are render-time values, never literal text *(AC-25.3)*
- [ ] The private lint warns when a template holds, as literal text, a configured value of 8 characters or more *(AC-25.4)*
- [ ] A value that several routines use is one shared value, per BR-45 *(AC-25.5)*
- [ ] The private lint warns when two routines define the same value key with the same value *(AC-25.6)*
- [ ] Two routines whose prompts differ only by values render from one template with per-routine values: the two tribe digests share one template *(AC-25.7)*
- [ ] A routine without `sources` renders, diffs, lints and syncs *(AC-25.8)*
- [ ] The runtime refuses a routine whose `sources` is absent or empty, naming the key path *(AC-25.9)*
- [ ] The private lint passes on all 5 routines and warns of no unused shared value *(AC-25.10)*

### Ship skeletons for the other routines {#US-26}

WHEN a user of the public plugin has no private template for a chat recap or a weekly status
THE skill renders the plugin's structure-only skeleton for it, marked not runnable

**Acceptance Criteria:**
- [ ] Three templates ship: the runnable tribe digest (AC-41.1), and the chat recap and weekly status skeletons *(AC-26.1)*
- [ ] Each skeleton lists its steps, its sources by role and its outputs, with placeholders only, per BR-8 and BR-30 *(AC-26.2)*
- [ ] A template is marked not runnable when its first line is exactly `<!-- not runnable -->`, whether it is a public skeleton or a private template *(AC-26.3)*
- [ ] The chat recap and weekly status skeletons carry the marker; the tribe digest template does not, since it runs (AC-41.1) *(AC-26.4)*
- [ ] Rendering a marked template keeps the marker line and prints a warning naming the template *(AC-26.5)*
- [ ] `diff` and `lint` treat a marked template like any other *(AC-26.6)*
- [ ] `sync` refuses a marked template before any API call, and `body` before printing a body, naming the template, per BR-46 *(AC-26.7)*
- [ ] `/routines run` refuses a marked template before collecting, naming the template, per BR-46 *(AC-26.8)*
- [ ] The skeletons pass the public lint *(AC-26.9)*
- [ ] The plugin README lists every skeleton and says whether it runs *(AC-26.10)*

### Read the issue tracker {#US-27}

WHEN a run collects an issue tracker source
THE collector reads the issues of the source's saved filter updated since its cursor, through the source's transport, and writes them in the issue tracker record schema

**Acceptance Criteria:**
- [ ] The issue tracker is a role, with an adapter for the issue tracker of the private config, over both transports, per BR-24 and BR-30 *(AC-27.1)*
- [ ] A source names a saved filter, and may add a query that narrows its updated read *(AC-27.2)*
- [ ] The collector reads the filter's issues updated after the cursor minus 1 hour, and keeps one record per issue key, the newest update winning, per BR-49 *(AC-27.3)*
- [ ] A source may also read every issue of the filter's open sprints, whatever their update time and the query; with no open sprint it reads none and reports no blind spot *(AC-27.4)*
- [ ] An issue record holds its key, title, type, status, priority, creation and update times, link, and whether it sits in an open sprint, per BR-52 *(AC-27.5)*
- [ ] The cursor is the newest update time read, unchanged when no issue is read *(AC-27.6)*
- [ ] An issue absent from a read, moved out of the filter or deleted, is never read as resolved or closed *(AC-27.7)*
- [ ] A read that reaches the page cap marks the source not read, per BR-28 *(AC-27.8)*

### Read chat threads {#US-28}

WHEN a run collects a chat source
THE collector also reads the replies of the threads started in the window, and keeps one record per message

**Acceptance Criteria:**
- [ ] A message record holds the root timestamp of its thread, or null for a message outside any thread *(AC-28.1)*
- [ ] The replies of a thread whose root is in the window are read, up to the window end *(AC-28.2)*
- [ ] Replies to a thread whose root is older than the window are not read *(AC-28.3)*
- [ ] A message returned both by the channel history and by a thread read gives one record, keyed by channel and timestamp *(AC-28.4)*
- [ ] The collector reads every channel the source lists, whatever the cursors hold, per BR-48 *(AC-28.5)*
- [ ] A listed channel with no cursor is read over the routine's first-read span, per BR-50 *(AC-28.6)*
- [ ] A channel the chat tool reports as not found, archived or not joined is a failed entry of the source, and the other channels are still read *(AC-28.7)*
- [ ] Any other failure marks the source not read, per AC-13.3 *(AC-28.8)*
- [ ] A channel with no message in the window keeps a cursor equal to the window end, in the timestamp format of the chat tool, per BR-14 *(AC-28.9)*

### Read changed documents {#US-29}

WHEN a run collects a document store source that lists pages
THE collector reads only the pages edited since their cursor

**Acceptance Criteria:**
- [ ] A source sets either the single sources page of US-17 or a list of pages, never both *(AC-29.1)*
- [ ] The collector reads each listed page's edit time, then the content of the pages whose edit time, at minute precision, differs from their cursor, per BR-51 *(AC-29.2)*
- [ ] A page record holds its id, title, edit time, link and blocks, as in the document store schema *(AC-29.3)*
- [ ] The cursor holds the edit time per page; a page with no cursor is read whole once, whatever its edit time *(AC-29.4)*
- [ ] A page that is deleted or no longer shared is a failed entry of the source, and the other pages are still read *(AC-29.5)*
- [ ] A source that reaches its request cap is not read, per BR-28 *(AC-29.6)*

### Read trend windows {#US-30}

WHEN a metric entry of the query pack sets a trend span
THE collector also reads that entry as a daily series over the span ending at the window end

**Acceptance Criteria:**
- [ ] A `scalar` or `hourly` metric entry may set a trend span of 7 to 31 days, on either schedule *(AC-30.1)*
- [ ] A trend span on a `top` entry, on a monitor entry, or next to a lookback, is invalid, per AC-17.2 *(AC-30.2)*
- [ ] The entry's record holds a trend series of one value per local day of the configured timezone, next to its window value *(AC-30.3)*
- [ ] A day with no datapoint is absent from the series, never zero *(AC-30.4)*
- [ ] Days follow the configured timezone across clock changes, as hour buckets do, per AC-10.3 *(AC-30.5)*
- [ ] A trend read that fails, or returns no datapoint, is a blind spot of its entry, per BR-53, unless the entry reads an empty result as zero, per BR-65 *(AC-30.6)*

### Collect the tribe digest sources {#US-31}

WHEN the owner runs a collection for a tribe digest routine
THE collector reads every source the routine file lists, by role, for a window

**Acceptance Criteria:**
- [ ] A tribe digest routine file lists its chat channels, issue tracker filters, document pages and observability sources, and query pack entries with trend spans *(AC-31.1)*
- [ ] The routine file sets its first-read span, per BR-50 *(AC-31.2)*
- [ ] Each source of a tribe digest routine collects outside a run: `fetch` for an `api` source, plan, saved responses and parse for an `mcp` source, per AC-13.9 and US-15 *(AC-31.3)*
- [ ] Each new adapter gives byte-identical records and cursor over both transports from the same provider data, per AC-13.2 *(AC-31.4)*
- [ ] Sources added to a mirrored routine change neither its render nor its live prompt *(AC-31.5)*
- [ ] A replay compare script lists, for the window of each reference digest, every issue key, document page and chat channel the reference cites, each as found in the collections or with one reason: outside the configured sources, outside the window, moved out of the filter, deleted or unshared, or capped *(AC-31.6)*
- [ ] The compare script exits 1 when a cited record is neither found nor given a reason *(AC-31.7)*

### Keep the tribe state between runs {#US-32}

WHEN a tribe digest run starts or ends
THE engine loads and saves a tribe state on the `claude/state` branch, as Prod watch does, per BR-23 and BR-27

**Acceptance Criteria:**
- [ ] The state keeps the warnings and checks by key, each with the cites it relies on and its count of runs under every threshold *(AC-32.1)*
- [ ] The state keeps the cursors of every source, the blind spots with their run counts, the retired keys, the previous digest page with its write time, and the week of the last weekly heading *(AC-32.2)*
- [ ] A run with no state file is a baseline run *(AC-32.3)*
- [ ] The collectors start each source from its stored cursor, per BR-50 *(AC-32.4)*
- [ ] The chat collector also reads the new replies of the threads the state cites, even when the thread started before the window *(AC-32.5)*
- [ ] A cited thread that is deleted or unreadable is a blind spot keyed `<channel>:<root ts>` *(AC-32.6)*
- [ ] A state with a wrong schema or a missing key is rejected with the key path, and nothing is written *(AC-32.7)*
- [ ] A report-only run writes its run record and leaves the state unchanged, per BR-22 *(AC-32.8)*

### Seed the tribe state from a live digest {#US-33}

WHEN the owner seeds a tribe routine
THE seeding script turns the Run state of the newest live digest page that holds a valid one into a tribe state, so the first runtime run continues the live keys

**Acceptance Criteria:**
- [ ] A newer page without a valid Run state is skipped and named; with no valid page at all, seeding stops and names the pages it read *(AC-33.1)*
- [ ] Warnings, checks, cursors and blind spot counts carry over by key; the retired keys start empty; the weekly heading week is the seeded page's week *(AC-33.2)*
- [ ] A Run state whose warning or check lacks a field, or holds a value outside BR-54 other than a warning `status`, is rejected with its key path *(AC-33.3)*
- [ ] Seeding pushes the state only after the owner's approval in the session, by a fast-forward push, per BR-27 *(AC-33.4)*
- [ ] A warning `status` outside BR-54 is read as the BR-54 word it starts with, else `open`, and each reading is printed with the key and the original status *(AC-33.5)*

### Compute the tribe features {#US-34}

WHEN a tribe digest run has collected its sources
THE evaluator writes the features the model judges: the records of the window, the trends of each metric entry, and the previous warnings and checks

**Acceptance Criteria:**
- [ ] Each record reaches the features with its link, and each chat message with its thread *(AC-34.1)*
- [ ] Each metric entry with `trend_days` (7 to 31) lists its window value, `max_7d` and `mean_7d` over the last 7 days, `max_span` and `mean_span` over the `trend_days` span, and `growth_monthly` *(AC-34.2)*
- [ ] Each previous warning and check reaches the features with its stored fields and cites *(AC-34.3)*
- [ ] Source text is cleaned as in Prod watch, so it reaches the model as data, per AC-22.3 *(AC-34.4)*
- [ ] The same collections, state and config give byte-identical features *(AC-34.5)*
- [ ] Features hold no threshold and no severity other than the stored ones, per BR-38 *(AC-34.6)*
- [ ] A stored warning whose cited sources or metric entry were not read is deferred, per BR-63 *(AC-34.7)*

### Merge the owner's page edits {#US-35}

WHEN the owner edited the previous digest page after its write time, at minute precision per BR-51
THE run reads that page and merges the checks ticked and the statuses edited there, by key, per BR-61

**Acceptance Criteria:**
- [ ] A check ticked on the page at read time is done in this run; a check unticked at read time is not *(AC-35.1)*
- [ ] A warning whose status on the page differs from the stored one takes the page's status, when it is one of BR-54 *(AC-35.2)*
- [ ] Any other edit (free text, an invalid status, a row or to-do matching no key) is ignored and listed in the run record *(AC-35.3)*
- [ ] A merged edit wins over the model's judgment of the same field in this run *(AC-35.4)*
- [ ] A previous page that cannot be read is a blind spot, and the stored values hold *(AC-35.5)*

### Judge the tribe digest with the model {#US-36}

WHEN the features are written
THE model writes one judgment: the warnings with their fields, the checks, the decisions, the details and the corrections of the run

**Acceptance Criteria:**
- [ ] Each warning has a key, title, topic, severity, when, runway, status, confidence, risk, impact, 1 to 3 mitigation leads and evidence *(AC-36.1)*
- [ ] Each warning carries a verdict, open or under every threshold, for the lifecycle of BR-57 *(AC-36.2)*
- [ ] A stored warning keeps its key; a new warning gets a new kebab-case key never used before, per BR-56 *(AC-36.3)*
- [ ] A new warning that replaces a stored one names it, and the stored one resolves *(AC-36.4)*
- [ ] Each piece of evidence cites a record link of this run's collections, a cite stored with the warning, or a feature value, per BR-59 *(AC-36.5)*
- [ ] Each check has a key, text, topic and group (`This week`, `Before the month-end`, `Investigate`); only the owner's tick marks it done *(AC-36.6)*
- [ ] Decisions are at most 3, each with deadline, options and topic, per BR-62; they belong to this run and are not stored *(AC-36.7)*
- [ ] Details list, per topic, only what changed since the previous run, with cites *(AC-36.8)*
- [ ] Corrections list each earlier number the run found wrong, with the corrected value and its cite *(AC-36.9)*
- [ ] The rules the model applies, the meanings of BR-54 and the warning thresholds included, are prose in the private config, per BR-33 *(AC-36.10)*
- [ ] The model judges from the features and the rules only, and makes no provider call in this step (model eval) *(AC-36.11)*
- [ ] The judgment may add up to 10 coverage notes, each a source label and one line on what the run did not cover and why; they show under Blind spots for this run only, per BR-64 *(AC-36.12)*

### Check the tribe judgment {#US-37}

WHEN the model has written its tribe judgment
THE checker validates it against the features and the state before the engine applies it

**Acceptance Criteria:**
- [ ] A key that is unknown, reused or retired is rejected with its key path *(AC-37.1)*
- [ ] A stored warning absent from the judgment is rejected, unless it is deferred or a new warning replaces it *(AC-37.2)*
- [ ] A new warning whose title matches a stored or retired one is rejected, unless it replaces that key *(AC-37.3)*
- [ ] A field outside its allowed values, or a text over 300 characters, is rejected with its key path *(AC-37.4)*
- [ ] A cite that matches no record link of the collections, no cite stored with the warning and no feature value, or a cited value that differs from the features, is rejected, per BR-59 *(AC-37.5)*
- [ ] A `measured` warning without a feature cite, or a `reported` one without a record cite, is rejected *(AC-37.6)*
- [ ] A text holding a chat author id or an email is rejected, per BR-52 *(AC-37.7)*
- [ ] More than 3 decisions are rejected *(AC-37.8)*
- [ ] A first rejection is corrected once from the checker's message; a second ends the run with no state and no run record written, and one message that starts with `degraded: judgment rejected`, per AC-21.6 and AC-21.7 *(AC-37.9)*

### Apply the tribe lifecycle {#US-38}

WHEN the judgment is checked
THE engine applies the warning and check lifecycle and writes the next state, the change summary and the run record

**Acceptance Criteria:**
- [ ] A warning resolves when its status is decided or dropped, or after 2 runs in a row with a verdict under every threshold, per BR-57 *(AC-38.1)*
- [ ] A deferred warning is held: no verdict, its count kept and no resolution, per BR-63; an owner's status edit on the page still applies *(AC-38.2)*
- [ ] A reported warning with no metric resolves only by its status *(AC-38.3)*
- [ ] A resolved warning and a done check appear once in the summary, then leave the state, per BR-58 *(AC-38.4)*
- [ ] Moved severity, when or status appear in the summary *(AC-38.5)*
- [ ] Every resolved key joins the retired keys, which are kept without limit *(AC-38.6)*
- [ ] Blind spots follow BR-12, BR-19 and BR-21 *(AC-38.7)*

### Render and write the digest page {#US-39}

WHEN the state is applied
THE renderer writes the digest page in layout version 1 from the summary, the state and the collections, and the model creates it under the tribe's main page unchanged, per BR-60

**Acceptance Criteria:**
- [ ] The page holds the sections of layout version 1 in order, from Since last run to Run state *(AC-39.1)*
- [ ] The Sources section lists each source with what was read and its window, from the collections *(AC-39.2)*
- [ ] The Blind spots section lists the summary's blind spots, and How this digest is built points to the template and the routine's sources *(AC-39.3)*
- [ ] The Run state section names the window, the page ids and where the state lives, never the state itself, per BR-55 *(AC-39.4)*
- [ ] The structure check of layout version 1 runs as a script on the rendered page and stops the run before any write *(AC-39.5)*
- [ ] A page create that fails writes the run record, leaves the state unchanged, and posts one `degraded` message *(AC-39.6)*
- [ ] The first run of an ISO week, in the configured timezone, appends a weekly heading to the main page; a heading that fails is reported and tried again on the next run *(AC-39.7)*
- [ ] A report-only run renders the page into the session and writes nothing to the document store, per BR-22 *(AC-39.8)*

### Post the tribe chat message {#US-40}

WHEN the digest page is written
THE renderer writes the chat message, and the model posts it unchanged to the digest channel, per BR-42

**Acceptance Criteria:**
- [ ] The message holds the summary, the important points, the blind spots in one line and the page link *(AC-40.1)*
- [ ] A run that failed the structure check posts one `degraded` message instead *(AC-40.2)*
- [ ] A local run posts only with `--post`, per BR-26 *(AC-40.3)*

### Run a tribe digest on the runtime {#US-41}

WHEN a tribe digest routine runs, in the cloud or locally
THE runtime template drives the steps from collection to post, as the Prod watch template does

**Acceptance Criteria:**
- [ ] The public tribe digest skeleton is runnable, with placeholders only, per BR-8 and BR-30 *(AC-41.1)*
- [ ] Each step calls a script; the model writes only the judgment and relays connector calls *(AC-41.2)*
- [ ] The private repository's settings deny the push notification tool and sleeping commands, and the private lint fails without that deny list *(AC-41.3)*

### Match the live tribe digests {#US-42}

WHEN a tribe state seeded from one live digest is replayed over the window of the next live digest
THE replay's warnings, checks, decisions and blind spots match the live digest's, apart from data that changed since

**Acceptance Criteria:**
- [ ] A key map, written in the replay session, pairs each replay key with a live key or with none *(AC-42.1)*
- [ ] A compare script lists each live warning as matched (same severity, when and status) or with one reason: data changed since the live run, source not read in the replay, resolved in one run and open in the other with the cite that shows why, the live run read a source the routine does not configure (named, live-only lines), or the judgment differs with a one-line why (warnings, checks, decisions, live blind spots and coverage notes; never a gap a collector hit) *(AC-42.2)*
- [ ] It lists each replay-only warning with one reason from the same list *(AC-42.3)*
- [ ] It compares checks by key, decisions by topic and blind spots by source the same way *(AC-42.4)*
- [ ] It exits 1 when a difference has no reason *(AC-42.5)*

### Read an empty count as zero {#US-43}

WHEN a pack entry counts rare events, such as error statuses, retries or out-of-memory kills, and its read succeeds with no datapoint
THE runtime reads the entry as 0 instead of a blind spot, when the entry declares it

**Acceptance Criteria:**
- [ ] A `scalar` or `top` entry may set `empty` to `zero`; the default, `gap`, keeps a read with no datapoint as a blind spot *(AC-43.1)*
- [ ] With `zero`, a read that succeeds with no datapoint gives a value of 0, a `top` entry with no group, and no blind spot *(AC-43.2)*
- [ ] With `zero`, a trend read that succeeds with no datapoint gives 0 for its window values and a null `growth_monthly` *(AC-43.3)*
- [ ] A read that fails is a blind spot whatever `empty` says *(AC-43.4)*
- [ ] `empty` on an `hourly` or monitor entry, or a value other than `gap` or `zero`, is invalid with its key path *(AC-43.5)*

### Read the Prod watch message at a glance {#US-44}

WHEN a Prod watch run posts its digest to the chat channel
THE message follows the compact chat layout the routine posted before the runtime: local times, a counts line, one block per new or escalated item, one line per resolved item, still open items as short lists, and the gaps on one line

**Acceptance Criteria:**
- [ ] The title is the bold digest name with the run time as `DD Mon HH:MM <city>` in the config timezone, then `(since <weekday HH:MM>)` of the window start, or `(baseline)` on a baseline run *(AC-44.1)*
- [ ] A Summary section always shows `N new, N escalated, N resolved, N still open`; any other section with no content is skipped *(AC-44.2)*
- [ ] A new or escalated item is a block: the urgency mark (🔴 now, 🟠 within months, 🟡 watch), ⬆️ before it when escalated, and the bold title; then `<severity> · <urgency> · since <time> · [<label>](<link>)`; then the Risk, Reason, Mitigation and Action bullets it holds, each claim of Reason followed by its tag, with the trailing period of the claim dropped before the tag, and the mitigation leads joined by semicolons *(AC-44.3)*
- [ ] A resolved item is one line: `✅ **<title>** · [<label>](<link>) · last value <value>` *(AC-44.4)*
- [ ] Still open shows `**Still open (N)**` and one bullet per severity, High to Low, with at most 3 titles in the summary's order then `+N` for the rest *(AC-44.5)*
- [ ] Blind spots, unread sources and the cut window share one `**Blind spots:**` line; muted changes and dropped blind spots one `**Not shown:**` line; overrides one `**Overrides:**` line; no item key appears in the text *(AC-44.6)*
- [ ] A link label is `monitor <id>` for a monitor link and `metric` otherwise, and a Markdown link only for an `http://` or `https://` link, the label alone otherwise, with the destination's parentheses, spaces and backslashes percent-encoded *(AC-44.7)*
- [ ] Every time is in the config timezone: a time on the run's local day shows `HH:MM`, another day `DD Mon HH:MM`, and a `since` that is not a UTC time shows as stored *(AC-44.8)*

### Run the chat recap on the runtime {#US-45}

WHEN the chat recap routine runs
THE runtime collects the owner's direct conversations, mentions, threads and announcements of the window through the chat role, scripts compute the facts of each conversation unit, the model classifies and summarizes the units, and scripts check the judgment, keep the unit history, render the message and save the state on the state branch

**Acceptance Criteria:**
- [ ] A run reads, through the chat role: the direct and group conversations with a message from someone else in the window, the messages that mention the owner or a configured group, the owner's messages of the look-back days whose thread has a reply from someone else in the window, and one announcement search over the configured channels *(AC-45.1)*
- [ ] Each direct conversation is one unit keyed `dm-<channel>`, each thread one unit keyed `thread-<channel>-<root ts>`; a thread found by two reads is one unit *(AC-45.2)*
- [ ] Messages of configured excluded authors and channels are dropped before any unit is built *(AC-45.3)*
- [ ] The window starts at the previous run; a baseline run, or a gap longer than the configured working days, reads the last configured working days only, and the summary line says so *(AC-45.4)*
- [ ] A unit stored as waiting or promise is read again on every run from its last message, even when the window starts later *(AC-45.5)*
- [ ] A search cut by pagination, a channel the owner cannot read and a read that failed are blind spots, named in the summary line *(AC-45.6)*

### Compute the facts of each unit {#US-46}

WHEN the units of a recap run are collected
THE scripts compute, per unit, the facts the classification depends on, so the model never decides them

**Acceptance Criteria:**
- [ ] Per unit: the author of the last message, whether the owner wrote or reacted after each message from someone else, the configured groups it mentions and the section each lands in, and its age in working days in the config timezone *(AC-46.1)*
- [ ] The owner's messages and reactions count as his answers; a message from an excluded author counts as nobody's *(AC-46.2)*
- [ ] Working days are Monday to Friday in the config timezone; a run across a daylight saving change counts the same days *(AC-46.3)*

### Classify and summarize the units {#US-47}

WHEN the facts of a recap run are ready
THE model writes one kind and one short summary per unit, plus the reading, and a script rejects any judgment that contradicts the facts

**Acceptance Criteria:**
- [ ] Every unit gets exactly one kind: `waiting on you`, `promise`, `team ask`, `you're waiting on`, `already handled`, `announcement` or `noise` *(AC-47.1)*
- [ ] The checker rejects a missing or unknown unit, and a kind the facts forbid: `waiting on you` on a unit whose last ask the owner answered, `you're waiting on` on a unit whose last message is not the owner's, `team ask` on a unit with no group that lands in Good to know, `announcement` on a unit outside the announcement channels *(AC-47.2)*
- [ ] A summary is one sentence of at most 200 characters, a title at most 8 words; neither holds a control character, `<`, `>`, `@`, `://` or a chat author id *(AC-47.3)*
- [ ] A promise carries its due time, or none; it is late once that time has passed, or from the next business day when it names none *(AC-47.4)*
- [ ] The reading holds at most 4 bullets, each citing at least one unit of the run; a bullet that changes nothing for the next 48 hours is left out, so a quiet run has none *(AC-47.5)*
- [ ] As for the other engines, one correction is allowed; a second rejection posts the degraded message and writes no state *(AC-47.6)*

### Keep the unit history {#US-48}

WHEN a recap run applies its judgment
THE lifecycle script updates each unit's history from the stored state and the facts, never from message text

**Acceptance Criteria:**
- [ ] A unit keeps `first_seen`, `last_ts`, `runs_waiting`, `status` and, when late, its age *(AC-48.1)*
- [ ] A waiting unit unanswered for more than the configured working days is late *(AC-48.2)*
- [ ] A stored waiting or promise unit that the owner answered, or that the judgment marks handled, is resolved and shows once under Already handled *(AC-48.3)*
- [ ] A unit absent from the run whose last message is older than the configured days leaves the state; a unit read in the run stays *(AC-48.4)*

### Post the recap message {#US-49}

WHEN a recap run has applied its judgment
THE script renders one message in the recap layout, and the run posts it to the digest channel only when at least one unit is waiting, new or resolved

**Acceptance Criteria:**
- [ ] Sections in order: Title with the run time and window start in the config timezone, Summary, Waiting on you, Good to know, You're waiting on, Already handled (at most 5, then `+N`), Reading; an empty section is skipped, except Summary *(AC-49.1)*
- [ ] Summary: `N waiting on you (N late), N new, N resolved, N you're waiting on`, and one line for window limits and blind spots when there are any *(AC-49.2)*
- [ ] Waiting on you is sorted blocking first, then direct conversation, direct mention, group, thread, then oldest first, with ⏰ before a late unit; a promise reads `**You** promised <what>, by <when>` *(AC-49.3)*
- [ ] Names are the display names the chat source gives; links are built by the script from the channel and timestamps, labelled by kind (`DM`, `group DM`, `thread in #channel`, `mention in #channel`) *(AC-49.4)*
- [ ] The message holds no state, JSON or unit key, and no text the model wrote other than checked summaries, titles and reading bullets *(AC-49.5)*

### Move the recap configuration and state into the private repository {#US-50}

WHEN the owner switches the chat recap routine to the runtime
THE configuration lives in its routine file in the private repository and the state on the state branch, seeded from the last state the routine kept in the document store

**Acceptance Criteria:**
- [ ] The routine file holds the owner identity, the groups with their landing section, the sources, the window and look-back days, the excluded authors and channels, and the announcement channels and topics; the lint names the key path of an invalid value *(AC-50.1)*
- [ ] A seed command converts the last stored state to the runtime state, validates it and keeps no message text *(AC-50.2)*
- [ ] After the switch, a run reads no document store page *(AC-50.3)*

### Replay a run on its collected data {#US-51}

WHEN a local run ends
THE run folder keeps every raw source result, sorted by role and source, and a replay rebuilds the run's collections from them with no network

**Acceptance Criteria:**
- [ ] Every source's raw results land under `<run>/raw/<role>/<source>/`: the connector results of an `mcp` source, and one record per HTTP call of an `api` source *(AC-51.1)*
- [ ] An `api` record holds the method, the path with its query, the request body, the status, the `Link` response header and the decoded response, and no request header *(AC-51.2)*
- [ ] A local run's folder lives under the place's `runs_dir`, named by routine and start time; without `runs_dir`, the run folder is a temporary folder under `/tmp` *(AC-51.3)*
- [ ] `collect.py replay` rebuilds every collection of a run from its raw folder, byte-identical to the collections the run wrote, and fails naming the first request it holds no record for *(AC-51.4)*

### Prefer the api transport, fall back to the connector {#US-52}

WHEN a source lists several transports for a place
THE collector reads it through the first listed transport the place can use: `api` when every credential variable of its provider holds a value, else the next one

**Acceptance Criteria:**
- [ ] A transport for a place is `api`, `mcp`, or an ordered list of both without repeats; a single value keeps its meaning *(AC-52.1)*
- [ ] A credential variable that is unset, empty or blank counts as missing, per BR-72, in the transport choice, the environment check and the HTTP client *(AC-52.2)*
- [ ] `collect.py sources` writes the choice of the run to `<run>/sources.json`: per source, the chosen transport and each skipped transport with its missing variables; `fetch`, `plan` and `parse` read the chosen transport from that file *(AC-52.3)*
- [ ] The choice happens once, before collecting; a failed read through the chosen transport never falls back, per BR-24 *(AC-52.4)*
- [ ] The run record names, per source, the chosen transport and the skipped ones with their reason *(AC-52.5)*
- [ ] A source with no usable transport is not read, and the environment check names its missing variables, as before *(AC-52.6)*

### Collect the owner's week {#US-53}

WHEN a weekly status run reads its sources
THE collectors return what the owner did during the week, from Monday 00:00 in the configured timezone to the run time, one collection per source

**Acceptance Criteria:**
- [ ] An issue tracker source takes a `jql` query instead of a saved filter, on both transports; the collector adds the window bound *(AC-53.1)*
- [ ] A code host source takes `searches`, pull request search queries; the collector adds the window start, keeps each pull request once, and reads its comments, reviews and review comments written in the window by a human *(AC-53.2)*
- [ ] A document store source takes `edited_by`, a user id; the collector lists the pages that user last edited in the window, newest first, and reads their blocks *(AC-53.3)*
- [ ] A chat source takes the recap's `searches`, so the owner's threads come with their messages *(AC-53.4)*
- [ ] Code host `searches` and document store `edited_by` read over `api` only; a source that sets them with an `mcp` transport fails the load with its key path *(AC-53.5)*

### Summarise the week {#US-54}

WHEN a weekly status run has its collections
THE scripts turn them into items, the model writes the status from the items, and the scripts check it and render the message

**Acceptance Criteria:**
- [ ] `weekly.py features` writes one item per issue, pull request, chat thread and page with activity in the window: key, title, status, link, time, people and short excerpts; it drops the routines' own channels *(AC-54.1)*
- [ ] The judgment holds the key accomplishments (1 to 6, none when there is no item), the decisions (up to 6) and what stays open (up to 8, each with its owner when another person), each a plain sentence citing item keys *(AC-54.2)*
- [ ] `weekly.py judge` rejects, naming the key path, a cite that is not an item key, a text with a link, a line break or over 200 characters, and judgment texts over 220 words in total; a second rejection gives a degraded run *(AC-54.3)*
- [ ] `weekly.py message` renders the title with the week's Monday, the three sections in order, the links of each bullet from its cited items, `None recorded` for no decision, and the sources checked with any that were not read *(AC-54.4)*
- [ ] The state and the run record hold the window, counts and keys, never a message, comment or page text, per BR-75 *(AC-54.5)*

### Run the weekly status on the runtime {#US-55}

WHEN the owner switches the weekly status to the runtime
THE routine renders from the runnable `weekly-status` template and a private routine file with `engine: weekly`, keeps its state on the state branch, and posts one message to the digest channel

**Acceptance Criteria:**
- [ ] The `weekly-status` template runs: runtime check, state, window, environment check, collect, features, judge, apply, save, message, report *(AC-55.1)*
- [ ] The routine file names the owner's identities per source, the excluded channels and the sources; the lint names the key path of an invalid value *(AC-55.2)*
- [ ] A local report-only run prints the status and saves only its run record *(AC-55.3)*

## Business Rules

- No private name, identifier, URL host or secret is committed to this public repository *(BR-1)*
- Leak findings show the path, the line and the rule, never the matched text *(BR-2)*
- An allowlist entry exempts one path, or one commit, for one rule; it never contains the matched text *(BR-3)*
- main accepts changes only through pull requests whose leak check passes *(BR-4)*
- Git is the source of truth for routine prompts: a live routine that differs from its rendered template is drift *(BR-5)*
- No live routine is changed without showing its diff and getting an explicit approval in the session *(BR-6)*
- A sync succeeds only when the routine exported after the push equals the rendered one *(BR-7)*
- Public skeletons hold placeholders only: no thresholds, identifiers, channel names, service names or hosts *(BR-8)*
- An item resolves after 2 consecutive runs where its source was read and its verdict is not open *(BR-9)*
- An item escalates when its severity or urgency moves up, or when its value exceeds 150 % of its value at opening *(BR-10)*
- A resolved item is reported once, then removed from state *(BR-11)*
- Blind spots are capped at 8 entries, known gaps first, and the change summary lists them with their gap and run count and counts the entries the cap dropped *(BR-12)*
- The run window starts at the previous run, at most 72 hours back *(BR-13)*
- Cursors only move forward *(BR-14)*
- Cloud runs use the scripts of one pinned release tag *(BR-15)*
- The document store holds the sources page with the mutes, never instructions, rules or run state *(BR-16)*
- The leak check fails closed: a scan that cannot run counts as a failure *(BR-17)*
- The owner mutes a key until a date in the mutes table of the sources page; a muted item stays tracked, and none of its changes, escalations included, reach the change summary before that date, except as a count *(BR-18)*
- A gap seen on 3 consecutive runs becomes a known gap and is not retried within the same day *(BR-19)*
- A baseline run reads the last 3 hours *(BR-20)*
- A known gap is retried on the first run of each day, and a retry that reads the source removes it *(BR-21)*
- A run with an explicit start time, or a local run without `--post`, reports only: it never advances the state or its cursors *(BR-22)*
- Run state and run records live only in the private repository, on the `claude/state` branch *(BR-23)*
- Each source has an ordered list of transports per place, its own or else its provider's default; a run reads it through the first one the place can use, chosen once before collecting, and a failed read never falls back to another transport *(BR-24)*
- Credentials live only in the environment variables of the place that runs the collector, never in config, templates, repositories, facts, run records or state *(BR-25)*
- A local run posts its digest to the chat channel only when the owner passes `--post` *(BR-26)*
- State moves only by fast-forward pushes to `claude/state`: a save builds on the latest tip, retries a rejected push once, and is never forced or merged *(BR-27)*
- A source read only in part counts as not read, so no item resolves on partial data *(BR-28)*
- A provider adapter calls only the HTTPS host the config sets for that provider *(BR-29)*
- Public prose and skeletons name roles (observability tool, chat channel, document store, code host, issue tracker), never providers; provider names appear only under `providers/`, in the private repository and in live routines *(BR-30)*
- Each routine's query pack (queries, read modes, lookbacks, rules, schedules) lives in the private config *(BR-31)*
- An entry that is not due, is a known gap not retried this run, has no data, or fails on its own is deferred, and so is a tracked metric key whose entry left the query pack: its item is held unchanged, and the rest of its source still counts as read *(BR-32)*
- Judgment rules, per pack entry and routine-wide, are prose in the private config; public skeletons and the sources page hold none *(BR-33)*
- A group of a top read is tracked under its own key; a tracked group missing from a read that returned fewer groups than the limit is not open, and one missing from a read that reached the limit is deferred *(BR-34)*
- A monitor has one key, `monitor-<id>`, and one item, whatever the number of rules it matches; that item takes the highest severity among them *(BR-35)*
- A tracked monitor key is read by id until its item resolves, whether it is in the pack or was discovered; the `not in the query pack` hold of BR-32 applies to metric keys only *(BR-36)*
- An item's analysis is written when the change summary lists it as new, and rewritten only when the summary lists it as escalated; a muted change gets no analysis *(BR-37)*
- Scripts set every value; the model sets only the verdicts (open, severity, urgency, rank) and the analysis *(BR-38)*
- The evaluator computes the features, the model judges them, the checker validates the judgment, and the engine applies the lifecycle *(BR-39)*
- Discovery only opens items: a discovery read that fails or stops at its page cap adds a blind spot to the monitors source, and the source's by-id reads still count as read *(BR-40)*
- A mute on an entry key also covers the group keys of that entry *(BR-41)*
- A script renders the digest text from the change summary; the model posts that text unchanged and writes none of it *(BR-42)*
- Each routine is defined once: under `routines` in `config.json` or in its own routine file, never both *(BR-43)*
- The timezone, the runtime pin, the places and the providers are defined once, in `config.json` *(BR-44)*
- A value that several routines use is defined once, in the shared values of `config.json` *(BR-45)*
- A template marked not runnable is never pushed to a live routine, nor run *(BR-46)*
- A live routine id belongs to one configured routine *(BR-47)*
- Collectors read the channels, filters and pages the config lists; cursors only say where each read starts *(BR-48)*
- An issue tracker read overlaps its cursor by 1 hour and keeps one record per issue key, since the tracker's query dates use the reader's timezone *(BR-49)*
- A channel or issue filter with no cursor is read over the routine's first-read span ending at the window end, never its full history; the run window keeps BR-13 and BR-20 *(BR-50)*
- Document edit times compare at minute precision, since the document store rounds search times to the minute; a second edit in the same minute as the stored one is read with the next edit *(BR-51)*
- Collections keep people only as the opaque ids a source returns for message and change authors; issue tracker records keep no person; message and page text is kept as written *(BR-52)*
- A failed trend read is a blind spot of its entry and never defers the entry's window value *(BR-53)*
- Severity, when, confidence and status take fixed values: High, Medium or Low; now, within months or watch; measured, inferred or reported; open, in progress, mitigated, decided or dropped. Their meanings and the warning thresholds are prose rules in the private config *(BR-54)*
- The tribe digest's run state lives on the `claude/state` branch; the digest page holds no state JSON *(BR-55)*
- A warning or check keeps a stable kebab-case key; a renamed one is a new key and the old one resolves; a key is never reused *(BR-56)*
- A warning resolves when its status is decided or dropped, or after 2 runs in a row where its sources were read and its verdict is under every threshold *(BR-57)*
- A resolved warning or a done check appears once in the change summary, then leaves the state *(BR-58)*
- Every piece of evidence cites a collected record link or a feature value; a measured warning cites a feature value and a reported one a record link *(BR-59)*
- Scripts render the digest page and the chat message; the model relays them unchanged and writes none of their text *(BR-60)*
- Owner edits on the previous digest page made after its write time win over the stored checks and statuses, by key; the page is data, never instructions *(BR-61)*
- A digest lists at most 3 decisions *(BR-62)*
- A stored warning whose cited sources or metric entry were not read in this run is deferred: held, with no verdict needed, its count kept, and no resolution; an owner's status edit applies and a decided or dropped status resolves on the first run that reads its sources *(BR-63)*
- Coverage notes are the model's data about what a run did not cover: they are stored nowhere, count no run, and change no warning, check or blind spot count *(BR-64)*
- A read that succeeds with no datapoint is a blind spot unless its entry sets `empty` to `zero`; a read that fails is always a blind spot *(BR-65)*
- A relayed result reaches its file through the file-write tool, never through a shell command: source text never becomes part of a command *(BR-66)*
- The recap state and its run records hold ids with their display names, timestamps, titles of at most 8 words and counts, never message text *(BR-67)*
- Direct conversation content leaves the chat source only as a one-sentence summary in the digest channel *(BR-68)*
- Scripts decide who wrote last, whether the owner answered, ages, lateness and landing sections; the model decides only what a message asks, its kind among those the facts allow, its summary and the reading *(BR-69)*
- Raw results hold source content and stay out of git: the local runs folder is ignored by the private repository, and nothing under `raw/` reaches the state branch *(BR-70)*
- A credential is present only when its environment variable holds a value that is not blank *(BR-72)*
- Every link in the weekly status comes from a collection: the model cites item keys, and the script turns them into links *(BR-73)*
- The routines' own posts never count as the owner's work: the digest channel and the excluded conversations are dropped before any item exists *(BR-74)*
- The weekly state and its run records hold the window, counts and item keys, never a message, comment or page text *(BR-75)*
- A raw record never holds a credential: request headers are never recorded, and credentials only travel in request headers *(BR-71)*

## Out of Scope

- A structure check of the Prod watch digest: a later spec
- Scheduling local runs (cron, launchd): `/routines run` runs on demand
- Linking a shared platform-limit key from another digest read less than 24 hours earlier, instead of reading it again
- Reading code host searches and edited document store pages through the connector: the weekly status reads them over `api` only
- Jira status transitions and comment text in the weekly status: issues carry their current status only
- Reading chat channels in full for the recap: the announcement scan searches the configured channels only
- Changing the 4 mirrored live prompts: the mirrors reproduce them as they are
- After the tribe judgment:
  - pull requests cited by issues
  - dashboards' widget queries
  - a closed sprint's final numbers
  - month-end comparisons
- Excluding chat conversations from search-based reads: with the chat recap and the weekly status
- A shared source catalog: each routine defines its own sources and names providers
- Drafting issues or tracker comments from items
- Letting the model decide whether to post: the post rule stays in the scripts
- Creating or deleting routines: only existing routines are exported and updated
- Rewriting git history to remove past leaks: the one known case is acknowledged in the allowlist, and a rewrite stays the owner's decision
- Stats or dashboards built from the run records: a later spec
- Event-driven (webhook) triggers

## Open Questions

None open. Settled before design:
- Adapters: the observability tool, the document store, the chat channel and the code host ship in this phase (owner, 2026-10-17).
- Query packs: in the private config, not on the sources page; the sources page keeps the mutes (owner, 2026-10-17).
- Local digest: printed in the session, posted only with `--post`.
- Environment cache: whatever the setup cache does, the prompt checks the runtime commit hash (AC-11.3), so a stale clone runs degraded, never with wrong scripts.
- Partial routine updates: 5 updates on 2026-10-17 that sent only the prompt fields kept the connectors, name, schedule and notification settings. The sync still sends the unchanged fields from a fresh snapshot (AC-8.2).
- State revision: no revision number. The `claude/state` branch history records every state; manual edits happen outside run times.
- Judgment: the model judges every observed key, scripts compute every value and check every verdict (owner, 2026-10-18).
- A monitor matching several rules: the highest severity wins (owner, 2026-10-18).
- A tracked group missing from a top read: not open when the read was complete, deferred when it reached its limit (owner, 2026-10-18).
- Analysis: stored in the item and reused until it escalates (owner, 2026-10-18).
- A muted change gets no analysis, and the item keeps its earlier one (owner, 2026-10-18).
- Digest text: rendered by a script from the summary, posted unchanged by the model (owner, 2026-10-18).
- Config split: shared `config.json` plus one file per routine, providers defined once (owner, 2026-10-18).
- Shared transport: a provider default per place, with a per-source override, and no source catalog yet (owner, 2026-10-18).
- Public skeletons for the other routines: structure only, marked not runnable (owner, 2026-10-18).
- Routine forms: inline under `routines` and one file per routine both load, so single-file configs keep working.
- Values: a routine's value overrides the shared one of the same key, and the lint warns on a value repeated across routines.
- Not runnable: an exact first-line marker, refused by `sync`, `body` and `/routines run`.
- Tribe digests: collectors first (issue tracker, chat threads, changed documents, trend windows), then judgment and rendering; the digest page keeps layout version 1 (owner, 2026-10-18).
- Settings-enforced rules (no push notification, no sleep): with the runtime rollout, through the private repository's settings (owner, 2026-10-18).
- Tribe judgment: one phase for state, features, judgment, lifecycle, page and message (owner, 2026-10-18).
- Page edits: the run keeps merging the owner's edits on the previous digest page (owner, 2026-10-18).
- Reported warnings: the model proposes them freely from collected records, each citing a record link (owner, 2026-10-18).
- Acceptance: a state seeded from one live digest, replayed over the next live digest's window.
