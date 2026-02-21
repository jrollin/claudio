> Reference for: Spec Implement
> Load when: Executing tasks from a completed spec — need concrete good/bad examples

# Implementation: Do & Don't Examples

Side-by-side examples showing common mistakes when executing spec tasks.

---

## Dependency Ordering

### Bad: Pick a blocked task because it's "next in the file"

```
tasks.md has:
  T-1 (no deps)        → Status: Complete
  T-2 (Blocked by T-1) → Status: Complete
  T-3 (Blocked by T-5) → Status: Not Started
  T-4 (no deps)        → Status: Not Started
  T-5 (Blocked by T-2) → Status: Not Started

Agent picks T-3 because it's "next in the file."
```

**Why it's wrong:** T-3 is blocked by T-5, which is `Not Started`. The agent must check `Blocked by` fields first to determine which tasks are eligible, then pick the first eligible one by document order.

### Good: Check blocked status first, then pick by document order

```
After T-1, T-2 complete:
  T-3 → blocked (T-5 not done) ✗
  T-4 → unblocked (no deps)   ✓ ← first eligible by document order
  T-5 → unblocked (T-2 done)  ✓

Agent picks T-4 (first unblocked by document order).
```

---

## Parsing Tasks

### Bad: Assume field order

```
Agent reads the task block and assumes:
  line 1 = Refs
  line 2 = Files
  line 3 = Verify

But T-3 has a Blocked by field between Files and Verify,
so the agent reads the wrong line as Verify.
```

**Why it's wrong:** Optional fields (`Blocked by`, `Rules`) may be present or absent, shifting line positions. Field order is not guaranteed.

### Good: Match by label prefix

```
For each line in the task block:
  - starts with "- **Refs**:"      → extract refs
  - starts with "- **Files**:"     → extract files
  - starts with "- **Verify**:"    → extract verify command
  - starts with "- **Blocked by**:" → extract dependencies
  - starts with "- **Rules**:"     → extract business rules
  - starts with "- **Status**:"    → extract status

Missing fields mean "not applicable" — don't error on absence.
```

---

## Design Sufficiency

### Bad: Guess when design is unclear

```
Task T-3: "Add caching layer"
design.md says: "Consider adding caching for performance"

Agent thinks: "I'll use Redis since it's common"
→ Implements Redis caching without user input
```

**Why it's wrong:** "Consider" is not a decision. No TD-X reference, no alternatives evaluated. The agent improvised an infrastructure dependency.

### Good: Stop and ask

```
Task T-3: "Add caching layer"
design.md says: "Consider adding caching for performance"

Agent: "design.md doesn't specify a caching strategy for T-3.
Missing: what to cache, TTL policy, storage backend (in-memory vs Redis vs DB).
Please update the design before I continue."
```

### Good: Skip check when design area already validated

```
T-2 validated TD-1 (database-backed sessions) and TD-2 (service layer).
T-3 references TD-2 only.

Agent: TD-2 was already validated for T-2, same architectural area.
→ Skip design sufficiency check, proceed to implement.
```

---

## Task Completion

### Bad: Mark complete without verification

```markdown
### T-2: Create AuthService with login/logout
- **Status**: Complete
```

Agent updated status after writing the code but before running the Verify command.

**Why it's wrong:** The Verify command was never run. Tests might fail.

### Bad: Mark complete when verification fails

```
$ <verify command>
  ✓ creates session on valid login
  ✗ returns 401 on invalid password
  1 failing (exit code 1)

Agent: "Most tests pass, marking Complete."
```

**Why it's wrong:** Exit code is non-zero. One failing test means the task is not done. Status stays `In Progress`.

### Good: Verify passes, then update with Result

```markdown
### T-2: Create AuthService with login/logout
- **Refs**: US-1, US-2, TD-2
- **Files**: `src/auth/service.ts` (new), `src/auth/types.ts` (new), `tests/auth/service.test.ts` (new)
- **Verify**: `pytest tests/auth/test_service.py -v`
- **Blocked by**: T-1
- **Rules**: BR-1
- **Status**: Complete
- **Result**: AuthService with login/logout — 6 passing tests
```

---

## Verification Failure

### Bad: Give up or mark Complete anyway

```
Verify exits with code 1. Agent says:
"Tests are failing but the implementation looks correct.
Marking Complete and moving on."
```

### Good: Diagnose, fix, re-run

```
1. Read error output → "expected 401, got 500"
2. Find the bug → missing error handler in login route
3. Fix the code (not the test)
4. Re-run the exact Verify command
5. Exit code 0 → now mark Complete

If stuck after multiple attempts:
"T-2 verification is failing with: [error output].
I've tried [what you tried]. Need guidance to proceed."
```

---

## Status Updates in tasks.md

### Bad: Overwrite the task entry

Agent rewrites the entire task block, changing Files or Refs in the process.

**Why it's wrong:** The spec is the source of truth. Only `Status` and `Result` should change during implementation.

### Good: Only update Status and append Result

Change `**Status**: Not Started` → `**Status**: In Progress` when starting.
Change `**Status**: In Progress` → `**Status**: Complete` and add `**Result**:` line when done.
Leave all other fields untouched.

---

## Session Resume

### Bad: Rely on memory from previous session

```
"Last time I was working on T-3, I think I had created the file
but hadn't written tests yet. Let me continue from there."
```

**Why it's wrong:** Chat history is unreliable. The file may not exist, or T-3 may have been completed by another session.

### Good: Reconstruct from tasks.md

```
1. Read tasks.md
2. Find T-3 has Status: In Progress
3. Check what files exist on disk vs what T-3 lists
4. Run T-3's Verify command to see current state
5. Determine actual state, resume from there
```

---

## Unlisted Work

### Bad: Fix something you noticed along the way

```
While implementing T-3 (lockout), agent notices a bug in
the user model validation. Fixes it without updating tasks.md.
```

**Why it's wrong:** Untracked work breaks traceability. If the fix introduces a regression, there's no task to trace it to.

### Good: Ask user, then add to tasks.md

```
Agent: "While implementing T-3, I found a bug in user model
validation (email regex allows invalid formats). Should I
add a new task T-7 to fix this?"

User: "Yes, add it."

Agent adds to tasks.md:
### T-7: Fix email validation regex in user model
- **Refs**: US-1
- **Files**: `src/models/user.py` (modify), `tests/models/test_user.py` (modify)
- **Verify**: `pytest tests/models/test_user.py -k "email_validation" -v`
- **Status**: Not Started
```

---

## Verification Commands

### Bad: Skip verification because "the code looks right"

```
Agent: "The implementation follows the design exactly
and the types check out. Marking T-2 as Complete."
```

**Why it's wrong:** "Looks right" is not evidence. Run the command.

### Bad: Run a different command than specified

```
Task says:  Verify: `cargo test auth::lockout`
Agent runs: cargo clippy

Task says:  Verify: `pytest tests/auth/ -v`
Agent runs: python -c "import auth; print('OK')"
```

**Why it's wrong:** Static analysis / import checks are not the specified verification. The task's Verify command tests behavior.

### Good: Run exactly what the task specifies

```
Task says: Verify: `cargo test auth::lockout`
Agent runs: cargo test auth::lockout
Output: test result: ok. 4 passed; 0 failed (exit code 0)
→ Verification passed
```

### Bad: Loop on a broken Verify command

```
Task says: Verify: `pytest tests/auth/test_lockout.py -v`
Agent runs the command → "file not found"
Agent: "Test is failing, let me fix the code..."
→ Tries to fix code, re-runs, same error. Repeats 3 times.
```

**Why it's wrong:** The error is "file not found" — a command failure, not a test failure. The agent should recognize the Verify command references a path that doesn't exist (spec-create wrote it before the file was created with a wrong name).

### Good: Identify a broken Verify command and ask user

```
Task says: Verify: `pytest tests/auth/test_lockout.py -v`
Agent runs the command → "file not found"

Agent: "The Verify command references tests/auth/test_lockout.py
but the test file I created is tests/auth/test_account_lockout.py.
Suggested fix: `pytest tests/auth/test_account_lockout.py -v`
— should I update tasks.md with this command?"

User: "Yes."
→ Agent updates Verify in tasks.md, re-runs, proceeds.
```

---

## Dependency Installation

### Bad: Loop on import errors without installing

```
Agent implements T-3 which uses bcrypt (referenced in TD-4).
Runs Verify → "ModuleNotFoundError: No module named 'bcrypt'"
Agent: "Let me fix the import..." → same error. Loops.
```

**Why it's wrong:** The module isn't installed. TD-4 in design.md chose bcrypt. The agent should install it.

### Good: Install dependencies referenced in design.md

```
Agent implements T-3 which uses bcrypt (referenced in TD-4).
Runs Verify → "ModuleNotFoundError: No module named 'bcrypt'"
Agent: TD-4 specifies bcrypt as the hashing library.
→ Installs: pip install bcrypt
→ Re-runs Verify → exit code 0
```

### Good: Stop when dependency is not in design.md

```
Agent implements T-3 and considers using a caching library
not mentioned anywhere in design.md.

Agent: "T-3 would benefit from redis for caching, but
design.md doesn't specify a caching backend. This is a
design gap — should I proceed with redis or update the design?"
```

---

## Test File Scope

### Bad: Refuse to create test file not listed in Files

```
Task says:
  Files: `src/auth/lockout.ts` (new)
  Verify: `npm test -- --grep "lockout"`

Agent: "The test file isn't listed in Files. I can't create
unlisted files. Marking as blocked."
```

**Why it's wrong:** The Verify command is a test runner — TDD requires a test file. Test files implied by the Verify command are always in scope.

### Good: Create test files implied by Verify

```
Task says:
  Files: `src/auth/lockout.ts` (new)
  Verify: `npm test -- --grep "lockout"`

Agent: Verify runs tests matching "lockout". Following TDD:
→ Creates tests/auth/lockout.test.ts with failing test
→ Implements src/auth/lockout.ts
→ Runs Verify → exit code 0
```

---

## Restate Before Coding

### Bad: Jump straight to implementation

```
Agent reads T-3 and immediately starts writing code
without stating what it's doing or why.
```

**Why it's wrong:** No checkpoint for the user to catch misunderstandings before code is written.

### Good: Brief restate, then implement

```
**T-3: Implement account lockout**
- Goal: Lock accounts after 5 failed attempts (BR-2),
  auto-unlock after 30 min (BR-3)
- Files: src/auth/lockout.rs (new), tests/auth/lockout_test.rs (new)
- Verify: cargo test auth::lockout

Proceeding with implementation.
```

---

## Full Execution Walkthrough

A complete cycle for one task, showing all workflow steps:

```
═══ Step 2: Pick Next Task ═══

Scanning tasks.md:
  T-1: Status: Complete
  T-2: Status: Complete
  T-3: Blocked by T-2 → T-2 is Complete → unblocked, Status: Not Started ✓
  T-4: Blocked by T-3 → T-3 is Not Started → still blocked ✗

→ Selected T-3

═══ Step 3: Restate ═══

**T-3: Implement account lockout**
- Goal: Lock accounts after 5 failed attempts (BR-2), auto-unlock after 30 min (BR-3)
- Files: src/auth/lockout.go (new), tests/auth/lockout_test.go (new)
- Rules: BR-2, BR-3
- Verify: go test ./internal/auth/ -run TestLockout -v

Setting Status: In Progress in tasks.md.

═══ Step 4: Design Check ═══

T-3 references TD-2 (service layer pattern).
TD-2 was validated during T-2 implementation → same area → skip.

═══ Step 5: Implement ═══

[Write failing test first — tdd red-green-refactor]
[Implement lockout logic]
[Tests pass locally]

═══ Step 6: Validate ═══

$ go test ./internal/auth/ -run TestLockout -v
=== RUN   TestLockout_LocksAfterFiveFailures
--- PASS
=== RUN   TestLockout_AutoUnlockAfterThirtyMinutes
--- PASS
=== RUN   TestLockout_ResetOnSuccess
--- PASS
PASS (exit code 0)

═══ Step 7: Update tasks.md ═══

- **Status**: Complete
- **Result**: Lockout logic with 3 passing tests covering BR-2, BR-3

Task ready for review and commit.

═══ Step 8: Repeat → back to Step 2 ═══
```

---

## Quick Checklist

Before marking any task Complete:

- [ ] `**Status**: In Progress` was set before coding started
- [ ] Verification command was run (not skipped, not substituted)
- [ ] Exit code was 0
- [ ] `**Status**: Complete` set in tasks.md
- [ ] `**Result**:` field appended with summary
- [ ] No other fields in the task entry were modified
- [ ] User informed for review and commit
