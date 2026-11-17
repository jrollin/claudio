---
name: verify-findings
description: >
  Use when findings already produced by a review agent need checking before anyone acts on them:
  hand them to a fresh read-only adversary agent that looks for counter-evidence in the code, then
  tag each finding confirmed, plausible, refuted, not relevant, stale, or unverified, with
  `path:line` evidence. Checks existing findings, it does not review a diff.
  Trigger for: "verify these findings", "are these findings real?", "confirm or refute the
  review", "double-check the review agent's output", "any false positives in the review agent's
  report?", "/verify-findings".
  NOT for producing findings (use the *-review agents), NOT for a pull request review (pr-review
  has its own verify step), NOT for challenging a PR as an architect (use pr-challenge), and NOT
  for addressing human review comments on your own PR (use pr-triage).
---

# Verify Findings

Treat every agent finding as a claim until the code proves it. The `verify-adversary` agent
(`../../agents/verify-adversary.md`) checks each claim and returns a verdict with evidence. This
skill prepares its brief and checks what it returns.

## Iron rule

- The adversary sees a neutral claim and its location only: no rationale, impact, severity, fix,
  or source.
- Every verdict rests on a `path:line` or a listed search that the main model has read or re-run.
- Static only: nobody edits code or runs tests, scripts, or builds.

## Workflow

### 1. Collect

Pick the findings:

- A report named in the request wins.
- Otherwise take every agent report from the latest review run in the conversation (for example
  the 4 agents of a pre-merge gate).
- Unclear which run: ask.
- Zero findings: say so and stop.

Normalize each finding into a row:

| Field | Content |
| --- | --- |
| `id` | `F1`, `F2`, … assigned after sorting |
| `claim` | `<defect>` at the location, with no impact and no reason |
| `location` | `path:line`, or a symbol name |
| `kind` | `runtime`, `structural`, or `absence` (definitions in the agent file) |
| `severity` | As the source gave it, never sent |
| `source` | The agent or report that raised it, never sent |
| `fix` | The source's suggested fix, never sent |

Rules:

- Claim example: "`sort` request param interpolated into a SQL string", not "SQL injection
  allowing data theft".
- A claim that fits two kinds takes `runtime`.
- Split a finding holding 2+ claims: `F3.1`, `F3.2`.
- Merge findings with the same location and defect into one row listing every source.
- Sort by source severity, critical first, then assign ids: if the adversary runs short, the least
  severe claims are the ones left unchecked.
- Do not send these, mark them `unverified` with the reason:
  - no location found after a symbol search: `no location`
  - a location outside the repo, or a claim needing external data (CVE database, live
    infrastructure, another repo): `outside scope`
- Above 10 claims, ask the user whether to verify all of them in one run or pick a subset.

### 2. Pin the code

```bash
git rev-parse HEAD
git status --porcelain
```

- The adversary reads the working tree.
- Record the commit and the uncommitted files for the report header.
- The source report names another ref: stop and ask the user to check it out, or to approve a
  detached worktree in the scratchpad (`git worktree add --detach <dir> <ref>`, removed after the
  run).

### 3. Dispatch

Dispatch one `claudio-craft:verify-adversary` agent, never a fork: a fork inherits the reviewer's
reasoning. The brief:

```text
Code root: <absolute path>
Excluded paths: <source report file, if it lives under the code root>

Claims:
F1 | runtime | src/api/user.ts:42 | `sort` request param interpolated into a SQL string
F2 | absence | src/jobs/ | no dead-letter queue on the import consumer
...
```

No Agent tool available (for example when this skill runs inside a subagent): stop and say so.
Verifying in the same context is anchored on the findings and defeats the skill.

### 4. Check the adversary

Its output is leads. Read every cited line, for every verdict.

| Adversary output | Check | Fails → |
| --- | --- | --- |
| Any verdict | The cited line shows what the adversary says | `unverified`, reason `bad citation` |
| Any verdict | Evidence matches the verdict's required shape in the agent file | `plausible` |
| `confirmed`, runtime | An `entry` line is cited | `plausible`, reason `no entry point cited` |
| `confirmed`, absence | Re-run one listed search, still 0 relevant hits | `unverified`, reason `search not reproduced` |
| `refuted` by a guard | Read the path from guard to fault: the guard runs first on the claim's exact input | `unverified`, reason `refutation rejected` |
| `refuted` by no entry point | Re-run one refs search (cartog when available, else grep), check framework wiring | `unverified`, reason `refutation rejected` |
| `refuted` by a test | The test is not skipped and a CI line runs its suite | `plausible`, settles it: run the test |
| `not relevant` | A `bound` line holds an in-repo fact | `plausible`, severity lowered |
| Claim missing from output | none | `unverified`, reason `not checked` |

Then:

- A source `critical` or `high` finding with any verdict but `confirmed`: read the whole path
  between the cited lines, not just the lines.
- Severity: compare the adversary's absolute severity with the source's. Change it only when the
  adversary's reason holds after your reading.

### 5. Report

```markdown
## Verified findings

- Code: `<sha>`, working tree with <n> uncommitted files
- Mode: static, no code run
- Findings: 6 (2 confirmed, 1 plausible, 1 unverified, 1 not relevant, 1 refuted)

| # | Finding | Source | Verdict | Severity | Evidence | Source fix |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | <claim> | security-review | confirmed | critical | • fault `src/api/user.ts:42`<br>• entry `src/routes.ts:10` | <fix> |
| F2 | <claim> | observability-review | plausible | high → medium | • depends on `MAX_BATCH`<br>• settles it: prod config value | <fix> |
| F3 | <claim> | test-review | unverified | medium | refutation rejected: guard at `:30` checks format, not ownership | <fix> |
| F4 | <claim> | quality-review | refuted | ~~medium~~ | • counter `src/plugins.ts:8` registers it by name | - |

### Source verdicts

- security-review: Vulnerable → Needs changes (its only critical is refuted)
```

Rules:

- Sort by verdict, then by severity:
  - `confirmed`
  - `plausible`
  - `unverified`
  - `stale`
  - `not relevant`
  - `refuted`
- A changed severity shows `old → new`.
- A refuted finding strikes its severity.
- A cell with 2+ facts puts each on its own line.
- `Source fix` is filled for `confirmed` and `plausible` rows only.
- Source verdicts: recompute each agent's own verdict rule over its surviving `confirmed` and
  `plausible` findings. Omit the section when no verdict changes.
- Map to `pr-review` verdicts: `refuted` and `not relevant` are its `dropped`.

## Red flags

- A claim that carries impact, severity, or the reviewer's reasoning.
- Accepting a refutation after reading the guard line alone.
- A `confirmed` with no cited line, resting on "found nothing".
- An `absence` verdict accepted without re-running a search.
- Verifying in the same context because the Agent tool is missing.
- Reporting a finding the user already fixed as `refuted` instead of `stale`.
