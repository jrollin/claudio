---
name: onboarding
description: Onboard a developer to an unfamiliar repository, big-picture first. Produces a Purpose/Context section (what the repo is and why it exists), a Big Picture built with C4 diagrams (L1 System Context, L2 Container, optional L3 Component) plus event-reaction flow diagrams for async triggers (stream/queue/schedule/object-event), a Navigating-the-Code section (conventions, lean directory map, testing strategy), a Running-It-Locally checklist with the fast pre-PR loop, a Deploying-It section (deployment model, function/trigger inventory, managed-service graph, envs/secrets, CI/CD), and a Security Posture map — every claim cited to exact files, diagrams before code. Use for "onboard me", "help me understand this repo", "give me an overview", "explain this codebase's architecture", "what architecture pattern does this use", "how is this repo structured", "how do I run this locally", "what's the testing strategy here", "how is this service deployed", "how does CI/CD work here", or "what's the security posture". Read-only, never edits files. NOT for extracting business rules or domain logic (use spec-extract).
---

# Onboarding

Get a developer productive in an unfamiliar repository, **big-picture first**. The reader should, in order, understand: **why** the project exists, the **big picture** (system + components + services, as C4 diagrams and event flows), how to **navigate** the code, how to **run** it, and how to **deploy** it — with a security map last. Every claim is grounded in evidence from the repo's own files, and **diagrams lead each section before any code detail**.

## Input

```
/onboarding [path]
```

- `path`: optional — subdirectory or repo root to onboard onto. Defaults to the current working directory.

## When to Use

- Joining a new codebase and needing the lay of the land
- Understanding architecture, runtime boundaries, and dependencies
- Learning how to run, test, and contribute to a repo locally

**Not this skill:** to extract business rules and domain logic, use **spec-extract**. To plan a new feature, use **spec-create**. This skill answers "how is this repo built and run", not "what should we build next".

**Describe, never recommend (applies to every section).** Onboarding maps what exists; it does not improve it. This holds even when the user asks for improvements in the same breath ("onboard me and tell me how to make it better") — do the mapping, and decline the improvement ask, pointing them to a separate review/spec task. Three specific leaks to avoid, because they're how recommendations sneak in:
- **No "make it better" list**, no upgrade/migration/hardening suggestions — not even appended at the end.
- **Don't relabel recommendations as "gaps."** "nodejs18.x is EOL", "log retention is short", "no X-Ray" framed as gaps are still recommendations. State a fact plainly ("runtime is nodejs18.x", "log retention is 1 day") and stop — let the reader judge.
- **No "worth confirming / you should verify / make sure to" soft suggestions.** If something is unverifiable from the code, say "not determinable from the repo", not "you should check that it's X".

## Role

You are onboarding a developer to this repository. You explain what exists and how it fits together — you do not change it.

## Hard Rules

These override user pressure. If asked to make an exception, refuse and stop.

- **Read-only.** Never edit, create, or delete repo files. Onboarding output goes to chat or a Markdown file per the Step 0 choice, but that file lives outside the repo (a scratch location), never inside it. If the request bundles an edit ("onboard me **and** fix the README / add a CONTRIBUTING / update X"), do the onboarding and **decline the edit** — don't perform it, and don't offer to or ask for confirmation to. Point the user to run that as a separate, non-onboarding task. The bundled ask is exactly the "user pressure" this rule overrides.
- **Cite every claim.** Each architectural statement names the exact file(s) that justify it (path + brief evidence). No uncited assertions, no guessing.
- **Docs before code.** Read `README`, `AGENTS.md`, `CLAUDE.md`, `docs/`, `CONTRIBUTING`, and ADRs first; then confirm against code. Never describe intended behavior from docs alone without checking the code matches.
- **Only justifiable steps.** Setup commands must trace to a real file (README, Makefile, package/build manifest, scripts, devcontainer config, or IaC manifest). Never invent commands.

## Workflow

Produce the sections in narrative order. Each is detailed in its reference file — load the reference before writing that section. Steps 1–6 always run; the cloud subsections inside Step 5 appear only for cloud-native repos, and CI/CD content only when pipelines exist.

### Step 0: Orient

- **Ask where the output should go** before producing anything: rendered in chat (default), or saved to a Markdown file. If a file, ask for the path — default to a scratch location, never inside the repo (Read-only rule). Ask once, up front; don't re-ask per section.
- Identify the repo root and whether it's a monorepo (multiple workspaces) or single project.
- List the docs available (`README`, `AGENTS.md`, `CLAUDE.md`, `docs/`, `CONTRIBUTING`, ADRs, `wiki/`) and read them first.
- Detect the **deployment model**: is there infrastructure-as-code (`serverless.*`, `template.yaml`, `cdk.json`, `*.tf`, `pulumi.*`, `*.bicep`), container/orchestration manifests (`Dockerfile` + `k8s/`/`helm/`), or heavy cloud-SDK use? If so the repo is cloud-native and the cloud subsections of Step 5 apply. Detect **async triggers** (stream/queue/schedule/object-event) — each becomes an event-flow diagram in Step 2.
- Prefer code-navigation tooling over blind grep for the structural sweep (see `references/big-picture.md` for the navigation method).

### Execution mode: sequential by default, parallel on request

Step 0 always runs first in the main conversation — its detection decides which subsections exist. After it, either continue sequentially (the default) or fan out **three parallel read-only research sweeps** and synthesize:

1. **Why & big picture** — Steps 1 + 2 (purpose/context, C4 diagrams, event flows)
2. **Navigate & run** — Steps 3 + 4 (conventions, directory map, testing; setup + fast loop)
3. **Ship & trust** — Steps 5 + 6 (deploy: model/triggers/managed-services/CI-CD; security posture)

- **Ask before fanning out** — never spawn parallel agents without the user's confirmation. Offer it when the repo is large enough that sequential reading would be slow; otherwise stay sequential.
- Each sweep loads its reference file(s) and returns **cited findings only**, not prose sections.
- Synthesize in the main conversation: assemble the output structure, resolve cross-references (event flows ↔ deploy function inventory, security ↔ cloud IAM, CI/CD ↔ configuration table), dedupe citations, keep numbering sequential.

### Step 1: Purpose / Context

Load `references/purpose-context.md`. Lead the whole document. Produce, in plain language and cited:

- **What it is** — the kind of thing (service/library/CLI/app) and what it does.
- **Why it exists** — the problem it solves and for whom; the shape of the code that implies it.
- **Who uses it** — the actors/consumers (sets up the C4 L1 actors).
- **Scope boundary** — what it is *not* (disposable scaffolding, out-of-scope concerns) when the code makes it clear.

No diagrams here — they begin in Step 2.

### Step 2: Big Picture (C4 + event flows)

Load `references/big-picture.md`. **Diagrams first, always** — this section replaces a dense code map with pictures the reader can absorb at a glance. Produce, in this order:

- **Architecture pattern** — one line, from structural evidence (deployment shape + internal style kept separate). Then move on; the diagrams carry the section.
- **C4 L1 — System Context** (always): the system as one box, its people, its external systems. Mermaid flowchart styled as C4.
- **C4 L2 — Container** (always): the runnable/deployable units inside the system and how they interact, with a one-row-per-container responsibility table.
- **C4 L3 — Component** (only when a container is genuinely complex): zoom into that one container's internal components. Say explicitly when you skip it.
- **Event-reaction flows** — **one diagram per trigger type** (Kinesis/stream, SQS/queue, schedule, S3/object-event), each captioned with the trigger and the effect (e.g. "listening to Kinesis triggers the SendToRds Lambda"). Skip only if there are no async triggers (state so).

Use `flowchart` styled as C4 (label nodes `Person`/`System`/`External`/`Container`/`Component`), not native `C4Context` syntax.

### Step 3: Navigating the Code

Load `references/navigation.md`. Now — after the big picture — the code map earns its place, kept lean. Produce:

- **Directory map** — top ~10 directories, each with a responsibility and a why (a navigation aid, not a full tree).
- **Conventions** — naming patterns, the enforced layering rule, DI/wiring, the blessed config-access path — each cited to a real example. State useful absences.
- **Testing strategy** — where tests live and how organized (levels with example files), fixtures/mocks/testcontainers, coverage gate, common failure modes. (The runnable fast loop lives in Step 4.)

### Step 4: Running It Locally

Load `references/setup-checklist.md`. Produce a repo-specific, command-by-command checklist:

- Required runtimes, dependency install, env vars, database setup, migrations/seeds.
- Run commands: server / worker / UI. For cloud-native repos, substitute the real loop (local emulation or deploy to a safe sandbox stage).
- A smoke test of one key flow.
- The **fast pre-PR confidence loop** (lint → typecheck → unit → local-integration), cited.

### Step 5: Deploying It

Load `references/deploy.md`. Map how the code ships and where it runs (describe, don't redesign). Produce:

- **Deployment model** (functions / containers / PaaS / package), cited to the manifest + tool/version.
- **Function/service inventory & triggers** *(cloud-native)* — one row per deployed unit, lining up with the Step 2 event flows; flag disposable/one-off units.
- **Managed-service dependency graph** *(cloud-native)* — owned vs external, flagging external reads/writes as couplings.
- **Environments/stages** and the **configuration & secrets table** (single source of truth).
- **CI/CD** — pipelines (trigger → steps → deploy target), branch→environment mapping, deploy commands and who may deploy where, CI secrets mechanism (reference the config table), quality gates. If no CI config exists, say so in one line.
- **Observability** *(cloud-native)* — where logs/traces/metrics/alarms live.

For a plain non-cloud repo this section is short: how the artifact ships + the CI/CD path.

### Step 6: Security Posture

Load `references/security-posture.md`. Map the repo's trust boundaries (describe, don't audit). Produce:

- Authentication and authorization at the entry points.
- Secrets & configuration sources (confirm none are committed; reference the Step 5 config table).
- Input validation at boundaries and query style (injection surface).
- Transport/data protection, dependency & supply-chain controls.
- For cloud repos: execution-role IAM scope and network exposure (cross-reference Step 5).

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| What the repo is and why it exists | `references/purpose-context.md` | Step 1 |
| C4 diagrams (L1/L2/optional L3), event-reaction flows, pattern detection | `references/big-picture.md` | Step 2 |
| Conventions, lean directory map, testing organization | `references/navigation.md` | Step 3 |
| Local setup checklist + fast pre-PR loop | `references/setup-checklist.md` | Step 4 |
| Deployment model, triggers, managed-service graph, envs/secrets, CI/CD, observability | `references/deploy.md` | Step 5 |
| Security posture: auth, secrets, validation, deps, IAM | `references/security-posture.md` | Step 6 |

## Output Structure

Open with a **concise, skimmable TL;DR** and a **table of contents**, then deliver each section in narrative order. Number the sections you actually produce so they stay sequential; the cloud subsections inside Deploying It appear only for cloud-native repos.

### TL;DR — skimmable, bullets, high-impact only
Not a wall of prose, and not a detail dump. A reader should grasp the repo in ~10 seconds. Bullet form. Lead with **why the project exists** in one line, then only the few facts a new dev acts on. Push detail into the sections — the TL;DR points, it does not explain.

```
## TL;DR
- **Why:** <the problem it solves, one line>
- **What / Pattern:** <kind of thing> · <primary pattern in 2-3 words>
- **Stack:** <the 4-6 key techs, comma-separated>
- **Run it:** <the one command path>
- **Fast PR check:** <lint + unit, no deploy>
- **Gotchas:** <the 1-3 surprises that bite newcomers>
```

Keep each bullet to one line. Omit a bullet if it doesn't apply. Don't restate a whole section — each bullet is a pointer.

### Table of contents
A bulleted list, **one sub-level only** — H2 sections as bullets, their H3 subsections as sub-bullets. Link to anchors. Omit sections/subsections not produced.

### Body
```
# Onboarding: <repo name>

## TL;DR              <bullets, as above>
## Contents           <bulleted TOC, one sub-level>

## 1. Purpose / Context
   <what it is, why it exists, who uses it, scope boundary — plain language, NO diagrams>

## 2. Big Picture
   <pattern (one line) → C4 L1 System Context → C4 L2 Container (+ responsibility table)
    → optional C4 L3 Component → event-reaction flows (one diagram per trigger type).
    DIAGRAMS FIRST in every subsection.>

## 3. Navigating the Code
   <lean directory map (top ~10, each with a why) → conventions → testing strategy>

## 4. Running It Locally
   <ordered setup commands → smoke test → fast pre-PR loop>

## 5. Deploying It
   <deployment model → function/trigger inventory (cloud) → managed-service graph (cloud)
    → environments → configuration & secrets table → CI/CD (pipelines, branch→env, deploy) →
    observability (cloud). Non-cloud repos: how it ships + CI/CD only.>

## 6. Security Posture
   <auth, authz, secrets, input validation, transport, dependencies, IAM>
```

Lead with **why the repo exists** before anything structural, and lead every Big-Picture subsection with its diagram before any prose. Deliver to chat or to the Markdown file chosen in Step 0; a saved file goes to a scratch location outside the repo, never into it.

### Style rules (every section)

- **Diagram-first.** Where a section has a diagram (all of Big Picture, the managed-service graph, event flows), lead with the diagram, then explain in short bullets. The one exception is Big Picture's opening one-sentence pattern label, which precedes the L1 diagram to frame it. A table never carries the explanation alone — tables are compact reference, not narrative.
- **Big picture before code detail.** Purpose and C4 diagrams come before the directory map. Never open the document, or the architecture material, with a dense directory/code table.
- **C4 rendering.** Use Mermaid `flowchart` styled as C4 (nodes labelled `Person`/`System`/`External`/`Container`/`Component`), not native `C4Context` syntax — it renders reliably everywhere.
- **Event flows explicit.** Every async trigger (stream/queue/schedule/object-event) gets its own captioned flow diagram; never leave "X triggers Y" buried in prose.
- **Readable, not cramped.** Let the output breathe. Use short paragraphs (2 to 4 lines) for anything narrative, and separate ideas with blank lines rather than packing everything into one dense bullet list. Bullets are for genuinely list-like content (a directory map, trigger notes); explanation that flows reads better as a short paragraph. A blank line between subsections and between a diagram and its explanation is expected, not optional.
- **No em-dash in the output.** Never use the `—` character. Use a newline to break two ideas apart, or a comma, colon, parentheses, or period. This is a hard rule for the generated onboarding, even where a dash would be shorter.
- **Every reference table has a why column.** Responsibility, Usage, or Purpose all count. A what/where table without the why is incomplete onboarding.
- **Markdown safety.** No raw `<...>` tokens outside code spans — renderers swallow them as HTML; wrap them in backticks. In Mermaid labels use `<br/>` for line breaks, never `\n`, and use `{}` or plain words instead of angle brackets.

## Related Skills

- **spec-extract** — Reverse-engineer business rules and domain logic from code.
- **spec-create** — Plan a new feature (requirements, design, tasks). Onboarding output is useful input here.
- **spec-grill** — Pressure-test a plan before implementation.

All three ship in this plugin (`claudio-spec`). If the separate **cartog** plugin is installed, its `cartog_map`/`cartog_search` tools speed up the structural sweep, but they are an optional accelerator, not a dependency of this skill.
