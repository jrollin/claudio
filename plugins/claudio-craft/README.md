# claudio-craft

Engineering craft plugin for Claude Code: TDD discipline, skill testing, doc/code consistency.

## Components

### Skills

- **`tdd`** — Test-driven development workflow. Enforces the red-green-refactor
  cycle and the Iron Law (no production code without a failing test first).
  Auto-triggers on requests to implement, build, fix, or write production code.
  - `SKILL.md` — core rules, exceptions checklist, red flags table.
  - `testing-anti-patterns.md` — common pitfalls (mock-behavior tests,
    test-only methods in production, mocking without understanding,
    incomplete mocks).
  - `references/typescript.md`, `references/rust.md` — language-specific
    walkthroughs.

- **`skill-testing`** — Author LLM-as-judge behavioral evals for agent skills.
  Auto-triggers on requests to add evals, golden examples, or behavioral tests
  to a skill.
  - `references/golden-examples-schema.md` — YAML schema for test scenarios.
  - `templates/eval.sh` — multi-backend (claude / opencode) eval harness with
    dual judge mode (behavioral + command-routing).

### Agents

- **`doc-vs-code-review`** — Reviews documentation drift against the current
  codebase. Reports stale references, broken commands, and undocumented
  behavior. Read-only by default. Triggers on "is the doc still accurate?",
  "review docs vs code", post-refactor verification.

## Install

Via the claudio marketplace:

```
/plugin install claudio-craft@claudio-power
```

## Usage

- TDD: invoke implicitly (any implementation task) or explicitly via skill
  recognition.
- Skill testing: ask "create evals for skill X" or "add golden examples to skill Y".
- Doc review: ask "review docs vs code" or "@doc-vs-code-review docs/architecture.md".

## Running TDD evals

```bash
# All scenarios (default: claude backend, sonnet model)
bash skills/tdd/tests/eval.sh

# Filter by id or tag
bash skills/tdd/tests/eval.sh --id write_test_before_code
bash skills/tdd/tests/eval.sh --tag iron-law

# Dry run (prints prompts only)
bash skills/tdd/tests/eval.sh --dry-run

# Alternate backend
bash skills/tdd/tests/eval.sh --backend opencode --model anthropic/claude-sonnet-4-6
```

Requires `claude` or `opencode` CLI, `python3 + pyyaml`, `jq`.

## Layout

```
claudio-craft/
  .claude-plugin/plugin.json
  agents/doc-vs-code-review.md
  skills/
    tdd/
      SKILL.md
      testing-anti-patterns.md
      references/{typescript,rust}.md
      tests/{eval.sh,golden_examples.yaml}
    skill-testing/
      SKILL.md
      references/golden-examples-schema.md
      templates/eval.sh
```
