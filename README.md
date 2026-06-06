# Claudio

Claude Code plugin suite for spec-driven development, engineering craft, and tooling.

## Plugins

This repository hosts three plugins, each shipped independently from the `claudio-power` marketplace.

### `claudio-spec` — Spec-driven development

| Skill / Agent | Description |
|---|---|
| `spec-create` | Create feature specifications (Requirements → Design → Tasks) |
| `spec-impl` | Implement tasks from a completed specification |
| `spec-extract` | Extract business rules and domain logic from existing codebases |
| `spec-grill` | Interview you relentlessly to pressure-test a plan before implementation |
| `event-modeling-spec` | Design systems with Event Modeling methodology |
| `event-modeling-tasks` | Translate a completed event model into implementation tasks |
| `@agent-claudio-spec:spec-review` | Review a feature spec for completeness and readiness for `spec-impl` |

### `claudio-craft` — Engineering craft

| Skill / Agent | Description |
|---|---|
| `tdd` | Test-driven development: red-green-refactor cycle, write failing tests first |
| `skill-testing` | Create LLM-as-judge behavioral evals for an agent skill |
| `@agent-claudio-craft:doc-vs-code-review` | Review whether documentation matches the current code |

### `claudio-tools` — Operational tools

| Skill | Description |
|---|---|
| `agent-browser` | Use a browser to check UI or test automation |

## Install

### From the marketplace

```bash
# Add the marketplace once
/plugin marketplace add git@github.com:jrollin/claudio.git

# Install the plugins you need
/plugin install claudio-spec
/plugin install claudio-craft
/plugin install claudio-tools
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

/claudio-craft:tdd
/claudio-craft:skill-testing
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

## Repository layout

```
plugins/
  claudio-spec/    skills/ + agents/ + .claude-plugin/plugin.json
  claudio-craft/   skills/ + agents/ + .claude-plugin/plugin.json
  claudio-tools/   skills/ + .claude-plugin/plugin.json
.claude-plugin/
  marketplace.json
```
