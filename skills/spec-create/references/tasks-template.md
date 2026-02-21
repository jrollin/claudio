> Reference for: Spec Create
> Load when: Writing task breakdown (Phase 3)

# Tasks Template

## Structure

Follow this skeleton exactly — every heading must appear in the output. The Example section below illustrates the structure with concrete content; do not copy example content into output.

```markdown
# <Feature Name> — Tasks

## Phase 1: <Phase Title>

### T-1: <Task title>
- **Refs**: US-1, US-2, TD-1
- **Files**: `src/auth/service.ts` (new), `src/auth/types.ts` (modify)
- **Verify**: `npm test -- --grep "auth service"`
- **Rules**: BR-1
- **Status**: Not Started

### T-2: <Task title>
- **Refs**: US-3, TD-2
- **Files**: `src/auth/lockout.ts` (new)
- **Verify**: `npm test -- --grep "lockout"`
- **Blocked by**: T-1
- **Rules**: BR-2, BR-3
- **Status**: Not Started

## Phase 2: <Phase Title>

### T-3: <Task title>
...

## Related Features

- **<feature-name>**: [What shared state or business rules overlap — informational, not parsed by agents]
```

## Field Definitions

- **Refs**: User story and technical decision references from requirements/design (e.g., `US-1, TD-2`)
- **Files**: Files to create or modify, with action in parentheses — subset of File Inventory in design.md. If they drift, design.md's File Inventory is the source of truth; update tasks to match
- **Verify**: Command that proves the task is done — must be a single inline code span (backtick-delimited) runnable with the project's test runner (e.g., `npm test`, `cargo test`, `pytest`). The command must exit with code 0 on success and non-zero on failure. Prefer test runner commands over inspection commands that merely print output
- **Blocked by**: Task IDs that must complete first — omit if none
- **Rules**: Business rule IDs from requirements (e.g., `BR-1`) that this task enforces — omit if none
- **Status**: `Not Started` | `In Progress` | `Complete` — spec-create sets all to `Not Started`; consuming agents (spec-impl) update status as they execute tasks. A task whose verification fails remains `In Progress` until resolved — there is no `Failed` state

Fields with no value (**Blocked by**, **Rules**) can be omitted entirely to reduce noise on small specs. Fields are identified by their `**Label**:` prefix, not by position — agents should parse by label, not line order.

## Task Sizing

- A task should be independently verifiable — one Verify command proves it works
- A task should touch 1-4 files; if more, consider splitting
- Each user story (`US-X`) should map to at least one dedicated task
- If a feature has no business rules, omit `Rules` fields and `## Business Rules` — this is valid

## Rules

### DO

- Use imperative verb form for task titles ("Create AuthService", "Add lockout logic", not "AuthService" or "The login endpoint")

- Use `T-X` IDs for every task — these are parsed by spec-impl for tracking
- Group tasks by implementation phase (Phase 1, Phase 2, etc. — sequential starting at 1, no gaps) — phases are for human readability only; **execution order is determined by `Blocked by` fields**, not phase boundaries. An agent should topologically sort on `Blocked by` and ignore phase grouping. Tasks with all dependencies satisfied may be executed in any order (or in parallel if the agent supports it). A task with no `Blocked by` field can start immediately — if ordering matters, add an explicit `Blocked by`
- Reference user stories (`US-1`) and technical decisions (`TD-2`) in Refs
- Reference business rules (`BR-1`) in Rules field
- List concrete files with action (`new` / `modify`) — must align with design's File Inventory. Every file in File Inventory must appear in at least one task; if a file has no task, it's either missing a task or shouldn't be in the inventory
- Provide a runnable verification command or test pattern
- Note dependencies between tasks using `T-X` IDs in Blocked by
- Note cross-feature impact when tasks touch shared state — include a `## Related Features` section

### DON'T

- Don't create micro-checklists for every test case — tests prove implementation, not the reverse
- Don't duplicate acceptance criteria text from requirements.md — the `AC-X.Y` IDs in requirements exist for reviewers to verify coverage, not for task Refs
- Don't enumerate individual test *cases* beyond what's in File Inventory — test files listed in File Inventory must appear in tasks, but don't add extra test files that aren't in the inventory
- Don't create tasks without clear verification methods
- Don't use tables — heading-based entries are more reliably parsed by agents
- Don't create a single task covering multiple user stories unless they are truly inseparable — each `US-X` should map to at least one dedicated `T-X`
- Don't create circular dependencies — `Blocked by` must form a DAG (directed acyclic graph)

## Test Quality Rules

- Tests must cover the business rule, not just the happy path — include edge cases, error paths, boundary conditions
- No flaky tests: deterministic, no timing dependencies, no external service calls without mocks
- If a task touches shared state or cross-feature behavior, note related features that could be affected

## Example

See `references/example-tasks.md` for a full User Authentication tasks example. The same feature is used across `example-requirements.md` and `example-design.md` for end-to-end traceability.
