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
- Apply all feedback before re-presenting
- Use `AskUserQuestion` for targeted clarification when feedback is unclear

## Phase Gate Checklists

### Before Phase 2 (Design)

- [ ] requirements.md exists and is complete
- [ ] At least one user story with acceptance criteria
- [ ] Non-functional requirements addressed (or explicitly marked N/A)
- [ ] Open questions resolved or deferred to "Out of Scope"
- [ ] User has explicitly approved

### Before Phase 3 (Tasks)

- [ ] design.md exists and is complete
- [ ] Architecture overview covers affected components
- [ ] At least one technical decision documented with alternatives
- [ ] Design is consistent with approved requirements
- [ ] User has explicitly approved

### Before Phase 4 (Summary)

- [ ] tasks.md exists and is complete
- [ ] All tasks reference user stories from requirements
- [ ] Each task has a verification method
- [ ] Dependencies between tasks are noted
- [ ] User has explicitly approved

## Error Handling

| Situation | Action |
|-----------|--------|
| Requirements are unclear or vague | Ask targeted questions via `AskUserQuestion` — don't guess |
| Design is too complex for one feature | Suggest decomposing into smaller features |
| Tasks are too broad | Break into smaller, verifiable units |
| User wants to skip a phase | Refuse — explain phases are sequential and each builds on the previous |
| Template section doesn't apply | Include the section header with "N/A — [brief reason]" |
| Conflicting requirements discovered | Flag the conflict, ask user to resolve before proceeding |

## Resume Protocol

When invoked for a feature that already has partial files:

1. Check `docs/features/<feature-name>/` for existing files
2. Determine which phases are complete:
   - `requirements.md` exists → Phase 1 done
   - `design.md` exists → Phase 2 done
   - `tasks.md` exists → Phase 3 done
3. If partial: read existing files to restore context
4. Ask user: "I found existing [files]. Resume from [next phase] or start fresh?"
5. If resuming: read and summarize existing docs, confirm they're still valid, then continue
