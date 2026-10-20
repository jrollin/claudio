# Claudio

Claude Code plugin suite for spec-driven development, engineering craft, and tooling.

## Plugins

This repository hosts several plugins, each shipped independently from the `claudio-power` marketplace.

### `claudio-spec`: Spec-driven development

| Skill / Agent | Description |
|---|---|
| `spec-create` | Create feature specifications (Requirements → Design → Tasks) |
| `spec-impl` | Implement tasks from a completed specification |
| `spec-extract` | Extract business rules and domain logic from existing codebases |
| `spec-grill` | Interview you relentlessly to pressure-test a plan before implementation |
| `event-modeling-spec` | Design systems with Event Modeling methodology |
| `event-modeling-tasks` | Translate a completed event model into implementation tasks |
| `doc-diataxis` | Structure and write user docs with the Diátaxis framework (tutorials, how-to, reference, explanation) |
| `onboarding` | Onboard a developer to an unfamiliar repo: architecture map, testing strategy, local setup, security posture (+ cloud architecture & CI/CD when present) |
| `@agent-claudio-spec:spec-review` | Review a feature spec for completeness and readiness for `spec-impl` |

### `claudio-craft`: Engineering craft

| Skill / Agent | Description |
|---|---|
| `tdd` | Test-driven development: red-green-refactor cycle, write failing tests first |
| `skill-testing` | Create LLM-as-judge behavioral evals for an agent skill |
| `writing-style` | Concise, bullet-first prose with no filler; write or review mode |
| `pr-review` | Review someone else's pull request: threads, diff, severity-tagged comments posted after approval |
| `pr-triage` | Address review feedback on your own pull request: verify, fix, reply |
| `pr-challenge` | Challenge a pull request as an architect: scale, monitoring, failure modes, cost |
| `@agent-claudio-craft:doc-vs-code-review` | Review whether documentation matches the current code |
| `@agent-claudio-craft:documentation-review` | Judge documentation quality: completeness, clarity, structure |
| `@agent-claudio-craft:quality-review` | Review readability, duplication, dead code and simplicity |
| `@agent-claudio-craft:architecture-review` | Check layering, dependency direction, coupling and module boundaries |
| `@agent-claudio-craft:security-review` | Audit injection, secret handling, auth and input validation |
| `@agent-claudio-craft:test-review` | Review test coverage, test level, assertions and flakiness |
| `@agent-claudio-craft:performance-review` | Find N+1 queries, quadratic scans and other avoidable slowness |
| `@agent-claudio-craft:observability-review` | Check logging, metrics, tracing and failure visibility |
| `@agent-claudio-craft:infrastructure-review` | Review deployment, network exposure, IaC and resilience |

### `claudio-rust`: Rust architecture

| Skill / Agent | Description |
|---|---|
| `rust-hexagonal` | Ports and adapters architecture in Rust, scaffold and review modes |
| `rust-hexagonal-impl` | Implement one hexagonal slice end to end with the hexagonal agents |
| `rust-decompose` | Split a module or function into cohesive pieces, scaffold and review modes |
| `@agent-claudio-rust:hexagonal-core-builder` | Build the domain core of a slice: entities, ports, use cases, in-memory tests |
| `@agent-claudio-rust:hexagonal-driven-adapter` | Implement one driven adapter (repository, client, sender) behind a domain port |
| `@agent-claudio-rust:hexagonal-driving-adapter` | Implement one driving adapter (HTTP handler, CLI, consumer) over the use cases |
| `@agent-claudio-rust:hexagonal-review` | Review a slice against the hexagonal layering rules |

### `claudio-tools`: Operational tools

| Skill | Description |
|---|---|
| `agent-browser` | Use a browser to check UI or test automation |

### `claudio-routines`: claude.ai routines as code

| Skill / Script | Description |
|---|---|
| `routines` | Export live routines, render prompts from private templates, show drift, lint, push after approval, print the environment setup script, seed a tribe routine's state from its previous digest pages or a recap routine's state from its stored state (`seed`), and run a routine locally. `lint --private` also fails a private repository whose `.claude/settings.json` is missing (`settings-missing`), invalid (`settings-invalid`) or lacks a denied tool (`deny-missing:<entry>`) |
| `runtime/state.py` | State engine for routine runs: window, item lifecycle, blind spots, mutes |
| `runtime/collect.py` | Collectors: read a source over its provider API or through a claude.ai connector, chosen per source and place |
| `runtime/relay_capture.py` | `PostToolUse` hook command that saves each connector result byte-exact, so a relay run never copies a result by hand; `collect.py plan` and `tribe.py publish-plan` pick the captures up |
| `runtime/evaluate.py` | Compute the judgment features from collections and a query pack, check the model's judgment and analysis, and merge them into the facts the state engine takes |
| `runtime/digest.py` | Digest: renders the posted message from the change summary, the next state and the base file, so the model posts it unchanged and writes none of it |
| `runtime/features.py` | Features, base and rules files: the named numbers the model judges and cites |
| `runtime/judgment.py` | Judgment and analysis checks: every cited value must match the features |
| `runtime/tribe.py` | Tribe digest engine and its `tribe_*.py` modules: window, seed, features, judgment check, lifecycle, page render with its structure check, page write plan and chat message, for a routine with `engine: tribe` |
| `runtime/recap.py` | Chat recap engine and its `recap_*.py` modules: window, seed, features, judgment check, lifecycle and chat message, for a routine with `engine: recap` |
| `runtime/config_tree.py` | Config tree: loads `config.json` and the routine files, resolves transports, rejects secrets |
| `runtime/roles.py` | Role record schemas, collector config and query pack validation |
| `runtime/providers/` | One adapter per vendor, per role, for both transports; credentials and hosts in its README |

Setup and configuration: [plugins/claudio-routines/README.md](plugins/claudio-routines/README.md).

## Install

### From the marketplace

```bash
# Add the marketplace once
/plugin marketplace add git@github.com:jrollin/claudio.git

# Install the plugins you need
/plugin install claudio-spec
/plugin install claudio-craft
/plugin install claudio-tools
/plugin install claudio-rust
/plugin install claudio-routines
```

### Local development

```bash
claude --plugin-dir /path/to/claudio/plugins/claudio-spec
```

## Usage

```
/claudio-spec:spec-create <feature-name> [description]
/claudio-spec:spec-impl <feature-name>
/claudio-spec:spec-extract <concept>
/claudio-spec:event-modeling-spec <system-name> [description]
/claudio-spec:event-modeling-tasks <system-name>
/claudio-spec:doc-diataxis <content-or-topic>   # or --audit [path]

/claudio-craft:tdd
/claudio-craft:skill-testing

/claudio-rust:rust-hexagonal
/claudio-rust:rust-hexagonal-impl
/claudio-rust:rust-decompose

/claudio-tools:agent-browser

/claudio-routines:routines sync <slug>
/claudio-routines:routines run <slug> [--since T] [--post]
/claudio-routines:routines seed <slug>
```

Typical workflow:

1. `/claudio-spec:spec-create my-feature` — generates `docs/features/my-feature/{requirements,design,tasks}.md`
2. `@agent-claudio-spec:spec-review docs/features/my-feature/` — review before implementation
3. `/claudio-spec:spec-impl my-feature` — implements tasks one-by-one from the spec

For existing codebases, `/claudio-spec:spec-extract pricing` reverse-engineers business rules into `docs/rules/pricing.md`. Supports `--symbol`, `--path`, and `--broad` options.

The `tdd` skill activates automatically when implementing features or bugfixes, enforcing the red-green-refactor cycle.

After a refactor:

```
@agent-claudio-craft:doc-vs-code-review
```

## Migration from `claudio` 1.x

The previous single `claudio` plugin has been split into three. There is no in-place upgrade.

1. Uninstall the old plugin: `/plugin uninstall claudio`
2. Install the replacements above.
3. Update any saved invocations: `claudio:` becomes `claudio-spec:`, `claudio-craft:`, or `claudio-tools:` depending on the skill (see tables above).

`claudio-rust` and `claudio-routines` are new plugins with no 1.x counterpart.

## Repository layout

```
plugins/
  claudio-spec/       skills/ + agents/ + .claude-plugin/plugin.json
  claudio-craft/      skills/ + agents/ + .claude-plugin/plugin.json
  claudio-tools/      skills/ + .claude-plugin/plugin.json
  claudio-rust/       skills/ + agents/ + .claude-plugin/plugin.json
  claudio-routines/   skills/ + runtime/ + .claude-plugin/plugin.json
.claude-plugin/
  marketplace.json
scripts/              leak guard: leak_check.py, hooks installer, protection check, tests
.githooks/            pre-commit, pre-merge-commit and commit-msg hooks running the leak check
.github/workflows/    CI: leak check, template lint, unit tests
docs/features/        feature specs (requirements, design, tasks)
```

## Contributing

This repository is public. The leak guard blocks private names, ids, tokens and home paths before they are committed or merged.

1. Install the hooks once per clone: `scripts/install-hooks.sh`.
2. List private words, one per line, in `~/.config/claudio/deny-words.txt`, or point `CLAUDIO_DENY_WORDS_FILE` at another file. An entry starting with `=` matches whole words only.
3. Run the checks:
   - `python3 scripts/leak_check.py --tree`: the working tree.
   - `python3 scripts/leak_check.py --history`: every past commit and commit message.
   - `python3 scripts/leak_check.py --range main..HEAD`: the commits of a branch, as CI does.
   - Set `CLAUDIO_REQUIRE_DENY_WORDS=1` to make the hooks fail when no deny-words are found.
4. Allow an example or an acknowledged commit in `scripts/leak-allow.txt`, as `path:<glob> <rule>` or `commit:<hash> <rule>`.
5. Run the tests, one discovery per directory:
   - `python3 -m unittest discover -s scripts`
   - `python3 -m unittest discover -s plugins/claudio-routines/runtime`
   - `python3 -m unittest discover -s plugins/claudio-routines/skills/routines/scripts`

Findings print `path:line:rule` for the tree and staged modes, and `<short-hash>:path:line:rule` for the history and range modes. They never print the matched text: a part of a path that matches a rule prints as `<redacted>`. Exit codes: 0 clean, 1 findings, 2 the check could not run.

CI needs the deny-words secret, which GitHub does not pass to pull requests from forks, so a fork pull request fails the `leak-check` status and cannot merge. A maintainer pushes the contributor's branch to this repository to run CI on it.

### One-time GitHub setup

1. Store the deny-words for CI: `gh secret set LEAK_DENY_WORDS < ~/.config/claudio/deny-words.txt`.
2. Protect main: pull requests, the `leak-check` status, admins included.

```bash
gh api -X PUT 'repos/{owner}/{repo}/branches/main/protection' --input - <<'JSON'
{"required_status_checks": {"strict": true, "contexts": ["leak-check"]},
 "enforce_admins": true,
 "required_pull_request_reviews": {"required_approving_review_count": 0},
 "restrictions": null}
JSON
```

3. Enable secret scanning with push protection in the repository's security settings.
4. Check the protection: `scripts/check_protection.py` exits 0 only when main requires a pull request, the `leak-check` status and admin enforcement. It does not check secret scanning. Set `CLAUDIO_REPO=owner/name` to skip the `gh repo view` lookup.

