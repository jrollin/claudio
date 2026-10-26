# Store By Day: Requirements

## Overview

Files the records of every read published to the shared store a second time, by message day, in hive-style `year=/month=/day=` folders, so the owner finds what a provider said on a given day and a routine reuses a past day another routine already read.

- Builds on [provider-store](../provider-store/requirements.md) and only states what changes. The read folders, their replay, reparse and prune, and the `max_age` reuse keep their rules unless a story below changes them.
- Local place only: the day layer lives under `places.<place>.store_dir`. A run without `store_dir` gets no day layer.
- Slack is the first provider. The layout is the one every provider takes when it moves to the read store.
- The first routine that reads a span still fills the store; no separate collector job.

## Problem Statement

**Who** is affected: the owner, who runs several local routines over the same Slack workspace and wants to query what they collected.
**What** problem they face:
- Reads are filed by entity and fetch, not by day: finding "what was said in channel X on Oct 26" means scanning every read whose span overlaps that day and merging duplicates by hand.
- A read is reused only within `max_age` minutes: a routine whose window covers last week fetches it again, although another routine read it completely days ago.
- Pruning reads deletes the only copy of the records: there is no durable history to query later.
**Why** it matters:
- Repeated reads of closed days cost Slack calls, rate-limit headroom and relayed tokens.
- Day-partitioned files let DuckDB, Polars or pyarrow answer date questions without the runtime.
**How** success is measured:
- One DuckDB query over the day layer returns a day's messages for a channel, each message once.
- A routine whose window covers closed days already fully read makes no Slack call for them, as `reads.reused` in its run record shows.

## User Stories

### File published records by message day {#US-1}

WHEN a run publishes a complete read to `store_dir`
THE store merges the read's records into the day folders of the UTC days its records fall on

**Acceptance Criteria:**
- [ ] A `history` record lands at `days/provider=<key>/kind=history/year=YYYY/month=MM/day=DD/channel=<channel>/` *(AC-1.1)*
- [ ] A `thread` record lands under `kind=thread/year=/month=/day=/channel=<channel>/root=<root ts>/`, by the record's own ts: a thread spanning 3 days fills 3 day folders *(AC-1.2)*
- [ ] A `search` hit lands under `kind=search/year=/month=/day=/search=<search name>/`, by the hit's message ts *(AC-1.3)*
- [ ] A `reactions` read lands under `kind=reactions/year=/month=/day=/channel=<channel>/message=<message ts>/`, by the day of the message it reacts to *(AC-1.4)*
- [ ] `members` and `users` reads get no day folder *(AC-1.5)*
- [ ] A `reactions` read with no reaction still writes its message's day folder, holding its snapshot coverage and no record *(AC-1.12)*
- [ ] A message at `1793059199.999999` (2026-10-26T23:59:59Z) lands in `day=26`, one at `1793059200.000000` in `day=27` *(AC-1.6)*
- [ ] A `failed` or `partial` read adds nothing to the day layer *(AC-1.7)*
- [ ] A `history`, `thread` or `search` read covering a day with no record still writes that day's folder, holding its coverage and no record (US-3) *(AC-1.8)*
- [ ] The read folders under `provider=<key>/` and the run folder are unchanged, byte for byte; a run still replays alone *(AC-1.9)*
- [ ] Without `store_dir`, the run writes no day layer and its outputs are unchanged *(AC-1.10)*
- [ ] A DuckDB `read_json(..., hive_partitioning = true)` over one kind returns one row per record with `year`, `month`, `day` and the entity keys as columns, documented in the plugin README *(AC-1.11)*

### Keep each record once, newest fetch winning {#US-2}

WHEN a day folder already holds a record with the same key as an incoming record
THE store keeps the record of the newer fetch

**Acceptance Criteria:**
- [ ] Two overlapping history reads of one channel give each ts once in the day file *(AC-2.1)*
- [ ] An edited message fetched later replaces the earlier text *(AC-2.2)*
- [ ] An incoming record of an older fetch than the stored one is dropped *(AC-2.3)*
- [ ] A reactions read replaces the whole reaction set of its message when newer *(AC-2.4)*
- [ ] A record of the same fetch replaces the stored one, so a reparse fixes the day layer (US-4) *(AC-2.5)*
- [ ] Records in a day file are ordered by ts, then by key, so the same inputs give the same bytes in any publish order *(AC-2.6)*
- [ ] Each day record names its fetch id and fetch time *(AC-2.7)*

### Record what each day folder covers {#US-3}

WHEN a complete read is merged into a day folder
THE store records the part of that day the read covered

**Acceptance Criteria:**
- [ ] A `history`, `thread` or `search` day folder lists its covered spans, clipped to the day, merged when they touch or overlap *(AC-3.1)*
- [ ] A read whose span covers a day with no message still records that coverage, so "read, nothing said" differs from "never read" *(AC-3.2)*
- [ ] Coverage names, per span, the transport of the read that covered it, for the trust rule (BR-6) *(AC-3.3)*
- [ ] A `reactions` day folder records the fetch id, fetch time and transport of its newest read, no span *(AC-3.4)*

### Build the day layer from stored reads {#US-4}

WHEN the owner runs `days.py build --root <store_dir>`
THE store merges every complete read under the root into the day layer

**Acceptance Criteria:**
- [ ] Reads published before this feature are filed by day *(AC-4.1)*
- [ ] Running the command twice writes the same bytes *(AC-4.2)*
- [ ] After a `reparse`, the command replaces the reparsed records in the day layer *(AC-4.3)*
- [ ] `--provider`, `--kind`, `--from` and `--to` restrict the reads merged, with the meaning `reparse` gives them *(AC-4.4)*
- [ ] It prints, per provider and kind, the reads merged and the day folders written *(AC-4.5)*
- [ ] It makes no network call *(AC-4.6)*
- [ ] A root that is not a folder exits 2, naming the path *(AC-4.7)*

### Look up a day {#US-5}

WHEN the owner runs `days.py show --root <store_dir> --date YYYY-MM-DD`
THE store prints the coverage of that UTC day per provider, kind and entity

**Acceptance Criteria:**
- [ ] Each entity shows `full`, `partial` with its uncovered spans, or is absent when never read *(AC-5.1)*
- [ ] `--to YYYY-MM-DD` shows each day of an inclusive range *(AC-5.2)*
- [ ] `--provider`, `--kind` and `--channel` narrow the output *(AC-5.3)*
- [ ] `--records` prints the records instead, one JSON line each, with the path values added back *(AC-5.4)*
- [ ] A malformed date, or `--to` before `--date`, exits 2 naming the flag *(AC-5.5)*
- [ ] A `reactions` entity shows the fetch time of its newest read *(AC-5.7)*
- [ ] Message text is printed as data, never interpreted *(AC-5.6)*

### Reuse closed days in a routine {#US-6}

WHEN a source with closed-day reuse turned on needs a `history` or `thread` span that includes closed days
THE collector takes the covered parts of those days from the day layer and fetches only the gaps, whatever their fetch age

**Acceptance Criteria:**
- [ ] A closed day fully covered is not fetched; `reads.reused` counts it *(AC-6.1)*
- [ ] A closed day partly covered fetches only its gaps, as gap fill does today *(AC-6.2)*
- [ ] The current UTC day, and any span ending after the run start, keeps the `max_age` rule *(AC-6.3)*
- [ ] `reactions` and `search` are never reused this way: reactions keep `max_age`, search keeps BR-9 of provider-store *(AC-6.4)*
- [ ] Off by default: a source without the setting behaves as today *(AC-6.5)*
- [ ] Reused day records are linked into `<run>/store` and listed in the manifest, so the run folder replays alone *(AC-6.6)*
- [ ] For the same messages, the collection is the one a fresh fetch gives, except for edits and deletions after the stored fetch (BR-5) *(AC-6.7)*
- [ ] An invalid value of the setting fails the config load, naming the key path *(AC-6.8)*
- [ ] An `api` source skips a day folder holding any record fetched over `mcp`, and fetches that day (BR-6) *(AC-6.9)*

### Prune the day layer by day {#US-7}

WHEN the owner runs `days.py prune --root <store_dir> --older-than-days N`
THE store deletes the day folders whose day ended more than N days before now

**Acceptance Criteria:**
- [ ] Age is the day the folder names, not the fetch time *(AC-7.1)*
- [ ] `store.py prune` still prunes read folders only, and leaves the day layer untouched *(AC-7.2)*
- [ ] `--dry-run` prints the same counts and deletes nothing *(AC-7.3)*
- [ ] A run folder's linked day records survive the prune, and the run still replays *(AC-7.4)*
- [ ] A non-positive N exits 2 *(AC-7.5)*

### File every other provider's collection by day {#US-8}

WHEN a run with `store_dir` writes the collection of a source whose adapter has no read store (issue tracker, code host, document store, observability)
THE store merges the collection's records into day folders, one per record kind

**Acceptance Criteria:**
- [ ] Issues land at `days/provider=<key>/kind=issues/year=/month=/day=/` by `updated`, keyed by issue key *(AC-8.1)*
- [ ] Pull requests and code-host issues land by `updated_at`, keyed by repository and number *(AC-8.2)*
- [ ] Pages land by `last_edited`, keyed by page id, with their blocks *(AC-8.3)*
- [ ] Monitors land on the day of the window end, keyed by monitor id; transitions by `last_ts_ms`, and metrics on the window end day, both keyed by routine, source and their own key (BR-12) *(AC-8.4)*
- [ ] Each row names its fetch id, fetch time, routine and source; the newest fetch wins per key (BR-3) *(AC-8.5)*
- [ ] A collection with `read` false, a replay, and a chat collection file nothing *(AC-8.6)*
- [ ] A filing failure prints `days: cannot file <source> by day: <reason>` and never fails the source *(AC-8.7)*
- [ ] `show` prints a collection day as `fetches <N> newest <time>`; `prune` and DuckDB treat it like any day folder *(AC-8.8)*

## Business Rules

- A record's day is the UTC calendar day of its message ts; a reactions read takes the day of its message *(BR-1)*
- Day folders are `year=YYYY/month=MM/day=DD`, zero-padded, after `provider=` and `kind=` and before the entity keys, under a `days/` tree apart from the read folders, so a glob over one never reads the other *(BR-2)*
- One record per key in a day folder: `history` by ts, `thread` by root and ts, `search` by search name, channel and ts, `reactions` by message; the newer fetch wins, the same fetch replaces *(BR-3)*
- Only `complete` reads feed the day layer *(BR-4)*
- A closed day is a UTC day that ended before the run start; its reused messages are as fetched, edits and deletions after the fetch are not seen *(BR-5)*
- Trust rule of provider-store: an `api` source reuses day coverage read over `api` only; an `mcp` source reuses both *(BR-6)*
- A source reuses only the day layer of its own provider key *(BR-7)*
- The day layer is durable: pruning reads never removes day records; only `days.py prune` deletes day folders *(BR-8)*
- No reader sees a partly written day file, and a day folder's coverage never claims a span its records do not yet hold *(BR-9)*
- A collection record's day is the UTC day of its own time field, or of the window end for a record that is a state as of the run (monitors, metrics) *(BR-11)*
- A record whose meaning depends on the routine's own window or query (transitions, metrics) is keyed by routine and source too, so two routines never overwrite each other *(BR-12)*
- Collection days carry no coverage spans: a collection covers its source's scope, not the whole provider, so they are never reused by a routine *(BR-13)*
- The day layer holds text written by other people and stays outside every git working tree, or inside one that ignores it, never pushed, as provider-store BR-6 requires *(BR-10)*

## Out of Scope

- Cloud runs and any store shared between machines or places
- Fetch reuse for the other providers: their collections are filed by day (US-8) but never reused; a full read store per provider stays a later spec
- Rebuilding collection days from stored data: collections are filed when collected only, `days.py build` files reads
- `members` and `users` reads: snapshots with no message day
- `partial` reads in the day layer
- Detecting edits or deletions on closed days
- Reusing `reactions` or `search` from the day layer in a routine
- A separate collector job that fills the store on its own schedule
- Compacting day files into Parquet
- A day clock other than UTC

## Open Questions

None open. Settled before requirements:
- Local only, cloud deferred (owner, 2026-10-26)
- Day by message date, not fetch date (owner, 2026-10-26)
- First routine fills the store, add lookup by date; no collector job (owner, 2026-10-26)
- Slack first, same layout for every provider (owner, 2026-10-26)
- `year=/month=/day=` folders (owner, 2026-10-26)
- UTC day clock (owner, 2026-10-26)
- Lookup is both a `days.py` command and closed-day reuse in routines (owner, 2026-10-26)
- Kinds: `history`, `thread`, `reactions`, `search` (owner, 2026-10-26)
- Day layer is a durable archive with its own prune (owner, 2026-10-26)
- Other providers: day layer of collections, no fetch reuse (owner, 2026-10-26)
- `store_dir` may sit inside the private repository when git ignores it; provider-store BR-6 amended (owner, 2026-10-26)
