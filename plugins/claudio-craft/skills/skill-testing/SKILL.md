---
name: skill-testing
description: >
  Use when creating LLM-as-judge behavioral evals for an agent skill.
  Trigger for: "create tests for skill", "add evals to skill", "test this skill",
  "behavioral testing", "eval harness", "golden examples".
  NOT for unit tests, integration tests, or application testing.
---

# Skill Testing

Create LLM-as-judge behavioral evals for agent skills.

## What This Produces

```
<skill>/tests/
  eval.sh                 # evaluation harness (from template)
  golden_examples.yaml    # test scenarios
```

## Workflow

### 1. Understand the skill

Read the target skill's `SKILL.md` and any supplementary files. Identify:

- Core behaviors the skill enforces
- Exceptions / edge cases it handles
- Anti-patterns it warns against
- Decision boundaries (when to do X vs Y)

### 2. Write golden examples

Create `<skill>/tests/golden_examples.yaml` following the schema in `references/golden-examples-schema.md`.

**Aim for ~2-3 scenarios per behavioral category** (typically 8-15 total). Group with YAML comments.

Writing good scenarios:

- **Queries must be unambiguous.** State the context explicitly. If a scenario assumes a specific phase or state, say so in `context` and `user_query`.
- **Expected behavior must be verifiable in one sentence.** The judge LLM reads this and decides PASS/FAIL. Vague expectations cause flaky results.
- **Anti-patterns focus on the primary action.** Edge case caveats in the agent response are acceptable — only the main course of action matters.
- **Prefer narrow, specific queries.** Broad queries (e.g. "implement feature X") produce overview responses that gloss over details. "Write the first user story for X" tests specific behavior much better.
- **For multi-phase skills, scope each scenario to one phase.** Include the phase name in both `context` and `user_query` so the agent doesn't produce a generic overview.
- **Use `expected.tool_calls` for command-routing skills** (which CLI command first). Use `expected.behavior` for behavioral skills (what the agent should do/say).

### 3. Create eval.sh from template

Copy `templates/eval.sh` to `<skill>/tests/eval.sh`. Customize the config block only:

```bash
# --- SKILL CONFIG ---
SKILL_NAME="my-skill"
SKILL_FILES=("SKILL.md")                    # relative to skill dir
EVAL_BACKEND_VAR="MY_SKILL_EVAL_BACKEND"    # env var name
EVAL_MODEL_VAR="MY_SKILL_EVAL_MODEL"        # env var name
AGENT_INSTRUCTION="..."                     # how agent should format response
```

Two common agent instruction patterns:

| Skill type | AGENT_INSTRUCTION |
|---|---|
| Behavioral (TDD-style) | "list the steps you would take in order, prefixed with a number. Be concise -- one sentence per step. Do not write code. Do not use tools." |
| Command routing (cartog-style) | "describe which commands you would run. List each command on its own line prefixed with '> '. Do not explain -- just list the commands." |

### 4. Validate

```bash
# Syntax check
bash -n <skill>/tests/eval.sh

# Dry run — verify prompts look right
bash <skill>/tests/eval.sh --dry-run

# Smoke test one scenario
bash <skill>/tests/eval.sh --id <first_scenario>

# Full run
bash <skill>/tests/eval.sh
```

After the full run, iterate: fix failures using the troubleshooting order below, re-run the failing scenario with `--id`, then do a full run again to confirm no regressions.

**Note:** when using `--backend opencode`, run from a temp directory (e.g. `workdir=/tmp/eval-run`) to avoid polluting the project with session files.

## When Evals Fail

Troubleshoot in this order:

**Step 0 — Consistent failures are a signal.** If a scenario fails repeatedly across runs, report it to the user as a potential skill improvement opportunity — the SKILL.md wording may need strengthening, not just the eval.

| Step | Action | Example |
|---|---|---|
| 1. Skill wording | Tighten the SKILL.md where the agent rationalizes past it | "Write simplest code" -> "Write the stupidest code that makes the test green. Not a regex. Not email.includes('@')." |
| 2. Golden example | Make query/context more explicit so agent can't misinterpret | "Write the implementation" -> "RED phase complete. Now make it green." |
| 3. Expected behavior | Relax if the judge is too strict about phrasing | Remove "must explicitly state deferral" if the implementation choice is what matters |
| 4. Judge prompt | Last resort — only if the judge misunderstands the scenario type | Add context to judge so it knows which phase applies |

**Never** fix flaky evals by making the judge more lenient globally. Fix the specific scenario.

## LLM Non-Determinism

Some scenarios will fail 1 in 5 runs. This is inherent to LLM-as-judge. Acceptable flake rate: <20% per scenario. If a scenario fails >20%:

1. The skill wording is ambiguous — tighten it
2. The query triggers strong model priors — reword to break the prior
3. The expected behavior is too narrow — relax the success criteria

## Template Features

The `templates/eval.sh` harness provides:

- **Multi-backend**: `--backend claude` (default) or `--backend opencode`
- **Filtering**: `--id <scenario>`, `--tag <tag>`, `--dry-run`
- **Dual judge mode**: auto-selects command-routing or behavioral judge based on which `expected` fields are present
- **Output sanitization**: strips ANSI codes and `<system-reminder>` tags from CLI output
- **Security**: arg validation, safe temp file deletion (TMPDIR guard)
- **Error handling**: surfaces CLI errors, detects empty responses (quota exhaustion)
