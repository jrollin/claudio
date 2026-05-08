> Reference for: Event Modeling
> Load when: Generating an event model document from a workshop or design session

# Output Template

The generated event model document serves two audiences:
- **Stakeholders and developers** reading it to understand the system design
- **Agents** (event-modeling-tasks) consuming it to generate implementation tasks

It must include a preamble so readers unfamiliar with Event Modeling can understand the notation.

## Per-Pattern Section Guide

Not every slice has the same sections. Use this table:

| Section | Command | View | Automation | Translation |
|---------|---------|------|------------|-------------|
| **Trigger** | ✅ UI/API + role | ✅ UI/API + role | — (robot is actor) | — (robot is actor) |
| **Command (blue)** | ✅ | — | ✅ (called by robot) | ✅ (called by translator) |
| **Event(s) (orange)** | ✅ produced | — (listed as View sources) | ✅ produced, removes todo row | ✅ produced in our domain |
| **View (green)** | — | ✅ with source events | — | — |
| **Todo-list view** | — | — | ✅ what populates/depopulates | ✅ what populates/depopulates |
| **Robot** | — | — | ✅ named | ✅ named ("Translator") |
| **External source** | — | — | — | ✅ system + event type |
| **Specification** | Given-When-Then | Given-Then | Given-When-Then | Given-When-Then |

## Template

````markdown
# <System Name> — Event Model

## How to Read This Document

This document describes the system as a **timeline of events** — business facts that happen over time. Everything the system does is captured in **slices**, each representing one feature or use case.

### Building Blocks

| Block | Color | What it is |
|-------|-------|------------|
| **Trigger** | White | What starts a use case: a UI screen, an API endpoint, or an automated process |
| **Command** | Blue | An intention to change system state, with parameters |
| **Event** | Orange | A business fact that happened and was persisted. Past tense, business language |
| **View** | Green | A read-only query that presents data from events for a screen, report, or process |

### Patterns

Each slice follows one of four patterns:

- **Command** — A user or API triggers a state change: `Trigger → Command → Event(s)`
- **View** — Events are projected into a query result: `Event(s) → View → Trigger`
- **Automation** — The system reacts automatically via a todo-list: `Event(s) → Todo View → 🤖 Robot → Command → Event(s)`. A row appears when Event A exists without Event B. The robot processes each row. The produced event (Event B) removes the row — guaranteeing each item is processed exactly once.
- **Translation** — An external system sends data that we translate into our domain: `External Event(s) → View → 🤖 Translator → Command → Event(s)`. Same mechanics as Automation, but the source events come from outside.

### Specifications

Every slice has a **specification** — the contract for implementation:

- **Commands** use Given-When-Then: what events already exist (preconditions) → what command is issued → what event is produced. If preconditions aren't met, the command is rejected.
- **Views** use Given-Then: what events exist → what the query returns
- **Automations** use Given-When-Then: what the todo list shows → what the robot calls → what event is produced (and the row disappears)

---

## Swim Lanes

| Lane | Domain | Description |
|------|--------|-------------|
| <name> | <domain> | <what this lane covers> |

---

## Slices

<!-- COMMAND PATTERN -->

### <Slice ID>: <Slice Name>
**Pattern:** Command
**Swim Lane:** <domain>

**Trigger:**
- Role: <who triggers this>
- UI: `[<wireframe description>]` or API: `<HTTP method> <endpoint>`

**Command (blue):**
```
<CommandName> {
  field: "realistic value"
}
```

**Event(s) (orange):**
```
<EventName> {
  field: "realistic value"
}
```

**Specification:**
> Given: <prior events with realistic data — or "(no prior events)" if none>
> When: <command with realistic data>
> Then: <produced event with realistic data>

---

<!-- VIEW PATTERN -->

### <Slice ID>: <Slice Name>
**Pattern:** View
**Swim Lane:** <domain>

**Trigger:**
- Role: <who sees this>
- UI: `[<wireframe description>]` or API: `<HTTP method> <endpoint>`

**View (green):**
```
<ViewName> {
  field: "realistic value"
}
```
Source events: <list of event types this view reads>

**Specification:**
> Given: <events with realistic data>
> Then: <expected query result with realistic data>

---

<!-- AUTOMATION PATTERN -->

### <Slice ID>: <Slice Name>
**Pattern:** Automation
**Swim Lane:** <domain>

**Todo-list view:**
```
<TodoViewName> {
  rows: [{ field: "value" }]
}
```
Feeds from: <Event A where Event B missing for same ID>

**Robot:** <Robot Name>

**Command (blue):**
```
<CommandName> {
  field: "realistic value"
}
```

**Event(s) (orange):**
```
<EventName> {
  field: "realistic value"
}
```

**Specification:**
> Given: Todo view "<TodoViewName>" shows [{ ... }]
> When: Robot calls <CommandName> { ... }
> Then: <EventName> { ... } — row removed from todo

---

<!-- TRANSLATION PATTERN -->

### <Slice ID>: <Slice Name>
**Pattern:** Translation
**Swim Lane:** <domain>

**External source:** <System name> emits `<ExternalEventName>`

**Todo-list view:**
```
<TodoViewName> {
  rows: [{ field: "value" }]
}
```
Feeds from: <ExternalEventName> where <DomainEventName> missing for same ID

**Robot:** <Translator Name>

**Command (blue):**
```
<CommandName> {
  field: "realistic value"
}
```

**Event(s) (orange):**
```
<DomainEventName> {
  field: "realistic value"
}
```

**Specification:**
> Given: Todo view "<TodoViewName>" shows [{ ... }]
> When: Translator calls <CommandName> { ... }
> Then: <DomainEventName> { ... } — row removed from todo

---

## Swim Lane Ownership

| Team | Lane | Slices |
|------|------|--------|
| <team name> | <lane> (sub-domain note if applicable) | <slice IDs and names> |

## Completeness Check

| Criterion | Status | Notes |
|-----------|--------|-------|
| Every UI field traces to an event (origin) or view (destination) | ✅/❌ | |
| Every command has a Given-When-Then with realistic data | ✅/❌ | |
| Every view has a Given-Then specification | ✅/❌ | |
| Every automation has a named todo-list view, named robot, and produced command | ✅/❌ | |
| No orphan events (events nothing reads) | ✅/❌ | |

## Summary

- **Total slices:** <N>
- **Patterns:** <N> commands, <N> views, <N> automations, <N> translations
- **Swim lanes:** <list>
- **Events:** <total count>
````

## Key Rules for Generating

1. **Preamble always included** — "How to Read This Document" must be in every generated event model
2. **Use the per-pattern section guide** — only include sections relevant to the pattern. Do not add Trigger to Automation/Translation. Do not add Todo-list to Command/View.
3. **Realistic data in specifications** — never use placeholders. Use concrete, plausible values
4. **One slice = one section** — do not combine or abbreviate slices
5. **Todo-list views: explain population and removal** — always state "Feeds from: Event A where Event B missing"
6. **Name every robot** — Automations and Translations must have a named robot
7. **Completeness check at the end** — verify every criterion
8. **Swim lane ownership** — assign slices to teams. Note sub-domains in parentheses if a lane has multiple owners
