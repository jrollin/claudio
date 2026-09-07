---
name: writing-style
description: >
  Load an explicit writing style for prose: concise, bullet-first, straight to the point, no AI slop.
  Invoke only when asked: "/writing-style", "load the writing style", "apply my writing style",
  "rewrite this without AI slop", "make this concise", "review this text for slop".
  Applies to chat replies, docs, READMEs, specs, commit bodies, PR descriptions.
  NOT auto-triggered while writing docs, and NOT for code style (see quality-review) or grammar/spellcheck.
---

# Writing Style

Two modes. Pick from the request.

- **Write mode** — author new prose under these rules.
- **Review mode** — an existing text is supplied ("rewrite this", "review this text"): audit it against the rules, then output the rewrite.

## Rules

### Density

- Lead with the answer. No preamble, no restating the question.
- One idea per sentence. Cut every sentence that carries no new information.
- Bullets over paragraphs when listing 2+ items, comparing, or enumerating steps.
- Paragraphs only for a single connected argument.
- No summary section that repeats what was just said.
- Numbers, names, and paths beat adjectives: "3 retries, 200ms backoff", not "a robust retry policy".

### Tone

- Direct and factual. State it, don't sell it.
- Hedge only when genuinely uncertain, and say what the uncertainty is.
- No apologies, no enthusiasm markers, no self-congratulation.
- Never an em-dash. Use a comma, colon, parentheses, or a period.

### Banned patterns (AI slop)

| Pattern | Example | Fix |
| --- | --- | --- |
| Empty opener | "Great question!", "Certainly!" | Delete |
| Restating the ask | "You want to know how to X. Let me explain X." | Delete |
| Hollow intensifier | "seamlessly", "robust", "powerful", "comprehensive", "cutting-edge" | Delete or replace with the fact |
| Rule of three padding | "fast, reliable, and scalable" | Keep the one that matters |
| "It's not just X, it's Y" | "It's not just a linter, it's a workflow" | State what it is |
| "Let's dive in" / "Let's explore" | Transition filler | Delete |
| Meta-narration | "In this section, we will cover…" | Delete, the heading says it |
| Fake balance | "While X has benefits, it also has drawbacks" with no specifics | Name the actual tradeoff |
| Closing flourish | "Hope this helps!", "Happy coding!" | Delete |
| Over-qualification | "It's generally often the case that…" | Assert or state the condition |
| Emoji as decoration | "🚀 Deploy" | Delete unless the user's format uses them |
| Bold sprayed on nouns | "the **service** calls the **handler**" | Bold only a term being defined |
| Pseudo-heading label | `**Tenant isolation.** OSS has no row security…` | Promote to a real heading, one level below the section |

### Structure

- Headings when a doc has 3+ distinct sections. Not before.
- Tables for 3+ items compared on 2+ axes.
- Code blocks for anything a reader will copy.
- Front-load: conclusion, then evidence.

## Review mode

Run this pass, in order:

1. **Slop scan** — flag every hit from the banned-patterns table, quoting the span.
2. **Density pass** — mark sentences carrying no new information.
3. **Structure pass** — should a paragraph be bullets, or bullets be a table?
4. **Fact check** — flag adjectives that should be numbers or names.
5. **Rewrite** — output the corrected text.

Report findings compactly, then the rewrite:

```
## Findings
- L3 "seamlessly integrates" — hollow intensifier, say what it does
- L7-9 — restates the heading, delete
- L12 — paragraph of 4 parallel items, convert to bullets

## Rewrite
<text>
```

If the text is already clean, say so in one line and skip the rewrite.

## Self-check

Before returning any prose, verify:

- [ ] First sentence carries the answer
- [ ] No banned pattern from the table
- [ ] No em-dash
- [ ] Every adjective earns its place, or is a number instead
- [ ] Nothing repeated
