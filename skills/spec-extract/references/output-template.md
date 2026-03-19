> Reference for: Spec Extract
> Load when: Phase 4 (Output) — writing the rule catalog

# Output Template: Rule Catalog

Copy this template when writing `docs/rules/<concept>.md`. Replace all `<placeholders>`.

---

```markdown
# Extracted Rules: <Concept>

> Extracted from codebase on <YYYY-MM-DD>. Source of truth is the code — this document
> is a point-in-time snapshot for human understanding.

## Summary

<2-3 sentences: what this feature area does, how many rules were found, and which types dominate. Mention any surprising findings.>

**Extraction scope:** <concept | symbol name | directory path>
**Rules found:** <N> (high confidence: <X>, medium: <Y>, low: <Z>)

## Rules

### R-<N>: <Rule Name — plain English, verb phrase>

- **Type:** <Business Rule | Validation | Derived Value | State Transition | Constraint | Fallback>
- **Confidence:** <high | medium | low>
- **Source:** `<path/to/file.ext:line>`
- **Description:** <One sentence: what this rule does in domain language, not code language>
- **Inputs:** <What data this rule examines — entity fields, parameters, config values>
- **Output/Effect:** <What changes — return value, state change, side effect>
- **Dependencies:** <Other rules this depends on: R-X, R-Y. "None" if standalone>
- **Code:**
  ```<language>
  <Relevant snippet — minimal, just the decision logic. Max ~10 lines.>
  ```

## Open Questions

- [ ] <Thing that looks like a rule but intent is unclear — include source location>
- [ ] <Potential bug vs intentional behavior — describe both interpretations>
- [ ] <Missing rule: behavior implied by other rules but not implemented>
- [ ] <Contradiction between R-X and R-Y — which is authoritative?>

## Symbol Cluster

<Paste the table from Phase 2 checkpoint>

| # | Symbol | File | Role |
|---|--------|------|------|
| 1 | ... | ... | ... |

**Cluster size:** <N> functions
**Entry points:** <list>
**Leaf nodes:** <list>
```

---

## Writing Good Rule Names

| Bad | Good | Why |
|-----|------|-----|
| R-1: Discount logic | R-1: VIP customers get 20% discount | Name should be the rule, not the topic |
| R-2: Check eligibility | R-2: Users must have verified email to place orders | State the constraint, not the action |
| R-3: Tax calculation | R-3: Gift orders are tax-exempt | Be specific about what makes this a rule |

Rule names should read like business policy statements. A product manager should understand R-1 through R-N without reading the code.

## Writing Good Descriptions

| Bad | Good |
|-----|------|
| "Checks if the user is eligible" | "Users must have a verified email and at least one completed order to access premium features" |
| "Calculates the discount" | "Discount is 20% for VIP users, or the coupon value if present, with VIP taking priority" |
| "Returns early if invalid" | "Orders with zero items are rejected before processing" |

Descriptions should answer: **what happens, under what conditions, and why it matters to the business?**

## Code Snippet Guidelines

- Include only the decision logic, not the full function
- Trim logging, error handling, and infrastructure around the rule
- If the rule spans multiple functions, show the key branch and note "continues in R-X"
- Add `// ← this line` annotations only when the relevant line isn't obvious
- Max ~10 lines per snippet. If longer, extract the core condition

## Dependencies Between Rules

Document when rules interact:

- **R-3 depends on R-1**: "Tax exemption (R-3) only applies after eligibility check (R-1) passes"
- **R-5 overrides R-4**: "VIP discount (R-5) takes priority over standard coupon (R-4)"
- **R-2 feeds R-6**: "The derived subtotal (R-2) is input to the shipping threshold check (R-6)"

This creates a dependency graph that helps understand execution order and impact of changes.

## Open Questions: What to Flag

Flag anything where you're interpreting rather than reading:

- **Ambiguous intent**: Code does X, but is X the goal or a side effect?
- **Dead branches**: Code path that can never execute given current callers — bug or defensive?
- **Hardcoded values**: Magic number with no constant or comment — what's the policy?
- **Inconsistencies**: Two functions handle the same case differently — which is correct?
- **Missing edge cases**: Rule handles A and B but not C, which seems like it should be handled
- **Assumptions**: Working interpretations you made during extraction — e.g., "Assumed `isActive` means the subscription is not cancelled, based on naming — not confirmed by domain experts"

Assumptions are distinct from unknowns: an assumption is your best interpretation, an open question is something you can't interpret. Both go in this section — prefix assumptions with "Assumed:" to distinguish them.
