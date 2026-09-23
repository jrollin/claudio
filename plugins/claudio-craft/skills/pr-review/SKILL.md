---
name: pr-review
description: >
  Use when reviewing someone else's pull request: re-check the unresolved review threads against
  the latest code, review the diff, and draft severity-sorted comments (summary + inline) that are
  posted only after explicit user approval.
  Trigger for: "review PR 123", "review this pull request", "re-review the PR", "check the
  comments were addressed", "draft review comments for this PR".
  NOT for addressing feedback on your own PR (use pr-triage), NOT for reviewing an uncommitted
  local diff (use the *-review agents), and NOT for opening or updating a PR.
---

# PR Review

Review a pull request as the reviewer: verify what is still open, find what is new, and draft
comments the user approves before anything reaches GitHub.

## Iron rule

**Never post, reply, or edit anything on GitHub without explicit approval in the current turn.**

- Approval is a command naming what to post (`post all`, `post 1,3`), not "looks good" or "ok".
- Approval covers only the numbered items named, in that turn. A later change re-requires it.
- Never resolve a thread, approve, or request changes. The user does that.

## Scope

- A PR number or URL in the request wins.
- Otherwise use the PR for the current branch (`gh pr view --json number`).
- No PR found: stop and ask, do not guess.
- Take `<owner>/<repo>` from the PR URL, never from the current directory: the PR may live in
  another repository. Pass `-R <owner>/<repo>` to every `gh pr` call and spell it out in every
  `gh api` path. `gh`'s `{owner}`/`{repo}` placeholders resolve to the current directory's repo.
- PR authored by the current user (`gh api user --jq .login`): say so, and offer `pr-triage` to
  address its feedback instead. Proceed with a self-review only if the user confirms.

## Workflow

### 1. Gather

```bash
gh pr view <pr> -R <owner>/<repo> --json number,title,body,author,headRefOid,baseRefName,url,comments,reviews
gh pr diff <pr> -R <owner>/<repo>
```

Record `headRefOid`: every file read and every inline comment is anchored to it.

Review threads need GraphQL: REST does not expose whether a thread is resolved. Page until
`hasNextPage` is false; never review a partial thread list.

```bash
gh api graphql -F owner=<owner> -F repo=<repo> -F pr=<pr> -F cursor=null -f query='
query($owner:String!,$repo:String!,$pr:Int!,$cursor:String){repository(owner:$owner,name:$repo){
pullRequest(number:$pr){reviewThreads(first:100,after:$cursor){
pageInfo{hasNextPage endCursor}
nodes{isResolved isOutdated path line
comments(first:50){nodes{databaseId author{login} body}}}}}}}'
```

Re-run with `-F cursor=<endCursor>` while `hasNextPage` is true. A thread with more than 50
comments is truncated: say so in the report.

Read files at the PR head, never from the local working tree (it may be another branch):

```bash
gh api "repos/<owner>/<repo>/contents/<path>?ref=<headRefOid>" -H "Accept: application/vnd.github.raw"
```

Or run `gh pr checkout <pr> -R <owner>/<repo>` first, with the user's agreement, and confirm
`git rev-parse HEAD` equals `headRefOid`.

Conversation comments and review bodies (`comments`, `reviews`) cannot be resolved: use them
only for dedupe in step 3.

### 2. Re-review open threads

Resolved threads are skipped here and kept for dedupe in step 3. Threads opened by the PR author
are skipped too. Bot threads are re-reviewed like any other: a review bot is often the main
reviewer.

One exception to skipping resolved threads: a thread resolved with no reply and not outdated
(`isResolved`, `!isOutdated`, a single comment) was closed without a fix or an answer. Do not
re-review it; list it in the summary so the user can decide.

For each remaining unresolved thread, read the code at its path at `headRefOid` (for an outdated
thread, the file's current content, not the old line) and mark it:

| Status | Meaning | Draft |
| --- | --- | --- |
| **addressed** | The latest code fixes the concern | None, list it so the user can resolve |
| **not addressed** | The concern still holds | A short reply on the thread |
| **unclear** | Partially fixed, or the change moved the concern | A question on the thread |

Cite file and line for every status.

### 3. Review the diff

One pass over the diff, in this order:

- Correctness: logic errors, edge cases, error handling, concurrency
- Security: injection, secrets, authorization, input validation
- Tests: new behavior and bug fixes covered, assertions that would catch a regression
- Quality: dead code, naming, error-message context, needless complexity
- Docs: README, specs, or inline docs left stale by the change
- Facts: claims about an external system (a schema, an index, an API, a count) checked against
  the live source when one read confirms them

Rules:

- Read the surrounding file at `headRefOid`, not only the hunk, before raising a finding.
- Comment only on lines the PR changed; pre-existing issues go to the summary as follow-ups.
- Do not raise what is already covered by a review thread (resolved or not), a conversation
  comment, or a review body.
- No style nits a formatter or linter would catch.

### 4. Report

Two sections, numbered continuously so one number addresses one draft:

1. **Open threads**, listed first: every re-reviewed thread with its status, `path:line`,
   evidence, and the draft reply for `not addressed` and `unclear`. `addressed` threads carry
   no number: nothing to post, the user resolves them.
2. **New findings**, sorted by severity: **critical** > **high** > **medium** > **low**.

For each new finding:

| Field | Content |
| --- | --- |
| Severity | critical / high / medium / low |
| Location | `path:line`, or `summary` when the line is outside the diff |
| Risk | What can go wrong |
| Impact | Who or what is affected, and how badly |
| Mitigation | The concrete fix |
| Draft | The comment text, 1 to 3 sentences |

Draft comment style: direct, specific, one issue per comment, a suggested fix, no praise padding,
no hedging. Example: "`userId` comes from the query string and is used without an ownership
check, so any user can read another user's invoices. Load the invoice scoped to
`current_user`."

End with the draft summary comment: verdict in one line, finding counts per severity, status of
open threads, threads resolved without a fix or reply, out-of-diff follow-ups.

### 5. Validate

Stop and wait. The user answers with:

- `post all` / `post 1,3,5` / `post summary`
- `edit 2: <new text>`, then show the edited draft again
- `drop 4`

Nothing else is a posting instruction. If unsure, ask.

### 6. Post

Before posting, re-read `headRefOid`. If it changed, stop: re-gather and re-validate.

Post only the approved items, as separate comments. Write each payload to a JSON file in the
scratchpad (never inline shell strings: multi-line text and backticks break quoting):

```bash
# Summary
gh pr comment <pr> -R <owner>/<repo> --body-file summary.md

# Inline comment on a changed line
# inline-N.json: {"body": "...", "commit_id": "<headRefOid>", "path": "<path>", "line": <line>, "side": "RIGHT"}
gh api repos/<owner>/<repo>/pulls/<pr>/comments --input inline-N.json

# Reply on an open thread (databaseId of the thread's first comment)
# reply-N.json: {"body": "..."}
gh api repos/<owner>/<repo>/pulls/<pr>/comments/<id>/replies --input reply-N.json
```

An inline comment GitHub rejects (line outside the diff) is not retried elsewhere: report it and
ask whether to fold it into the summary. Report the URL of each posted comment.

## Red flags

- Posting, replying, or resolving anything without an explicit `post` command this turn.
- Marking a thread "addressed" without reading the code at `headRefOid`.
- Reading files from the local working tree without checking it is the PR head.
- Reviewing a partial thread list because pagination stopped early.
- Re-raising a point an existing thread or comment already covers.
- A finding without risk, impact, and mitigation.
- Inline comments anchored to a stale commit.
- Resolving `{owner}`/`{repo}` from the current directory when the PR lives elsewhere.
