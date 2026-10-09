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
  - a pre-existing problem the PR does not worsen goes to **Considered, not raised**
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
| Data | Which stores it reads and writes, and how big they are? | • models and migrations<br>• queries |
| Downstream | Which services or APIs it calls, and their rate, timeout, and quota limits? | • clients<br>• SDK config |
| Consumers | Who reads what it writes: events, API responses, tables? | • event schemas<br>• API contracts<br>• other repos named in docs |
| Signals | Which metrics, logs, traces, monitors, and alerts already cover it? | • instrumentation code<br>• monitors as code<br>• dashboard config |
| Decisions | Which ADRs, design docs, or tickets constrain it? | • `docs/` and ADR folders<br>• PR body and linked issues |

Cartog indexes the clone's working tree, not the PR head: confirm in the worktree any caller the
PR changes.

### 3. Size it

List candidate challenges with a first pass of the lenses in step 4, then size the quantities
they rest on: peak requests per second, rows per call and per tenant, payload size, fan-out per
call, growth per month, retention. Every value carries a source tag:

| Tag | Meaning |
| --- | --- |
| `measured` | Read from a live tool, with the query and window cited |
| `stated` | Written in code, config, the PR, a ticket, or a doc, or given by the user in chat, with the reference cited |
| `derived` | Computed from `measured` or `stated` values, with the computation shown |
| `unknown` | Becomes an open question for the author |

Live sources, when one is connected (MCP or CLI):

- Observability (APM, metrics, logs), read-only, no need to ask:
  - take the service name from config (service tag, IaC), never guess it
  - use the peak hour over the last 30 days
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

Run each lens over what the PR adds or worsens. Skip a lens with nothing specific to say.

| Lens | Ask | Signals in code |
| --- | --- | --- |
| Volumetry | • What is N per call, per tenant, in total?<br>• How fast does it grow?<br>• How long is it kept? | • unbounded load into memory<br>• per-tenant fan-out<br>• new table with no retention |
| Scalability | • What breaks first at 10x: CPU, memory, connections, a lock, a hot key, a downstream limit?<br>• Does it scale out? | • in-process state or cache<br>• global lock<br>• single partition key<br>• one job looping over all tenants |
| Performance | • Is it on a user-facing path?<br>• What is its latency budget?<br>• Could the work be async? | • sync remote call in a request<br>• serial calls that could run together<br>• heavy work in a hot loop |
| Monitoring | • How will we know it works?<br>• How fast will we know it breaks?<br>• Which alert fires, and who gets paged? | • new job, endpoint, or consumer with no metric<br>• errors logged but not counted<br>• dead-letter queue with no alarm |
| Failure modes | • What happens when a dependency is slow, down, or wrong?<br>• Is a retry safe?<br>• What is the blast radius? | • no timeout<br>• retry with no backoff or cap<br>• non-idempotent write on an at-least-once consumer<br>• partial write with no compensation |
| Data lifecycle | • Does the migration lock a large table?<br>• Who backfills?<br>• Can it roll back without data loss?<br>• Do old and new code share the schema during deploy? | • column renamed in one step<br>• NOT NULL added on a large table<br>• destructive migration<br>• no purge |
| Cost | • What does one call cost?<br>• What does it cost at 10x? | • paid API call per item<br>• log line per item on a hot path<br>• high-cardinality metric tag<br>• unbounded storage growth |
| Alternatives | • Is there a simpler or better-placed design at this volume? | • rebuilds an existing component<br>• sync call where an event fits<br>• logic in the wrong service |

Fill the Monitoring table for every new behavior (endpoint, job, consumer, external call), even
when no challenge results. A log line nobody queries is not monitoring.

Two kinds of challenge carry extra fields:

- Antipattern:
  - name the pattern in the title (N+1 across services, dual write without outbox, retry storm,
    chatty I/O, shared database between services, polling where an event exists, distributed
    monolith)
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
- Check the existing comments: a question already answered on the PR is dropped.
- Rank it by horizon:
  - `now`: hurts at today's volume
  - `10x`: hurts at plausible growth, with the growth named
  - `later`: debt in operations, cost, or evolvability
- Keep at most 8 challenges:
  - zero is a valid result
  - weaker ones go to **Considered, not raised**, since more challenges dilute the strong ones

### 5. Report

Number items continuously across Open questions and Challenges, so one number addresses one
item. Numbers stay stable after a `drop`: gaps are fine. Each bullet is one sentence.

```markdown
## Context

- Intent: <what the PR does, one line>
- Trigger: <route, job, consumer> · `path:line`
- Runs on: <runtime and limits>
- Data: <stores and sizes>
- Downstream: <services and limits>
- Consumers: <who reads what it writes>
- Decisions: <ADRs, docs, tickets that constrain it>

## Volumes

| Quantity | Value | Source |
| --- | --- | --- |
| Peak requests | 40/s | measured: APM, `<query>`, peak hour over 30 days |
| Runs per hour | 12 | stated: cron at `path:line` |
| Rows per hour | about 6k | derived: batch of 500 at `path:line` × 12 runs |
| Growth | unknown | question 1 |

## Monitoring

| New behavior | Signal that proves it works | Alert when it fails | Status |
| --- | --- | --- | --- |
| `POST /exports` | `exports.created` counter · `path:line` | none found | missing: challenge 2 |

## Open questions

1. <a missing number or constraint, one line>

## Challenges

### Now

2. <Lens> · <title> · <`path:line` or component>

   - Observation: <what the PR adds or changes>
   - Why it matters here: <consequence tied to a volume or a threshold>
   - Suggestion: <the change>
   - Cost: <what adopting it takes>
   - Question: <what the author should answer>

### At 10x

3. <Lens> · Antipattern: <name> · <`path:line` or component>

   - Observation: <what the PR adds or changes>
   - Why it matters here: <consequence tied to a volume or a threshold>
   - Acceptable when: <the condition>
   - Suggestion: <the change>
   - Cost: <what adopting it takes>
   - Question: <what the author should answer>

### Later

4. <Lens> · Best practice: <name> · <`path:line` or component>

   - Observation: <what the PR does instead>
   - Why it matters here: <consequence tied to a volume or a threshold>
   - How here: <the change, with the existing example at `path:line` when one exists>
   - Cost: <what adopting it takes>
   - Question: <what the author should answer>

## Considered, not raised

- <candidate>: why it does not hold here (bounded volume, handled at `path:line`, pre-existing
  and not worsened)

## Notes for you

- head `<headRefOid>`
- code source: worktree, scratchpad clone, or API
- live tools queried, with their windows
- entry points left out of the map
- correctness bugs spotted on the way, to raise with `pr-review`

## Draft comment

<the comment as posted>
```

The draft comment is for the PR author:

- First line: `Architecture challenge at <short sha>: scale, operations, and design questions, not a correctness review.`
- The `derived` volumes the challenges rest on, so the author can correct them.
- The Monitoring table.
- Open questions, then challenges by horizon, with the same numbers.
- No context map, no source tags, no **Notes for you**.
- Never a tenant or customer identifier.
- In a public repository, ask before including `measured` production figures.

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
- A challenge about a pre-existing problem the PR does not worsen.
- One challenge per line where one pattern explains them all.
- A generic challenge that would fit any PR, or one added to reach a count.
- A number with no source tag, or a `derived` number with no computation shown.
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
