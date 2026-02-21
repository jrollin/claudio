> Reference for: Spec Create
> Load when: Writing requirements (Phase 1)

# Requirements Template

## Structure

Follow this skeleton exactly — every heading must appear in the output. The Example section below illustrates the structure with concrete content; do not copy example content into output.

```markdown
# <Feature Name> — Requirements

## Overview

[Brief description of the feature, the problem it solves, and who benefits from it]

## User Stories

### US-1 <Story Title>

WHEN [actor] [condition/event]
THE [expected behavior]

**Acceptance Criteria:**
- [ ] AC-1.1: [Specific, testable criterion]
- [ ] AC-1.2: [Another criterion]

### US-2 <Story Title>

WHEN [actor] [condition/event]
THE [expected behavior]

**Acceptance Criteria:**
- [ ] AC-2.1: ...

## Business Rules

- **BR-1**: [Rule description — e.g., "Account locks after 5 failed login attempts"]
- **BR-2**: [Rule description]

## Non-Functional Requirements

- **NFR-1** (Performance): [Response time, throughput constraints]
- **NFR-2** (Security): [Auth, data protection, input validation]
- **NFR-3** (Compatibility): [Platforms, versions, dependencies]

## Out of Scope

- [Explicitly excluded functionality]
- [Things that look related but are deferred]

## Open Questions

- [ ] [Unresolved decisions that need stakeholder input]
```

## User Story Format

Use `US-X <Title>` with WHEN/THE notation:

```
WHEN [actor] [condition/event]
THE [expected behavior]
```

- **WHEN**: describes the trigger — who does what, under what condition
- **THE**: describes what the system does in response

We use WHEN/THE instead of AS A/I WANT/SO THAT because it focuses on observable behavior (trigger → response) rather than persona and motivation. This maps directly to test cases: the WHEN becomes the test setup, THE becomes the assertion.

Do **not** use "SYSTEM SHALL" — the THE clause already implies system behavior.

Each US must have at least one acceptance criterion that is directly testable.

## Acceptance Criteria IDs

Prefix each criterion with `AC-X.Y` where X is the story number and Y is the criterion number. IDs are assigned once and stay stable — if you insert a criterion between AC-3.2 and AC-3.3, use AC-3.4 (append, don't renumber):

```
### US-3 Password Reset

**Acceptance Criteria:**
- [ ] AC-3.1: Reset email sent within 5 seconds of request
- [ ] AC-3.2: Reset link expires after 1 hour
- [ ] AC-3.3: Using an expired link shows an error message
```

These IDs provide fine-grained traceability. Tasks reference stories at the `US-X` level; `AC-X.Y` IDs let reviewers verify that all criteria are covered.

## Business Rules

Extract reusable domain rules into the `## Business Rules` section with `BR-X` IDs. Business rules are referenced by tasks and acceptance criteria:

- A rule that applies across multiple stories belongs in Business Rules (not inline in AC)
- Each BR should be a single, testable constraint
- Include **business-owned thresholds** (lockout after 5 attempts, session expires after 24h) — these are business decisions. Exclude **implementation choices** (bcrypt, Redis, specific DB schema) — those belong in design
- Tasks reference `BR-X` to indicate which rules they enforce

```markdown
## Business Rules

- **BR-1**: Sessions expire after 24 hours of inactivity
- **BR-2**: Account locks after 5 consecutive failed login attempts
- **BR-3**: Locked accounts unlock automatically after 30 minutes
```

## Example

See `references/example-requirements.md` for a full User Authentication requirements example. The same feature is used across `example-design.md` and `example-tasks.md` for end-to-end traceability.

## Common Mistakes to Avoid

- **Vague language**: "The system should handle errors gracefully" — specify *which* errors and *what* handling
- **Untestable criteria**: "The UI should be user-friendly" — replace with measurable behavior
- **Missing error cases**: Always include what happens when things go wrong (invalid input, network failure, missing files)
- **Actor ambiguity**: "When data is processed" — specify *who* triggers it and *how*
- **Scope creep in AC**: Acceptance criteria should validate the US, not introduce new requirements
- **Inline business rules**: If a rule applies to multiple stories, extract it to `## Business Rules` with a `BR-X` ID
- **Missing AC IDs**: Every acceptance criterion must have an `AC-X.Y` prefix for task traceability
