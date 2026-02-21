---
name: spec-impl
description: Task-by-task implementer that reads a completed spec and executes each task atomically. Use when a feature spec exists and you're ready to implement. Invoke for spec implementation, task execution, spec-driven development.
---

# Spec Implement

Task-by-task implementer that reads a completed specification and executes each task atomically. Reads `docs/features/<feature-name>/` files produced by `/spec-create`.

## Input

```
/spec-impl <feature-name>
```

- `feature-name`: required — must match an existing directory under `docs/features/`

## When to Use

- A feature spec exists (requirements, design, tasks) and you're ready to implement
- Resuming implementation after a session interruption

**Not this skill:** To create or update a spec, use **spec-create**. To implement a single task test-first, use **tdd**.

## Role

You are a spec-driven implementer. You execute tasks from a completed specification one-by-one, ensuring traceability and test coverage.

## Workflow

### 1. Initialize

1. Verify `docs/features/<feature-name>/` exists
2. Read all 3 spec files for full context:
   - `docs/features/<feature-name>/requirements.md`
   - `docs/features/<feature-name>/design.md`
   - `docs/features/<feature-name>/tasks.md`
3. Identify the project's ecosystem and test runner from project files (see `references/verify-by-language.md` for the detection table)
4. Handle edge cases (see Edge Cases below)

### 2. Pick Next Task

Scan `tasks.md` for the next task to execute:

1. Read all `### T-X` headings
2. For each, read its `**Status**:` and `**Blocked by**:` fields (match by `**Label**:` prefix, not line position)
3. A task is **unblocked** when it has no `Blocked by` field, or all tasks listed in `Blocked by` have `**Status**: Complete`
4. Select the first unblocked task (by document order) with status `Not Started` or `In Progress` — document order provides determinism; `Blocked by` fields determine what is *eligible*, document order determines which eligible task is picked
5. If resuming a session, reconstruct state from `tasks.md` — never rely on chat history

### 3. Restate Before Coding

Before touching any code, restate:
- **Goal**: what this task achieves (from task title + Refs)
- **Key files**: files to create or modify (from `Files` field)
- **Rules**: business rules this task enforces (from `Rules` field, if any)
- **Verify**: the exact command that will prove completion

Set `**Status**: In Progress` in `tasks.md`.

### 4. Design Sufficiency Check

Check whether `design.md` provides enough detail for this task. This is required when:
- The task references a `TD-X` not yet validated by a previous task, or
- The task creates files in a directory not yet touched by any completed task

Skip if a previous task already validated the same `TD-X` references and directory.

If the design is ambiguous, incomplete, or needs updating:
- **Stop immediately** — do not guess or improvise
- Inform the user what is missing or unclear
- Ask the user to update the design before continuing
- Do not resume implementation until the design gap is resolved

### 5. Implement

- Write the code following design decisions from `design.md`
- When the `Verify` command is a test runner, follow the tdd skill's red-green-refactor cycle: write the failing test first, then implement until it passes
- When the `Verify` command is NOT a test runner (e.g., build, lint, type check, migration), implement the code directly and proceed to validation — TDD does not apply
- Test files implied by the `Verify` command are always in scope, even if not explicitly listed in the task's `Files` field — the `Files` field is guidance for what to touch, not an exhaustive allowlist
- If implementation requires touching a file not in the task's `Files` field but listed in `design.md`'s File Inventory (e.g., adding an import to an index file), proceed — File Inventory is the broader source of truth. If the file is not in the File Inventory at all, inform the user before modifying it
- If implementation requires a new dependency referenced in `design.md` (e.g., a library choice in a `TD-X`), install it as part of the task. If the dependency is NOT mentioned in `design.md`, treat it as a design gap — stop and ask the user before installing

### 6. Validate

Run the exact `Verify` command from the task. Do not substitute a different command.

- **Exit code 0** → verification passed, proceed to step 7
- **Exit code non-zero** → verification failed:
  1. Read the error output, diagnose the failure
  2. Distinguish between a **code failure** (test assertion fails, logic bug) and a **command failure** (file not found, test runner not installed, grep pattern matches nothing, syntax error in the command itself)
  3. **Code failure**: fix the code (not the test, unless the test itself is wrong), re-run the same `Verify` command
  4. **Command failure**: the Verify command itself is likely wrong (spec-create writes these before code exists — they are predictions). Inform the user that the command appears incorrect, explain what's wrong, and suggest a corrected command. Do not silently update the Verify field — get user confirmation first, then update `tasks.md`
  5. Repeat until exit code 0 or you're stuck — if stuck, inform the user with the error output and ask for guidance

A task stays `In Progress` until verification passes. Never mark Complete on a failing verify.

### 7. Update tasks.md

- Set `**Status**: Complete`
- Append a `**Result**:` field — state what was implemented and the test outcome in one line (e.g., "AuthService with login/logout — 6 passing tests" or "DB migration applied — schema test passing")
- Inform the user that the task is ready for review and commit

You may batch up to 3 consecutive tasks that share the same Phase heading before pausing for user review. Always pause after tasks that introduce new architectural patterns or touch shared state.

### 8. Repeat

Go back to step 2. Pick the next unblocked task.

### 9. Completion

When all tasks are done:
- Summarize what was implemented
- List any issues encountered and how they were resolved

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| Implementation do & don't | `references/do-dont-impl.md` | Executing tasks — need concrete good/bad examples |
| Verify commands by language | `references/verify-by-language.md` | Writing or running verify commands — need language-specific patterns |

## Edge Cases

| Edge Case | Behavior |
|-----------|----------|
| `docs/features/<name>/` doesn't exist | List existing feature dirs under `docs/features/`, suggest closest match. If none exist: "No specs found. Run `/spec-create <name>` first." |
| `tasks.md` missing but requirements/design exist | Error: "Spec incomplete — tasks.md missing. Complete spec with `/spec-create <name>`." |
| Design insufficient for current task | Stop implementation. Inform user what is missing. Ask user to update design via plan mode before continuing. |
| All tasks already Complete | Inform user, ask if they want to add new tasks or review |
| New work discovered during implementation | Ask user to confirm, then add to `tasks.md` — never work on unlisted tasks |
| Task blocked by unresolved dependency | Skip to next unblocked task, inform user |
| Verify command is wrong | Inform user what's wrong, suggest correction, update `tasks.md` after user confirms |
| Task needs unlisted dependency | If dependency is in `design.md`, install it. If not, treat as design gap — ask user |
| Task needs file not in its Files field | If file is in File Inventory, proceed. If not in File Inventory, inform user |
| Session interrupted mid-task | On resume, read `tasks.md` to find in-progress task, continue from there |
| Multiple tasks `In Progress` on resume | Pick the first by document order. Complete it before moving to the next `In Progress` task |

## Test Quality

### Test Types

| Type | Scope | When to Use | Characteristics |
|------|-------|-------------|-----------------|
| **Unit** | Single function/class in isolation | Default for service logic, utilities, pure functions | Mock all dependencies (DB, APIs, other services). Fast, deterministic. |
| **Integration** | Multiple components working together | When a task wires components (routes → service → DB) | Use real dependencies where practical (test DB, in-memory stores). Verify contracts between layers. |
| **E2E** | Full user flow through the system | Final tasks that validate complete features | Run the actual application. Test from the user's entry point (HTTP request, CLI command, UI action). Slower, use sparingly. |

### Choosing the Right Type

- Task creates a service/utility with mocked deps → **unit**
- Task wires components together (routes → service → DB) → **integration**
- Task validates a complete user-facing flow → **e2e**
- Migration + schema assertion → **integration**

For language-specific verify command patterns, see `references/verify-by-language.md`.

### Quality Rules

- Tests must cover business rules and edge cases, not just the happy path
- No flaky tests: deterministic, no timing dependencies, no external service calls without mocks
- Unit tests mock dependencies — if your test hits a real database, it's integration
- Integration tests verify component boundaries — if everything is mocked, it's a unit test
- E2E tests validate what the user sees — don't test internal implementation details at this level

## Constraints

### MUST DO

- Read all 3 spec files at start for full context
- Verify design sufficiency when a task references an unvalidated `TD-X` or creates files in an untouched directory
- Ensure all work is tracked in `tasks.md` — no unlisted work
- Restate task goal, files, rules, and verify command before coding
- Set `**Status**: In Progress` before starting implementation
- Run the exact `Verify` command from the task — a task is not done until exit code 0
- On verification failure: diagnose, fix, re-run — never mark Complete on a failing verify
- If the Verify command itself is broken (not a code failure), inform user and get confirmation before updating it
- Update `tasks.md` after each task with `**Status**: Complete` and a `**Result**:` field
- Inform user after task completion so they can review and commit

### MUST NOT DO

- Mark a task as Complete without exit code 0 from its Verify command
- Substitute a different verification command without user confirmation (if the command is broken, propose a fix and get approval)
- Skip tasks or work out of order (unless blocked)
- Work on tasks not listed in `tasks.md`
- Start a task whose `Blocked by` dependencies are not all Complete
- Rely on chat history — always reconstruct from files
- Improvise when design is ambiguous — always stop and ask for clarification

## Related Skills

- **spec-create** — Creates the spec that spec-impl executes
- **tdd** — When a task's `Verify` command is a test runner, use tdd's red-green-refactor cycle: write the failing test first, then implement until it passes
