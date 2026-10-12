---
name: pr-review
description: >
  Use when reviewing someone else's pull request: re-check the unresolved review threads against
  the latest code, review the diff, and draft severity-sorted comments (summary + inline) that are
  posted only after explicit user approval.
  Trigger for: "review PR 123", "review this pull request", "re-review the PR", "check the
  comments were addressed", "draft review comments for this PR".
  NOT for addressing feedback on your own PR (use pr-triage), NOT for an architect challenge on
  scale, monitoring, or design (use pr-challenge), NOT for reviewing an uncommitted local diff
  (use the *-review agents), and NOT for opening or updating a PR.
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
gh pr view <pr> -R <owner>/<repo> --json number,author,headRefOid,baseRefName,isCrossRepository,url
gh pr diff <pr> -R <owner>/<repo>
```

Record `headRefOid`: every file read and every inline comment is anchored to it.

#### Intent

Write the intent from the diff alone, before reading the title, the body, or any comment or
thread: the description must not shape it.

- 2 to 4 bullets: what the change does, and why it seems to do it.
- No `path:line`, no evidence, no verdict: what was understood, nothing more.

Then read the description:

```bash
gh pr view <pr> -R <owner>/<repo> --json title,body,comments,reviews
```

Score how well the title and body state that intent:

| Score | Meaning |
| --- | --- |
| 5 | Same intent, nothing missing |
| 4 | Same intent, minor omission |
| 3 | Same goal, but a notable change is not mentioned, or a claim is not visible in the diff |
| 2 | The described intent only partly matches the diff |
| 1 | The description contradicts the diff or is unrelated to it |
| n/a | Empty or template-only description |

Below 5, name the main gap: the single biggest difference between the intent and the
description, in one phrase (about 10 words). One gap only, the one that costs the most points.
Name the difference, never a verdict on the author.

| Gap kind | Example |
| --- | --- |
| Undeclared change | `also changes the default retry count, not mentioned` |
| Missing work | `claims docs update, none in the diff` |
| Different purpose | `described as a refactor, diff changes behavior` |
| Scope mismatch | `describes the full feature, diff is only the API layer` |
| Vague description | `says "fixes" without saying what` |

The intent bullets and the score are for the user: never posted.

At 3 or below, or n/a, draft a numbered comment asking the author to fix the description. At 4
or 5, no draft: a minor omission is not worth a comment.

- One sentence naming the gap, one asking for the update.
- The understood intent as bullets, so the author can confirm or correct it.
- No score: it reads as a grade.

```markdown
The description does not mention the default timeout change. Could you add it, so reviewers
and release notes see it? My reading of the diff:

- adds exponential backoff to the payment client
- raises the default timeout
```

The draft is not a finding: the summary does not count it. Once approved, it goes into the
review body (step 6).

#### Review threads

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
comments is truncated: say so in the report. Record the thread count and the total comment count
(thread comments, conversation comments, review bodies) for the freshness check in step 6.

Conversation comments and review bodies (`comments`, `reviews`) cannot be resolved: use them
only for dedupe in step 3.

#### Code source

Read files at the PR head, never from the user's working tree (it may be another branch). A local
clone is faster and allows grep and test runs, so look for one first:

1. The current directory, if `git remote get-url origin` points to `<owner>/<repo>`.
2. Otherwise ask the user for the path of a local clone, or "none".

With a clone, check out the head in a detached worktree in the scratchpad, never in the clone:

```bash
git -C <clone> fetch origin pull/<pr>/head
git -C <clone> worktree add --detach <scratchpad>/pr-<pr> <headRefOid>
git -C <scratchpad>/pr-<pr> rev-parse HEAD   # must equal headRefOid
```

Remove it after posting, or when the user stops: `git -C <clone> worktree remove <scratchpad>/pr-<pr>`.

Running PR code (repros, tests, installs) executes the author's code on this machine:

- Same-repository PR (`isCrossRepository` false): run it.
- Fork: ask first.
- Install with lifecycle scripts disabled (`npm ci --ignore-scripts`, `pnpm install --ignore-scripts`).

Without a clone, or if the fetch fails, read each file through the API:

```bash
gh api "repos/<owner>/<repo>/contents/<path>?ref=<headRefOid>" -H "Accept: application/vnd.github.raw"
```

### 2. Re-review open threads

Resolved threads are skipped here and kept for dedupe in step 3. Bot threads are re-reviewed like
any other: a review bot is often the main reviewer.

Threads opened by the PR author are skipped, unless another participant replied: then re-review
the thread against that reply.

A thread resolved with no reply and not outdated (`isResolved`, `!isOutdated`, a single comment)
may have been closed without a fix. Read the code: if the concern still holds, list it under
**Notes for you** so the user can decide. If it was fixed, drop it silently.

For each remaining unresolved thread, read the code at its path at `headRefOid` (for an outdated
thread, the file's current content, not the old line) and mark it:

| Status | Meaning | Draft |
| --- | --- | --- |
| **addressed** | The latest code fixes the concern | None, list it so the user can resolve |
| **not addressed** | The concern still holds | A short reply on the thread |
| **unclear** | Partially fixed, or the change moved the concern | A question on the thread |

Cite file and line for every status.

On a thread opened by another reviewer, draft a reply only when it adds evidence the thread lacks
(a new `path:line`, a consequence the reviewer did not name). A reply that only restates the ask
is noise: list the thread with its status and no draft.

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
- No style nits a formatter or linter would catch.

Dedupe check, for each candidate finding before it enters the report: list every thread (resolved
or not), conversation comment, and review body on the same path or topic. Drop the finding if one
already raises it, or if it would undo what a thread asked for and got. Record each drop under
**Checked and dropped**.

A resolved thread whose concern still holds at `headRefOid`, fully or in part, does not cover the
finding: nobody acts on a resolved thread. List it under **Notes for you** with the thread and the
`path:line`, never under **Checked and dropped**.

### 4. Report

One block per item, draft right under it. Numbered continuously across sections, so one number
addresses one draft. Only postable items get a number.

```markdown
## Intent

- Understood:
  - <what the change does>
  - <why it seems to do it>
- Description match: 3/5
- Main gap: <one phrase, omitted at 5, `no description` at n/a>

1. description · <main gap>
   Draft: "..."

## Open threads

2. not addressed · <reviewer> · `path:line`
   Evidence: `path:line` still ...
   Draft: "..."

Nothing to post:
- addressed · `path:line` · evidence (the user can resolve it)
- not addressed, no new evidence · <reviewer> · `path:line`

## New findings

3. 🟡 medium · `path:line` · <title>

   🟡 medium: <title>

   - Risk: what can go wrong
   - Impact: who or what is affected, and how badly
   - Fix: the concrete change
   - Repro: `call(...)` returns X, expected Y (only when run)

## Checked and dropped

- <suspected issue>: why it does not hold, or which thread already covers it

## Notes for you

- head `<headRefOid>`, N threads read, code source (worktree or API)
- review states, threads resolved without a fix, skipped author threads worth a look

## Summary comment

<the draft summary, posted as the review body>
```

New findings are sorted by severity, one emoji each: 🔴 critical > 🟠 high > 🟡 medium >
⚪ low. The draft is the comment text as posted: severity line, then Risk, Impact, and Fix, one
sentence each (about 25 words). Evidence the author does not need to act (runtime source lines,
private symbols) goes to **Notes for you**. A finding confirmed by running code gets a `Repro:`
bullet: one line of code, its result, and the expected result. A finding outside the diff has no
number: it goes into the summary comment.

Thread replies stay 1 to 2 sentences, no severity block.

Draft style: direct, specific, one issue per comment, no praise padding, no hedging. Example:

```markdown
🟠 high: invoice lookup has no ownership check

- Risk: `userId` comes from the query string and is used without an ownership check
- Impact: any user can read another user's invoices
- Fix: load the invoice scoped to `current_user`
```

The summary comment is for the PR author, not a log of the review:

- Verdict in one line: `Blocking: <reason>`, `Non-blocking: <reason>`, or `No issues found`.
  Never "Approve" or "Request changes": those are review states the user sets.
- Finding counts per severity, and open threads by status.
- Out-of-diff follow-ups.

Thread bookkeeping (counts read, resolved-without-reply, skipped threads) goes to **Notes for
you**, never to the summary.

### 5. Validate

Stop and wait. The user answers with:

- `post all` / `post 1,3,5` / `post summary`
- `edit 2: <new text>`, then show the edited draft again
- `drop 4`

The summary counts and cites only findings that reach the PR, in the same review or earlier.
Rebuild it (severity counts, verdict, references to inline comments) and show it again:

- after a `drop`
- when a `post` names the summary but leaves some findings unposted

A changed summary needs a new `post`.

Nothing else is a posting instruction. If unsure, ask.

### 6. Post

Freshness check, before posting: re-read `headRefOid` and re-run the thread query and
`gh pr view --json comments,reviews`. If the head, the thread count, or the comment count changed
since step 1, stop: re-gather, re-review what is new, and re-validate.

Post the approved inline findings, description draft, and summary as one review with `event: COMMENT`: one
notification for the author instead of one per comment. Write each payload to a JSON file in the
scratchpad (never inline shell strings: multi-line text and backticks break quoting):

```bash
# review.json:
# {"commit_id": "<headRefOid>", "event": "COMMENT", "body": "<summary>",
#  "comments": [{"path": "<path>", "line": <line>, "side": "RIGHT", "body": "<draft>"}]}
gh api repos/<owner>/<repo>/pulls/<pr>/reviews --input review.json

# Reply on an open thread (databaseId of the thread's first comment), one call per reply
# reply-N.json: {"body": "..."}
gh api repos/<owner>/<repo>/pulls/<pr>/comments/<id>/replies --input reply-N.json
```

`body` is required with `event: COMMENT`. It is the approved summary, then the approved
description draft. With neither approved, use `Inline comments at <headRefOid>`.

Before posting, check that every inline `line` falls inside a hunk of `gh pr diff`. GitHub rejects
the whole review if one line is outside the diff: nothing is posted, so report which comment and
ask whether to fold it into the summary. Report the URL of the review and of each reply.

## Red flags

- Posting, replying, or resolving anything without an explicit `post` command this turn.
- Writing the intent after reading the title, body, or comments.
- Posting the description score.
- Marking a thread "addressed" without reading the code at `headRefOid`.
- Reading files from the user's working tree instead of a worktree at the PR head.
- Reviewing a partial thread list because pagination stopped early.
- Posting after new threads or comments appeared since the gather.
- Re-raising a point an existing thread or comment already covers.
- Dropping a finding as covered by a resolved thread whose concern still holds.
- A summary that counts or cites findings that are not posted.
- Running code from a fork without asking, or installing with lifecycle scripts enabled.
- A finding that undoes what a resolved thread asked for.
- A reply on another reviewer's thread that only restates the ask.
- A finding without risk, impact, and fix.
- Inline comments anchored to a stale commit.
- Resolving `{owner}`/`{repo}` from the current directory when the PR lives elsewhere.
