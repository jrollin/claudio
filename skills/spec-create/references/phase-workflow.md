> Reference for: Spec Create
> Load when: Need detailed phase guidance, edge cases, or resume protocol

# Phase Workflow

## Phase Sequence

```
Phase 1: Requirements → [approval] → Phase 2: Design → [approval] → Phase 3: Tasks → [approval] → Phase 4: Summary
```

Phases are strictly sequential. No skipping.

## Approval Criteria

Accepted approval responses: "yes", "approved", "looks good", "lgtm", "go ahead", "proceed", "ok", "ship it"

If the response is ambiguous (e.g., "maybe", "I think so"), ask for explicit confirmation.

## Revision Cycle

```
Write draft → Present to user → Receive feedback → Revise → Re-present → ... → Approved
```

- Never proceed on partial approval ("looks good except for US-3" = not approved)
- On partial feedback, revise only the flagged items, keep approved items stable, and re-present the full document for final approval
- Apply all feedback before re-presenting
- Use `AskUserQuestion` for targeted clarification when feedback is unclear

## Phase Gate Checklists

### Before Phase 2 (Design)

- [ ] requirements.md exists and is complete
- [ ] At least one user story with acceptance criteria
- [ ] All acceptance criteria have `AC-X.Y` IDs
- [ ] Business rules extracted as `BR-X` (if applicable) — domain intent only, no implementation parameters
- [ ] Non-functional requirements have `NFR-X` IDs (or section explicitly marked N/A)
- [ ] Open questions resolved or deferred to "Out of Scope"
- [ ] User has explicitly approved

### Before Phase 3 (Tasks)

- [ ] design.md exists and is complete
- [ ] Architecture overview covers affected components
- [ ] Usage flow diagram (Mermaid flowchart) present
- [ ] Component diagram (Mermaid graph) present
- [ ] At least one technical decision documented with `TD-X` ID and alternatives
- [ ] File Inventory table lists all files to create/modify
- [ ] Design is consistent with approved requirements
- [ ] User has explicitly approved

### Before Phase 4 (Summary)

- [ ] tasks.md exists and is complete
- [ ] All tasks have `T-X` IDs (heading-based entries)
- [ ] All tasks reference `US-X` from requirements in Refs
- [ ] Tasks reference `TD-X` from design where applicable
- [ ] All tasks list files matching design's File Inventory — every inventory file appears in at least one task
- [ ] Each task has a runnable verification command
- [ ] Dependencies between tasks use `T-X` IDs
- [ ] Business rules referenced via `BR-X` where applicable
- [ ] IDs are consistent across all 3 documents (each `T-X` traces to `US-X`, `TD-X`, `BR-X`)
- [ ] User has explicitly approved

## Error Handling

| Situation | Action |
|-----------|--------|
| Requirements are unclear or vague | Ask targeted questions via asking the user directly — don't guess |
| Design is too complex for one feature | Suggest decomposing into smaller features |
| Tasks are too broad | Break into smaller, verifiable units |
| User wants to skip a phase | Refuse — explain phases are sequential and each builds on the previous |
| Template section doesn't apply | Include the section header with "N/A — [brief reason]" |
| Conflicting requirements discovered | Flag the conflict, ask user to resolve before proceeding |

## Resume Protocol

When invoked for a feature that already has partial files:

1. Check `docs/features/<feature-name>/` for existing files
2. Determine which phases *may* be complete based on file existence:
   - `requirements.md` exists → Phase 1 likely done
   - `design.md` exists → Phase 2 likely done
   - `tasks.md` exists → Phase 3 likely done
3. If partial: read existing files to restore context. Validate **structural completeness** (required headings present, IDs assigned, sections non-empty) before treating any phase as done — a file may be incomplete if the session was interrupted mid-write. Quality checks (content adequacy, consistency) are deferred to user review
4. Ask user: "I found existing [files]. Resume from [next phase] or start fresh?"
5. If resuming: read and summarize existing docs, confirm they're still valid, then continue
