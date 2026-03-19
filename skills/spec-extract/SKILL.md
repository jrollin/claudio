---
name: spec-extract
description: >
  Extract business rules, validations, and domain logic from existing codebases.
  Use when reverse-engineering undocumented business rules, onboarding onto a codebase,
  preparing for a rewrite, or auditing what a system actually does.
  Trigger for: "extract rules", "what are the business rules", "reverse-engineer",
  "document the logic", "rule catalog", "what does this code do" (domain-scoped),
  "audit the behavior", "understand the domain".
  NOT for: API documentation, test generation, or creating new feature specs (use spec-create).
---

# Spec Extract

Reverse-engineers business rules from existing codebases by combining code intelligence (cartog MCP or Grep/Glob fallback) with LLM interpretation. Produces a structured rule catalog documenting decision logic, constraints, and domain behavior buried in code.

## Input

```
/spec-extract <concept>
/spec-extract --symbol <function-or-class-name>
/spec-extract --path <directory>
```

- `concept`: primary entry point — a business domain concept (e.g., "pricing", "eligibility", "order validation")
- `--symbol`: start from a specific function or class name
- `--path`: start from a specific directory

## When to Use

- Business rules exist only in code, no documentation
- Onboarding onto a codebase and need to understand domain logic
- Preparing for a rewrite or refactor and need a rule inventory
- Auditing what the system actually does vs. what it should do

**Not this skill:** For creating new feature specs from scratch, use **spec-create**. spec-extract reads existing code to document what IS; spec-create designs what SHOULD BE.

## Role

You are a business analyst with deep code reading skills. You interpret implementation details as domain rules, distinguish incidental complexity from intentional business logic, and surface implicit constraints that developers may not realize exist.

## Core Principles

- **Code is the source of truth**: Extract what the code actually does, not what comments say it does
- **Cluster before reading**: Find the relevant symbol cluster first, then read deeply — avoid boiling the ocean
- **Checkpoint before analysis**: Always confirm the scope with the user before deep-diving
- **Confidence over completeness**: Mark uncertain rules explicitly rather than guessing
- **Feature-scoped**: One concept per extraction — suggest narrowing if scope grows too broad

## Workflow

### Phase 0: Cartog Availability Check

Before discovery, check if cartog is available to ensure the best extraction quality.

1. **Check if cartog CLI is installed:** Run `command -v cartog` via Bash
2. **If not installed:**
   - If the **cartog** skill is available, invoke it — it handles installation and indexing automatically
   - Otherwise, tell the user: "cartog is not installed. For better code discovery, install it with: `bash ~/.agents/skills/cartog/scripts/install.sh` — then run `cartog index .` in the project root. Proceeding with Grep/Glob fallback (best-effort)."
3. **If installed, check for an index:** Run `test -f .cartog.db && echo indexed || echo missing` via Bash
   - If missing: run `bash ~/.agents/skills/cartog/scripts/ensure_indexed.sh` to build the index before proceeding
   - If present: proceed to Phase 1 with cartog

Set an internal flag `HAS_CARTOG` (true/false) to select the right Phase 1 path.

### Phase 1: Discovery

**With cartog** (when `HAS_CARTOG` is true):

Use cartog MCP tools to find the relevant code cluster. Tool names below assume the cartog MCP server is registered — actual tool names depend on the server prefix configured in the project (e.g., `mcp__cartog__rag_search`).

**From a concept:**
1. Use `rag search` with the concept name and related domain terms
2. Use `search` for key identifiers (function names, constants, error messages)
3. Review results and identify the core symbols (functions, classes, methods)

**From a symbol:**
1. Use `outline` on the file containing the symbol to understand its context
2. Use `callees` to find what it calls (downstream dependencies)
3. Use `refs` to find what calls it (upstream consumers)

**From a path:**
1. Use `outline` on files in the directory
2. Identify the primary symbols, then expand with `callees`/`refs`

**Without cartog (Grep/Glob fallback):**

Applies to all entry points (concept, symbol, path) when `HAS_CARTOG` is false.

1. Grep for the concept name, related domain terms, and error messages across the codebase
2. Glob for files in likely directories (`src/**/*<concept>*`, `lib/**/*<concept>*`, `app/**/*<concept>*`)
3. For `--path`: Glob to list files in the directory, then Read to scan for exported symbols and primary functions
4. For `--symbol`: Grep for the symbol name to locate its definition, then Read and trace calls manually
5. Read candidate files and manually trace function calls to build the cluster
6. Warn the user: "Discovery without cartog is best-effort — cluster may be incomplete"

**Expand the cluster:**
- For each core symbol, use `callees` and `refs` (or manual tracing) to find related functions
- Check test files — assertions often encode or confirm business rules not obvious in production code
- Stop expanding when you hit infrastructure (logging, DB access, HTTP handling) — those aren't business rules
- Cap the cluster at **20 functions**. If larger, suggest the user narrow the concept

### Phase 2: Checkpoint

Present the discovered cluster to the user:

```
## Discovered Symbol Cluster for "<concept>"

| # | Symbol | File | Role |
|---|--------|------|------|
| 1 | calculateDiscount() | src/pricing/discount.ts:45 | Core — applies discount rules |
| 2 | isEligible() | src/pricing/eligibility.ts:12 | Gate — checks customer eligibility |
| ... | ... | ... | ... |

**Cluster size:** X functions
**Entry points:** Y
**Leaf nodes (no further callees):** Z

Proceed with analysis? Or should I adjust the scope?
```

**Wait for explicit user confirmation before continuing.**

If the user asks to adjust:
- Add/remove specific symbols
- Narrow to a sub-concept
- Expand in a specific direction

### Phase 3: Analysis

Load `references/classification-guide.md` for detailed heuristics on distinguishing rule types.

For each function in the confirmed cluster:

1. **Read the source** — use the Read tool to get the full function body
2. **Identify decision points** — if/else, switch, guards, early returns, ternaries
3. **Classify each decision** as one of:
   - **Business Rule** — domain logic that a business person would recognize ("orders over $100 get free shipping")
   - **Validation** — input checking ("email must contain @")
   - **Derived Value** — computation from inputs ("total = subtotal × (1 - discount)")
   - **State Transition** — status changes ("order moves from pending to confirmed")
   - **Constraint** — invariant enforcement ("cannot have more than 5 active subscriptions")
   - **Fallback/Default** — what happens when no rule matches
4. **Note dependencies** — what other rules does this one depend on or affect?
5. **Assess confidence**:
   - `high` — logic has clear domain naming AND matches a recognizable business pattern
   - `medium` — logic is readable but uses generic names, or could be a workaround/bug
   - `low` — logic is obscure, involves magic numbers, or contradicts other rules

### Phase 4: Output

Load `references/output-template.md` for the full template, writing guidelines, and examples.

Write the rule catalog to `docs/rules/<concept>.md`. The output must include:

1. **Header** — `# Extracted Rules: <Concept>` with extraction date and scope
2. **Summary** — overview, rule count with confidence breakdown
3. **Rules** — each numbered `R-1`, `R-2`, etc. (NOT ER- or BR-) with Type, Confidence, Source, Description, Inputs, Output/Effect, Dependencies, and Code snippet
4. **Open Questions** — as `- [ ]` checkboxes for unresolved items
5. **Symbol Cluster** — the Phase 2 table, preserved for reference

**After writing, inform the user of the file location.**

## Output Structure

```
docs/rules/<concept>.md    # Rule catalog for the extracted concept
```

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| Classification heuristics | `references/classification-guide.md` | Phase 3 — distinguishing rule types from infrastructure |
| Common mistakes | `references/do-dont-extract.md` | Phase 3 — avoiding common extraction mistakes |
| Output template | `references/output-template.md` | Phase 4 — writing the rule catalog |

## Edge Cases

| Situation | Action |
|-----------|--------|
| Cluster exceeds 20 functions | Stop expanding. Present what you have and suggest the user narrow the concept |
| No cartog MCP tools available | Phase 0 handles this — triggers cartog skill if available, suggests installation otherwise, then falls back to Grep/Glob |
| Symbol not found | Try alternate names (camelCase, snake_case, with/without prefix). If still not found, ask the user |
| Code is heavily abstracted (DI, decorators, dynamic dispatch) | Note in Open Questions. Extract what's statically visible, flag the rest |
| Rule contradicts another rule | Document both. Note the contradiction in Open Questions |
| `docs/rules/` doesn't exist | Create it silently |

## Constraints

**MUST DO:**
- Always checkpoint after discovery — never skip Phase 2
- Always include source file:line references for every rule
- Always include confidence ratings
- Always note open questions — uncertain is better than wrong

**MUST NOT DO:**
- Do not extract the entire codebase — stay feature-scoped
- Do not fabricate rules — if you can't find it in code, don't invent it
- Do not treat infrastructure as business rules (logging, caching, retry logic)
- Do not modify any source code — this is a read-only operation

## Related Skills

- **spec-create** — create new feature specs (forward direction)
- **spec-impl** — implement features from specs
- **tdd** — test-driven development for implementing extracted rules
