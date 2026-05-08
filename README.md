# Claudio

Claude Code plugin for spec-driven development and TDD.

## Skills

| Skill | Description |
|-------|-------------|
| `spec-create` | Create feature specifications (Requirements → Design → Tasks) |
| `spec-impl` | Implement tasks from a completed specification |
| `spec-extract` | Extract business rules and domain logic from existing codebases |
| `tdd` | Test-driven development: red-green-refactor cycle, write failing tests first |
| `event-modeling-spec` | Design systems with Event Modeling methodology (commands/events/views blueprints) |
| `event-modeling-tasks` | Translate a completed event model into implementation tasks |

## Agents

| Agent | Description |
|-------|-------------|
| `doc-vs-code-review` | Review whether documentation matches the current code (README, ADRs, CLAUDE.md, feature docs). Optional path argument. |
| `spec-review` | Review a feature spec (`requirements.md`, `design.md`, `tasks.md`) for completeness, traceability, and readiness for `spec-impl`. Optional spec folder path. |

Invoke explicitly with `@agent-claudio:doc-vs-code-review` or `@agent-claudio:spec-review`, or describe the task and let Claude auto-delegate.

## Install

### From Git repository

```bash
# Add marketplace
/plugin marketplace add git@github.com:jrollin/claudio.git

# Install the plugin
/plugin install claudio
```

### Local development

```bash
claude --plugin-dir /path/to/claudio
```

## Usage

```
/claudio:spec-create <feature-name> [description]
/claudio:spec-impl <feature-name>
/claudio:spec-extract <concept>
/claudio:tdd
/claudio:event-modeling-spec <system-name> [description]
/claudio:event-modeling-tasks <system-name>
```

Typical workflow:

1. `/claudio:spec-create my-feature` — generates `docs/features/my-feature/{requirements,design,tasks}.md`
2. `/claudio:spec-impl my-feature` — implements tasks one-by-one from the spec

For existing codebases, use `/claudio:spec-extract pricing` to reverse-engineer business rules into `docs/rules/pricing.md`. Supports `--symbol`, `--path`, and `--broad` options for different entry points.

The `tdd` skill activates automatically when implementing features or bugfixes, enforcing the red-green-refactor cycle.

Run a spec review before implementation:

```
@agent-claudio:spec-review docs/features/my-feature/
```

Run a docs vs. code review after a refactor:

```
@agent-claudio:doc-vs-code-review
```
