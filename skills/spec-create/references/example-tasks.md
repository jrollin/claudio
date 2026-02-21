> Reference for: Spec Create
> Load when: Writing tasks (Phase 3) — need to see a completed example

# User Authentication — Tasks (Example)

This illustrates the structure defined in `tasks-template.md` with concrete content. Follow the structure; do not copy this content.

All three example files use the same feature so you can trace `US-X` → `TD-X` → `T-X` → `BR-X` end-to-end: see also `example-requirements.md` and `example-design.md`.

---

```markdown
# User Authentication — Tasks

## Phase 1: Core Auth Service

### T-1: Set up database schema
- **Refs**: US-1, US-3, TD-1
- **Files**: `migrations/add-auth-tables.sql` (new)
- **Verify**: `npm run migrate && npm run migrate:status`
- **Rules**: BR-1, BR-2
- **Status**: Not Started

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

### T-4: Add password hashing
- **Refs**: US-1, TD-2
- **Files**: `src/auth/service.ts` (modify)
- **Verify**: `npm test -- --grep "password hashing"`
- **Blocked by**: T-2
- **Status**: Not Started

## Phase 2: API Integration

### T-5: Create /auth/login endpoint
- **Refs**: US-1, TD-1
- **Files**: `src/routes/auth.ts` (new), `src/middleware/auth.ts` (new), `tests/auth/routes.test.ts` (new)
- **Verify**: `npm test -- --grep "POST /auth/login"`
- **Blocked by**: T-2, T-4
- **Status**: Not Started

### T-6: Create /auth/logout endpoint
- **Refs**: US-2
- **Files**: `src/routes/auth.ts` (modify)
- **Verify**: `npm test -- --grep "POST /auth/logout"`
- **Blocked by**: T-2
- **Status**: Not Started

## Related Features

- **password-reset**: Shares lockout state — resetting password must clear lockout counter (BR-2, BR-3)
- **user-profile**: Login creates session used by profile endpoints
```
