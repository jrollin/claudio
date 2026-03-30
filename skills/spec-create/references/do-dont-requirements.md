> Reference for: Spec Create
> Load when: Writing requirements (Phase 1) — need concrete good/bad examples

# Requirements: Do & Don't Examples

Side-by-side examples showing common mistakes and their corrections. Use alongside `requirements-template.md` for the formal rules. All examples use the User Authentication feature from `example-requirements.md`.

---

## Problem Statement

### Bad: Overview with no business context

```markdown
## Overview
Session-based authentication for a web API.
```

**Why it's wrong:** No mention of who is affected, what the actual problem is, or why it matters. Impossible to evaluate whether the proposed solution is the right one.

### Good: Problem statement with clear business justification

```markdown
## Problem Statement
**Who** is affected: All application users
**What** problem they face: No authentication — all endpoints are public
**Why** it matters: User data exposed; compliance risk
**How** success is measured: 100% protected endpoints require valid session
```

**Why it's right:** Who/What/Why/How forces the author to justify the feature. Reviewers can challenge scope, and success is measurable.

---

## User Story Format

### Bad: AS A / I WANT / SO THAT

```markdown
### User login {#US-1}

AS A user
I WANT to log in with my email and password
SO THAT I can access protected pages
```

**Why it's wrong:** Persona-and-motivation format doesn't map to test cases. "I want" describes intent, not observable system behavior. The acceptance criteria still have to re-state the trigger and response.

### Bad: SYSTEM SHALL

```markdown
### User login {#US-1}

SYSTEM SHALL authenticate users via email and password credentials.
```

**Why it's wrong:** "SYSTEM SHALL" is requirements-document jargon. It says nothing about who triggers the behavior or what the observable result is.

### Good: WHEN / THE

```markdown
### User login {#US-1}

WHEN a user submits valid email and password to the login endpoint
THE system creates a session and returns an auth token
```

**Why it's right:** WHEN = test setup (trigger + actor + condition). THE = test assertion (observable system response). Maps directly to a test case.

---

## Acceptance Criteria

### Bad: Vague, untestable criterion

```markdown
- [ ] Login should work correctly *(AC-1.1)*
- [ ] The UI should be user-friendly *(AC-1.2)*
- [ ] Errors should be handled gracefully *(AC-1.3)*
```

**Why it's wrong:** "Work correctly", "user-friendly", "gracefully" are not measurable. No test can verify these pass or fail.

### Bad: Criterion that introduces a new requirement

```markdown
### User login {#US-1}

**Acceptance Criteria:**
- [ ] POST /auth/login with valid credentials returns 200 + token *(AC-1.1)*
- [ ] Token contains user ID and expiration timestamp *(AC-1.2)*
- [ ] System also supports login via OAuth (Google, GitHub) *(AC-1.3)*   ← NEW REQUIREMENT
```

**Why it's wrong:** AC-1.3 is a new feature (OAuth) smuggled into a criterion. ACs validate the story — they do not expand scope.

### Good: Specific, testable, scoped to the story

```markdown
### User login {#US-1}

**Acceptance Criteria:**
- [ ] POST /auth/login with valid credentials returns 200 + token *(AC-1.1)*
- [ ] Token contains user ID and expiration timestamp *(AC-1.2)*
- [ ] Password is verified against stored hash, never compared in plaintext *(AC-1.3)*
```

**Why it's right:** Each criterion names a specific endpoint, response code, or verifiable property. AC-1.3 is testable (a code review criterion or a test that checks no plaintext comparison occurs).

---

## Missing Error Cases

### Bad: Happy path only

```markdown
### User login {#US-1}

**Acceptance Criteria:**
- [ ] POST /auth/login with valid credentials returns 200 + token *(AC-1.1)*
```

**Why it's wrong:** Only the success path is specified. What happens with wrong password? Non-existent email? Malformed request? These silently become "undefined behavior."

### Good: Include error paths

```markdown
### User login {#US-1}

**Acceptance Criteria:**
- [ ] POST /auth/login with valid credentials returns 200 + token *(AC-1.1)*
- [ ] POST /auth/login with wrong password returns 401 *(AC-1.2)*
- [ ] POST /auth/login with unknown email returns 401 (same error as wrong password — no user enumeration) *(AC-1.3)*
- [ ] POST /auth/login with missing fields returns 400 *(AC-1.4)*
```

---

## Business Rules

### Bad: Implementation detail as a business rule

```markdown
## Business Rules

- Sessions are stored in Redis with a 24-hour TTL *(BR-1)*
- Passwords are hashed with bcrypt, cost factor 12 *(BR-2)*
```

**Why it's wrong:** Redis and bcrypt are implementation choices. Business rules capture *what* the business requires (24h expiry, locked after 5 attempts) — not *how* the system implements it. Implementation choices belong in `design.md` as `TD-X` decisions.

### Good: Business-owned thresholds and constraints

```markdown
## Business Rules

- Sessions expire after 24 hours of inactivity *(BR-1)*
- Account locks after 5 consecutive failed login attempts *(BR-2)*
- Locked accounts unlock automatically after 30 minutes *(BR-3)*
```

**Why it's right:** These are decisions the business owns. Changing the lockout threshold (5 → 10 attempts) is a business decision. Changing bcrypt to Argon2 is an engineering decision.

### Bad: Inline business rule (not extracted)

```markdown
### Account lockout on failed attempts {#US-3}

WHEN a user fails to log in 5 consecutive times
THE system locks the account for 30 minutes and rejects further login attempts

**Acceptance Criteria:**
- [ ] 6th attempt returns 423 Locked *(AC-3.1)*
- [ ] Account unlocks after 30 minutes *(AC-3.2)*
```

**Why it's wrong:** The lockout threshold (5) and duration (30 min) are business rules that apply across multiple stories (US-1, US-3). If they're only inline in AC-3.2, tasks can't reference them via `BR-X`, and changing the threshold requires hunting through all ACs.

### Good: Extracted and ID'd

```markdown
### Account lockout on failed attempts {#US-3}

**Acceptance Criteria:**
- [ ] 6th login attempt returns 423 Locked *(AC-3.1)*
- [ ] Locked account unlocks automatically after 30 minutes (BR-3) *(AC-3.2)*

## Business Rules

- Account locks after 5 consecutive failed login attempts *(BR-2)*
- Locked accounts unlock automatically after 30 minutes *(BR-3)*
```

---

## Success Metrics (KPIs) vs NFRs

> Non-functional requirements (performance, security, compatibility) belong in design.md, not requirements.md.

### Bad: Engineering constraint as KPI

```markdown
## Success Metrics
- Login endpoint responds in under 200ms *(KPI-1)*
```

**Why it's wrong:** This is an NFR — it measures engineering performance, not product outcome. Move to design.md.

### Good: Product outcome as KPI

```markdown
## Success Metrics *(optional)*
- 95% of users complete login on first attempt *(KPI-1)*
  - **Baseline**: N/A (new feature)
  - **Measured by**: Application analytics dashboard
```

**Why it's right:** This measures whether the feature achieves its goal for users. Engineering constraints (latency, throughput) belong in design.md as NFRs.

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

- [ ] Problem Statement with Who/What/Why/How present?
- [ ] Every `US-X` uses WHEN/THE format (not AS A / I WANT / SYSTEM SHALL)
- [ ] Every AC is measurable — specifies endpoint, status code, or verifiable property
- [ ] Every AC includes at least one error/edge case, not just happy path
- [ ] Business rules with thresholds or durations are extracted as `BR-X`
- [ ] No `BR-X` contains implementation choices (libraries, DB schema, algorithms)
- [ ] Out of Scope lists explicitly deferred items by name
- [ ] IDs use suffix style: `{#US-X}`, `*(AC-X.Y)*`, `*(BR-X)*` — never renumbered, only appended
