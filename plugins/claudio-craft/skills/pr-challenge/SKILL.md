---
name: pr-challenge
description: >
  Use when challenging a pull request from an architect's point of view: put the change in its
  production context (volumes, traffic, data, dependencies) and question its scalability,
  performance, monitoring, failure modes, data lifecycle, cost, antipatterns, and missing best
  practices. Assumes the code is correct and asks whether it holds at scale and over time. Drafts
  one review comment, posted only after explicit user approval.
  Trigger for: "challenge PR 123", "architect review of this PR", "review this PR as an
  architect", "will this PR scale?", "how will this PR be monitored?", "what happens to this PR
  at 10x?", "big-picture review of the PR", "challenge my PR before I ask for review".
  NOT for a line-level correctness review (use pr-review), NOT for addressing feedback on your own
  PR (use pr-triage), NOT for an uncommitted local diff (use the performance-review,
  observability-review, architecture-review, or infrastructure-review agents), and NOT for
  stress-testing a design before code exists (use spec-grill).
---

# PR Challenge

Review a pull request as an architect: assume the code does what it says, then ask what it does
to the system. Every challenge ties a fact in the code to a production context: a volume, a
dependency, a failure, a cost.

## Iron rule

**Never post anything on GitHub without explicit approval in the current turn.**

- Approval is a command naming what to post (`post all`, `post 1,3`), not "looks good" or "ok".
- A later change to the draft re-requires it.
- Never approve, request changes, or resolve threads. The user does that.

## Stance

- Challenge, don't verify:
  - correctness, style, and naming belong to `pr-review`
  - a bug spotted on the way goes to **Notes for you**
- The delta, not the system:
  - challenge what the PR adds or worsens against `baseRefName` (calls per request, rows, cost)
  - a pre-existing problem that limits the PR's stated goal is raised, scoped to that goal
  - any other pre-existing problem the PR does not worsen goes to **Considered, not raised**
- Patterns over lines: three new clients with no timeout make one challenge (no resilience
  policy), not three.
- Context over code: "what happens at N calls a second, on M rows, with dependency D down", not
  "is this line right".
- Specific, not generic: a challenge that would fit any PR ("add caching", "consider
  scalability") is dropped.
- Numbers, not adjectives: "loads every order of a customer (up to 200k rows) into memory", not
  "may not scale".
- Ask before you assert:
  - every challenge ends with a question
  - the author may know a constraint the code does not show

## Scope

- A PR number or URL in the request wins.
- Otherwise use the PR for the current branch (`gh pr view --json number`).
- No PR found: stop and ask, do not guess.
- Take `<owner>/<repo>` from the PR URL, never from the current directory: the PR may live in
  another repository.
- Pass `-R <owner>/<repo>` to every `gh pr` call, and spell it out in every `gh api` path.
- PR authored by the current user (`gh api user --jq .login`):
  - ask the open questions in chat and fold the answers in
  - the default output is the local report, and posting stays available
- Read-only: never run the PR's code.

## Workflow

### 1. Gather

```bash
gh pr view <pr> -R <owner>/<repo> --json number,title,body,author,headRefOid,baseRefName,url,files,additions,deletions,comments,reviews,closingIssuesReferences
gh pr diff <pr> -R <owner>/<repo>
gh api --paginate repos/<owner>/<repo>/pulls/<pr>/comments    # inline review comments
gh issue view <n> -R <issue-owner>/<issue-repo> --json title,body   # per linked issue
```

- Record `headRefOid`: every file read is anchored to it.
- The PR body and linked issues give the intent and, often, the expected volume.
- Tickets in other trackers come from links in the PR body.
- Note questions already asked or answered in comments and reviews, so the challenge does not
  repeat them.
- An earlier review starting with `Architecture challenge at`:
  - carry its unanswered items forward
  - drop the answered ones
- No runtime impact (docs, tests, comments, a rename that changes no call, query, or data): say
  so in one line and stop, with no draft.
- Several entry points or services:
  - map the context per entry point
  - keep the 3 with the highest traffic or risk
  - list the rest under **Notes for you**

#### Code source

Read code at the PR head, never from the user's working tree (it may be another branch). The
context map needs repo-wide search, so a clone matters more here than in a diff review.

1. Find a local clone: the current directory if `git remote get-url origin` points to
   `<owner>/<repo>`, otherwise ask the user for a path or "none".
2. No clone: offer a blobless clone in the scratchpad:

   ```bash
   gh repo clone <owner>/<repo> <scratchpad>/<repo> -- --filter=blob:none
   ```

3. Check out the head in a detached worktree in the scratchpad, never in the clone:

   ```bash
   git -C <clone> fetch origin pull/<pr>/head
   git -C <clone> worktree add --detach <scratchpad>/pr-<pr> <headRefOid>
   git -C <scratchpad>/pr-<pr> rev-parse HEAD   # must equal headRefOid
   ```

   `pr-review` uses the same path: reuse an existing worktree, checking out `headRefOid` in it
   when its HEAD differs.
4. Clone declined, or the fetch fails:
   - read each file through the API:
     `gh api "repos/<owner>/<repo>/contents/<path>?ref=<headRefOid>" -H "Accept: application/vnd.github.raw"`
   - mark unknown every context point that needs a search

Remove the worktree at the end of every run, posted or not, with
`git -C <clone> worktree remove <scratchpad>/pr-<pr>`. Remove the scratchpad clone too if this
run created it.

### 2. Map the context

Zoom out from the diff before judging it. Answer each point with evidence (`path:line`, a doc,
a config file), or mark it unknown.

| Point | Question | Where to look |
| --- | --- | --- |
| Trigger | What runs this code: HTTP route, job, queue or stream consumer, cron, CLI? | • routes and handlers<br>• IaC and schedules<br>• callers via cartog (`impact`, `refs`) or grep |
| Frequency | How often: per request, per tenant, per batch, on a schedule? | • trigger config<br>• cron expressions<br>• call sites |
| Runtime | Where it runs, with which concurrency, memory, and timeout limits? | • IaC<br>• container and function config |
| Data | Which stores it reads and writes, how big they are, and their capacity limits (throughput mode, partition or connection caps)? | • models and migrations<br>• queries<br>• IaC capacity settings |
| Downstream | Which services or APIs it calls, and their rate, timeout, and quota limits? | • clients<br>• SDK config |
| Consumers | Who reads what it writes: events, API responses, tables? | • event schemas<br>• API contracts<br>• other repos named in docs |
| Signals | Which metrics, logs, traces, monitors, and alerts already cover it? | • instrumentation code<br>• monitors as code<br>• dashboard config |
| Decisions | Which ADRs, design docs, or tickets constrain it? | • `docs/` and ADR folders<br>• PR body and linked issues |

Cartog indexes the clone's working tree, not the PR head: confirm in the worktree any caller the
PR changes.

### 3. Size it

Load `references/lenses.md` and list candidate challenges with a first pass of the lenses. Then
size the quantities they rest on: peak requests per second, rows per call and per tenant,
payload size, fan-out per call, growth per month, retention. Every value carries a source tag:

| Tag | Meaning |
| --- | --- |
| `measured` | Read from a live tool, with the query and window cited |
| `stated` | Written in code, config, the PR, a ticket, or a doc, or given by the user in chat, with the reference cited |
| `derived` | Computed from `measured` or `stated` values, with the computation shown |
| `unknown` | Becomes an open question for the author |

A `derived` value computed from a range stays a range: "4 to 8 s", not "~4 s".

Live sources, when one is connected (MCP or CLI):

- Observability (APM, metrics, logs), read-only, no need to ask:
  - take the service name from config (service tag, IaC), never guess it
  - use one window for every measured value, last 30 days by default, stated once
  - for traffic, take the peak hour in that window
  - a new endpoint or job has no traffic yet: measure its caller
- Production database:
  - ask the user before the first query
  - prefer planner statistics and table sizes over `count(*)` on a large table
  - use a read replica when one exists
  - never read rows

Unknown quantities:

- One that would flip a conclusion: ask the user before writing the challenges, all such
  questions in one message.
- One that stays unknown:
  - compute the threshold where the conclusion flips, from the code or the runtime limits
  - phrase the challenge as a condition: "15 min timeout at about 50 ms per tenant: above about
    18k tenants, the job times out"
- Never invent a number.

### 4. Challenge

Run each lens in `references/lenses.md` over what the PR adds or worsens. Skip a lens with
nothing specific to say.

Fill the Monitoring table for every new behavior (endpoint, job, consumer, external call), even
when no challenge results. A log line nobody queries is not monitoring.

Two kinds of challenge carry extra fields:

- Antipattern:
  - name a known pattern in the title (N+1 across services, dual write without outbox, retry
    storm, chatty I/O, shared database between services, polling where an event exists,
    distributed monolith)
  - no known name fits: frame it as a missing best practice instead
  - say why it hurts here, tied to a volume or a threshold
  - say when it would be acceptable
- Missing best practice:
  - name the practice in the title
  - say why it matters here
  - say how to apply it in this codebase, citing an existing example in the repo when one exists
  - give the cost of adopting it

Before a challenge enters the report:

- Check it against the context map: a timeout set in a shared client, or an alert defined in
  another repo, drops a "missing" challenge.
- Check it against measured values: a challenge built on a `stated` claim that a `measured`
  value contradicts becomes an open question.
- Check the existing comments: a question already answered on the PR is dropped.
- Rank it by horizon:
  - `now`: hurts at today's volume
  - `10x`: hurts at plausible growth, with the growth named
  - `later`: debt in operations, cost, or evolvability
- Keep at most 8 challenges:
  - zero is a valid result
  - weaker ones go to **Considered, not raised**, since more challenges dilute the strong ones

### 5. Report

Load `references/report-template.md`: writing rules, Monitoring status, local report, and draft
comment.

- Number items 1 to N across Open questions and Challenges, so one number addresses one item.
- Renumber on every rebuild, cross-references included. Commands refer to the last draft shown.
- The draft comment never holds a tenant or customer identifier.
- In a public repository, ask before including `measured` production figures in the draft.

### 6. Validate

Stop and wait. The user answers with:

- `post all` or `post 1,3,5` (only those items)
- `edit 2: <new text>`
- `drop 4`

After an edit, a drop, or a partial `post`, rebuild the draft comment and show it again. A
changed draft needs a new `post`.

Nothing else is a posting instruction. If unsure, ask.

### 7. Post

Freshness check: re-run `gh pr view --json headRefOid,comments,reviews` and the inline comments
call. If the head changed or new comments appeared:

- re-check each approved item against them
- show what changed
- re-validate

Post one review with `event: COMMENT` and no inline comments: a challenge is about the system,
rarely about one line. Build the payload with `jq` from the approved draft (hand-escaped JSON
breaks on multi-line markdown):

```bash
jq -n --rawfile body <scratchpad>/draft.md --arg sha <headRefOid> \
  '{commit_id: $sha, event: "COMMENT", body: $body}' > <scratchpad>/review.json
gh api repos/<owner>/<repo>/pulls/<pr>/reviews --input <scratchpad>/review.json
```

Report the review URL.

## Red flags

- Posting without an explicit `post` command this turn.
- A challenge about correctness, style, or naming.
- A challenge about a pre-existing problem the PR neither worsens nor depends on for its goal.
- One challenge per line where one pattern explains them all.
- A generic challenge that would fit any PR, or one added to reach a count.
- A number with no source tag, or a `derived` number with no computation shown.
- A number in the draft that its numbers table does not hold, unless the PR itself shows it.
- A challenge built on a `stated` claim that a `measured` value contradicts.
- A Monitoring status pointing to a challenge about another row.
- A field or table cell holding 2+ facts on one line.
- An antipattern named without why it hurts here.
- A best practice with no "how".
- A challenge with no question for the author.
- A new behavior missing from the Monitoring table.
- Flagging missing monitoring without checking the instrumentation and monitors in place.
- Querying a production database without asking, or reading rows.
- A tenant or customer identifier in the draft.
- More than 8 challenges.
- Reading files from the user's working tree instead of the PR head.
- Running the PR's code.
- Leaving the worktree behind.
