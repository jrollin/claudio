---
name: event-modeling-tasks
description: Use when translating a completed event model into implementation tasks. Invoke when an event model with slices and specifications exists and needs to become a development plan, task breakdown, or spec-create compatible output.
---

# Event Model to Tasks

Translates a completed event model into implementation tasks. Each slice becomes one task with the specification as its acceptance criteria.

## Input

A completed event model document (produced by **event-modeling-spec** skill) containing:
- Named slices, each with a pattern (Command / View / Automation / Translation)
- Specifications: Given-When-Then for commands/automations, Given-Then for views
- Swim lanes with domain assignments
- Passed completeness check

If the event model is incomplete, use **event-modeling-spec** first.

## Task ID Convention

```
<TRIGRAM>-<SHORT_NAME>
```

- **Trigram:** 3 letters from the feature name (confirm with user if ambiguous)
- **Short name:** Short, readable abbreviation of the slice — prefer a single word when unambiguous, use two words hyphenated when needed

| Slice Name | Short Name | Why |
|------------|-----------|-----|
| RegisterGuest | `REGISTER` | Unambiguous single word |
| InitiateBooking | `BOOK` | "Initiate" is ceremony — "book" is the action |
| RoomAvailability | `AVAIL` | Common abbreviation |
| ConfirmBooking | `CONFIRM` | Unambiguous |
| CancelBooking | `CANCEL` | Unambiguous |
| GuestProfile | `PROFILE` | Unambiguous |
| EarnLoyaltyPoints | `EARN` | Clear in context |
| OpenLoyaltyAccount | `LOYALTY-OPEN` | Two words needed — "open" alone is ambiguous |

Infrastructure: `HTL-INFRA-EVENTS`, `HTL-INFRA-DISPATCH`

## Rules

- **One slice = one task.** Do not merge. Do not split. Merging makes it impossible to correctly sequence dependent slices, eliminates parallelism within a phase, and prevents spec-impl from marking partial work as complete.
- **Event names:** Use exactly as named in the model. Do not rename.
- **Specifications → Acceptance criteria:** Copy Given-When-Then verbatim from the event model.
- **No invented concepts:** No aggregates, entities, or schemas not in the model.
- **Infrastructure tasks** go in Phase 0, marked `[INFRA]`, kept minimal.
- **Error case verification per pattern:**
  - Commands: test precondition rejection (Given events missing → rejected)
  - Automations: test idempotency (run robot twice → second run does nothing)
  - Views: test empty/missing data response (no events → empty result or 404)

## Deriving Dependencies

Trace the Given clause of each slice:

- **Command** depends on: any Command whose events appear in its Given clause
- **View** depends on: all Commands producing the events it reads
- **Automation** depends on: the Commands producing events for its todo-list view

## Phasing

Group tasks by dependency depth:
- Phase 1: slices with no dependencies
- Phase 2: slices depending only on Phase 1
- Phase N: slices depending on Phase N-1

Tasks within the same phase can be implemented in parallel. Order tasks within a phase by: Commands first, then Views, then Automations.

## Process

1. **Assign trigram** — Confirm with user
2. **List slices** — ID, pattern, swim lane
3. **Build dependency graph** — Trace Given clauses
4. **Phase by depth**
5. **Write task file** — Using `references/output-template.md` (includes developer preamble)
6. **Add [INFRA] tasks** in Phase 0 if needed
7. **Generate Mermaid dependency graph**

## Output Format

The task file has two levels per task:
- **Table row** — for spec-impl scanning: task ID, status, one-line verification summary, blocked-by
- **Detailed section** — for developer/agent: Build instructions, verbatim acceptance criteria, full verification list

The `Blocked by:` in the Notes column is the **source of truth** for dependencies. The Mermaid graph is generated from it.

See `references/output-template.md` for the full template with preamble.

## Reference

| Reference | Load When |
|-----------|-----------|
| `references/output-template.md` | Generating the task file — template with developer preamble, table + detail format |
| `references/tasks-example.md` | Full Hotel Booking example — 18 tasks across 6 phases with Mermaid dependency graph |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Merging slices into one task | One slice = one task. Merging breaks sequencing, parallelism, and atomic completion |
| Renaming events from the model | Use event names verbatim — the model IS the contract |
| Introducing aggregates not in the model | Event Modeling doesn't prescribe aggregates |
| Dropping specifications from tasks | Copy Given-When-Then exactly as acceptance criteria |
| Applying Command error tests to Views | Commands: test rejection. Automations: test idempotency. Views: test empty response |
| Business logic in the automation robot | Robot just reads todo and calls command. Logic lives in handler |
| Preamble missing from task file | Always include "How to Read These Tasks" for the developer |
| Inconsistent task ordering within phases | Commands first, then Views, then Automations |
