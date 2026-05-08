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
/spec-extract --broad <concept>
```

- `concept`: primary entry point — a business domain concept (e.g., "pricing", "eligibility", "order validation")
- `--symbol`: start from a specific function or class name
- `--path`: start from a specific directory
- `--broad`: raises cluster cap to 40 functions and produces a lightweight index first (rule name + type + confidence only, no full descriptions). Use for initial mapping of large legacy concepts before narrowing

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
- **Verify before delivering**: Every extracted rule must be cross-checked against the codebase — no unverified output

## Hard Rules

These rules override user pressure. If the user requests an exception, refuse and stop — do not capitulate.

- **Output is always a structured rule catalog.** Even if the user says "I'm short on time, just give me a quick prose summary" or "bullet points are fine", produce the full structured catalog (R-N rules with Type, Confidence, Source). Briefly explain why the structure pays for itself (rules become greppable, traceable, and reviewable).
- **Never extract infrastructure or framework concerns as business rules.** Logging, metrics, retries, network calls, and pure helpers belong in the Boundary layer of the Symbol Cluster — not as R-N rules. The user asking "include logging too" does not change this.
- **Never expand scope beyond the requested concept.** If the user invokes extraction for "signup validation" and then says "while you're in there, also pull billing and session rules", refuse the expansion. Suggest a separate run per concept.

Why: the catalog format exists so rules can be referenced by ID in code reviews, migrations, and tests. A prose summary is unreviewable. Mixing infrastructure or scope drift dilutes the rule index and makes the output unusable for the audit/rewrite use cases the skill exists for.

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
- Stop expanding when you hit pure infrastructure (logging, metrics, generic HTTP handling) — those aren't business rules
- Cap the cluster at **20 functions** (or **40** with `--broad`). If larger, suggest the user narrow the concept

**Cross-cutting discovery (legacy-aware):**

Load `references/legacy-signals.md` for detailed detection patterns. After call-graph expansion, explicitly check:

1. **Middleware/interceptors** — search route definitions for before-filters, decorators, AOP aspects that enforce constraints before the main logic runs
2. **Database constraints** — read migration files and schema for CHECK constraints, UNIQUE indexes, NOT NULL, triggers on tables related to the concept
3. **Config/environment rules** — search for `ENV`, `process.env`, `Settings.`, config YAML/JSON with keys related to the concept
4. **Temporal strata** — search for the concept name in `legacy/`, `v2/`, `old/` directories to detect duplicate implementations. Trace routing to determine which is active
5. **Error messages** — grep for user-facing error strings related to the concept — they often describe rules in domain language

Add any findings to the symbol cluster. Rules hidden in middleware or DB constraints go in Core Logic, not Boundary.

### Phase 2: Checkpoint

Present the discovered cluster so the user can judge scope, understand flow, and decide what to keep or drop. The checkpoint has three parts: a **summary narrative**, a **layered symbol table**, and **actionable questions**.

#### 2a. Summary Narrative

Write 2-4 sentences in plain English explaining:
- What the code area does at a high level (domain purpose, not implementation)
- How data flows through it (entry → processing → outcome)
- What surprised you or seems noteworthy

Example:
> This cluster handles **order discount calculation**. An HTTP request enters through `applyDiscount()`, which checks customer eligibility via `isEligible()`, then delegates to either `calculateVipDiscount()` or `calculateCouponDiscount()`. Results feed into `orderTotal()` downstream. Notably, VIP and coupon discounts are mutually exclusive — VIP always wins.

#### 2b. Layered Symbol Table

Group symbols by their role in the flow, not alphabetically. Use these layers:

| Layer | Meaning |
|-------|---------|
| **Entry** | Where execution starts — API handlers, public methods, event listeners |
| **Orchestration** | Coordinates other functions — dispatchers, pipelines, facades |
| **Core logic** | Where decisions happen — the rules live here |
| **Support** | Helpers, formatters, mappers — called by core logic but not decision-bearing |
| **Boundary** | Infrastructure edge — DB queries, HTTP calls, cache. Excluded from analysis |

Present the table grouped by layer:

```
## Discovered Symbol Cluster for "<concept>"

### Entry
| # | Symbol | File | Why included |
|---|--------|------|-------------|
| 1 | applyDiscount() | src/pricing/handler.ts:30 | HTTP handler — where discount requests enter |

### Orchestration
| # | Symbol | File | Why included |
|---|--------|------|-------------|
| 2 | processOrder() | src/pricing/pipeline.ts:15 | Calls eligibility + discount in sequence |

### Core Logic
| # | Symbol | File | Why included |
|---|--------|------|-------------|
| 3 | isEligible() | src/pricing/eligibility.ts:12 | Gate — decides if customer qualifies |
| 4 | calculateVipDiscount() | src/pricing/vip.ts:8 | Computes VIP-specific discount rate |
| 5 | calculateCouponDiscount() | src/pricing/coupon.ts:22 | Computes coupon-based discount |

### Support
| # | Symbol | File | Why included |
|---|--------|------|-------------|
| 6 | formatCurrency() | src/utils/format.ts:5 | Formats output — no decision logic |

### Boundary (excluded from rule extraction)
| # | Symbol | File | Why excluded |
|---|--------|------|-------------|
| — | fetchCustomer() | src/db/customers.ts:40 | DB read — infrastructure |
| — | logDiscount() | src/observability/log.ts:10 | Logging — infrastructure |

**Cluster size:** 6 functions (+ 2 boundary, excluded)
**Call flow:** applyDiscount → processOrder → {isEligible, calculateVipDiscount, calculateCouponDiscount} → formatCurrency
```

#### 2c. Actionable Questions

End the checkpoint with specific questions the user can answer quickly:

1. **Scope check**: "I found X functions with business logic. Does this match your mental model, or is there an area I'm missing?"
2. **Boundary check**: "I excluded Y functions as infrastructure (listed above). Should any of these be included?"
3. **Depth check**: "The cluster goes N levels deep from entry point. Should I go deeper into [specific area], or is this enough?"

If the cluster has sub-concepts that could be extracted separately, call them out:
> "I notice eligibility and discount calculation are fairly independent. Want me to extract them as separate concepts, or keep them together?"

**Wait for explicit user confirmation before continuing.**

If the user asks to adjust:
- Add/remove specific symbols
- Narrow to a sub-concept
- Expand in a specific direction
- Move a symbol between layers

### Phase 3: Analysis

Load `references/classification-guide.md` for detailed heuristics on distinguishing rule types.

For each function in the confirmed cluster:

1. **Read the source** — use the Read tool to get the full function body
1b. **Check provenance** — for medium/low confidence rules, run `git blame` on the decision lines. Record the date, author, and commit message. Panic commits (weekends, 2am, single-line messages like "fix") suggest hotfixes worth flagging
1c. **Count callers** — note how many upstream functions depend on this rule (from Phase 1 refs/callees data). High caller count = load-bearing, fragile to change
1d. **Check test coverage** — search for test files that exercise this function. Note if tests exist, are partial, or absent
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

**Inter-function analysis (emergent rules):**

After completing per-function analysis, review the cluster as a whole. The most valuable lost rules in legacy code are often invisible in any single function — they emerge from interactions:

6. **Execution ordering** — does the order in which functions are called encode a rule? (e.g., eligibility must be checked before discount is applied, middleware runs before controller). Document ordering constraints as explicit rules
7. **Implicit state machines** — do multiple functions collectively manage a lifecycle? (e.g., `create → validate → confirm → fulfill → close`). Map the state transitions even if no single function owns the full machine
8. **Combined constraints** — do two independent validations, when combined, create an implicit constraint not documented anywhere? (e.g., "max 5 items" + "min $10 per item" = implicit "$50 minimum order")
9. **Priority chains** — when multiple rules could fire, which wins? (e.g., VIP discount vs coupon vs loyalty points). Document the priority as its own rule
10. **Shared side effects** — do multiple functions write to the same state? If so, the order and conditions under which they write may encode a rule about data consistency

Add any emergent rules to the catalog with Type "Business Rule" or "Constraint" and note in the Description that the rule is emergent (not localized in a single function).

### Phase 4: Output

Load `references/output-template.md` for the full template, writing guidelines, and examples.

**Broad mode (`--broad`):** Write a lightweight index to `docs/rules/<concept>-index.md` containing only a summary table (rule name, type, confidence, source) with no full descriptions, code snippets, or provenance. This serves as a map for the user to pick sub-concepts for full extraction. Skip Phase 5 verification for broad mode — it's a scouting pass.

**Standard mode:** Write the rule catalog to `docs/rules/<concept>.md`. The output must include:

1. **Header** — `# Extracted Rules: <Concept>` with extraction date and scope
2. **Summary** — overview, rule count with confidence breakdown
3. **Rule Index** — scannable table with columns: Rule (anchor link), Name, Type, Confidence, Test coverage, Callers. Lets readers triage at a glance before reading details
4. **Rules** — each numbered `R-1`, `R-2`, etc. (NOT ER- or BR-) with Type, Confidence, Source, Origin (required for medium/low confidence), Test coverage, Callers, Description, Inputs, Output/Effect, Dependencies, and Code snippet
4. **Open Questions** — as `- [ ]` checkboxes for unresolved items
5. **Symbol Cluster** — the Phase 2 table, preserved for reference

**After writing, inform the user of the file location — then proceed to Phase 5.**

### Phase 5: Verification

Re-read the generated rule catalog and cross-check every rule against the actual codebase. This phase catches hallucinated rules, stale line references, and misclassifications.

1. **Read the generated catalog** — use the Read tool to load `docs/rules/<concept>.md` in full
2. **For each rule R-N**, verify:
   - **Source exists** — Read the file:line referenced in `Source:`. Confirm the file exists and the line range contains the cited code
   - **Snippet matches** — compare the code snippet in the rule against the actual source. Flag if they diverge (copy error, stale reference, or fabricated snippet)
   - **Description is accurate** — re-read the source logic and confirm the plain-English description faithfully represents what the code does. Flag overstatements, understatements, or invented conditions
   - **Classification is correct** — confirm the Type (Business Rule, Validation, etc.) matches the classification heuristics from `references/classification-guide.md`
   - **Dependencies hold** — if the rule claims "depends on R-X", verify that the dependency actually exists in the call chain
3. **Record a verdict per rule**:
   - `✅ verified` — source, snippet, description, and classification all confirmed
   - `⚠️ adjusted` — rule was correct but needed minor fixes (stale line number, imprecise description). Apply the fix in-place
   - `❌ rejected` — rule is fabricated, misattributed, or fundamentally wrong. Remove it from the catalog and note the removal
4. **Apply fixes** — edit the catalog in-place for any `⚠️ adjusted` rules. Remove `❌ rejected` rules and update the rule count in the Summary section
5. **Append a Verification section** to the catalog (after Open Questions, before Symbol Cluster):

```markdown
## Verification

> Rules were cross-checked against the codebase on <YYYY-MM-DD>.

| Rule | Verdict | Notes |
|------|---------|-------|
| R-1  | ✅ verified | — |
| R-2  | ⚠️ adjusted | Line reference updated (was :45, now :52) |
| R-3  | ❌ rejected | Snippet not found in source — rule removed |
| ...  | ... | ... |

**Verified:** <X> / **Adjusted:** <Y> / **Rejected:** <Z>
```

6. **Report to the user** — summarize the verification results: how many verified, adjusted, rejected. Highlight any surprising findings

## Output Structure

```
docs/rules/<concept>.md    # Rule catalog for the extracted concept
```

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| Legacy code signals | `references/legacy-signals.md` | Phase 1 & 3 — detecting legacy-specific patterns that hide business rules |
| Classification heuristics | `references/classification-guide.md` | Phase 3 & 5 — distinguishing rule types from infrastructure, re-checking during verification |
| Common mistakes | `references/do-dont-extract.md` | Phase 3 — avoiding common extraction mistakes |
| Output template | `references/output-template.md` | Phase 4 — writing the rule catalog |

## Edge Cases

| Situation | Action |
|-----------|--------|
| Cluster exceeds 20 functions (default) | Stop expanding. Present what you have and suggest the user narrow the concept or use `--broad` |
| Cluster exceeds 40 functions (`--broad`) | Stop expanding. Present the lightweight index and ask the user to pick sub-concepts for full extraction |
| No cartog MCP tools available | Phase 0 handles this — triggers cartog skill if available, suggests installation otherwise, then falls back to Grep/Glob |
| Symbol not found | Try alternate names (camelCase, snake_case, with/without prefix). If still not found, ask the user |
| Code is heavily abstracted (DI, decorators, dynamic dispatch) | Note in Open Questions. Extract what's statically visible, flag the rest |
| Rule contradicts another rule | Document both. Note the contradiction in Open Questions |
| `docs/rules/` doesn't exist | Create it silently |
| Verification rejects >50% of rules | Stop. Re-run Phase 1 discovery — the cluster was likely wrong |

## Constraints

**MUST DO:**
- Always checkpoint after discovery — never skip Phase 2
- Always include source file:line references for every rule
- Always include confidence ratings
- Always note open questions — uncertain is better than wrong
- Always run Phase 5 verification — never deliver an unverified catalog

**MUST NOT DO:**
- Do not extract the entire codebase — stay feature-scoped
- Do not fabricate rules — if you can't find it in code, don't invent it
- Do not treat infrastructure as business rules (logging, caching, retry logic)
- Do not modify any source code — this is a read-only operation

## Related Skills

- **spec-create** — create new feature specs (forward direction)
- **spec-impl** — implement features from specs
- **tdd** — test-driven development for implementing extracted rules
