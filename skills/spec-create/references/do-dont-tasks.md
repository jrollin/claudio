> Reference for: Spec Create
> Load when: Writing tasks (Phase 3) — need concrete good/bad examples

# Tasks: Do & Don't Examples

Side-by-side examples showing common mistakes and their corrections. Use alongside `tasks-template.md` for the formal rules.

---

## Task Sizing

### Bad: God task

One task covers 3 user stories, 7 files, and all business rules. Impossible to verify atomically.

```markdown
### T-1: Implement full authentication system
- **Refs**: US-1, US-2, US-3, TD-1, TD-2
- **Files**: `src/auth/service.ts` (new), `src/auth/types.ts` (new), `src/auth/lockout.ts` (new), `src/routes/auth.ts` (new), `src/middleware/auth.ts` (new), `tests/auth/service.test.ts` (new), `tests/auth/routes.test.ts` (new)
- **Verify**: `npm test`
- **Rules**: BR-1, BR-2, BR-3
- **Status**: Not Started
```

**Why it's wrong:** Touches 7 files, covers 3 stories, verification is too broad (`npm test` — the entire suite). If lockout logic fails, the whole task is blocked.

### Good: One concern per task

```markdown
### T-2: Create AuthService with login/logout
- **Refs**: US-1, US-2, TD-2
- **Files**: `src/auth/service.ts` (new), `src/auth/types.ts` (new), `tests/auth/service.test.ts` (new)
- **Verify**: `npm test -- --grep "AuthService"`
- **Blocked by**: T-1
- **Rules**: BR-1
- **Status**: Not Started

### T-3: Implement account lockout
- **Refs**: US-3, TD-2
- **Files**: `src/auth/lockout.ts` (new), `tests/auth/lockout.test.ts` (new)
- **Verify**: `npm test -- --grep "lockout"`
- **Blocked by**: T-2
- **Rules**: BR-2, BR-3
- **Status**: Not Started
```

**Why it's right:** Each task has a focused concern, 2-3 files, targeted verification, and clear dependencies.

---

## Task Sizing (opposite extreme)

### Bad: Micro-tasks

```markdown
### T-5: Create LoginRequest type
- **Refs**: US-1
- **Files**: `src/auth/types.ts` (new)
- **Verify**: `npx tsc --noEmit`
- **Status**: Not Started

### T-6: Create LoginResponse type
- **Refs**: US-1
- **Files**: `src/auth/types.ts` (modify)
- **Verify**: `npx tsc --noEmit`
- **Blocked by**: T-5
- **Status**: Not Started

### T-7: Create Session type
- **Refs**: US-1, TD-1
- **Files**: `src/auth/types.ts` (modify)
- **Verify**: `npx tsc --noEmit`
- **Blocked by**: T-6
- **Status**: Not Started
```

**Why it's wrong:** Three tasks for one file, each adding a type. Not independently meaningful — type definitions aren't verifiable behavior. Creates artificial dependency chains.

### Good: Types bundled with the feature that uses them

```markdown
### T-2: Create AuthService with login/logout
- **Refs**: US-1, US-2, TD-2
- **Files**: `src/auth/service.ts` (new), `src/auth/types.ts` (new), `tests/auth/service.test.ts` (new)
- **Verify**: `npm test -- --grep "AuthService"`
- **Blocked by**: T-1
- **Rules**: BR-1
- **Status**: Not Started
```

**Why it's right:** Types are created alongside the service that uses them. One verification proves they work together.

---

## Verify Commands

### Bad: Inspection command (no pass/fail signal)

```markdown
- **Verify**: `npm run migrate:status`
```

**Why it's wrong:** Prints status but always exits 0. An agent cannot determine success or failure from the output.

### Bad: Entire test suite

```markdown
- **Verify**: `npm test`
```

**Why it's wrong:** Runs everything. A pre-existing failure in an unrelated module fails this task. Too broad to be meaningful.

### Good: Targeted test command with exit code semantics

```markdown
- **Verify**: `npm test -- --grep "AuthService"`
```

```markdown
- **Verify**: `cargo test auth::lockout`
```

```markdown
- **Verify**: `pytest tests/auth/test_service.py -v`
```

**Why it's right:** Scoped to the task's concern. Exit code 0 = pass, non-zero = fail.

### Good: Migration with assertion

```markdown
- **Verify**: `npm run migrate && npm test -- --grep "schema"`
```

**Why it's right:** Runs the migration, then verifies the schema with a test that asserts correctness.

---

## Dependencies

### Bad: Circular dependency

```markdown
### T-1: Create user model
- **Blocked by**: T-3

### T-2: Create auth service
- **Blocked by**: T-1

### T-3: Create auth middleware
- **Blocked by**: T-2
```

**Why it's wrong:** T-1 → T-3 → T-2 → T-1 forms a cycle. No task can start.

### Bad: Missing dependency (tasks share files)

```markdown
### T-2: Create AuthService with login
- **Files**: `src/auth/service.ts` (new)
- **Status**: Not Started

### T-3: Add lockout to AuthService
- **Files**: `src/auth/service.ts` (modify)
- **Status**: Not Started
```

**Why it's wrong:** T-3 modifies a file T-2 creates, but has no `Blocked by: T-2`. An agent could execute them in any order or in parallel, causing conflicts.

### Good: Explicit dependency chain

```markdown
### T-2: Create AuthService with login
- **Files**: `src/auth/service.ts` (new)
- **Status**: Not Started

### T-3: Add lockout to AuthService
- **Files**: `src/auth/service.ts` (modify)
- **Blocked by**: T-2
- **Status**: Not Started
```

---

## Refs and Rules

### Bad: Business rules in Refs field

```markdown
### T-3: Implement account lockout
- **Refs**: US-3, TD-2, BR-2, BR-3
```

**Why it's wrong:** `BR-X` IDs belong in the `Rules` field, not `Refs`. Agents parse by label.

### Bad: Acceptance criteria in Refs

```markdown
### T-2: Create AuthService with login/logout
- **Refs**: US-1, AC-1.1, AC-1.2, US-2, AC-2.1, TD-2
```

**Why it's wrong:** `AC-X.Y` IDs are for reviewers verifying coverage in requirements.md. Tasks reference stories (`US-X`), not individual criteria.

### Good: Clean separation

```markdown
### T-3: Implement account lockout
- **Refs**: US-3, TD-2
- **Rules**: BR-2, BR-3
```

---

## Task Titles

### Bad

```markdown
### T-1: Database
### T-2: The authentication service needs to be created
### T-3: service.ts and types.ts
```

**Why it's wrong:** Not imperative verbs. Unclear, passive, or file names instead of intent.

### Good

```markdown
### T-1: Set up database schema
### T-2: Create AuthService with login/logout
### T-3: Implement account lockout
```

**Why it's right:** Imperative verb form. States what the task achieves, not what it touches.

---

## Related Features

### Bad: Omitted when cross-feature impact exists

No `## Related Features` section, even though lockout state is shared with password-reset.

### Good: Documents shared state and overlapping rules

```markdown
## Related Features

- **password-reset**: Shares lockout state — resetting password must clear lockout counter (BR-2, BR-3)
- **user-profile**: Login creates session used by profile endpoints
```

---

## Quick Checklist

Before finalizing tasks.md, verify:

- [ ] Every `US-X` from requirements maps to at least one `T-X`
- [ ] Every file in design's File Inventory appears in at least one task
- [ ] Every `Verify` command exits 0 on success, non-zero on failure
- [ ] `Blocked by` forms a DAG (no cycles)
- [ ] Tasks sharing files have explicit `Blocked by` dependencies
- [ ] `BR-X` references use the `Rules` field, not `Refs`
- [ ] Task titles use imperative verb form
- [ ] Each task touches 1-4 files
