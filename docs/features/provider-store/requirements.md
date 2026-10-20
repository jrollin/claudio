# Provider Store: Requirements

## Overview

Files every Slack read of a routine run under the entity it covers (a channel span, a thread, a message's reactions, a user), with its raw pages and its parsed records side by side, so a run selects, reparses and replays only the reads an action needs. A local store then shares those reads across runs and routines.

- Phase 1 (US-1 to US-5): the entity layout inside the run folder. No change downstream of the collections.
- Phase 2 (US-6 to US-8): a persistent local store at `places.<place>.store_dir`, shared by every routine of that place, with reuse under a per-source `max_age`.
- Slack is the first provider. Both transports, `api` and `mcp`, are covered.
- This spec builds on [routines-as-code](../routines-as-code/requirements.md) and only states what changes. The collectors (US-13, US-15), the run replay (US-51), the transport choice (US-52), known threads (US-59) and the relay capture hook (US-60) keep their rules unless a story below changes them.

## Problem Statement

**Who** is affected: the owner, who runs several routines that read the same Slack workspace, locally and in the cloud.
**What** problem they face:
- Slack raw results are named by call order (`<source>-<n>`), and one walk parses a whole source in sequence: a parser change is checked only by replaying every source in full.
- Nothing selects the raw data of one channel, time range or thread.
- Each run fetches its Slack data again, even when another routine read the same span minutes before.
- Over the connector, every fetched page passes through the model: the recap example raises its `call_cap` to 200.
**Why** it matters:
- Parser work is slow when each check replays whole sources.
- Repeated reads cost Slack calls, rate-limit headroom and relayed tokens.
**How** success is measured:
- A parser change is checked by reparsing only the reads of the affected kind, with no network.
- For the same raw responses, phase 1 writes byte-identical collections.
- With `max_age` set, a run whose span overlaps a fresh stored read makes fewer Slack calls, as its run record shows.

## User Stories

### Save each Slack read under its entity {#US-1}

WHEN a run reads a Slack source, over `api` or `mcp`
THE collector saves each read in its own folder, named by provider, entity and span, under the run's store root

**Acceptance Criteria:**
- [ ] Without a store folder configured, the store root is `<run>/store` *(AC-1.1)*
- [ ] Each read lands at the path BR-1 gives for its kind *(AC-1.2)*
- [ ] A read folder holds the read's pages in call order and a `read.json` naming the kind, the transport, the tool or endpoint, the arguments, the fetch time and the outcome *(AC-1.3)*
- [ ] The outcome is `complete`, `failed` with the reason, or `partial` with the reason the source gets today (`partial: page cap`, `partial: call cap`) *(AC-1.4)*
- [ ] A connector page is saved byte for byte, by the capture hook or by hand, per US-60 *(AC-1.5)*
- [ ] An `api` page is the HTTP record of the providers README, holding no request header *(AC-1.6)*
- [ ] The relay plan prints, for each call, the file its result goes to, and a hand save writes that file *(AC-1.7)*
- [ ] `plan` still prints the `relay capture mismatch` line for a call it lists again *(AC-1.8)*
- [ ] A folder without `read.json` is ignored by selection, reparse and replay, per BR-3 *(AC-1.9)*
- [ ] Sources of the other roles keep `<run>/raw/<role>/<source>/` *(AC-1.10)*

### Parse each read into records {#US-2}

WHEN a read folder holds all its pages
THE collector parses them into a `records.jsonl` in the same folder, one record per line, before it writes `read.json`

**Acceptance Criteria:**
- [ ] The records hold every field that the chat collection's `messages` and `units` shapes need, so a collection is built from records without reading a page *(AC-2.1)*
- [ ] `read.json` names the runtime commit that parsed the records *(AC-2.2)*
- [ ] Parsing the same pages twice writes the same bytes *(AC-2.3)*
- [ ] A page the parser rejects marks the read `failed` with the reason and writes no records; the collection gets the outcome the source gets today *(AC-2.4)*
- [ ] A channel the token cannot read, or a missing thread, gives a `failed` read keyed as today's failed entry (`channel_not_found`, `is_archived`, `not_in_channel`, `thread_not_found`) *(AC-2.5)*
- [ ] A record holds no value the read's path already holds (BR-1); loading a read adds those values back *(AC-2.6)*

### Build a source's collection from selected reads {#US-3}

WHEN the collector writes a Slack source's collection
THE collection is assembled from the records of the reads whose entity the source names and whose span overlaps the source's span

**Acceptance Criteria:**
- [ ] Selection opens only the folders of the source's channels, threads, searches and users, and within them only the reads whose span overlaps the needed span *(AC-3.1)*
- [ ] For the same raw responses, the collection is byte-identical to the one release 0.5.8 writes, for channel sources, search sources, cited threads, rereads and known threads *(AC-3.2)*
- [ ] The cursor, the failed entries, `read`, the reason and the call counts stay as release 0.5.8 computes them *(AC-3.3)*
- [ ] When two selected reads hold the same message ts, the record of the newer fetch wins, per BR-5 *(AC-3.4)*
- [ ] The run writes `<run>/manifest.json`: per source, the read folders its collection used *(AC-3.5)*

### Reparse only the selected reads {#US-4}

WHEN the owner runs the reparse command with filters on provider, channel, thread root, read kind or time range
THE command rewrites `records.jsonl` and `read.json` of the matching reads only, from their saved pages

**Acceptance Criteria:**
- [ ] Filters combine with AND, and a time range selects the reads whose span overlaps it *(AC-4.1)*
- [ ] The command makes no network call and reads no environment variable *(AC-4.2)*
- [ ] The command prints each read it reparsed and whether its `records.jsonl` bytes changed *(AC-4.3)*
- [ ] With an unchanged parser, no byte changes *(AC-4.4)*
- [ ] A read the parser rejects is named with its folder and reason, the other selected reads are still reparsed, and the command exits 3 *(AC-4.5)*
- [ ] Filters that match no read exit 2, naming the filters *(AC-4.6)*
- [ ] The command takes a store root: a run's `<run>/store`, or a `store_dir` in phase 2 *(AC-4.7)*

### Replay a run read by read {#US-5}

WHEN the owner replays a run folder
THE replay runs each Slack source's walk against the run's own reads, with no network, and rebuilds every collection

**Acceptance Criteria:**
- [ ] With an unchanged parser and walk, every Slack collection is byte-identical to the run's *(AC-5.1)*
- [ ] Each read the walk asks for is served from the read of the manifest with the same kind, entity, span and arguments *(AC-5.2)*
- [ ] A read the walk asks for that the run did not make fails with exit 3, naming its kind, entity and span, never a value *(AC-5.3)*
- [ ] An `api` read replays its own HTTP records in call order; a request that differs fails with exit 3, naming the read folder, the call number, the method and the path *(AC-5.4)*
- [ ] A run folder with no `manifest.json` exits 2, naming the run folder *(AC-5.5)*
- [ ] Sources of the other roles replay as release 0.5.8 replays them *(AC-5.6)*

### Keep Slack reads in a store shared by routines {#US-6}

WHEN `places.<place>.store_dir` is set
THE runs of that place save their Slack reads under `<store_dir>/provider=<key>/` and select from every read there

**Acceptance Criteria:**
- [ ] `store_dir` follows the path rules of `runs_dir`; anything else fails the config check, naming `places.<place>.store_dir` *(AC-6.1)*
- [ ] Without `store_dir`, the store root stays `<run>/store`; the cloud place leaves it unset *(AC-6.2)*
- [ ] A `store_dir` inside a git working tree makes `collect.py sources` exit 2, naming the key, per BR-6 *(AC-6.3)*
- [ ] Folders are created with mode 0700 and files with 0600; a store folder that is a link or belongs to another user is refused *(AC-6.4)*
- [ ] Two runs writing at the same time never expose a partial read, per BR-3 *(AC-6.5)*
- [ ] A run hard-links, or copies when the filesystems differ, every file of the reads in its manifest into `<run>/store`, so its run folder replays alone (US-5) *(AC-6.6)*

### Reuse a fresh read instead of fetching it {#US-7}

WHEN a source sets `max_age` and the store holds complete reads of an entity the source needs, fetched within it
THE collector reuses them and fetches only the parts of the needed span they do not cover

**Acceptance Criteria:**
- [ ] A channel history span is read as the needed span minus the union of the fresh reads' spans: one new read per gap *(AC-7.1)*
- [ ] A thread is read from the end of its latest fresh read; the stored replies are reused *(AC-7.2)*
- [ ] The override keys `max_age.history`, `max_age.thread`, `max_age.reactions` and `max_age.people` fall back to the source's `max_age` *(AC-7.3)*
- [ ] A `max_age` that is not a non-negative integer of minutes fails the config load, naming the key path *(AC-7.4)*
- [ ] With `max_age` unset or 0, every read is fetched and the collection equals phase 1's *(AC-7.5)*
- [ ] A source reuses only reads its trust rule allows, per BR-7 and BR-12 *(AC-7.6)*
- [ ] Failed and partial reads are fetched again, per BR-8 *(AC-7.7)*
- [ ] Searches run on every run, per BR-9; the channel and thread reads their hits lead to may be reused *(AC-7.8)*
- [ ] A read whose records another runtime commit parsed is reparsed from its pages before use, with no network *(AC-7.9)*
- [ ] Reused reads count no call, per BR-13 *(AC-7.10)*
- [ ] The run record gives, per Slack source, the number of reads fetched and the number reused *(AC-7.11)*

### Prune the store on command {#US-8}

WHEN the owner runs the prune command with an age
THE command deletes the reads fetched before that age, and every kept run folder still replays

**Acceptance Criteria:**
- [ ] The age is a required argument in days, per BR-10; a value that is not a positive integer exits 2 *(AC-8.1)*
- [ ] The command deletes whole read folders only *(AC-8.2)*
- [ ] A folder without `read.json` older than the age is deleted too *(AC-8.3)*
- [ ] The command prints, per provider, the number of reads deleted and kept *(AC-8.4)*
- [ ] `--dry-run` prints the same counts and deletes nothing *(AC-8.5)*
- [ ] A run folder's linked or copied reads (AC-6.6) survive the prune, and the run still replays *(AC-8.6)*

## Business Rules

- Slack reads are filed in hive-style `key=value` folders: the provider's config key, then the read kind, then the entity, then one `read=` folder per read carrying its span when it has one and a fetch id *(BR-1)*:
  - channel history: `provider=<key>/kind=history/channel=<channel>/read=<from>_<to>-<fetch id>/`
  - thread: `provider=<key>/kind=thread/channel=<channel>/root=<root ts>/read=<from>_<to>-<fetch id>/`
  - reactions: `provider=<key>/kind=reactions/channel=<channel>/message=<message ts>/read=<fetch id>/`
  - conversation members: `provider=<key>/kind=members/channel=<channel>/read=<fetch id>/`
  - user lookup: `provider=<key>/kind=users/user=<user id>/read=<fetch id>/`
  - search: `provider=<key>/kind=search/search=<search name>/read=<from>_<to>-<fetch id>/`
- The reparse and replay unit is one read, with all its pages: a page is never parsed alone *(BR-2)*
- A read becomes visible when its `read.json` exists, and its pages and `records.jsonl` are written before it *(BR-3)*
- Phase 1 changes no byte of any collection, feature, state, run record, digest or message, for the same raw responses *(BR-4)*
- When two reads hold the same message ts, the record of the newer fetch wins *(BR-5)*
- The store holds text written by other people: it lives outside every git working tree and is never pushed, as routines-as-code BR-70 requires of raw results *(BR-6)*
- An `api` source reuses only reads made over `api`; an `mcp` source reuses reads of either transport *(BR-7)*
- Only complete reads are reused *(BR-8)*
- Search pages are never reused *(BR-9)*
- Nothing deletes a read except the prune command, and the command takes an explicit age *(BR-10)*
- A read is fresh when it was fetched at most `max_age` minutes before the run start *(BR-11)*
- A source reuses only the reads of its own provider key *(BR-12)*
- A reused read counts against no cap: `call_cap`, `search_page_cap` and the page caps count the calls the run makes *(BR-13)*

## Out of Scope

- The other providers (issue tracker, code host, document store, observability): they keep `<run>/raw/<role>/<source>/`, and a later spec moves them to the same layout
- A persistent store for cloud runs: the cloud container's disk ends with the run
- Sharing a store between machines or places
- Reusing search pages (BR-9)
- Automatic pruning or a default retention (BR-10)
- Merged per-day or per-thread files: selection reads the read folders directly
- A `day=` partition: a read spans days, and splitting it would break BR-2; records split by message day inside a read can come later without changing the read layout
- Replaying a run folder written before this change with the new runtime: replay it with the runtime tag that wrote it
- Encrypting the store at rest

## Open Questions

None open. Settled before design:
- Store lifetime: per run (phase 1) and a persistent local store (phase 2) (owner, 2026-10-20).
- Transports: `api` and `mcp` both (owner, 2026-10-20).
- Freshness: set per source and per data kind by its reader, `max_age` 0 by default (owner, 2026-10-20).
- Span reuse: gap fill, fetching only what fresh reads do not cover (owner, 2026-10-20).
- Searches: never reused (owner, 2026-10-20).
- Retention: by command only, no automatic pruning (owner, 2026-10-20).
- Layout: hive-style `key=value` folders, kind first, records as JSON lines (owner, 2026-10-20).
