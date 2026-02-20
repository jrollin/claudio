> Reference for: Spec Create
> Load when: Writing task breakdown (Phase 3)

# Tasks Template

## Structure

```markdown
# <Feature Name> — Tasks

## Phase 1: <Phase Title>

| Task | Status | Refs | Verification | Notes |
|------|--------|------|--------------|-------|
| <Task description> | Not Started | US-1 | <What proves it's done> | <Context> |

## Phase 2: <Phase Title>

| Task | Status | Refs | Verification | Notes |
|------|--------|------|--------------|-------|
| ... | ... | ... | ... | ... |

## Related Features

- **<feature-name>**: [What shared state or business rules overlap]
```

## Column Definitions

- **Task**: Imperative description of the work unit (e.g., "Create NotificationRouter service")
- **Status**: `Not Started` | `In Progress` | `Complete`
- **Refs**: User story references from requirements (e.g., `US-1, US-3`)
- **Verification**: What test, check, or evidence proves the task is done
- **Notes**: Implementation details, file paths, business rules

## Rules

### DO

- Group tasks by implementation phase (Phase 1, Phase 2, etc.)
- Reference user stories (`US-1`, `US-2`) instead of repeating acceptance criteria
- Focus on major milestones (service creation, API endpoints, integrations)
- Track progress with simple status: Not Started | In Progress | Complete
- Each task references which US/AC it proves (traceability)
- Each task states what validates it (unit test, integration test, manual check)
- Note dependencies and blockers between tasks
- Note business rules inline (e.g., "BR: max 3 retries before lockout")
- Note cross-feature impact when tasks touch shared state

### DON'T

- Don't create micro-checklists for every test case — tests prove implementation, not the reverse
- Don't duplicate acceptance criteria from requirements.md
- Don't list every single test file — link to test suite, not individual cases
- Don't create tasks without clear verification methods

## Test Quality Rules

- Tests must cover the business rule, not just the happy path — include edge cases, error paths, boundary conditions
- No flaky tests: deterministic, no timing dependencies, no external service calls without mocks
- If a task touches shared state or cross-feature behavior, note related features that could be affected
- Track business rules inline: each task notes which business rule(s) it enforces

## Dependency Notation

Use "Blocked by:" prefix in Notes column for sequential dependencies:

```markdown
| Set up database schema | Not Started | US-1 | Migration runs clean | — |
| Create API endpoint    | Not Started | US-1, US-2 | Integration test passes | Blocked by: schema setup |
```

## Example

```markdown
# User Authentication — Tasks

## Phase 1: Core Auth Service

| Task | Status | Refs | Verification | Notes |
|------|--------|------|--------------|-------|
| Create `AuthService` with login/logout | Not Started | US-1, US-2 | `test_login_valid_credentials`, `test_logout_clears_session` | BR: session expires after 24h |
| Implement account lockout | Not Started | US-3 | `test_login_locks_after_5_failures`, `test_lockout_resets_after_30min` | BR: account locks after 5 failed attempts |
| Add password hashing | Not Started | US-1 | `test_password_not_stored_plaintext` | Use bcrypt, cost factor 12 |

## Phase 2: API Integration

| Task | Status | Refs | Verification | Notes |
|------|--------|------|--------------|-------|
| Create `/auth/login` endpoint | Not Started | US-1 | Integration test: valid login returns 200 + token | Blocked by: AuthService |
| Create `/auth/logout` endpoint | Not Started | US-2 | Integration test: logout invalidates token | Blocked by: AuthService |
| Add rate limiting middleware | Not Started | US-3 | `test_rate_limit_blocks_after_threshold` | BR: 10 req/min per IP |

## Related Features

- **password-reset**: Shares lockout state — resetting password must clear lockout counter
- **user-profile**: Login creates session used by profile endpoints
```
