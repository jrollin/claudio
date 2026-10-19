<!-- not runnable -->
# Chat recap

Structure only: no runtime runs this routine. Each step names what a script or the model does, never a command.

## Purpose

Tell {{owner.name}} what the chat channels hold for them since the last run: asks waiting on them, late answers, team asks, what they wait on, and what got handled.

## Sources

- Chat channel: direct and group messages, mentions of {{owner.name}} and of their groups, threads they took part in, and the announcement channels.
- Document store: the recap's sources page, with the channels, the groups and the exclusions.

## Steps

1. Load the run state from the `claude/state` branch of the private repository, or start a baseline run.
2. Compute the run window from the last run time, in `{{timezone}}`.
3. Collect each family of messages for the window, one collection per family.
4. Merge the messages into units by thread, and compute each unit's features with a script: who asked, who answered, and how long it waits.
5. Judge each unit against the routine's rules with the model: waiting on {{owner.name}}, late, team ask, waiting on someone else, or handled.
6. Check the judgment with a script, then apply the unit lifecycle: new, still open, resolved.
7. Save the next state and the run record to `claude/state`.
8. Render the recap with a script, and report it unchanged.

## Outputs

- One message to the chat channel `{{chat.digest_channel_id}}` when a unit qualifies, and nothing otherwise.
