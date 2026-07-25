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
- **`test-review`** — Test suite quality: coverage of new behavior, correct test
  level (unit/integration/functional/e2e), assertion quality, determinism, and
  anti-patterns (mock-only assertions, branching in tests, retried-into-green).
  Judges whether the suite would catch a regression, not a coverage percentage.
  Complements the `tdd` skill (which writes tests); this reviews them.
  Triggers on "are these tested?", "review the tests", "any flaky tests?".

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

## Recipes

Agents are dispatched by intent, not by a hook: nothing fires automatically.
Describe the *outcome* you want and the matching agents fan out in parallel, or
name them explicitly with `@`. With no path, each reviews the diff vs the base
branch.

| I want to… | Say this | Fans out to |
| --- | --- | --- |
| Ship a new feature properly | "I built feature X. Make sure it is documented, well organized, performant, and tested." | `documentation-review` + `doc-vs-code-review` + `architecture-review` + `quality-review` + `performance-review` + `test-review` |
| Pre-merge gate | "Is this ready to merge?" | `quality-review` + `security-review` + `test-review` + `doc-vs-code-review` |
| Pre-deploy gate | "Is this safe to deploy?" | `infrastructure-review` + `security-review` + `observability-review` |
| Post-refactor check | "I refactored X, did I break the structure or the docs?" | `architecture-review` + `doc-vs-code-review` + `test-review` |
| Inherited legacy code | "Audit this module before I touch it." | `architecture-review` + `quality-review` + `test-review` + `security-review` |
| Debug-readiness | "Will we see this fail in prod?" | `observability-review` |
| Full spectrum | "Full craft review of this change." | all nine |

### Worked example

You just finished a feature and want it held to the whole standard:

```
I finished the invoice export feature. Review it: documented, well organized,
performant, and tested.
```

That maps onto six agents, each with a distinct claim:

- `documentation-review` — is the new export flag/config documented, can a
  newcomer use it?
- `doc-vs-code-review` — do existing docs still match after the change?
- `architecture-review` — does the export sit in the right layer, no boundary
  leak?
- `quality-review` — dead code, duplication, function size, error context.
- `performance-review` — N+1 on the export query, unbounded result set,
  blocking I/O.
- `test-review` — is the new behavior covered, at the right level, with
  assertions that would catch a regression?

Scope it to a path when you know it:

```
@test-review src/invoices
@performance-review src/invoices/export.ts
```

### Note on "tested"

Two components split this concern:

- The **`tdd` skill** fires *while you implement*: it enforces a failing test
  before production code.
- The **`test-review` agent** fires *after*: it judges whether the resulting
  suite would actually catch a regression.

Asking "make sure it is tested" after the fact routes to `test-review`.

## Running evals

Both eval harnesses below (routing and TDD) require `claude` or `opencode` CLI,
`python3 + pyyaml`, `jq`, and `perl`.

### Routing evals

`tests/` holds an LLM-as-judge suite for agent **routing**: given only the
`description` frontmatter of every agent in `agents/` (exactly what a dispatcher
sees), does a request reach the right agent(s)? It does not test what an agent
concludes once dispatched.

```bash
# All 16 scenarios (default: claude backend, sonnet model)
bash tests/eval.sh

# Filter by id or tag
bash tests/eval.sh --id fanout_post_feature_full
bash tests/eval.sh --tag disambiguation

# Dry run (prints prompts only, no API calls)
bash tests/eval.sh --dry-run

# Alternate backend
bash tests/eval.sh --backend opencode --model anthropic/claude-sonnet-4-6
```

Tags: `single` (one clear winner), `fanout` (compound requests and gates),
`disambiguation` (overlapping pairs), `negative-routing` (must reach a skill,
not an agent), `boundary` (must not over-select).

The judge scores **set membership**, not ordering. Over-selection fails when a
scenario forbids a specific agent, so "dispatch everything to be safe" does not
pass.

Run these after editing any agent `description`: the descriptions are the
routing contract, and they are easy to break by accident. Two scenarios
(`fanout_pre_merge_gate`, `disambig_docs_quality_vs_drift`) caught real
over-selection and mis-routing during authoring.

### TDD evals

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
    test-review.md
  tests/
    eval.sh                  # routing eval harness (agent descriptions)
    golden_examples.yaml     # 16 routing scenarios
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
