<!-- not runnable -->
# Weekly status

Structure only: no runtime runs this routine. Each step names what a script or the model does, never a command.

## Purpose

Summarise what {{owner.name}} worked on this week, from Monday to the run time in `{{timezone}}`, as a status ready to share: outcomes, decisions, and what stays open.

## Sources

- Issue tracker: the issues {{owner.name}} created, was assigned, watched, moved or commented on this week.
- Code host: the pull requests {{owner.name}} authored, was assigned or reviewed, and the pull requests that received comments or reviews this week.
- Chat channel: the messages {{owner.name}} sent this week, with their thread context.
- Document store: the pages {{owner.name}} created or edited this week.

## Steps

1. Compute the week window with a script.
2. Collect each source for the window, one collection per source.
3. Group the items by theme or project with a script, and compute each group's features: links, states, and who waits on whom.
4. Summarise the groups with the model: accomplishments, decisions and what stays open, each citing its links.
5. Check that every cited link comes from a collection, with a script.
6. Save the run record to the `claude/state` branch of the private repository.
7. Render the status with a script, and report it unchanged.

## Outputs

- One message to the chat channel `{{chat.digest_channel_id}}`.
