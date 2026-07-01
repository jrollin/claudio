# claudio-craft

Engineering craft plugin for Claude Code: TDD discipline, skill testing, doc/code consistency, and a suite of read-only review agents that validate a change against best practices.

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

All agents are **read-only** by default: they report findings and suggested
fixes but do not edit code unless explicitly asked. Each takes an optional path
and otherwise reviews the current diff vs the base branch (or the repo's docs).
Each uses a severity scale (critical / high / medium / low) and a verdict.

- **`doc-vs-code-review`** — Reviews documentation drift against the current
  codebase. Reports stale references, broken commands, and undocumented
  behavior. Triggers on "is the doc still accurate?", "review docs vs code",
  post-refactor verification.

**Best-practice review agents**: one per engineering dimension. Each carries a
self-contained checklist (with per-language idiom tables for Rust, TS/JS, Ruby,
Python, Java, Go), so it is portable across repos and machines. Run them
individually, or fan them out in parallel for a full-spectrum review.

- **`architecture-review`** — *Code* architecture: layering, dependency
  direction, coupling, cohesion, and boundary discipline. Reads source
  (imports, module graph, manifests). Infers the intended pattern (layered,
  hexagonal, MVC, …) and flags violations. Triggers on "review the
  architecture", "check layering", "is this coupled?".
- **`infrastructure-review`** — *Infrastructure* and deployment architecture
  across any substrate: deployment model, network exposure, access scope,
  secrets, event/failure wiring, service supervision, config drift, resilience,
  scaling, and cost. Reads IaC (Terraform, CDK/SAM/CloudFormation, Serverless,
  Pulumi, K8s/Helm, Docker), config management (Ansible/Chef/Puppet), and
  self-managed VPS/on-prem (systemd, nginx, firewall, cron), not source.
  Cloud-native and bare-VPS alike. Triggers on "review the infra architecture",
  "review the Terraform/serverless.yml/Ansible playbook",
  "is anything publicly exposed?", "check our IaC".
- **`observability-review`** — Structured logging, metrics, tracing,
  correlation IDs, error context, and log hygiene (no secrets/PII in logs).
  Triggers on "is this observable?", "can we debug this in prod?".
- **`performance-review`** — N+1 queries, algorithmic complexity, allocations,
  blocking I/O, missing pagination/indexes. Reasons about complexity and data
  volume, not micro-benchmarks. Triggers on "review performance",
  "check for N+1", "will this scale?".
- **`security-review`** — Injection, secret handling, auth/authorization, input
  validation at boundaries, and unsafe data flow. Describes risk and fix; never
  prints exploits. Triggers on "review security", "is this safe?",
  "audit this endpoint".
- **`quality-review`** — Code quality and maintainability: dead code, real
  duplication, function/file size, naming, error-message context, comment
  discipline, and over-engineering (YAGNI). Triggers on "review code quality",
  "is this maintainable?", "is this over-engineered?".
- **`documentation-review`** — Documentation *quality*: completeness, clarity,
  structure, and coverage of public APIs/config/breaking changes. Complements
  `doc-vs-code-review` (which checks drift against code). Triggers on
  "are these docs clear/complete?", "is the README good?".

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
- Best-practice review: invoke a single dimension (e.g.
  "@performance-review src/api" or "@security-review") or ask for several at
  once ("review this change for architecture, security, and performance"). With
  no path, each agent reviews the current diff vs the base branch.

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
  agents/
    doc-vs-code-review.md
    architecture-review.md
    infrastructure-review.md
    observability-review.md
    performance-review.md
    security-review.md
    quality-review.md
    documentation-review.md
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
