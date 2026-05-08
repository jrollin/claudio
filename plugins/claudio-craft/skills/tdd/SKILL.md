---
name: tdd
description: >
  Use when implementing ANY feature or bugfix — invoke this skill before writing a single line of production code.
  Trigger for: test-driven development, red-green-refactor cycle, failing tests first, TDD workflow, test-first programming.
  Also trigger when the user asks to "implement", "add", "build", "fix a bug", "write a function", or "create" anything that involves production code — even if they don't mention TDD.
  Even if the task seems too simple to need tests, invoke this skill.
---

# Test-Driven Development (TDD)

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn't watch the test fail, you don't know if it tests the right thing.

**Violating the letter of the rules is violating the spirit of the rules.**

## When to Use

**Always:**

- New features
- Bug fixes
- Refactoring
- Behavior changes

**Exceptions (ask your human partner):**

Use this checklist to decide — if uncertain, default to TDD:

| Question | Yes → exception applies |
|----------|------------------------|
| Is the code intended to be fully discarded after the session (not merged)? | Throwaway prototype |
| Was the code produced entirely by a code-generation tool, not hand-written? | Generated code |
| Does the file contain only values and no logic (env vars, JSON config, Dockerfile)? | Configuration file |

If none of the above apply, follow TDD. "It feels too simple" is not an exception.

Thinking "skip TDD just this once"? Stop. That's rationalization.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write code before the test? Delete it. Start over.

**No exceptions:**

- Don't keep it as "reference"
- Don't "adapt" it while writing tests
- Don't look at it
- Delete means delete

Implement fresh from tests. Period.

## Red-Green-Refactor

```
RED (write test) → VERIFY FAIL → GREEN (minimal code) → VERIFY PASS → REFACTOR → repeat
```

### RED - Write Failing Test

**Pre-coding checklist (complete before writing a single line of production code):**

- [ ] No production code for this behavior exists yet — if it does, delete it first
- [ ] This is a behavioral change, not a config file / generated file / throwaway prototype
- [ ] I can describe the desired API (inputs, outputs, error cases) without looking at an implementation
- [ ] I know which test file to create or extend

Write one minimal test showing what should happen.

**Requirements:**

- One behavior
- Clear name describing expected outcome
- Real code (no mocks unless unavoidable)

See language-specific examples in `references/` directory.

### Verify RED - Watch It Fail

**MANDATORY. Never skip.**

Run the project's test command targeting the specific test.

Confirm:

- Test fails (not errors)
- Failure message is expected
- Fails because feature missing (not typos)

**Test passes?** You're testing existing behavior. Fix test.

**Test errors?** Fix error, re-run until it fails correctly.

### GREEN - Minimal Code

Write the **stupidest code that makes the test green**. Not "simple" — **minimal**.

- One test expects `true`? Return `true`. Not `email.includes('@')`. Not a regex.
- One test expects `3` for `add(1, 2)`? Return `a + b`. Not input validation.
- Any logic that handles untested cases = code without a failing test = violates the Iron Law.

Don't add features, handle edge cases, refactor other code, or "improve" beyond the test. Future tests will drive the real implementation.

### Verify GREEN - Watch It Pass

**MANDATORY.** Run tests again.

Confirm:

- Test passes
- Other tests still pass
- Output pristine (no errors, warnings)

**Test fails?** Fix code, not test.

**Other tests fail?** Fix now.

### REFACTOR - Clean Up

After green only:

- Remove duplication
- Improve names
- Extract helpers

Keep tests green. Don't add behavior.

### Repeat

Next failing test for next feature.

## Good Tests

| Quality          | Good                                | Bad                                                 |
| ---------------- | ----------------------------------- | --------------------------------------------------- |
| **Minimal**      | One thing. "and" in name? Split it. | `test('validates email and domain and whitespace')` |
| **Clear**        | Name describes behavior             | `test('test1')`                                     |
| **Shows intent** | Demonstrates desired API            | Obscures what code should do                        |

## Red Flags - STOP and Start Over

If you catch yourself doing or saying any of these, delete code and restart with TDD.

| Red Flag                               | Reality                                                                 |
| -------------------------------------- | ----------------------------------------------------------------------- |
| Code before test                       | Delete it. No exceptions.                                               |
| Test passes immediately                | You're testing existing behavior, not new behavior.                     |
| "Too simple to test"                   | Simple code breaks. Test takes 30 seconds.                              |
| "I'll test after"                      | Tests passing immediately prove nothing.                                |
| "Tests after achieve same goals"       | Tests-after = "what does this do?" Tests-first = "what should this do?" |
| "Already manually tested"              | Ad-hoc ≠ systematic. No record, can't re-run.                           |
| "Deleting X hours is wasteful"         | Sunk cost fallacy. Keeping unverified code is technical debt.           |
| "Keep as reference, write tests first" | You'll adapt it. That's testing after. Delete means delete.             |
| "Need to explore first"                | Fine. Throw away exploration, start with TDD.                           |
| "Test hard = design unclear"           | Listen to test. Hard to test = hard to use.                             |
| "TDD will slow me down"                | TDD faster than debugging. Pragmatic = test-first.                      |
| "This is different because..."         | It's not. Follow the cycle.                                             |

## Language References

For concrete TDD examples (red/green/refactor walkthroughs, test runners, good/bad patterns), see:

- `references/typescript.md` — Jest/Vitest, async patterns
- `references/rust.md` — cargo test, Result/Option patterns

Pick the reference matching the project's language.

## Verification Checklist

Before marking work complete:

- [ ] Every new function/method has a test
- [ ] Watched each test fail before implementing
- [ ] Each test failed for expected reason (feature missing, not typo)
- [ ] Wrote minimal code to pass each test
- [ ] All tests pass
- [ ] Output pristine (no errors, warnings)
- [ ] Tests use real code (mocks only if unavoidable)
- [ ] Edge cases and errors covered

Can't check all boxes? You skipped TDD. Start over.

## When Stuck

| Problem                | Solution                                                             |
| ---------------------- | -------------------------------------------------------------------- |
| Don't know how to test | Write wished-for API. Write assertion first. Ask your human partner. |
| Test too complicated   | Design too complicated. Simplify interface.                          |
| Must mock everything   | Code too coupled. Use dependency injection.                          |
| Test setup huge        | Extract helpers. Still complex? Simplify design.                     |

## Testing Anti-Patterns

When adding mocks or test utilities, read `testing-anti-patterns.md` to avoid common pitfalls:

- Testing mock behavior instead of real behavior
- Adding test-only methods to production classes
- Mocking without understanding dependencies

## Final Rule

```
Production code → test exists and failed first
Otherwise → not TDD
```

No exceptions without your human partner's permission.
