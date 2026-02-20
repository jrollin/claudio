> Reference for: Spec Create
> Load when: Writing requirements (Phase 1)

# Requirements Template

## Structure

```markdown
# <Feature Name> — Requirements

## Overview

[Brief description of the feature, the problem it solves, and who benefits from it]

## User Stories

### US-1 <Story Title>

WHEN [actor] [condition/event]
THE [expected behavior]

**Acceptance Criteria:**
- [ ] [Specific, testable criterion]
- [ ] [Another criterion]

### US-2 <Story Title>

WHEN [actor] [condition/event]
THE [expected behavior]

**Acceptance Criteria:**
- [ ] ...

## Non-Functional Requirements

- **Performance**: [Response time, throughput constraints]
- **Security**: [Auth, data protection, input validation]
- **Compatibility**: [Platforms, versions, dependencies]

## Out of Scope

- [Explicitly excluded functionality]
- [Things that look related but are deferred]

## Open Questions

- [ ] [Unresolved decisions that need stakeholder input]
```

## User Story Format

Use `US-X <Title>` with WHEN/THE notation:

```
WHEN [actor] [condition/event]
THE [expected behavior]
```

- **WHEN**: describes the trigger — who does what, under what condition
- **THE**: describes what the system must do in response

Each US must have at least one acceptance criterion that is directly testable.

## Examples

### Example 1: CLI Tool Feature

```markdown
# Dotfile Sync — Requirements

## Overview

A CLI command that synchronizes dotfiles between the local machine and a git repository,
ensuring consistent development environments across machines.

## User Stories

### US-1 Initial sync from repository

WHEN a user runs `dotfiles sync pull` on a new machine
THE SYSTEM SHALL clone the dotfiles repository and create symlinks for all managed files

**Acceptance Criteria:**
- [ ] All files listed in manifest.yml get symlinked to their target paths
- [ ] Existing files at target paths are backed up to `~/.dotfiles-backup/` before overwriting
- [ ] Command exits with error if repository URL is not configured

### US-2 Detecting local changes

WHEN a user runs `dotfiles sync status`
THE SYSTEM SHALL display files that differ between local and repository versions

**Acceptance Criteria:**
- [ ] Modified files shown with diff summary
- [ ] New local files (not in repo) shown as "untracked"
- [ ] Missing files (in repo but not local) shown as "missing"

## Non-Functional Requirements

- **Performance**: Sync status must complete in under 2 seconds for up to 200 managed files
- **Compatibility**: macOS and Linux (Ubuntu 22.04+)

## Out of Scope

- GUI interface
- Automatic conflict resolution (user must resolve manually)

## Open Questions

- [ ] Should we support per-machine overrides (e.g., different .zshrc for work vs personal)?
```

### Example 2: Config/Plugin Feature

```markdown
# Neovim Diagnostic Toggle — Requirements

## Overview

A keybinding to toggle inline diagnostic virtual text on/off in Neovim,
useful for markdown editing where diagnostics clutter the view.

## User Stories

### US-1 Hiding diagnostics in markdown

WHEN a user opens a markdown file
THE SYSTEM SHALL hide diagnostic virtual text by default

**Acceptance Criteria:**
- [ ] Virtual text is hidden on BufEnter for markdown filetypes
- [ ] Other diagnostic features (signs, underlines) remain active
- [ ] Non-markdown files are unaffected

### US-2 Toggling diagnostics manually

WHEN a user presses `<leader>dv` in a markdown buffer
THE SYSTEM SHALL toggle virtual text visibility for that buffer only

**Acceptance Criteria:**
- [ ] Toggle is per-buffer (not global)
- [ ] State persists while buffer is open
- [ ] Works regardless of how many LSP clients are attached

## Non-Functional Requirements

- **Compatibility**: Neovim 0.10+ with LazyVim

## Out of Scope

- Toggling other diagnostic display modes (signs, underlines)
- Per-project diagnostic settings

## Open Questions

- [ ] Should the toggle state persist across buffer re-opens?
```

## Common Mistakes to Avoid

- **Vague language**: "The system should handle errors gracefully" — specify *which* errors and *what* handling
- **Untestable criteria**: "The UI should be user-friendly" — replace with measurable behavior
- **Missing error cases**: Always include what happens when things go wrong (invalid input, network failure, missing files)
- **Actor ambiguity**: "When data is processed" — specify *who* triggers it and *how*
- **Scope creep in AC**: Acceptance criteria should validate the US, not introduce new requirements
