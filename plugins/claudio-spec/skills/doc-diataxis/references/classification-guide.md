> Reference for: Diátaxis
> Load when: Author Step 1 (Diagnose), Audit Step 2 (Map each doc to a quadrant)

# The Compass: Choosing a Quadrant

Diátaxis organizes documentation by **user need at the moment they reach for the doc**, not by topic. The same topic ("authentication") produces a different doc in each quadrant. To classify, diagnose the reader's situation against two axes.

## The two axes

```
                 ACQUISITION (study)         APPLICATION (work)
                 "I am learning"             "I have a goal"
              ┌─────────────────────────┬─────────────────────────┐
   ACTION     │      TUTORIAL           │     HOW-TO GUIDE         │
  "I am doing"│  learning by doing      │  achieving a real task   │
              ├─────────────────────────┼─────────────────────────┤
  COGNITION   │     EXPLANATION         │      REFERENCE           │
 "I am thinking"│ understanding the why │  looking up the facts    │
              └─────────────────────────┴─────────────────────────┘
```

- **Acquisition vs. application** — is the reader *studying* (building skill/understanding, no concrete goal yet) or *working* (has a specific goal right now)?
- **Action vs. cognition** — does the reader need to *do* something (hands on the keyboard) or *think* about something (build a mental model / find a fact)?

## Diagnostic questions

Answer these about the reader, in order:

1. **Does the reader already have a goal?**
   - No, they're learning the territory → top-left half (Tutorial or Explanation)
   - Yes, they came with a task or a question → top-right half (How-to or Reference)

2. **Do they need to act or to think?**
   - Act (run commands, build something) → Tutorial or How-to
   - Think (understand or look up) → Explanation or Reference

3. **Combine:**

| Goal? | Act or think? | → Type |
|-------|---------------|--------|
| No (learning) | Act | **Tutorial** |
| No (learning) | Think | **Explanation** |
| Yes (working) | Act | **How-to guide** |
| Yes (working) | Think | **Reference** |

## Fast signals (what the request usually means)

| The user says… | Likely type |
|----------------|-------------|
| "Get started", "your first…", "learn", "walk me through it" | Tutorial |
| "How do I…", "configure X to…", "deploy with…", "integrate…" | How-to guide |
| "What are the options/params/flags", "list of…", "the API for…" | Reference |
| "Why does…", "how does X work", "the design behind…", "trade-offs" | Explanation |

These are signals, not rules. Confirm against the diagnostic questions — phrasing lies (a "tutorial" request from someone with a specific production goal is really a how-to).

## Topic vs. type: the fan-out

A topic is not a doc type. Most substantial topics need more than one doc. Example — **"User authentication":**

| Doc | Type | Serves |
|-----|------|--------|
| "Build your first authenticated app" | Tutorial | A newcomer learning the system by doing |
| "How to add OAuth login to an existing app" | How-to | A developer with that exact goal |
| "Auth API: endpoints, scopes, token fields" | Reference | A developer who needs the facts mid-task |
| "How our token model works and why" | Explanation | Someone deciding whether/how to adopt it |

When a request names a topic, expect to produce 2–4 docs. Diagnose which are actually needed — don't manufacture all four if only two have an audience.

## The merge trap (why separation matters)

The most common documentation failure is one doc serving two needs. Each pairing fails a specific way:

- **Tutorial + Reference** — the learner drowns in options they don't need yet; the looker-upper can't find the fact under the narrative.
- **How-to + Explanation** — the worker wanted steps, now wades through theory; the understander wanted the why, gets a recipe.
- **Tutorial + Explanation** — the learner doing the steps is interrupted to think; momentum breaks.
- **Reference + How-to** — facts get buried in procedure; the procedure gets cluttered with exhaustive options.

When you spot a doc doing two jobs, the fix is always **split**, never trim. Link the resulting docs to each other.

## Worked classifications

- *"Document how to reset a password"* → has a goal, needs to act → **How-to**. (A reference of the password-policy fields may also be warranted.)
- *"Explain our caching strategy"* → wants understanding, thinking not doing → **Explanation**.
- *"List all CLI flags"* → working, needs facts → **Reference**.
- *"Help a new user make their first API call"* → learning, doing → **Tutorial**.
- *"Document the webhooks feature"* → topic, fans out → likely **Reference** (event types, payloads) + **How-to** (register a webhook) + maybe **Explanation** (delivery/retry model).
