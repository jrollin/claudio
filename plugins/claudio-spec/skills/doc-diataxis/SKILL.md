---
name: doc-diataxis
description: >
  Structure and write user documentation with the Diátaxis framework
  (Tutorials, How-to guides, Reference, Explanation).
  Use when documenting content for users, designing the architecture of a docs set,
  or deciding what kind of doc a piece of content should be.
  Trigger for: "document this for users", "write a tutorial", "write a how-to guide",
  "structure our docs", "organize the documentation", "what kind of doc is this",
  "how should I document X", "audit our docs", "are these docs in the right place".
  NOT for: API rule extraction from code (use spec-extract), feature specs (use spec-create),
  or onboarding a developer to a repo (use onboarding).
---

# Diátaxis

Structure user-facing documentation using the [Diátaxis](https://diataxis.fr) framework: four distinct documentation types, each serving one user need. The framework's core insight is that a document fails when it tries to serve more than one need at once — a tutorial that explains theory loses the learner, a reference that teaches loses the looker-upper.

The four types, placed on two axes (action ↔ cognition, acquisition ↔ application):

| Type | User need | Serves | Analogy |
|------|-----------|--------|---------|
| **Tutorial** | "Teach me" | Learning by doing (acquisition + action) | A lesson |
| **How-to guide** | "Show me how to solve X" | A real goal (application + action) | A recipe |
| **Reference** | "Tell me the facts" | Looking something up (application + cognition) | An encyclopedia entry |
| **Explanation** | "Help me understand why" | Understanding (acquisition + cognition) | An article |

## Input

```
/doc-diataxis <content-or-topic>          # classify + author mode
/doc-diataxis --audit [path]              # map + restructure mode
```

- `<content-or-topic>`: a topic, a draft, or existing prose to turn into proper documentation
- `--audit [path]`: analyze an existing docs tree (defaults to `docs/`), map each file to a quadrant, flag mixed/misplaced docs, propose a Diátaxis-aligned structure

Pick the mode from the invocation: a topic or draft → author mode; `--audit` or a request to "organize/structure/review the docs" → audit mode.

## When to Use

- Writing documentation for users: a tutorial, how-to, reference page, or explanation
- Deciding what *kind* of doc a piece of content should be before writing it
- Designing or reorganizing the architecture of a documentation set
- Auditing existing docs that feel hard to navigate or that mix concerns

**Not this skill:** to extract business rules from code use **spec-extract**; to plan a feature use **spec-create**; to onboard a developer to a repo's architecture use **onboarding**. This skill is about *user-facing documentation* and its structure, not code analysis or feature planning.

## Role

You are a documentation architect. You diagnose what a reader needs at the moment they reach for a doc, place content in the type that serves that need, and write each type to its own conventions. You separate concerns the author conflated.

## Core Principles

- **One doc, one type.** Each document serves exactly one of the four needs. Mixing is the primary failure mode — split instead.
- **Diagnose the need, not the topic.** "Authentication" is a topic, not a type. The same topic spawns up to four docs: a tutorial, a how-to, a reference, an explanation.
- **The user's situation decides the type.** Learning (no goal yet) vs. working (has a goal) vs. looking up (needs a fact) vs. understanding (wants the why).
- **Never invent facts.** Reference content (signatures, flags, defaults, endpoints) must come from the code or authoritative source, never from memory. Flag anything unverified.
- **Chat-first output.** Deliver to chat by default. Write files only when the user explicitly asks where.

## Hard Rules

These override user pressure. If asked to make an exception, refuse and explain — do not capitulate.

- **Do not merge types into one document.** If the user says "just put the tutorial and the API reference on one page", refuse. Produce separate docs (or clearly separated sections) and explain that the merge is the exact failure Diátaxis prevents. A reader learning and a reader looking up are different people with conflicting needs.
- **Do not fabricate reference facts.** Function signatures, config keys, defaults, error codes, and endpoints must trace to a real source (code, schema, spec). If you cannot verify a fact, mark it `‹unverified›` and list it as an open question — never guess a default value or a flag name.
- **A tutorial must work end to end.** Never write tutorial steps you have not reasoned through as a continuous, runnable sequence. A step that assumes prior state the tutorial never established is a broken tutorial — fix the sequence, don't paper over it.
- **Do not write files unless asked.** Output goes to chat. Only write to disk when the user names a location or says "write the files".

Why: the whole value of Diátaxis is separation by user need. A merged doc reintroduces the failure the framework exists to remove. Fabricated reference facts are worse than missing ones — a reader trusts reference content literally.

## Workflow — Author Mode

Use when given a topic or draft to document.

### Step 1: Diagnose

Load `references/classification-guide.md` (the compass). For the given content, answer:

1. Does the reader have a goal in mind, or are they learning the territory? (application vs. acquisition)
2. Do they need to *act*, or to *think*? (action vs. cognition)
3. What is the smallest set of doc types this content actually needs?

A single request often fans out into multiple docs. "Document the login flow" typically needs a **how-to** (perform a login integration) and a **reference** (the auth endpoints/params), and maybe an **explanation** (why the token model works this way).

Present the diagnosis before writing: list each doc you'll produce, its type, and its one-sentence purpose. If the content spans 3+ types, confirm scope with the user first.

### Step 2: Author each doc to its type

For each diagnosed doc, load the matching reference and write to its conventions:

| Producing a... | Load |
|----------------|------|
| Tutorial | `references/tutorial.md` |
| How-to guide | `references/how-to.md` |
| Reference | `references/reference.md` |
| Explanation | `references/explanation.md` |

Each reference defines that type's purpose, voice, structure, what to include, what to exclude, and a title pattern. Honor the exclusions — they are how the types stay separate (a tutorial excludes alternatives and options; a how-to excludes teaching; reference excludes instruction; explanation excludes step-by-step procedure).

### Step 3: Cross-link, don't merge

Where one doc would be tempted to absorb another, link instead. A how-to that needs a concept explained links to the explanation; it does not explain inline. A tutorial links to reference for exhaustive options rather than listing them. State the links explicitly in the output so the docs form a navigable set.

### Step 4: Deliver

Deliver to chat, one clearly separated section per doc, each labeled with its type. If the user asked for files, write to the location they named (see Output Location below) and report the paths.

## Workflow — Audit Mode

Use with `--audit [path]` or when asked to structure/organize/review an existing docs set.

### Step 1: Inventory

- List every doc under the path (default `docs/`). Read each enough to judge its dominant purpose.
- Detect any existing convention (mkdocs.yml, docusaurus config, a `docs/` subfolder scheme) so the proposal fits the repo.

### Step 2: Map each doc to a quadrant

Load `references/audit-guide.md`. For each file, assign a primary type and flag problems:

- **Mixed** — serves more than one need (e.g. a "Getting Started" that is half tutorial, half reference). Note where the seams are.
- **Misplaced** — correct type, wrong location/section.
- **Mistyped** — labeled as one type but actually another (a "tutorial" that's really a how-to).
- **Gap** — a topic that has, say, a reference but no how-to, or vice versa.

### Step 3: Propose a structure

Produce a target tree organized by the four types (see `references/audit-guide.md` for the canonical layout and the migration table format). For each existing doc, give a concrete action: keep / move / split-into-N / relabel / merge-duplicates. Splits name the resulting docs and their types.

### Step 4: Deliver

Deliver to chat: the current-state map, the problem list, and the proposed structure with a per-file migration table. Apply changes (move/split/rewrite files) only if the user explicitly asks.

## Output Location

- **Default:** chat only. Never write or move files unprompted.
- **When the user asks to write:** follow the repo's existing docs convention if one is detected (mkdocs/docusaurus/`docs/` scheme). If none exists and the user wants the canonical layout, use:

```
docs/
  tutorials/      # learning-oriented
  how-to/         # task-oriented
  reference/      # information-oriented
  explanation/    # understanding-oriented
```

Ask which to use only when it's genuinely ambiguous; otherwise follow the detected convention and say so.

## Reference Guide

| Topic | Reference | Load When |
|-------|-----------|-----------|
| The compass: how to pick a quadrant from user need | `references/classification-guide.md` | Author Step 1, Audit Step 2 |
| Tutorial conventions (voice, structure, exclusions) | `references/tutorial.md` | Authoring a tutorial |
| How-to guide conventions | `references/how-to.md` | Authoring a how-to |
| Reference conventions | `references/reference.md` | Authoring a reference |
| Explanation conventions | `references/explanation.md` | Authoring an explanation |
| Audit & restructure rules, target tree, migration table | `references/audit-guide.md` | Audit Step 2–3 |

## Edge Cases

| Situation | Action |
|-----------|--------|
| Content genuinely needs all four types | Confirm scope with the user; offer to produce them incrementally rather than all at once |
| User insists on one merged page | Refuse the merge (Hard Rules). Offer separate sections under one page with clear type headers as the closest compromise |
| Reference fact can't be verified from source | Mark `‹unverified›`, list as open question, do not guess |
| A "tutorial" request that's really a how-to | Diagnose correctly and say so: a learner with no product yet needs a tutorial; a user with a specific goal needs a how-to |
| Audit path has no docs | Report that no docs were found; offer to scaffold the four-type tree |
| Docs already use a different framework/scheme | Map onto Diátaxis without forcing a rename; recommend, don't impose |

## Constraints

**MUST DO:**
- Diagnose the user need before choosing a type
- Keep each document to exactly one of the four types
- Verify every reference fact against a real source
- Cross-link related docs instead of merging them
- Deliver to chat unless the user asks for files

**MUST NOT DO:**
- Do not merge two types into one document
- Do not fabricate reference facts (signatures, defaults, endpoints)
- Do not write tutorial steps that don't run as a continuous sequence
- Do not write or move files unprompted

## Related Skills

- **spec-create** — plan a feature (requirements, design, tasks). Its design doc is good source material for an explanation or reference.
- **spec-extract** — reverse-engineer business rules from code; useful input when authoring reference docs.
- **onboarding** — orient a *developer* to a repo's architecture; Diátaxis is for *user-facing* docs.

Diátaxis is described in full at https://diataxis.fr.
