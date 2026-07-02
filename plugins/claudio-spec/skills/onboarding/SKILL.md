---
name: onboarding
description: Onboard a developer to an unfamiliar repository. Produces an architecture map (architecture pattern, top-level structure, runtime boundaries, dependency diagram), a testing strategy summary, a repo-specific local setup checklist, and a security posture map, with every claim cited to exact files. For cloud-native repos (serverless, IaC, containers) it adds a cloud-architecture section covering deployment model, function triggers, managed-service dependencies, environments, secrets, and observability; when CI/CD config exists it adds a CI/CD section (pipelines, branch→env, deploy commands). Use for "onboard me", "help me understand this repo", "give me an overview", "explain this codebase's architecture", "what architecture pattern does this use", "how is this repo structured", "how do I run this locally", "what's the testing strategy here", "how is this service deployed", "how does CI/CD work here", or "what's the security posture". Read-only, never edits files. NOT for extracting business rules or domain logic (use spec-extract).
---

# Onboarding

Get a developer productive in an unfamiliar repository. Produce four core deliverables — architecture map, testing strategy, local setup, security posture — plus two conditional sections: cloud-architecture (when the repo is cloud-native) and CI/CD (when pipelines exist). Each is grounded in evidence from the repo's own files.

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

- **Read-only.** Never edit, create, or delete repo files. Onboarding output goes to chat (or a scratch file if the user asks), never into the repo. If the request bundles an edit ("onboard me **and** fix the README / add a CONTRIBUTING / update X"), do the onboarding and **decline the edit** — don't perform it, and don't offer to or ask for confirmation to. Point the user to run that as a separate, non-onboarding task. The bundled ask is exactly the "user pressure" this rule overrides.
- **Cite every claim.** Each architectural statement names the exact file(s) that justify it (path + brief evidence). No uncited assertions, no guessing.
- **Docs before code.** Read `README`, `AGENTS.md`, `CLAUDE.md`, `docs/`, `CONTRIBUTING`, and ADRs first; then confirm against code. Never describe intended behavior from docs alone without checking the code matches.
- **Only justifiable steps.** Setup commands must trace to a real file (README, Makefile, package/build manifest, scripts, devcontainer config, or IaC manifest). Never invent commands.

## Workflow

Produce the deliverables in order. Each is detailed in its reference file — load the reference before writing that deliverable. The four core steps always run; Step 1b runs only for cloud-native repos and Step 5 only when CI/CD config exists.

### Step 0: Orient

- Identify the repo root and whether it's a monorepo (multiple workspaces) or single project.
- List the docs available (`README`, `AGENTS.md`, `CLAUDE.md`, `docs/`, `CONTRIBUTING`, ADRs) and read them first.
- Detect the **deployment model**: is there infrastructure-as-code (`serverless.*`, `template.yaml`, `cdk.json`, `*.tf`, `pulumi.*`, `*.bicep`), container/orchestration manifests (`Dockerfile` + `k8s/`/`helm/`), or heavy cloud-SDK use? If so the repo is cloud-native and gets Step 1b; if not, the four core deliverables suffice.
- Prefer code-navigation tooling over blind grep for the structural sweep (see `references/architecture-map.md` for the navigation method).

### Execution mode: sequential by default, parallel on request

Step 0 always runs first in the main conversation — its detection decides which sections exist. After it, either continue sequentially (the default) or fan out **three parallel read-only research sweeps** and synthesize:

1. **Structure** — Steps 1 + 1b (architecture map, cloud architecture)
2. **Dev loop** — Steps 2 + 3 (testing strategy, local setup)
3. **Trust & delivery** — Steps 4 + 5 (security posture, CI/CD)

- **Ask before fanning out** — never spawn parallel agents without the user's confirmation. Offer it when the repo is large enough that sequential reading would be slow; otherwise stay sequential.
- Each sweep loads its reference file(s) and returns **cited findings only**, not prose sections.
- Synthesize in the main conversation: assemble the output structure, resolve cross-references (security ↔ cloud IAM, CI/CD ↔ configuration table), dedupe citations, keep numbering sequential.

### Step 1: Architecture Map

Load `references/architecture-map.md`. Produce (in this order — lead with what the repo *is* before classifying it):

- What it is + top-level architecture: one-paragraph purpose, then each app/service/library and what it does.
- Architecture pattern: match the repo against the catalog (Monolithic / Modular Monolith / Microservices / Event-Driven / CQRS / Event Sourcing / Hexagonal / Clean / API Gateway), naming the pattern it actually uses from structural evidence — keep deployment shape separate from internal style.
- Tech decisions observed: the stack choices already made (database, caching, message queue, authentication, frontend, cloud provider, API style) and where each shows. Describe, don't recommend.
- Directory map: top ~10 directories with responsibilities.
- Runtime boundaries: API layer, domain layer, persistence, async jobs, config.
- A Mermaid dependency diagram using the repo's actual module/package boundaries.
- For monorepos: the workspace/tooling setup.

### Step 1b: Cloud Architecture (cloud-native repos only)

If Step 0 detected IaC, container orchestration, or heavy cloud-SDK use, load `references/cloud-architecture.md`. For these repos the internal-module diagram covers only the application code; this step captures the rest of the system. It renders as a **peer top-level section** in the output (a sibling of Architecture Map, numbered sequentially — not nested under it). Produce:

- Deployment model (functions / containers / PaaS), cited to the IaC manifest.
- Function/service inventory with what triggers each (HTTP / queue / stream / schedule / object event).
- A managed-service dependency graph (owned vs external), flagging external reads/writes as couplings.
- Environments/stages, configuration & secrets sources, and where logs/traces/alarms live.

Skip this step entirely for repos that run as a plain local process.

### Step 2: Testing Strategy

Load `references/testing-strategy.md`. Produce:

- Where tests live and how they're organized (unit/integration/functional/e2e).
- The fastest local confidence loop: commands to run before a PR.
- How fixtures/mocks/testcontainers are handled.
- Common failure modes visible from config/docs.
- If no strategy exists: propose one following the testing pyramid (many unit, fewer e2e).

### Step 3: Local Setup Checklist

Load `references/setup-checklist.md`. Produce a repo-specific, command-by-command checklist:

- Required runtimes, dependency install, env vars, database setup, migrations/seeds.
- Run commands: server / worker / UI.
- Ends with a smoke test of one key flow.

### Step 4: Security Posture

Load `references/security-posture.md`. Map the repo's trust boundaries (describe, don't audit). Produce:

- Authentication and authorization at the entry points.
- Secrets & configuration sources (confirm none are committed).
- Input validation at boundaries and query style (injection surface).
- Transport/data protection, dependency & supply-chain controls.
- For cloud repos: execution-role IAM scope and network exposure (cross-reference Step 1b).

### Step 5: CI/CD

Load `references/cicd-pipeline.md`. Map how code reaches each environment (describe, don't redesign). Produce:

- Pipelines: one row per workflow — trigger → steps → deploy target.
- Branch → environment mapping and the promotion path.
- Deploy commands and who may deploy where.
- CI secrets/env mechanism — reference the configuration table rather than duplicating it.

Skip (with a one-line note) if the repo has no CI/CD config.

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| Architecture map format, diagram conventions, monorepo handling | `references/architecture-map.md` | Step 1 |
| Deployment model, triggers, managed-service deps, envs, secrets, observability | `references/cloud-architecture.md` | Step 1b (cloud-native only) |
| Testing strategy structure and pyramid fallback | `references/testing-strategy.md` | Step 2 |
| Local setup checklist rules and template | `references/setup-checklist.md` | Step 3 |
| Security posture: auth, secrets, validation, deps, IAM | `references/security-posture.md` | Step 4 |
| CI/CD pipelines, branch→env, deploy commands | `references/cicd-pipeline.md` | Step 5 |

## Output Structure

Open with a **concise TL;DR** and a **table of contents**, then deliver each section. Cloud Architecture is a peer section (number it sequentially, not "1b"); include it only for cloud-native repos, and CI/CD only if pipelines exist. Number the sections you actually produce so they stay sequential.

### TL;DR — keep it skimmable
Not a wall of prose. A reader should grasp the repo in ~10 seconds. One line each for **What / Pattern / Stack**, then a small table of the things a new dev acts on:

```
## TL;DR
**What:** <one line>   **Pattern:** <one line>   **Stack:** <key techs>

| | |
|---|---|
| Run it       | <the one command path> |
| Fast PR check| <lint + unit, no deploy> |
| Where data lives | <store + how data flows> |
| Auth         | <mechanism> |
| Gotchas      | <the 1–3 surprises that bite newcomers> |
```
Each TL;DR row is a pointer into a section below — don't restate the whole section.

### Table of contents
A bulleted list, **one sub-level only** — H2 sections as bullets, their H3 subsections as sub-bullets. Link to anchors. Omit sections not produced.

### Body
```
# Onboarding: <repo name>

## TL;DR              <as above>
## Contents           <bulleted TOC, one sub-level>

## 1. Architecture Map
   <what it is + overview FIRST, then architecture pattern, tech decisions observed, directory map, runtime boundaries, Mermaid diagram>

## 2. Cloud Architecture          (cloud-native repos only; renumber/omit otherwise)
   <deployment model, runtime-flow diagram + numbered walkthrough (pipelines), triggers, managed-service dependency graph, envs, configuration & secrets table, observability>

## 3. Testing Strategy
   <where tests live, fast loop, fixtures, failure modes>

## 4. Local Setup Checklist
   <ordered commands, ending with a smoke test>

## 5. Security Posture
   <auth, authz, secrets, input validation, transport, dependencies, IAM>

## 6. CI/CD                        (omit if no CI/CD config)
   <pipelines table, branch→env mapping, deploy commands, CI secrets — references the config table>
```

Lead with what the repo *is* before classifying it. If the user asks to save it, write to a scratch location they name, never into the repo.

### Style rules (every section)

- **Diagram-first.** Where a section has a diagram (architecture, cloud, flows), lead with the diagram, then explain in short bullets. A table never carries the explanation alone — tables are compact reference, not narrative.
- **No dense paragraphs.** One idea per bullet; prose paragraphs max 2–3 lines, only for narrative that genuinely flows.
- **Every reference table has a why column.** Responsibility / Usage / Purpose all count; a what/where table without the why is incomplete onboarding.
- **Markdown safety.** No raw `<...>` tokens outside code spans — renderers swallow them as HTML; wrap them in backticks. In Mermaid labels use `<br/>` for line breaks, never `\n`, and use `{}` or plain words instead of angle brackets.

## Related Skills

- **spec-extract** — Reverse-engineer business rules and domain logic from code.
- **spec-create** — Plan a new feature (requirements, design, tasks). Onboarding output is useful input here.
- **spec-grill** — Pressure-test a plan before implementation.

All three ship in this plugin (`claudio-spec`). If the separate **cartog** plugin is installed, its `cartog_map`/`cartog_search` tools speed up the structural sweep, but they are an optional accelerator, not a dependency of this skill.
