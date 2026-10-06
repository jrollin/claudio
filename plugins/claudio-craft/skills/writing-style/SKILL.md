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

- **Write mode**: author new prose under these rules.
- **Review mode**: an existing text is supplied ("rewrite this", "review this text"). Audit it against the rules, then output the rewrite.

## Rules

### Density

- Lead with the answer. No preamble, no restating the question.
- One idea per sentence. Cut every sentence that carries no new information.
- One idea per bullet: a bullet holding 2+ facts or sentences splits into sub-bullets,
  even when one sentence joins the facts with "and", "but" or a comma.
- Bullets over paragraphs when listing 2+ items, comparing, or enumerating steps.
- Paragraphs only for a single connected argument.
- No summary section that repeats what was just said.
- Numbers, names, and paths beat adjectives: "3 retries, 200ms backoff", not "a robust retry policy".
- Round to the precision the decision needs: "about 2 to 4 weeks", not "9 to 26.5 days".
  For effort, use T-shirt sizes with a legend (range and a staffing equivalent).

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
| Semicolon chain | "CPU at 90%; backlog growing; errors up 3x" | One item per line or per bullet |
| False precision | "11 to 20.5 person-weeks" | Round, add a human equivalent |
| Inline list after a label | "Dev: update the schema, migrate data, add tests" | Label alone, one sub-bullet per item |
| Compound fact after a label | "**Why:** we miss 7 of 11 practices and meet the other 4 partly" | Label alone, one sub-bullet per fact |

### Structure

- Headings when a doc has 3+ distinct sections. Not before.
- Tables for 3+ items compared on 2+ axes.
- Code blocks for anything a reader will copy.
- Front-load: conclusion, then evidence.
- One item per line, table cells included: a cell with 2+ facts puts each on its own line
  (`<br>` plus "• " in Markdown or Notion tables), never a semicolon chain.
- A lead-in label (bold or plain, e.g. "Why:", "Dev:") followed by 2+ facts or items stands
  alone as the bullet, with one sub-bullet per fact or item.
  - Tasks in sub-bullets start with a verb.
  - A label stays inline only with a single fact: a value, a name or a short phrase
    ("**Confidence:** High").
  - Example: `- **Why:**` then `  - today the services miss 7 of the 11 practices`
    and `  - the other 4 are only partly in place`.
- Vision and decision docs: show the recommended path, mark optional or conditional steps
  and who decides, leave rejected options out unless asked.

## Review mode

Run this pass, in order:

1. **Slop scan**: flag every hit from the banned-patterns table, quoting the span.
2. **Density pass**: mark sentences carrying no new information.
3. **Structure pass**: should a paragraph be bullets, bullets be a table, a bullet be split into
   sub-bullets, or a table cell be split into lines?
4. **Fact check**: flag adjectives that should be numbers or names.
5. **Rewrite**: output the corrected text.

Report findings compactly, then the rewrite:

```
## Findings
- L3 "seamlessly integrates": hollow intensifier, say what it does
- L7-9: restates the heading, delete
- L12: paragraph of 4 parallel items, convert to bullets

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
- [ ] No semicolon chain, in prose or in a table cell
- [ ] No bullet, label line or table cell holds 2+ facts or sentences, even joined by "and"
- [ ] Numbers rounded to the precision the decision needs
