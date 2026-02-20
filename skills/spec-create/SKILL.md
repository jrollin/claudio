---
name: spec-create
description: Create a new feature specification following a phased workflow. Use when starting a new feature that needs requirements, design, and task planning. Invoke for spec-driven development, feature specification, requirements-design-tasks workflow.
---

# Spec Create

Multi-phase workflow orchestrator for feature specification. Guides through Requirements → Design → Tasks with user approval gates between each phase.

## Input

```
/spec-create <feature-name> [description]
```

- `feature-name`: required — auto-normalized to kebab-case (strip spaces, lowercase, replace non-alphanum with hyphens)
- `description`: optional — used as initial context for requirements phase

## When to Use

- Starting a new feature from scratch
- Creating structured specification documents (requirements, design, tasks)
- Planning implementation before writing code

**Not this skill:** For deep-dive requirements workshops with interviews and EARS notation, use **feature-forge** instead. spec-create is the workflow orchestrator (3 phases, 3 files in `docs/features/`). feature-forge is the deep requirements specialist (single spec in `specs/`).

## Role

You are a spec-driven development facilitator. You ensure completeness and traceability across the full specification lifecycle.

## Core Principles

- **Sequential phases**: Requirements → Design → Tasks — no skipping
- **User approval gates**: Each phase requires explicit approval before proceeding
- **Codebase-first**: Analyze existing code before starting any phase
- **Single spec**: Only create one specification at a time

## Workflow

### Phase 0: Initialization

1. Normalize feature name to kebab-case
2. Check `docs/features/<feature-name>/` for existing files
3. Handle edge cases (see Edge Cases below)
4. If `docs/features/` doesn't exist, create it silently

### Phase 1: Requirements

Create `docs/features/<feature-name>/requirements.md`.

- Analyze existing codebase for context
- Use `AskUserQuestion` to clarify ambiguities
- Write user stories in WHEN/THE format
- Include acceptance criteria per user story
- **Wait for explicit user approval** before proceeding

### Phase 2: Design

Create `docs/features/<feature-name>/design.md`.

- Architecture overview and component relationships
- Technical decisions with rationale and alternatives considered
- Implementation considerations (performance, security)
- Sequence diagrams for critical flows (Mermaid)
- **Wait for explicit user approval** before proceeding

### Phase 3: Tasks

Create `docs/features/<feature-name>/tasks.md`.

- Group tasks by implementation phase
- Reference user stories (US-1, US-2, etc.)
- Each task must specify its verification method
- Note dependencies and blockers between tasks
- Track business rules inline
- Note cross-feature impact when tasks touch shared state
- Tests must target business rules and edge cases, not just happy paths
- No flaky tests — deterministic, no timing dependencies
- **Wait for explicit user approval** before proceeding

### Phase 4: Summary

Generate a completion summary:

- List all 3 file paths created
- Show user story count from requirements
- Show task count from tasks
- Suggest `/spec-impl <feature-name>` as next step

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| Requirements format and examples | `references/requirements-template.md` | Writing requirements (Phase 1) |
| Design document structure | `references/design-template.md` | Writing design (Phase 2) |
| Task breakdown format and rules | `references/tasks-template.md` | Writing tasks (Phase 3) |
| Phase gates, approval, edge cases | `references/phase-workflow.md` | Need detailed phase guidance |

## Edge Cases

| Edge Case | Behavior |
|-----------|----------|
| Partial spec exists (e.g., requirements.md only) | Detect existing files, ask user: resume from next phase or start fresh? |
| Feature dir exists with all 3 files | Offer to update existing spec instead of creating new |
| Similar feature name detected | List similar dirs under `docs/features/`, ask if it's the same or distinct |
| Args include description | Use as initial context for requirements phase |
| User wants to skip a phase | Refuse — phases are sequential |
| `docs/features/` doesn't exist | Create it silently |
| Feature name not kebab-case | Normalize automatically |
| Session interrupted mid-phase | On resume, detect partial state from existing files and continue |

## Constraints

### MUST DO

- Load reference templates before writing each phase document
- Check if feature spec already exists before creating new files
- Get explicit approval ("yes", "approved", "looks good", "lgtm") between phases
- Analyze existing codebase before each phase
- Revise and re-ask if user provides feedback

### MUST NOT DO

- Skip phases or proceed without approval
- Create duplicate specifications for similar features
- Generate tasks without approved requirements and design
- Proceed on partial approval ("looks good except for US-3" = not approved)

## Output Structure

```
docs/features/<feature-name>/
  requirements.md   # Phase 1
  design.md         # Phase 2
  tasks.md          # Phase 3
```

## Related Skills

- **feature-forge** — Deep requirements gathering with EARS format and interview process
- **spec-impl** — Implements tasks from a completed specification
- **tdd** — Test-driven implementation of individual tasks
