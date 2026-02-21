---
name: event-modeling-spec
description: Use when designing systems with Event Modeling methodology, creating event models, or when user mentions event modeling, commands/events/views blueprints, system timeline design, or CQRS system design workshops.
---

# Event Modeling

Produces a single visual blueprint of an entire system — one timeline read left-to-right that developers, designers, and stakeholders all share.

## 2 Core Ideas

1. **Events on a timeline** — The system is a sequence of business facts persisted over time. Events are the source of truth.
2. **State for UIs** — Users see views (screens, reports) built from events, not events directly.

## 4 Building Blocks

| Block | Color | What it is |
|-------|-------|------------|
| **Trigger** | White | What starts a use case: UI wireframe, HTTP endpoint, or robot. Start simple — a named white box is enough |
| **Command** | Blue | An intention to change state, with parameters |
| **Event** | Orange | A business fact persisted. Past tense, business language, realistic data. *Most important piece* |
| **View** | Green | A read-only query that curates event data for a UI, report, or automated process |

**Not in the blueprint:** Aggregates, entity diagrams, database schemas — those are implementation details.

## Slicing

A **slice** = the smallest implementable unit. Each pattern instance is one slice:
- One Command + its Events = 1 slice
- One View = 1 slice
- One Automation or Translation = 1 slice

## 4 Patterns

### Internal

**Command** — User changes something: `Trigger → Command (blue) → Event(s) (orange)`
Multiple roles can trigger the same command (e.g., Role 1 via UI, Role 2 via API).

| Section | Include |
|---------|---------|
| Trigger | ✅ UI wireframe or API endpoint |
| Command | ✅ with parameters |
| Event(s) | ✅ produced by the command |
| View | — |

**View** — User sees something: `Event(s) (orange) → View (green) → Trigger`
Views are **passive** — they read and curate events, never reject them.

| Section | Include |
|---------|---------|
| Trigger | ✅ UI or API response |
| View | ✅ with source events and fields |
| Command | — |
| Event(s) | — (listed as View sources) |

### External Communication

**Automation** — System reacts (we reach out): `Event(s) → Todo-list View → 🤖 Robot → Command → Event(s)`

The todo-list is a view that shows unprocessed items. A row appears when Event A exists without Event B for the same ID (e.g., "PaymentAuthorized where PaymentCaptured missing"). The robot reads each row, calls one command. The produced event (Event B) causes the row to disappear — guaranteeing each item is processed exactly once. **No business logic in the robot** — it just reads and calls.

| Section | Include |
|---------|---------|
| Trigger | — (robot is the actor) |
| Todo-list view | ✅ what populates it, what removes a row |
| Robot | ✅ named (e.g., "Payment Capturer") |
| Command | ✅ called by the robot |
| Event(s) | ✅ produced, removes the row |

**Translation** — External system notifies us: `Event(s) [source] → View → 🤖 Translator → Command → Event(s) [ours]`
Same structure as Automation but crosses system boundaries: an external system's events are the source. **Read side: one source system only. Write side: can publish to multiple via Pub/Sub.**

| Section | Include |
|---------|---------|
| Same as Automation, plus: | |
| External source | ✅ which system and event type |

**Key distinction:** Automation = we reach out. Translation = they notify us.

*Example Translation:* Stripe emits `payment_intent.succeeded` → Todo view "UnprocessedStripePayments" → 🤖 Stripe Translator → `RecordPayment` → `PaymentRecorded` in our domain.

## Swim Lanes

A **swim lane** is a horizontal row on the board representing a **domain** (e.g., Booking, Payment, Inventory). Events sit on their domain's lane.

During the workshop, lanes evolve:
- **Step 3:** Start with lanes per user role (Guest, Admin, Front Desk)
- **Step 5–6:** Reorganize by domain/bounded context. Assign team ownership per lane

A lane can have sub-domains (e.g., "Loyalty" within "Guest") — note these in the Swim Lane Ownership table.

## 7-Step Workshop

| Step | Action |
|------|--------|
| 1. **Brainstorm** | List all state-changing events. Filter out observations ("Guest viewed page" is NOT an event) |
| 2. **Plot** | Arrange events left-to-right in chronological order of a typical user journey |
| 3. **Storyboard** | Add wireframes at top. What does each role see at each moment? |
| 4. **Identify Inputs** | For each wireframe action, add a Command (blue) connecting the trigger to the produced Event(s) |
| 5. **Identify Outputs** | For each screen that displays data, add a View (green) connecting source Events to the trigger |
| 6. **Conway's Law** | Reorganize lanes by domain/bounded context. Assign team ownership |
| 7. **Specifications** | Write Given-When-Then for every slice (see below) |

## Specifications (Step 7)

Every slice gets a specification — the contract for implementation. Use **realistic data**, never placeholders.

**Command:** Given (prior events = preconditions) → When (command) → Then (produced event)
**View:** Given (accumulated events) → Then (query result)
**Automation:** Given (todo list rows) → When (robot calls command) → Then (event produced, row removed)

**Failure cases:** When a command's preconditions aren't met (Given events don't exist), the command is rejected. Failure events (e.g., `PaymentDeclined`) are optional — model them as separate Command slices only if the system needs to react to the failure.

## Completeness Check

After modeling, verify:
- Every UI field traces to an event (origin) or view (destination)
- Every command has a Given-When-Then with realistic data
- Every view has a Given-Then specification
- Every automation has a named todo-list view, a named robot, and a produced command
- No orphan events (events nothing reads)

## Output

Generate the event model document using `references/output-template.md`. The document includes a reader preamble so stakeholders unfamiliar with Event Modeling can understand the notation.

## Reference

| Reference | Load When |
|-----------|-----------|
| `references/output-template.md` | Generating an event model document — template with reader preamble, per-pattern section guide, and slice format |
| `references/event-model-example.md` | Full Hotel Booking example — 18 slices across 5 swim lanes with completeness check |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Including observations as events | Only persist facts that mutate state |
| Skipping wireframes — jumping to events | Always start from UI (Step 3 before Step 4) |
| Using DDD aggregates or entity diagrams | Event Modeling uses swim lanes by domain, not aggregates |
| Business logic in the automation robot | Robot reads todo and calls command. Logic lives in handler |
| Views that validate or reject | Views are passive — they only read and curate |
| Missing specifications with realistic data | Every slice needs Given-When-Then with concrete values |
| Automation vs Translation confusion | Automation = we reach out; Translation = they notify us |
| Trigger section on Automation slices | Automations have no user trigger — the robot is the actor. Omit the Trigger section |

## External References

- https://eventmodeling.org/posts/what-is-event-modeling/
- https://eventmodeling.org/posts/event-modeling-cheatsheet/
