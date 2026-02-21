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

**Not this skill:** For deep-dive requirements workshops with interviews, use **feature-forge** instead. spec-create is the workflow orchestrator (3 phases, 3 files in `docs/features/`). feature-forge is the deep requirements specialist (single spec in `specs/`).

## Role

You are a spec-driven development facilitator. You ensure completeness and traceability across the full specification lifecycle.

## Core Principles

- **Sequential phases**: Requirements → Design → Tasks — no skipping
- **User approval gates**: Each phase requires explicit approval before proceeding
- **Codebase-first**: Analyze existing code before starting any phase
- **Single spec**: Only create one specification at a time

## Cross-Reference Scheme

All three documents use a shared ID system for traceability:

| ID | Document | Example |
|----|----------|---------|
| `US-X` | requirements.md | US-1, US-2 |
| `AC-X.Y` | requirements.md | AC-1.1, AC-2.3 (story X, criterion Y) |
| `BR-X` | requirements.md | BR-1, BR-2 |
| `NFR-X` | requirements.md | NFR-1, NFR-2 |
| `TD-X` | design.md | TD-1, TD-2 |
| `T-X` | tasks.md | T-1, T-2 |

Traceability: each `T-X` references `US-X` (stories it implements), `TD-X` (decisions it follows), and `BR-X` (rules it enforces). `NFR-X` IDs are not referenced in tasks — they are cross-cutting constraints validated at integration/review time, not per-task.

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
- Write user stories in WHEN/THE format: WHEN describes the trigger, THE describes the system response (do not use "SYSTEM SHALL")
- Include acceptance criteria per user story with `AC-X.Y` IDs
- Extract business rules as `BR-X` in a dedicated section
- **Wait for explicit user approval** before proceeding

### Phase 2: Design

Create `docs/features/<feature-name>/design.md`.

- Architecture overview and component relationships
- Usage flow: Mermaid flowchart showing user journey through the feature
- Component diagram: Mermaid diagram showing system structure and relationships
- Technical decisions (`TD-X`) with rationale and alternatives considered
- Implementation considerations (performance, security)
- Sequence diagrams for critical multi-component flows (Mermaid)
- File Inventory: table of files to create/modify with purpose
- **Wait for explicit user approval** before proceeding

### Phase 3: Tasks

Create `docs/features/<feature-name>/tasks.md`.

- Use `T-X` IDs for every task (heading-based entries, not tables)
- Group tasks by implementation phase
- Each task references `US-X` (stories) and `TD-X` (decisions) in its `Refs` field, and `BR-X` (rules) in a separate `Rules` field
- Each task lists files to create/modify (must match File Inventory)
- Each task specifies a runnable verification command
- Note dependencies between tasks using `T-X` IDs
- Note cross-feature impact when tasks touch shared state
- Tests must target business rules and edge cases, not just happy paths
- No flaky tests — deterministic, no timing dependencies
- **Wait for explicit user approval** before proceeding

### Phase 4: Summary

Generate a completion summary (cross-reference consistency is validated by the Phase 4 gate before entering this phase):

- List all 3 file paths created
- Show user story count, business rule count, and task count
- Suggest `/spec-impl <feature-name>` as next step

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| Requirements format and examples | `references/requirements-template.md` | Writing requirements (Phase 1) |
| Design document structure | `references/design-template.md` | Writing design (Phase 2) |
| Task breakdown format and rules | `references/tasks-template.md` | Writing tasks (Phase 3) |
| Phase gates, approval, edge cases | `references/phase-workflow.md` | Need detailed phase guidance |
| Requirements example | `references/example-requirements.md` | Writing requirements (Phase 1) |
| Design example | `references/example-design.md` | Writing design (Phase 2) |
| Tasks example | `references/example-tasks.md` | Writing tasks (Phase 3) |
| Tasks do & don't | `references/do-dont-tasks.md` | Writing tasks (Phase 3) |

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

Each file follows a **fixed structure** defined in the reference templates. The structure is the contract — examples in templates illustrate it but are not the structure itself. When generating output, follow the structure skeleton; do not copy example content.

### requirements.md

Sections (all required):

```
# <Feature Name> — Requirements
## Overview
## User Stories          ← US-X with WHEN/THE + AC-X.Y criteria
## Business Rules        ← BR-X extracted rules
## Non-Functional Requirements
## Out of Scope
## Open Questions
```

Example snippet:

```markdown
### US-1 User login

WHEN a user submits valid email and password to the login endpoint
THE system creates a session and returns an auth token

**Acceptance Criteria:**
- [ ] AC-1.1: POST /auth/login with valid credentials returns 200 + token
- [ ] AC-1.2: Token contains user ID and expiration timestamp

## Business Rules

- **BR-1**: Session expires after 24 hours of inactivity
- **BR-2**: Account locks after 5 consecutive failed login attempts
```

### design.md

Sections (all required):

```
# <Feature Name> — Design
## Architecture Overview
## Usage Flow            ← Mermaid flowchart
## Component Diagram     ← Mermaid graph
## Technical Decisions   ← TD-X with alternatives + rationale
## Implementation Considerations
## Sequence Diagrams     ← Mermaid (multi-component flows only)
## File Inventory        ← table: File | Action | Purpose
```

Example snippet:

````markdown
### TD-1: Session storage

**Choice**: Database-backed sessions
**Alternatives considered**:
- JWT (stateless) — rejected: can't revoke tokens without a blocklist

**Rationale**: DB sessions are simple, revocable, and use existing infrastructure.

## File Inventory

| File | Action | Purpose |
|------|--------|---------|
| `src/auth/service.ts` | new | AuthService: login, logout, lockout |
| `src/routes/auth.ts` | new | POST /auth/login, POST /auth/logout |
````

### tasks.md

Sections (all required):

```
# <Feature Name> — Tasks
## Phase N: <Title>      ← group by implementation phase
### T-X: <Task title>    ← heading-based entries, not tables
  - Refs                 ← US-X, TD-X
  - Files                ← subset of File Inventory
  - Verify               ← runnable command
  - Blocked by           ← T-X (omit if none)
  - Rules                ← BR-X (omit if none)
  - Status
## Related Features
```

Example snippet:

```markdown
### T-1: Create AuthService with login/logout
- **Refs**: US-1, US-2, TD-2
- **Files**: `src/auth/service.ts` (new), `src/auth/types.ts` (new)
- **Verify**: `npm test -- --grep "AuthService"`
- **Rules**: BR-1
- **Status**: Not Started
```

For full examples, see `references/example-requirements.md`, `references/example-design.md`, and `references/example-tasks.md` (same feature, end-to-end traceable).

## Related Skills

- **feature-forge** — Deep requirements gathering with EARS format and interview process
- **spec-impl** — Implements tasks from a completed specification
- **tdd** — Test-driven implementation of individual tasks
