<!-- not runnable -->
# Tribe digest: {{digest.name}}

Structure only: no runtime runs this routine. Each step names what a script or the model does, never a command.

## Purpose

Report the warnings, decisions and checks of the tribe `{{digest.name}}` since the last run, each with its severity, urgency and source links, in one digest.

## Sources

- Issue tracker: the tribe's board filters, with the issues created, moved or blocked in the window.
- Chat channel: the tribe's channels, every message of the window and the replies of its threads.
- Observability tool: the tribe's services, read for the run window and for trend windows of 7 and 30 days.
- Document store: the tribe's pages edited since the last run.

## Steps

1. Load the run state from the `claude/state` branch of the private repository, or start a baseline run.
2. Compute the run window from the last run time, in `{{timezone}}`.
3. Collect each source for the window, one collection per source.
4. Compute the features of each item with a script: its values, its trends and the records it cites.
5. Judge each item against the routine's rules with the model: open or not, severity, urgency and rank. An item reported in chat, an issue or a page cites the record links it comes from.
6. Check the judgment with a script, then apply the item lifecycle: new, escalated, still open, resolved.
7. Save the next state and the run record to `claude/state`.
8. Render the digest with a script, and report it unchanged.

## Outputs

- A digest page in the document store.
- One message to the chat channel `{{chat.digest_channel_id}}`, linking the digest page.
