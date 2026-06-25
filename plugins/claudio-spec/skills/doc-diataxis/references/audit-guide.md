> Reference for: doc-diataxis
> Load when: Audit Step 2–3 (map docs to quadrants, propose a structure)

# Audit & Restructure

Use when analyzing an existing documentation set against Diátaxis and proposing a better structure. Load `classification-guide.md` alongside this — every mapping decision uses the compass.

## Step A: Map each doc to a quadrant

For every doc, determine its **dominant** user need (the compass). Then flag any problem:

| Flag | Meaning | Typical fix |
|------|---------|-------------|
| **OK** | Serves one need, correctly typed and placed | Keep |
| **Mixed** | Serves two+ needs in one doc | Split into N docs, one per type |
| **Mistyped** | Labeled as one type, actually another | Relabel + adjust to the real type's conventions |
| **Misplaced** | Right type, wrong section/location | Move |
| **Duplicate** | Overlaps another doc covering the same need | Merge |
| **Gap** | A topic missing a type its neighbors have | Author the missing doc |

Detecting **Mixed** docs (the highest-value finding): look for a single page that both teaches a beginner *and* lists exhaustive options, or both gives steps *and* argues the rationale at length. Name where the seam is so the split is obvious.

## Step B: Spot the gaps

For each significant topic, check coverage across the four types. A topic with a reference but no how-to leaves working users to reverse-engineer usage; a topic with a tutorial but no reference leaves graduates with nowhere to look things up. List gaps as proposed new docs (don't write them unless asked).

## Step C: Propose a target structure

Default to a four-type tree (adapt to the repo's existing convention if one is detected — mkdocs nav, docusaurus sidebar, an established `docs/` scheme):

```
docs/
  tutorials/      # learning-oriented — lessons for newcomers
  how-to/         # task-oriented — recipes for specific goals
  reference/      # information-oriented — the facts
  explanation/    # understanding-oriented — the why
```

Then give a **migration table**: one row per existing doc, with a concrete action.

```
| Current file | Detected type | Flag | Action | Target |
|--------------|---------------|------|--------|--------|
| docs/getting-started.md | Tutorial + Reference | Mixed | Split into 2 | tutorials/first-app.md + reference/config.md |
| docs/api.md | Reference | OK | Move | reference/api.md |
| docs/why-events.md | Explanation | Mistyped (labeled "guide") | Relabel + move | explanation/event-model.md |
| (none) | — | Gap | Author | how-to/deploy.md |
```

Actions are concrete verbs: **keep / move / split-into-N / relabel / merge / author**. For every split, name the resulting docs and their types.

## Step D: Deliver

To chat, in this order:

1. **Current-state map** — table of every doc → detected type + flag.
2. **Problems** — the mixed/mistyped/duplicate/gap findings, most impactful first.
3. **Proposed structure** — the target tree + the migration table.

Apply changes (moving, splitting, rewriting files) **only if the user explicitly asks**. The audit's default deliverable is the plan, not the execution.

## Audit rules

- Judge by **dominant user need**, not by the doc's current title or folder.
- The single most valuable output is usually catching **Mixed** docs — that's the failure Diátaxis exists to fix.
- Don't force a rename war: if the repo has a working scheme, map onto Diátaxis and recommend, don't impose.
- Never fabricate gaps to fill the grid — only flag a missing type if it has a real audience.
