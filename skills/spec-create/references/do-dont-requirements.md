> Reference for: Spec Create
> Load when: Writing requirements (Phase 1) — need concrete good/bad examples

# Requirements: Do & Don't Examples

Side-by-side examples showing common mistakes and their corrections. Use alongside `requirements-template.md` for the formal rules. All examples use the User Authentication feature from `example-requirements.md`.

---

## User Story Format

### Bad: AS A / I WANT / SO THAT

```markdown
### US-1 User login

AS A user
I WANT to log in with my email and password
SO THAT I can access protected pages
```

**Why it's wrong:** Persona-and-motivation format doesn't map to test cases. "I want" describes intent, not observable system behavior. The acceptance criteria still have to re-state the trigger and response.

### Bad: SYSTEM SHALL

```markdown
### US-1 User login

SYSTEM SHALL authenticate users via email and password credentials.
```

**Why it's wrong:** "SYSTEM SHALL" is requirements-document jargon. It says nothing about who triggers the behavior or what the observable result is.

### Good: WHEN / THE

```markdown
### US-1 User login

WHEN a user submits valid email and password to the login endpoint
THE system creates a session and returns an auth token
```

**Why it's right:** WHEN = test setup (trigger + actor + condition). THE = test assertion (observable system response). Maps directly to a test case.

---

## Acceptance Criteria

### Bad: Vague, untestable criterion

```markdown
- [ ] AC-1.1: Login should work correctly
- [ ] AC-1.2: The UI should be user-friendly
- [ ] AC-1.3: Errors should be handled gracefully
```

**Why it's wrong:** "Work correctly", "user-friendly", "gracefully" are not measurable. No test can verify these pass or fail.

### Bad: Criterion that introduces a new requirement

```markdown
### US-1 User login

**Acceptance Criteria:**
- [ ] AC-1.1: POST /auth/login with valid credentials returns 200 + token
- [ ] AC-1.2: Token contains user ID and expiration timestamp
- [ ] AC-1.3: System also supports login via OAuth (Google, GitHub)   ← NEW REQUIREMENT
```

**Why it's wrong:** AC-1.3 is a new feature (OAuth) smuggled into a criterion. ACs validate the story — they do not expand scope.

### Good: Specific, testable, scoped to the story

```markdown
### US-1 User login

**Acceptance Criteria:**
- [ ] AC-1.1: POST /auth/login with valid credentials returns 200 + token
- [ ] AC-1.2: Token contains user ID and expiration timestamp
- [ ] AC-1.3: Password is verified against stored hash, never compared in plaintext
```

**Why it's right:** Each criterion names a specific endpoint, response code, or verifiable property. AC-1.3 is testable (a code review criterion or a test that checks no plaintext comparison occurs).

---

## Missing Error Cases

### Bad: Happy path only

```markdown
### US-1 User login

**Acceptance Criteria:**
- [ ] AC-1.1: POST /auth/login with valid credentials returns 200 + token
```

**Why it's wrong:** Only the success path is specified. What happens with wrong password? Non-existent email? Malformed request? These silently become "undefined behavior."

### Good: Include error paths

```markdown
### US-1 User login

**Acceptance Criteria:**
- [ ] AC-1.1: POST /auth/login with valid credentials returns 200 + token
- [ ] AC-1.2: POST /auth/login with wrong password returns 401
- [ ] AC-1.3: POST /auth/login with unknown email returns 401 (same error as wrong password — no user enumeration)
- [ ] AC-1.4: POST /auth/login with missing fields returns 400
```

---

## Business Rules

### Bad: Implementation detail as a business rule

```markdown
## Business Rules

- **BR-1**: Sessions are stored in Redis with a 24-hour TTL
- **BR-2**: Passwords are hashed with bcrypt, cost factor 12
```

**Why it's wrong:** Redis and bcrypt are implementation choices. Business rules capture *what* the business requires (24h expiry, locked after 5 attempts) — not *how* the system implements it. Implementation choices belong in `design.md` as `TD-X` decisions.

### Good: Business-owned thresholds and constraints

```markdown
## Business Rules

- **BR-1**: Sessions expire after 24 hours of inactivity
- **BR-2**: Account locks after 5 consecutive failed login attempts
- **BR-3**: Locked accounts unlock automatically after 30 minutes
```

**Why it's right:** These are decisions the business owns. Changing the lockout threshold (5 → 10 attempts) is a business decision. Changing bcrypt to Argon2 is an engineering decision.

### Bad: Inline business rule (not extracted)

```markdown
### US-3 Account lockout on failed attempts

WHEN a user fails to log in 5 consecutive times
THE system locks the account for 30 minutes and rejects further login attempts

**Acceptance Criteria:**
- [ ] AC-3.1: 6th attempt returns 423 Locked
- [ ] AC-3.2: Account unlocks after 30 minutes
```

**Why it's wrong:** The lockout threshold (5) and duration (30 min) are business rules that apply across multiple stories (US-1, US-3). If they're only inline in AC-3.2, tasks can't reference them via `BR-X`, and changing the threshold requires hunting through all ACs.

### Good: Extracted and ID'd

```markdown
### US-3 Account lockout on failed attempts

**Acceptance Criteria:**
- [ ] AC-3.1: 6th login attempt returns 423 Locked
- [ ] AC-3.2: Locked account unlocks automatically after 30 minutes (BR-3)

## Business Rules

- **BR-2**: Account locks after 5 consecutive failed login attempts
- **BR-3**: Locked accounts unlock automatically after 30 minutes
```

---

## Out of Scope

### Bad: Omitted or vague

```markdown
## Out of Scope

- Other features
```

**Why it's wrong:** "Other features" is meaningless. Without explicit exclusions, scope creep is invisible. Stakeholders may assume OAuth or MFA are included.

### Good: Explicit deferred items

```markdown
## Out of Scope

- OAuth / social login (Google, GitHub) — deferred to v2
- Multi-factor authentication
- Admin-initiated session revocation
- Password reset flow (separate feature)
```

---

## Quick Checklist

Before presenting requirements for approval:

- [ ] Every `US-X` uses WHEN/THE format (not AS A / I WANT / SYSTEM SHALL)
- [ ] Every AC is measurable — specifies endpoint, status code, or verifiable property
- [ ] Every AC includes at least one error/edge case, not just happy path
- [ ] Business rules with thresholds or durations are extracted as `BR-X`
- [ ] No `BR-X` contains implementation choices (libraries, DB schema, algorithms)
- [ ] Out of Scope lists explicitly deferred items by name
- [ ] AC IDs follow `AC-X.Y` format — never renumbered, only appended
