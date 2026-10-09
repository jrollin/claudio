# Report template

## Writing

- One fact per line:
  - a field with one fact stays inline: `- Cost: one new monitor`
  - a field with 2+ facts keeps its label alone, with one sub-bullet per fact
- No semicolon chain, in a bullet or a table cell.
- A table cell holds a value, a name, or a condition. The reasoning lives in the challenge.
- One question per challenge.
- Cut any fact the question does not need.

## Monitoring status

| Status | Meaning |
| --- | --- |
| `covered` | An alert fires on this failure |
| `partial: <n>` | An alert exists, but misses this failure |
| `missing: <n>` | No alert |

`<n>` names the challenge about that row. With no such challenge, drop the pointer.

## Local report

```markdown
## Context

- Intent: <what the PR does, one line>
- Trigger: <route, job, consumer> · `path:line`
- Runs on: <runtime and limits>
- Data: <stores, sizes, capacity limits>
- Downstream: <services and limits>
- Consumers: <who reads what it writes>
- Decisions: <ADRs, docs, tickets that constrain it>

## Volumes

Window: <one window for every measured value>

| Quantity | Value | Source |
| --- | --- | --- |
| Peak requests | 40/s | measured: APM, `<query>`, peak hour |
| Runs per hour | 12 | stated: cron at `path:line` |
| Rows per hour | about 6k | derived: batch of 500 at `path:line` × 12 runs |
| Retry wait per call | 0.4 to 0.8 s | derived: 50 ms × (1+2+4+8), jitter 0.5 to 1× |
| Growth | unknown | question 1 |

## Monitoring

| New behavior | Signal that proves it works | Alert when it fails | Status |
| --- | --- | --- | --- |
| `POST /exports` | `exports.created` counter · `path:line` | none | missing: 2 |

## Open questions

1. <a missing number or constraint, one line>

## Challenges

### Now

2. <Lens> · <title> · <`path:line` or component>

   - Observation: <what the PR adds or changes>
   - Why it matters here:
     - <consequence tied to a volume or a threshold>
     - <second fact, only when needed>
   - Suggestion: <the change>
   - Cost: <what adopting it takes>
   - Question: <one question for the author>

### At 10x

3. <Lens> · Antipattern: <known name> · <`path:line` or component>

   - Observation: <what the PR adds or changes>
   - Why it matters here: <consequence tied to a volume or a threshold>
   - Acceptable when: <the condition>
   - Suggestion: <the change>
   - Cost: <what adopting it takes>
   - Question: <one question for the author>

### Later

4. <Lens> · Best practice: <name> · <`path:line` or component>

   - Observation: <what the PR does instead>
   - Why it matters here: <consequence tied to a volume or a threshold>
   - How here: <the change, with the existing example at `path:line` when one exists>
   - Cost: <what adopting it takes>
   - Question: <one question for the author>

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

## Draft comment

For the PR author. Same numbers and fields as the local report, without the context map, the
source tags, **Considered, not raised**, or **Notes for you**. Omit an empty section.

```markdown
Architecture challenge at <short sha>: scale, operations, and design questions, not a correctness review.

### Numbers these challenges rest on

Measured over <window>. Correct me where they are wrong.

| Quantity | Value |
| --- | --- |

### Monitoring

| New behavior | Signal that proves it works | Alert when it fails | Status |
| --- | --- | --- | --- |

### Open questions

1. ...

### Challenges

#### Now

2. ...

#### At 10x

#### Later
```

The numbers table holds every value a challenge rests on (`derived`, `measured`, or `stated`),
except stated values the PR itself shows. Any other number used in a challenge but missing
from the table is added to it, or cut. Drop the "Measured over" sentence when no value is
measured.
