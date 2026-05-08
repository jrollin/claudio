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

## Problem Statement

**Who** is affected: All application users
**What** problem they face: No way to authenticate — all endpoints are public
**Why** it matters: User data is exposed without access control; required for compliance
**How** success is measured: 100% of protected endpoints require valid session; zero plaintext password storage

## User Stories

### User login {#US-1}

WHEN a user submits valid email and password to the login endpoint
THE system creates a session and returns an auth token

**Acceptance Criteria:**
- [ ] POST /auth/login with valid credentials returns 200 + token *(AC-1.1)*
- [ ] Token contains user ID and expiration timestamp *(AC-1.2)*
- [ ] Password is verified against stored hash, never compared in plaintext *(AC-1.3)*

### User logout {#US-2}

WHEN an authenticated user calls the logout endpoint
THE system invalidates the session token

**Acceptance Criteria:**
- [ ] POST /auth/logout returns 200 and invalidates the token *(AC-2.1)*
- [ ] Subsequent requests with the invalidated token return 401 *(AC-2.2)*

### Account lockout on failed attempts {#US-3}

WHEN a user fails to log in 5 consecutive times
THE system locks the account and rejects further login attempts

**Acceptance Criteria:**
- [ ] 6th login attempt returns 423 Locked *(AC-3.1)*
- [ ] Lockout counter resets after a successful login *(AC-3.2)*
- [ ] Locked account unlocks automatically after 30 minutes (BR-3) *(AC-3.3)*

## Business Rules

- Sessions expire after 24 hours of inactivity *(BR-1)*
- Account locks after 5 consecutive failed login attempts *(BR-2)*
- Locked accounts unlock automatically after 30 minutes *(BR-3)*

## Success Metrics *(optional)*

- 95% of users complete login on first attempt within first week of launch *(KPI-1)*
  - **Baseline**: N/A (new feature)
  - **Measured by**: Application analytics dashboard

## Out of Scope

- OAuth / social login
- Multi-factor authentication

## Open Questions

- [ ] Should sessions be revocable from an admin panel?
```
