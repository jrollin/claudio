---
name: pr-triage
description: >
  Use when addressing review feedback on an existing pull request: verify each comment against the
  code, classify it, fix what is valid, and reply on the threads.
  Trigger for: "triage the PR comments", "address the review feedback", "handle the comments on PR
  123", "the reviewer says X, is that right?", "answer the review threads".
  NOT for producing a review of someone else's PR (use the *-review agents), NOT for opening or
  updating a PR, and NOT for reviewing an uncommitted local diff.
---

# PR Triage

Turn a pull request's review comments into verified fixes and answered threads.

Every comment is a claim until checked against the code. Some are wrong, some are out of scope,
and agreeing with all of them is how a PR grows a tail of noise commits.

## Scope

Resolve the target PR before anything else:

- A PR number or URL in the request wins.
- Otherwise use the PR for the current branch (`gh pr view --json number`).
- No PR found: stop and ask, do not guess.

## Workflow

### 1. Gather

```bash
gh pr view <pr> --json title,body,headRefName,state
gh pr diff <pr>
gh api repos/{owner}/{repo}/pulls/<pr>/comments    # inline review comments
gh api repos/{owner}/{repo}/issues/<pr>/comments   # top-level discussion
```

The diff is mandatory: a comment cannot be verified without the code it points at.

### 2. Classify

Read the cited file and line before forming an opinion. Classify each comment:

| Class | Meaning | Action |
| --- | --- | --- |
| **valid** | The claim holds against the current code | Fix it |
| **invalid** | The code already handles it, or the claim is factually wrong | Reply with the evidence, no code change |
| **out-of-scope** | Real, but not about this change | Reply, propose a follow-up issue |
| **unclear** | Ambiguous or missing context | Ask the reviewer, do not invent an interpretation |

State the evidence (file and line) for every classification. "The reviewer is right" without a
citation is not a classification.

### 3. Fix

For each valid finding, follow the `tdd` skill: write the test that fails for that finding, watch
it fail, then fix. One logical fix per change. No drive-by refactors riding along.

### 4. Verify

Run the repo's check gates: test suite, linter, formatter, type check. Use the project's own
scripts (`package.json`, `Makefile`, CI workflow) rather than assumed commands. All green before
anything is proposed for commit.

### 5. Hand back

Stop at "ready to commit". List what is staged or stageable, the classification table, and the
draft replies. The user commits, pushes, and decides which threads get resolved. See the global
git rules: no commit, push, or thread resolution without explicit approval in the current turn.

### 6. Reply

Once approved, reply on each thread: one or two sentences, the classification, and the commit or
evidence that backs it. Resolve only the threads the user names.

## Red flags

- Agreeing with a comment without opening the file it cites.
- Fixing several unrelated findings in one change.
- Resolving a thread the user did not confirm.
- Pushing before the check gates are green.
- Answering an unclear comment with a guess instead of a question.
