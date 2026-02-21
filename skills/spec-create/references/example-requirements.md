> Reference for: Spec Create
> Load when: Writing requirements (Phase 1) — need to see a completed example

# User Authentication — Requirements (Example)

This illustrates the structure defined in `requirements-template.md` with concrete content. Follow the structure; do not copy this content.

All three example files use the same feature so you can trace `US-X` → `TD-X` → `T-X` → `BR-X` end-to-end: see also `example-design.md` and `example-tasks.md`.

---

```markdown
# User Authentication — Requirements

## Overview

Session-based authentication for a web API, allowing users to log in with
email/password and access protected endpoints.

## User Stories

### US-1 User login

WHEN a user submits valid email and password to the login endpoint
THE system creates a session and returns an auth token

**Acceptance Criteria:**
- [ ] AC-1.1: POST /auth/login with valid credentials returns 200 + token
- [ ] AC-1.2: Token contains user ID and expiration timestamp
- [ ] AC-1.3: Password is verified against stored hash, never compared in plaintext

### US-2 User logout

WHEN an authenticated user calls the logout endpoint
THE system invalidates the session token

**Acceptance Criteria:**
- [ ] AC-2.1: POST /auth/logout returns 200 and invalidates the token
- [ ] AC-2.2: Subsequent requests with the invalidated token return 401

### US-3 Account lockout on failed attempts

WHEN a user fails to log in 5 consecutive times
THE system locks the account and rejects further login attempts

**Acceptance Criteria:**
- [ ] AC-3.1: 6th login attempt returns 423 Locked
- [ ] AC-3.2: Lockout counter resets after a successful login
- [ ] AC-3.3: Locked account unlocks automatically after 30 minutes (BR-3)

## Business Rules

- **BR-1**: Sessions expire after 24 hours of inactivity
- **BR-2**: Account locks after 5 consecutive failed login attempts
- **BR-3**: Locked accounts unlock automatically after 30 minutes

## Non-Functional Requirements

- **NFR-1** (Performance): Login endpoint responds in under 200ms (p95)
- **NFR-2** (Security): Passwords must never be stored in plaintext

## Out of Scope

- OAuth / social login
- Multi-factor authentication

## Open Questions

- [ ] Should sessions be revocable from an admin panel?
```
