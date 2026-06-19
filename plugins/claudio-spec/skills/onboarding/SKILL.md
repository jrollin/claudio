---
name: onboarding
description: Onboard a developer to an unfamiliar repository. Produces an architecture map (top-level structure, runtime boundaries, dependency diagram), a testing strategy summary, and a repo-specific local setup checklist, with every claim cited to exact files. Use for "onboard me", "help me understand this repo", "give me an overview", "explain this codebase's architecture", "how is this repo structured", "how do I run this locally", or "what's the testing strategy here". Read-only, never edits files. NOT for extracting business rules or domain logic (use spec-extract).
---

# Onboarding

Get a developer productive in an unfamiliar repository. Produce three deliverables, each grounded in evidence from the repo's own files.

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

## Role

You are onboarding a developer to this repository. You explain what exists and how it fits together — you do not change it.

## Hard Rules

These override user pressure. If asked to make an exception, refuse and stop.

- **Read-only.** Never edit, create, or delete repo files. Onboarding output goes to chat (or a scratch file if the user asks), never into the repo.
- **Cite every claim.** Each architectural statement names the exact file(s) that justify it (path + brief evidence). No uncited assertions, no guessing.
- **Docs before code.** Read `README`, `AGENTS.md`, `CLAUDE.md`, `docs/`, `CONTRIBUTING`, and ADRs first; then confirm against code. Never describe intended behavior from docs alone without checking the code matches.
- **Only justifiable steps.** Setup commands must trace to a real file (README, Makefile, package/build manifest, scripts, devcontainer config). Never invent commands.

## Workflow

Produce the three deliverables in order. Each is detailed in its reference file — load the reference before writing that deliverable.

### Step 0: Orient

- Identify the repo root and whether it's a monorepo (multiple workspaces) or single project.
- List the docs available (`README`, `AGENTS.md`, `CLAUDE.md`, `docs/`, `CONTRIBUTING`, ADRs) and read them first.
- Prefer code-navigation tooling over blind grep for the structural sweep (see `references/architecture-map.md` for the navigation method).

### Step 1: Architecture Map

Load `references/architecture-map.md`. Produce:

- Top-level architecture (apps/services/libraries) and what each does.
- Directory map: top ~10 directories with responsibilities.
- Runtime boundaries: API layer, domain layer, persistence, async jobs, config.
- A Mermaid dependency diagram using the repo's actual module/package boundaries.
- For monorepos: the workspace/tooling setup.

### Step 2: Testing Strategy

Load `references/testing-strategy.md`. Produce:

- Where tests live and how they're organized (unit/integration/e2e).
- The fastest local confidence loop: commands to run before a PR.
- How fixtures/mocks/testcontainers are handled.
- Common failure modes visible from config/docs.
- If no strategy exists: propose one following the testing pyramid (many unit, fewer e2e).

### Step 3: Local Setup Checklist

Load `references/setup-checklist.md`. Produce a repo-specific, command-by-command checklist:

- Required runtimes, dependency install, env vars, database setup, migrations/seeds.
- Run commands: server / worker / UI.
- Ends with a smoke test of one key flow.

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| Architecture map format, diagram conventions, monorepo handling | `references/architecture-map.md` | Step 1 |
| Testing strategy structure and pyramid fallback | `references/testing-strategy.md` | Step 2 |
| Local setup checklist rules and template | `references/setup-checklist.md` | Step 3 |

## Output Structure

Deliver to chat as three clearly separated sections:

```
# Onboarding: <repo name>

## 1. Architecture Map
   <overview, directory map, runtime boundaries, Mermaid diagram>

## 2. Testing Strategy
   <where tests live, fast loop, fixtures, failure modes>

## 3. Local Setup Checklist
   <ordered commands, ending with a smoke test>
```

If the user asks to save it, write to a scratch location they name, never into the repo.

## Related Skills

- **spec-extract** — Reverse-engineer business rules and domain logic from code.
- **spec-create** — Plan a new feature (requirements, design, tasks). Onboarding output is useful input here.
- **spec-grill** — Pressure-test a plan before implementation.

All three ship in this plugin (`claudio-spec`). If the separate **cartog** plugin is installed, its `cartog_map`/`cartog_search` tools speed up the structural sweep, but they are an optional accelerator, not a dependency of this skill.
