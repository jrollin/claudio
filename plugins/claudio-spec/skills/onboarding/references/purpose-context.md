# Purpose / Context

The opening section. Before any diagram or code, answer the two questions a new dev actually has: **what is this thing, and why does it exist?** Derived from the code and docs, not guessed.

## Method

1. Read `README`, `AGENTS.md`, `CLAUDE.md`, `docs/`, ADRs, and any `wiki/` for stated intent — treat as claims to verify.
2. Confirm against code: the entry points (`main.*`, `handlers.*`, route/CLI definitions), the primary data it reads/writes, and what it exposes. What the code *does* wins over what a stale README *says*; flag drift.
3. Infer the **why** from the shape: a service that mirrors another system's data and computes over it exists to offload/precompute; a gateway exists to front and route; a library exists to be consumed. Say what problem it solves for whom.

## Required Output

Keep it short — a few tight paragraphs or bullets, no diagrams here (diagrams start in Big Picture).

### What it is
One or two sentences: the kind of thing (service / library / CLI / app), and what it does in plain language. Cite the entry point or manifest.

### Why it exists (the problem it solves)
The purpose in the reader's terms — what would be missing or harder without it, who benefits, where it sits relative to the rest of the system. Cite the evidence (a doc that states it, or the code shape that implies it). If the repo states a purpose you cannot confirm from code, report what the code does and note the discrepancy.

### Who uses it
The consumers/actors: end users, other internal services, scheduled jobs, external systems. One line each. This sets up the C4 L1 actors in the next section.

### Scope boundary (what it is *not*)
If the code makes the boundary clear — a disposable migration path tagged "do not carry forward", an explicitly out-of-scope concern, a responsibility that lives in another repo — state it. This is high-value onboarding signal and prevents a new dev from misreading scaffolding as core.

## Rules

- Ground every claim in a file (doc line or code entry point). No invented purpose.
- Plain language over jargon. This is the one section a non-specialist should also understand.
- Write it as a few short paragraphs, one per question (what / why / who / scope), with a blank line between them. This is the most narrative section; let it read like prose, not a bullet dump.
- **No em-dash in the output.** Never emit the `—` character. Use a newline, comma, colon, parentheses, or period instead.
- Describe, don't recommend. No "this should also do X".
- Where docs and code disagree on purpose, report the code and flag the drift.
- No diagrams here. They begin in the Big Picture section.
