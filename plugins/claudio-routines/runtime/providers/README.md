# Provider adapters

One module per vendor reads one role through `_http.py`. This file lists, per vendor, what a place needs before it reads a source whose transport is `api`.

## Saved connector responses

- A `PostToolUse` hook captures each connector result byte-exact, and `collect.py plan` saves it at the planned call's `path` (see Relay capture in the plugin README).
- For a store-backed adapter (`STORE = True`), the `path` is a page of the read the call belongs to, in the run store (see Read store in the plugin README).
- For any other adapter, the `path` is `<run>/raw/<role>/<source>/<call id>.txt`.
- The model saves a result by hand, unchanged, only for a call the plan prints again: it copies the file to the call's `path` when the harness saved the result to one, else it writes the text there with the Write tool.
- A `relay capture mismatch` line in the error output of `plan` names the paths where the call the model made differs from the printed one, never a value. It is a diagnostic: the model still saves that call's result by hand.
- A harness-saved file holds a JSON list of `{"type": "text", "text": ...}` blocks. `collect.py`, or the page reader of a store-backed adapter, joins those texts before the adapter reads the response, so code-script checksums and digests apply to the result itself. Any other content reaches the adapter unchanged.

## Recorded HTTP calls

- `HttpClient` has a `recorder` attribute, `None` by default. When set, it is called once per `get`, `post` or `get_url` call with the record of that call, after the call ends.
- `collect.py fetch --run <run>` sets it for an adapter that is not store-backed, with `<dir>` the source's raw folder, `<run>/raw/<role>/<source>`. `<dir>` is created when absent and must be empty; a folder that holds any entry is refused with exit 2, naming it.
- A store-backed adapter saves each record as a page of its read, `page-<NNN>.json` in the read's folder, and the read's `read.json` lists the request of each page.
- Each record is written as its call ends, to `<dir>/<source>-<n>.json` as canonical JSON, with `n` from 1 in call order. A fetch that fails midway keeps the records so far.
- A record holds exactly these keys:
  - `method`: `GET` or `POST`.
  - `path`: the path of the requested URL, `base_url` path included.
  - `query`: the query string without `?`, as sent, `""` when none.
  - `body`: the request JSON for a `POST`, `null` for a `GET`.
  - `status`: `200` on a read answer, the HTTP status on an HTTP error, `null` when the call got no answer.
  - `link`: the `Link` response header of a read answer, else `null`.
  - `response`: the decoded JSON of a read answer, else `null`.
  - `error`: `null`, or `{"class", "message", "status"}` of the exception the call raised (`SourceUnreadable`, `PartialRead`, `CredentialsMissing`), `status` being the exception's own status.
- A failed call is recorded, then raises as it does without a recorder. A call retried after a 429 or 5xx answer writes one record, the final outcome.
- A `get_url` link refused for leaving the `base_url` host is a failed call: it is recorded with no status and no request.
- A request header never reaches the recorder, and credentials only travel in request headers, so a record holds no credential value.
- A lone surrogate in a record is written as U+FFFD, as in the collection.
- A record holds the source's content, so the folder is never pushed to `claude/state`.

## Replayed HTTP calls

- `providers/_replay.py` holds `ReplayClient`, an `HttpClient` that serves the records of a source instead of calling the network. `collect.py replay` gives it the records of `<run>/raw/<role>/<source>/`, read in call order.
- A store-backed source replays without it: its replay session serves each read's saved pages and compares each asked request with `read.json` (see Offline replay in the plugin README).
- Call `n` is checked against record `n` on method, path, query and body. Request headers are never compared.
- A request that differs, or a call past the last record, raises `ReplayMismatch`, a rejection with exit 3. The message names the source, the call number, the method and the path, and the differing parts (`method`, `path`, `query`, `body`), never a value.
- A record whose `error` is set raises that error again with its recorded message and status. The class is `SourceUnreadable`, `PartialRead` or `CredentialsMissing`; another class is a `ReplayMismatch`.
- A record with a `link` sets `response_headers` to `{"Link": <link>}` for that call, so an adapter follows the same next links as the run. Any other call leaves `response_headers` at `None`.
- The client reads no environment variable and builds no network opener: a call that reaches the opener fails with `ReplayMismatch`, so a replay needs no credential and no network.
- A link to another host than `base_url`'s is refused as in a run, before any record is used.
- An adapter's `fetch` runs unchanged against it, so a parser change shows in the replayed collection.

## Credentials in the config

- Credentials hold environment variable names, never values: `providers.<name>.api.credentials` maps each credential to a variable name matching `^[A-Z][A-Z0-9_]*$`.
- The loader rejects a key named `password`, `passwd`, `secret`, `token`, `api_key`, `apikey`, `app_key` or `private_key`, or ending in `_` and one of them, that holds anything but a variable name. Names are compared after splitting camelCase and turning dashes into underscores, so `apiKey`, `x-api-key` and `clientSecret` count. A mapping under such a key is checked leaf by leaf. The keys naming a routine, a provider or a source are names, never secret names.
- The loader also rejects a string or a key shaped like a known token or a private key header, anywhere in `config.json` or a routine file. The token shapes are those of the leak guard's `token` rule. The error names the file, the key path and the rule (`secret-key` or `token`), never the value.
- A secret without a known token shape, held under a key with an ordinary name, is not detected.
- A provider read only through its connector sets no `api` block.
- A credential variable that is unset, empty or whitespace-only counts as missing: `check-env`, the transport choice and `HttpClient` all refuse it, and the source is not read with `credentials missing: <variable>`.
- A provider listed as `["api", "mcp"]` in a place with a missing or blank variable is read through its connector instead (see the collectors section of the plugin README).

## Injected credentials

- `places.<place>.injected_hosts` lists the hosts whose credentials the place's proxy adds. A provider whose `api.base_url` host is listed there counts as usable over `api` without its variables, and `check-env` prints `injected <source> <host>`.
- For such a provider `collect.py` builds the client with `_common.injected_client`: no credential variable is read, no adapter auth function runs, and the request carries `Accept: application/json` plus the adapter's `STATIC_HEADERS`.
- `STATIC_HEADERS` is a dict every adapter declares: the non-secret headers its auth function sends next to the credential (`{}` when none). The document store sends its `Notion-Version`; the code host its `Accept` media type and `X-GitHub-Api-Version`.
- The adapter's `_auth` builds its headers from the same `STATIC_HEADERS`, so a local read and an injected read send the same non-credential headers.
- The code host is never injected: a config that lists the host of a code host provider fails the load, naming `places.<place>.injected_hosts`.
- `providers.<name>.api.credentials` may be `{}` for a provider every place injects.

## datadog

- Role: observability.
- Calls: `GET /api/v1/monitor/{id}`, `GET /api/v2/events` and, when the source sets `discovery_query`, `GET /api/v1/monitor/search` for the `monitors` kind, `POST /api/v2/query/scalar` and `POST /api/v2/query/timeseries` for the `metrics` kind.
- Connector: a `monitors` source plans the `aggregate_events` call first (Events below), then one code script; a `metrics` source plans the script alone. The script runs the reads through the connector's `@datadog/datadog-api-client` (`getMonitor`, `searchMonitors`, `queryScalarData`, `queryTimeseriesData`), and `parse` normalizes its payload with the same functions as the `api` transport. The discovery query, the monitor ids and the lookback spans sit inside the script's digested parameters.
- Events: the alert events are aggregated where they are read, over the events inside the window (bounds included). `records.transitions` holds `{monitor, count, first_ts_ms, last_ts_ms}` per numeric monitor id, sorted by id (shorter ids first); the cursor `events_ts_ms` is the newest event time, kept forward-only.
  - `api`: `GET /api/v2/events` in pages of 100 events from the stored cursor when it lies inside the window, up to 100 pages (10,000 events, a 72-hour window at about 75 events an hour); reaching the cap makes the source not read (`partial: page cap`). An event without a numeric monitor id or outside the window is not counted, and an event without a readable time is dropped.
  - `mcp`: the first plan step is one `aggregate_events` call: `query` is the `scope_filter`, `from` and `to` are the window in UTC, the events are grouped by `@monitor_id` (limit 1000) with `COUNT` as `count` and `MIN` and `MAX` of `timestamp` as `first_ts` and `last_ts`. `parse` reads the response: a `<total_buckets>` count and a tab-separated table in `<TSV_DATA>` with the header `@monitor_id`, `count`, `first_ts`, `last_ts` and times in epoch milliseconds. The call covers the whole window, whatever the cursor. A group without a numeric monitor id adds no transition but moves the cursor. More than 1,000 buckets makes the source not read (`partial: group cap`); a table with another header, a malformed or repeated row, or a row count other than `total_buckets` makes it unreadable.
- Discovery: the search runs with `discovery_query`, 100 monitors per page, up to the 20-page cap. Without a query, both transports write no search results and `discovery` read; `discovered` still lists the event monitors below. A search that fails, reaches the cap or returns an unreadable page marks the discovery not read with a reason and leaves the source read; the monitors found before the stop are kept. A found monitor keeps the state text the search returns, whatever it is; only a monitor without a text state makes its page unreadable. Both transports read a search result's `priority` when present; the live search returns no such field, so a discovered priority is null in practice; the features then take it from a leading `[P1]` to `[P5]` in the monitor name, and an API priority always wins.
- Event monitors: after the events read and the search, both transports read by id (`GET /api/v1/monitor/{id}`) every monitor id of `transitions` that is not an entry of the source and not found by the search, 50 at most per run, lowest ids first (shorter ids first), and add them to `discovered`; the cap sits in the script's digested parameters. Only the entries the run reads are excluded: a pack monitor deferred this run (not due, known gap) and a tracked monitor outside the pack are read by id when an event names them, and count toward the 50. The plan embeds the ids of the aggregate's transitions in the script's digested parameters, and the script keeps those the search did not find; `parse` keeps only the reads of the ids its own parsed transitions name and its parsed search leaves out, so a malformed search item does not change the collection.
- Event monitor failures: a monitor answered not found is skipped. Any other failed read (401, 403, 5xx, network error, a response without a state or with another id) never makes the source unreadable: it sets `discovery` to not read with the first failure's reason (a failed search keeps its own reason), which becomes the blind spot part `discovery incomplete`, and the monitors found before and after it are kept. A monitor in an unknown state is kept in `discovered` with the state text the API returns, as for a search result; the features step blind-spots it as `monitor state not recognised`. The excess of the cap sets `discovery.event_monitors_capped` to true, which becomes the blind spot part `event monitors capped at 50`; the field is absent otherwise.
- Not found: a `GET /api/v1/monitor/{id}` answered 404 is a `missing` entry with the reason `not found`, not a failed one.
- Lookbacks: an entry with a span reads over that span. An `hourly` entry is read at a daily interval and becomes a `daily` series; `scalar` and `top` entries aggregate over the span.
- Trends: a `scalar` or `hourly` metric entry that sets `trend_days` (7 to 31, with an aggregator of `max`, `min`, `sum`, `avg` or `last`, and no `lookback_days`) reads its query once more, as an hourly timeseries over the last `trend_days` local days of the config timezone, the window end's day included: from local midnight `trend_days - 1` days before the window end's local date, to the window end. Both transports run the same reads; the connector script runs them one after another, after the entry's window read, and the spans sit inside its digested parameters.
  - Each hourly point lands in its local day. A day's value is the entry's aggregator over that day's hourly values, so `avg` is the mean of the hourly values, and `excluded_hours` does not apply. A day with no point is absent from the list, and a 23-hour or 25-hour day aggregates the hours it has. A 31-day span reads about 750 points per entry.
  - The record holds `trend` (a list of `{day, value}`, `day` as local `YYYY-MM-DD`) and `trend_reason`, null when the read succeeds. A read with no point sets `trend` to null and `trend_reason` to `no datapoints`. An HTTP error on the trend read other than 401 and 403 sets `trend` to null and `trend_reason` to its message, and keeps the window value; a 401 or 403 makes the source not read. An entry whose window read failed reads no trend. The entry's status comes from its window read only.
- Empty reads: a `scalar` or `top` entry whose query succeeds with no datapoint yields a record with a null value, or no group, and the adapter marks no failure. The features step reads such a record as a blind spot, or as 0 when the entry sets `empty` to `zero` (a `top` entry then reads no group). A trend that returns no point, with `trend_reason` `no datapoints`, reads as 0 for `max_7d`, `mean_7d`, `max_span` and `mean_span` and null for `growth_monthly` under the same option. A zero `top` read resolves its tracked groups and a tracked entry key as `group missing` in one run. A response whose value is not a finite number reads as no value, so under `zero` it reads as 0. A failed read, with or without a record, stays a blind spot whatever `empty` says; `hourly` and monitor entries take no `empty`.
- Monitor states: `OK`, `Alert`, `Warn`, `No Data`, `Skipped`, `Unknown` and `Ignored`, under either transport. Any other state fails a by-id entry with `unknown monitor state`; a discovered monitor, found by the search or by an event, keeps it.

### Credentials

The adapter takes either an access token or a key pair, never both: a config naming `token` with `api_key` or `app_key` is refused.

| Credential | Header | Holds |
| --- | --- | --- |
| `token` | `Authorization: Bearer` | a personal or service access token limited to the read-only scopes below; no key is sent with it |
| `api_key` | `DD-API-KEY` | an API key of the organization, with `app_key` |
| `app_key` | `DD-APPLICATION-KEY` | an application key limited to the read-only scopes below, with `api_key` |

`providers.<name>.api.credentials` in `config.json` maps each credential to an environment variable. The variable names are a config choice:

```json
{
  "providers": {
    "observability": {
      "adapter": "datadog",
      "api": {
        "base_url": "https://api.datadoghq.com",
        "credentials": {"token": "OBS_ACCESS_TOKEN"}
      }
    }
  }
}
```

### Read-only scope

Create a scoped application key with these scopes only:

| Scope | Reads |
| --- | --- |
| `monitors_read` | monitors, and the discovery search (`GET /api/v1/monitor/search`) |
| `events_read` | events |
| `timeseries_query` | scalar and timeseries metric queries |

An API key carries no scopes: it names the organization, and the application key bounds what the calls can read.

### Hosts

- The cloud environment allows `api.<site>`, the host of `base_url`, for example `api.datadoghq.com` or `api.datadoghq.eu`.
- Record links are `<base>/monitors/<id>`, under either transport. The base is `links_base` when set, used as is. Otherwise it is the UI host of `base_url`: `base_url` without its leading `api.`, prefixed with `app.` when two labels remain (`app.datadoghq.eu`), as is otherwise (`us3.datadoghq.com`). The collector never calls that host.
- A provider read only through the connector has no `base_url`, so it must set `links_base`; without it, a `monitors` source is not read.

### Where each place reads the variables

| Place | Variables come from |
| --- | --- |
| `local` | the shell that runs `collect.py` |
| `cloud` | the environment's variables, set in the cloud environment settings at claude.ai |

## github

- Role: code host.
- Calls: `GET /repos/{owner}/{repo}/pulls` then `GET /repos/{owner}/{repo}/issues` for each repository listed in the source's `repos`, following the `Link` header's `rel="next"` page.
- Version: every call sends `X-GitHub-Api-Version: 2022-11-28` and `Accept: application/vnd.github+json`, pinned in the module.
- Issues disabled: a repository whose issue list answers HTTP 410 reads as having no issues.
- Query: a source with a non-empty `query` is not read, under either transport: neither the list endpoints nor the connector's list tools take a search query.
- Searches: a source sets `searches`, a list of pull request search queries such as `is:pr org:example-org author:dev`, in place of `repos` (exactly one of the two). It reads over `api` only: a source that sets `searches` with an `mcp` transport for either place fails the config load with the key path, and the connector steps refuse it. Optional `exclude_authors`, a list of logins, drops their activity.
  - Search: `GET /search/issues` for each query, with `q` set to the query followed by `updated:>=<window start date>` (UTC, `YYYY-MM-DD`), `per_page=100`, following the `Link` header's `rel="next"` page up to the page cap, which ends the read partial. Items that are not pull requests are skipped, and a pull request found by several queries is kept once by repository and number. Each becomes a `pull_requests` record, `issues` stays empty.
  - Activity: for each pull request, `GET /repos/{owner}/{repo}/issues/{number}/comments?since=<window start>`, `GET /repos/{owner}/{repo}/pulls/{number}/reviews` and `GET /repos/{owner}/{repo}/pulls/{number}/comments?since=<window start>`, each paged the same way. The collection gains `activity`, one record per comment (`kind` `comment`), submitted review (`review`) or review comment (`review_comment`) whose time is inside the window: `repo`, `number`, `kind`, `author` (login), `at` (comment creation or review submission time, UTC), `state` (the review state as the host returns it, such as `APPROVED`, null for a comment) and `text` (the body, at most 1000 characters, empty when the host sends none).
  - Dropped: activity by a login ending in `[bot]` or listed in `exclude_authors`, and reviews not yet submitted.
  - Cursor: `updated_at` stays null. The window alone bounds the read, so a stored cursor never narrows it.
- Connector: each repository costs at least 2 relay calls (its pull requests, then its issues), and a source stops at 50 relay calls (`call cap`). A source holds at most about 20 repositories over the connector transport: split a larger set into several sources.

### Credentials

| Credential | Header | Holds |
| --- | --- | --- |
| `token` | `Authorization: Bearer` | a fine-grained personal access token limited to the read-only permissions below |

`providers.<name>.api.credentials` in `config.json` maps the credential to an environment variable. The variable name is a config choice:

```json
{
  "providers": {
    "code_host": {
      "adapter": "github",
      "api": {
        "base_url": "https://api.github.com",
        "credentials": {"token": "CODE_TOKEN"}
      }
    }
  }
}
```

### Read-only scope

Create a fine-grained personal access token whose repository access lists only the repositories in `repos` (or those the `searches` reach), with these repository permissions only:

| Permission | Reads |
| --- | --- |
| Pull requests: Read-only | pull requests |
| Issues: Read-only | issues |

The host adds the mandatory Metadata: Read-only permission to every fine-grained token.

### Hosts

- The cloud environment allows `api.github.com`, the host of `base_url`.
- Pull request links are the links the host returns. Issue links are `<base>/<owner>/<name>/issues/<number>`. The base is `links_base` when set, else `base_url` without its leading `api.`, else `https://github.com` for a provider read only through a connector. The collector never calls that host.

### Where each place reads the variables

| Place | Variables come from |
| --- | --- |
| `local` | the shell that runs `collect.py` |
| `cloud` | the environment's variables, set in the cloud environment settings at claude.ai |

## jira

- Role: issue tracker.
- Calls: `POST /rest/api/3/search/jql` with a JSON body (`jql`, `fields`, `maxResults` 100, and `nextPageToken` after the first page), once per page, following `nextPageToken` until `isLast`. A read stops at 20 pages (`partial: page cap`); the updated read and the open sprint read each have their own cap.
- Fields: `summary`, `issuetype`, `status`, `priority`, `created` and `updated`. No assignee or reporter is requested or kept: records hold no person.
- Source: a source sets exactly one of `filter` (a saved filter id) and `jql` (non-blank JQL text); `open_sprints: true` needs `filter`, and config load refuses it with `jql`. With `jql`, the first clause is `(<jql>)` in place of `filter = <filter>`, so the updated read selects `(<jql>) AND (<query>) AND updated >= "<date>" ORDER BY key ASC`, on both transports. The `jql` must not hold an `ORDER BY`.
- Reads: the updated read selects `filter = <filter> AND (<query>) AND updated >= "<date>" ORDER BY key ASC`; with `open_sprints: true`, a second read selects `filter = <filter> AND sprint in openSprints() ORDER BY key ASC` with no time bound and no query, so it returns the whole open sprint whatever the query selects. The `query` narrows the updated read only and is omitted when the source sets none; the adapter appends its own `ORDER BY`, so the query must not hold one.
- Query bound and margin: the exact bound is the stored cursor minus 1 hour, or the routine's first-read start when it is later than that or no cursor is stored. The query date is the exact bound minus 24 hours, in UTC, to the minute, because the tracker reads query dates in its user's time zone and the margin covers any zone. The adapter then keeps only the issues whose update time is at or after the exact bound.
- Merge: results merge by key, the newest update wins, and records sort by key. `in_open_sprint` is true for the keys of the open sprint read; with no open sprint, no issue is flagged and the read is not an error. The cursor is the later of the stored cursor and the newest update time of the updated read, so it only moves forward, and `{"updated": null}` with neither.
- Times: update and creation times with an offset (`2026-10-16T17:38:23.178+0200`) become UTC `YYYY-MM-DDTHH:MM:SSZ`.
- Not found: a search answered with HTTP 403 or 404 (filter not found or forbidden) or HTTP 400 (filter or query rejected) makes the source not read, with a reason naming the filter, or `jql` for a `jql` source; the reason never repeats the JQL text.
- Connector: one call per page to `searchJiraIssuesUsingJql` with the same JQL, fields, page size and token, plus `cloudId` (the provider's `links_base`) and `view: full`, since the default view drops the update time. The model saves each response unchanged; `parse` reads `data.issues`, `data.nextPageToken` and `data.isLast`, and both transports give the same records. A response that is not JSON, has no `data` or no issues list makes the source not read; a response with no `data` and an `error` text names the filter (or `jql`) and the tool, and never repeats the error text, which can echo the query.

### Credentials

| Credential | Header | Holds |
| --- | --- | --- |
| `email` | `Authorization: Basic` (with the token) | the account email of the user who owns the token |
| `token` | `Authorization: Basic` (with the email) | an API token of that user |

`providers.<name>.api.credentials` in `config.json` maps each credential to an environment variable. The variable names are a config choice:

```json
{
  "providers": {
    "tracker": {
      "adapter": "jira",
      "links_base": "https://<site>.atlassian.net",
      "api": {
        "base_url": "https://<site>.atlassian.net",
        "credentials": {"email": "TRACKER_EMAIL", "token": "TRACKER_TOKEN"}
      }
    }
  }
}
```

### Read-only scope

Create the API token for a user who can browse the projects of the filter and can see the saved filter. The adapter only sends issue searches, so the token's reach is that user's browse access.

### Hosts

- The cloud environment allows `<site>.atlassian.net`, the host of `base_url`.
- Record links are `<base>/browse/<KEY>`. The base is `links_base` when set, else `base_url`. The collector never calls that host for links.
- A provider read only through the connector has no `base_url`, so it must set `links_base`, which is also the connector's `cloudId` argument; without it, the source is not read.

### Where each place reads the variables

| Place | Variables come from |
| --- | --- |
| `local` | the shell that runs `collect.py` |
| `cloud` | the environment's variables, set in the cloud environment settings at claude.ai |

## notion

- Role: document store.
- Calls: `GET /v1/pages/{page_id}` for the page, and `GET /v1/blocks/{id}/children` for its blocks, the blocks nested under them and the rows of each table; `POST /v1/search` for a source with `edited_by`; the connector's `notion-search` for a source with `created_by`.
- Request cap: a source makes at most 50 requests over the api transport, counting the page, each page of blocks (nested ones included) and each page of table rows. A source that needs more is not read (`partial: request cap`).
- Nesting: over the `api` transport, the children of a block that has them are read depth first, in page order, up to 4 levels below the page; deeper children are not read, without an error. A text block keeps its record and is followed by its children's, a `toggle` and a `callout` read as `paragraph`, a synced block adds its original's children (a reference reads the block it is synced from), a `column_list` and a `column` add only their children, and `child_page`, `child_database`, `link_to_page` and any other type stay `other` with their children unread. The connector does not read nested blocks.
- Page id: letters, digits and dashes only.
- Source kinds: a source sets exactly one of `page_id` (the sources page, read in full every run), `pages` (a list of page ids, the changed documents; list pages, not databases), `page_from_state`, `edited_by` or `created_by`. The page kinds give `pages` records with a `link`, `<base>/<page id without dashes>`, where the base is `links_base` when set, else `https://www.notion.so`.
- To-do flag: every block an adapter emits carries `checked`: `true` or `false` for a to-do and `null` for any other block. The collection check accepts a block without the key. Over the api transport it is the to-do's `checked` flag (a missing or non-boolean flag reads as `false`); over the connector it is the `- [ ]` marker (`false`) or the `- [x]` / `- [X]` marker (`true`) of a list item, in either `-` or `*` form.
- Pages edited by a user: `edited_by` (a non-blank user id) in place of `page_id` and `pages`, with the optional `edited_cap` (an integer from 1 to 20, default 10) that needs `edited_by`. The `api` transport only: a source with `edited_by` whose transport for a place is `mcp` fails the config load, naming `<source>.edited_by`.
  - Search: `POST /v1/search` with `{"filter": {"property": "object", "value": "page"}, "sort": {"timestamp": "last_edited_time", "direction": "descending"}, "page_size": 100}`, then `start_cursor` while `has_more`. The walk stops at the first page edited before the window start, and a read that still has a next page after 20 search pages is not read (`partial: page cap`). A search request does not count against the 50 page requests.
  - Kept pages: those whose `last_edited_by.id` is `edited_by` and whose edit time lies in the window, in search order (newest first). Each is read like a listed page, with the same records, cursor, entries and request cap.
  - Cap: the search stops at the `edited_cap`-th matching page, so the read keeps the newest pages up to the cap. Each page takes at least 2 requests (the page call and its blocks), so the cap of 20 stays within the 50 page requests.
  - Cursor: `{"pages": {<page id>: <edit time>}}` for the pages found in this run. A routine that keeps no document store cursor reads every page found.
- Pages created by a user: `created_by` (a non-blank user id, `me` for the connected user) in place of `page_id`, `pages` and `edited_by`, with the optional `exclude_paths` (a list of non-blank path prefixes) that needs `created_by`. The connector only: a source with `created_by` whose transport for a place lists `api` fails the config load, naming `<source>.created_by`, and the api read refuses it.
  - Call: one `notion-search` call, id `<source>-1`, with `{"query": "", "filters": {"created_by_user_ids": [<created_by>], "created_date_range": {"start_date": <window start, UTC date>}}, "page_size": 50, "max_highlight_length": 0}`.
  - Kept results: the JSON `results` of type `page` whose `timestamp` lies in the window (the search filters by date, so the parse trims to the exact start) and whose `path`, when it has one, starts with none of `exclude_paths` (for example `Notes / Projects`). A result without a `path` is a top-level page and is kept; any other type is skipped.
  - Records: one `pages` record per kept result, in search order: `id`, `title`, `last_edited` (the result's timestamp as `YYYY-MM-DDTHH:MM:SSZ`), the usual `link` and `blocks: []`. The page body is not read. The cursor is `{"pages": {<page id>: <timestamp>}}`.
  - Cap: a response of 50 results (the page size) may hide more, so the source is not read (`partial: result cap`).
  - Unreadable: a response that is not JSON, has no `results` list, or holds a page result without an `id` or a valid `timestamp` makes the source unreadable, naming the call id.
- Page from the state: a source of a `tribe` routine may set `page_from_state: previous_page` in place of `page_id` and `pages`. `collect.py` hands the adapter the page id of the state's `run.previous_page` as `page_id`, so the source is read like a sources page. A run with no previous page does not call the adapter: the collection is `read: false` with the reason `no previous digest page in the state`, empty records and the stored cursor.
- Page writes: the adapter only reads. The digest page create, its task polls and the weekly heading are connector calls named by the routine's `publish` key, planned by `tribe.py publish-plan` and relayed by the model; the provider named there needs an `mcp` connector for the place.
- Changed pages: records follow the configured page order, and the cursor is `{"pages": {<page id>: <edit time>}}`. A page whose edit time equals its stored one at minute precision is left out of the records, and a page that is unchanged or failed keeps its stored edit time in the cursor. Without a stored cursor every page is read.
  - Over the `api` transport, the page call gives each page's edit time, and only a page whose edit minute differs from its cursor is read in full (blocks, nested blocks and table rows).
  - Over the connector, no call gives an edit time: every listed page is fetched in full, one `notion-fetch` call per page, changed or not, and an unchanged page is dropped after the fetch. The cost grows with the number of pages, and each fetched page passes through the session.
  - Keep a `pages` source to about 10 pages: the 50 requests of the `api` transport cover the page call and the block reads of about 10 pages, fewer when pages nest deeply, and the connector stops at 50 calls (`partial: call cap`).
- Entries: per page id, `ok` when the page is read, `deferred` with the reason `unchanged`, or `failed` with the reason `not found or not shared`, `not a page` or `partial: page truncated`.
  - A page answered not found (HTTP 404, or over the connector a response reporting 404 or `object_not_found` without text) is a failed entry, and the other pages are still read. A shared integration reads a page only when the page is shared with it, so an unshared page reads as not found.
  - A database id in a `pages` source is a failed entry with the reason `not a page`, and the other pages are still read: over the `api` transport the page call answers HTTP 400, and over the connector the fetch reports `metadata.type` `database`. The client does not keep the error body, so every HTTP 400 on the page call counts as `not a page`. The sources page (`page_id`) has no such case: a database id there makes the source not read.
  - Over the `api` transport, a trashed or archived page is a failed entry too, even when its edit minute equals its cursor, and its blocks are not read.
  - Over the connector, a changed page the connector returns truncated (`truncated` true, or `unknown_block_count` above 0) is a failed entry with the reason `partial: page truncated`: it gives no record and keeps its stored edit time, and the other pages are still fetched and read. An unchanged page is dropped before this check. The `api` transport reads blocks directly and has no such case.
  - Any other failure makes the source not read: a permission error (HTTP 401 or 403, `restricted_resource`), an unreadable response or a request cap. The connector plan stops fetching at such a response.
- Version: every call sends `Notion-Version: 2026-03-11`, pinned in the module.

### Credentials

| Credential | Header | Holds |
| --- | --- | --- |
| `token` | `Authorization: Bearer` | the secret of an internal integration limited to the read-only capability below |

`providers.<name>.api.credentials` in `config.json` maps the credential to an environment variable. The variable name is a config choice:

```json
{
  "providers": {
    "document_store": {
      "adapter": "notion",
      "api": {
        "base_url": "https://api.notion.com",
        "credentials": {"token": "DOC_TOKEN"}
      }
    }
  }
}
```

### Read-only capability

Create an internal integration with this content capability only, and no comment or user capability:

| Capability | Reads |
| --- | --- |
| Read content | the sources page and the listed pages, their blocks, nested blocks and table rows |

An integration reads only the pages shared with it: add the integration to the sources page and to each listed page from the page's connections menu. A source with `edited_by` finds only the pages shared with the integration.

### Hosts

- The cloud environment allows `api.notion.com`, the host of `base_url`.

### Where each place reads the variables

| Place | Variables come from |
| --- | --- |
| `local` | the shell that runs `collect.py` |
| `cloud` | the environment's variables, set in the cloud environment settings at claude.ai |

### Connector transport

The connector transport calls the tool `notion-fetch` once per page of the source, with the page id as `{"id": "<page_id>"}`. The sources page (`page_id`) is read whole: a truncated sources page makes the source not read. A listed page the connector returns truncated is a failed entry of its source (see Entries). Both transports reduce inline formatting to plain text. Mentions, inline equations and block colors are not guaranteed equal across the two transports.

## slack

- Role: chat.
- Read store: the adapter is store-backed (`STORE = True`) and files each read in the run store, one folder per read (see Read store in the plugin README).
- Read kinds: `history` (one channel span), `thread` (one thread, whole or after an `oldest`), `search` (one search over its span), `reactions` (one message), `members` (one conversation, `api` only) and `users` (one user lookup, `api` only).
- `parse_read` and `to_rows` rebuild the records of a read from its saved pages, for `store.py reparse`.
- Day layer: `DAY_KINDS` names the kinds filed by day (`history`, `thread` and `search` with span coverage, `reactions` as a snapshot) and `day_row(kind, entity, row)` gives a row's message ts and its key in a day folder (the ts, `channel:ts` for a search hit, the user for a reaction). An adapter without `DAY_KINDS` gets no day layer. With `closed_days`, `history` and `thread` reads also take closed days from it. See Day layer in the plugin README.
- Reuse: with the place's `store_dir` and the source's `max_age` (minutes, default 0), `history` and `thread` reads fetch only the gaps that fresh stored reads leave, a thread from the end of its covered part; `reactions`, `members` and `users` reuse the newest fresh read whole (`max_age.people` covers the last two); `search` reads are never reused. Messages merge by ts, the newest fetch winning, and a reused read spends no call. See Shared store in the plugin README.
- Calls: `GET /api/conversations.history` for each page of each channel listed in the source's `channels`, then `GET /api/conversations.replies` for each page of each thread root of the window. Both reads send `oldest` and `latest` and no `inclusive` parameter, so both bounds are exclusive.
- Connector: `slack_read_channel` once per history page, then `slack_read_thread` once per page of each thread root of the window, both in the `detailed` response format.
- Page sizes: over the connector, a channel read asks for 30 messages a page (`limit` 30) and a thread read, whether of a window root, a cited thread, a search unit or a reread, for 20 replies a page (`limit` 20). The model copies each result into a file, and a result of a few KB passes its safeguard where a 60-reply thread in one page did not. A longer channel or thread takes more pages through the cursor, within the page and call caps: the 20-page cap stops a channel read at 600 messages and a thread read at 400 replies (`partial: page cap`). The `api` transport never goes through the model and keeps its own page size.
- Read start: a channel is read from its stored cursor when that is later than the routine's first-read start (`first_read_from_ts`), else from the first-read start, which is the window start when the routine sets no `first_read_days`. Messages after the read start and up to the window end are kept. Both transports return the same set: the connector's `oldest` and `latest` are exclusive too, so a message at exactly either ts is not returned.
- Join and leave messages are skipped over the api transport; over the connector they are assumed absent from the tool's output.
- Over the connector, a message body that imitates the connector's header format can split a message in two or forge a message under another author. A forged header whose `Message TS` is at or below the call's `oldest` stays body text; one whose `Message TS` lies between `oldest` and the real message's ts starts a forged message. The api transport is not affected: use it for channels where untrusted users post.
- Thread roots: the history read tells which messages have replies. Over the api transport, a root is a message whose `thread_ts` equals its `ts` and whose `reply_count` is above 0. Over the connector, a message body can end with a metadata block: any run of `Reactions: ...`, `Files: ...` and `Thread: N reply` or `Thread: N replies` followed by `(latest: <time>)` lines, in any order. The whole block is removed from the text, so both transports give the same text (the api text never holds these lines), and a message whose block holds the `Thread:` line, with N at least 1, is a root. A message body that ends with a forged block costs at most one extra thread read, and a real text that ends with a `Reactions: ` or `Files: ` line loses that line.
- Thread replies: each root whose ts lies in the window has its replies read up to the window end, following the page cursor. The record's `thread_ts` is the root's own ts for a root with replies, the root's ts for a reply read from its thread, and null for any other message. A reply that also shows in the channel history gives one record, the thread read's copy, which carries its root's ts; a reply seen only in the history carries null under both transports. Records are sorted by channel order, then ts. The author is the user id or bot id, and names and emails in the connector text are dropped. A reply's text loses its trailing metadata block like a history message's.
- Thread starts: a thread read of a root in the channel history or of a cited thread asks only for the replies after the start it needs, with `oldest` on both transports (`slack_read_thread` and `conversations.replies`, no `inclusive`): the channel's read start for a root read from the history, the previous window end for a cited thread. The root is always returned, and the connector counts the replies it returns (`(<N> total)`, `Reply <i> of <N>`). A search unit or a reread thread reads the whole thread, since the recap facts need the owner's earlier messages, unless it is a known thread (see Known threads).
- Thread text: the connector's `slack_read_thread` answers this text. A thread with no reply answers `No thread messsages`, spelled so by the tool; the corrected spelling is accepted too.
- Thread pages: they come newest first. The first page holds the latest replies, ascending within the page, and the cursor (an opaque value) leads to older replies. Each page repeats the whole parent block, and the count of `(<N> total)` and of `Reply <i> of <N>` is that of the replies on the page. More pages end with ``There are more messages in this thread. To view the next page, use cursor: `<cursor>` ``, the last page with `There are no more messages in this thread.`; the thread reader also accepts the channel read's wording.

```text
=== THREAD PARENT MESSAGE ===
From: <name> (<user id>)
Time: <time>
Message TS: <root ts>
<root text>
[Reactions: ...]
[Files: ...]

=== THREAD REPLIES (<N> total) ===

--- Reply <i> of <N> ---
From: <name> (<user id>)
Time: <time>
Message TS: <reply ts>
<reply text>
[Reactions: ...]
[Files: ...]
```

- Replies line: the first `=== THREAD REPLIES (<N> total) ===` line followed by a valid reply, by `No thread messsages`, or by the end of the page opens the replies; a copy of that line inside the root text stays text.
- Reply guards: the parent's `Message TS` must be the requested root, a reply's ts must be later than its root's and than the previous reply of the same page, each ts is new within the thread, and a reply after the window end is dropped. Replies ascend within a page and pages come newest first, so no order is required across pages. A response that fails a guard makes the source not read.
- Forged reply headers: over the connector, a reply text that imitates the reply header (a `--- Reply <i> of <N> ---` line with the same total, then `From:`, `Time:` and `Message TS:` lines) can split a reply in two or forge a reply under another author. A forged header whose `Message TS` is at or below the previous reply of the same page (the root's for the first reply of a page), or is a ts already read on any page, stays body text; one with a later, unused ts starts a forged reply. A forged replies line followed by such a block in the root text forges replies the same way. The api transport is not affected.
- Failed channels: a channel the tool reports as not found, archived or not joined is a failed entry keyed by the channel id, with the reason `channel_not_found`, `is_archived` or `not_in_channel`, and the other channels are still read. Any other failure makes the source not read.
- Cited threads: over a `tribe` routine, `collect.py` adds `threads` (a list of `{channel, root_ts}`) to the source, taken from the state's `threads` for that source. After the history of its channel, each cited thread of that channel whose root is not already read from the window history has its replies after the previous window end (`window.from_ts`) and up to the window end read, one record per reply with the root's ts as `thread_ts`. Over the api transport the call sends `oldest` and `latest`; over the connector the pages come newest first and the read stops at the first page that holds a reply at or before the previous window end. A thread listed twice is read once. A cited thread the tool reports as `thread_not_found` is a failed entry keyed `<channel>:<root ts>` with that reason, and so is a channel error on the thread read (the code is the reason); the other threads are still read. A cited thread of a channel the source does not list, or with a root ts that is not a Slack ts, is a failed entry with the reason `channel not listed` or `invalid root ts`, without a call. A cited thread of a failed channel is not read. Cited replies never move the cursor. Over the connector a `thread_not_found` code in the tool's error field or text (not in a thread page) counts as not found; a thread root read from the window history that is not found still makes the source not read.
- Call budget: a source makes at most 50 calls in all, history pages and thread reads together, under both transports; reaching it makes the source not read (`partial: call cap`). One channel or one thread stops at 20 pages (`partial: page cap`). Each channel costs at least one call and each thread root at least one more, so split a large channel set into several sources.
- Cursor: one ts per channel, the newest history ts read. A channel with no message in the window holds the later of its stored ts and `<window end>.000000`, so a cursor never moves back, and a failed channel keeps its stored ts.
- Searches: a source with `searches` also reads its units (`records.units`), next to the `messages` of its `channels` (`channels` is optional when `searches` is set; a source sets one of them). A search sets `name` (unique), `filters` (the search modifiers, with the owner and group ids written in the private config), `since` (`"window"`, or `{"lookback_days": N}` for the window end minus N days) and optionally `channel_types` (a comma list of `public_channel`, `private_channel`, `mpim`, `im`) and `keywords` (a list of strings). `owner` (the owner's user id) is required when `searches` or `reactions` is set; `reactions` (default false) reads reactions; `search_page_cap` (an integer from 1, default 10) is the page limit of each search; `call_cap` (an integer from 1 to 300, default 50) is the call budget of the whole source.
- Search calls: one call per page, oldest first, 20 results a page, no context messages. The next page comes from the response's cursor. A search that still has a next page after `search_page_cap` pages keeps the units read so far and adds the failed entry `search:<name>` with the reason `page cap: <N> page(s) read`; the source stays read and the cut is a blind spot. Hits outside `(since, window end]` by ts are dropped on both transports.
  - Connector: `slack_search_public_and_private` with `filters`, `channel_types` and `keywords` when set, `after` (Unix seconds as a string), `before` (the window end), `sort: timestamp`, `sort_dir: asc`, `limit: 20`, `include_context: false`, `natural_language_query: ""`, `response_format: detailed` and `cursor`. A page is a JSON object with `results` (text) and `pagination_info`; a last page has no cursor in `pagination_info`. Result headers must be numbered `### Result i of N` in order, `N` must equal the `## Messages (N results)` count, and a result without its `Channel`, `From` or `Message_ts` line makes the source not read. A result text that imitates the next result header can split a result; the api transport is not affected.
  - `api`: `GET /api/search.messages` with `query`, `sort=timestamp`, `sort_dir=asc`, `count=20` and `page`; the last page is `paging.pages`. The query is the filters, the keywords, then `after:<day>` and `before:<day>`, the UTC days of the search start and of the window end minus and plus 2 days: both modifiers are exclusive and read in the user's time zone, so the margin keeps every hit of the window, and the exact ts filter drops the rest. `channel_types` is applied to the hits (`is_im`, `is_mpim`, `is_private`). The search does not tell a root with replies, so a root is read as a thread only when its hit carries a `reply_count` or `thread_ts`.
- Units: each hit goes to one unit candidate. A hit in a direct or group conversation (a channel id starting with `D`, the channel name `group DM` or `mpdm-...`, a search whose `channel_types` are only `im` and `mpim`, or `is_im` and `is_mpim` over the api) adds one conversation read from the window start (`slack_read_channel` / `conversations.history`, with the replies of its thread roots), whether or not the hit is a thread reply. Otherwise a hit with `Reply count:`, or whose permalink or match has a `thread_ts`, adds one thread read by its root (`thread_ts`, else the message ts; `slack_read_thread` / `conversations.replies`), root included. Any other hit is a message of its own unit. A conversation and a thread are read once per run whatever the number of hits, and each hit's own message is kept, the read's copy winning.
- Rereads: over a `recap` routine, `collect.py` adds `rereads` to each chat source with `searches`, one `{kind, channel, root_ts, last_ts}` per stored unit with status `waiting` or `promise` (`root_ts` is null for a `dm-` unit, taken from the key of a `thread-` unit). A `dm-` unit adds a conversation read from just before its `last_ts` (the earlier of that and the window start when a hit reads the same conversation), so its last message is read again; a `thread-` unit adds a thread read by its root. A reread unit is read once whatever the number of hits, shares the call budget and has the same record on both transports; its `participants` stay empty (no hit, no lookup), and a thread's `name` is the channel name of a hit in the same channel, else the channel id. A reread unit without a message is dropped; a failed one is a failed entry as above. A `rereads` key written in the config is ignored.
- Known threads: over a `recap` routine with `thread_reads: since`, `collect.py` adds `known_threads` to each chat source with `searches`, one `{channel, root_ts, last_ts}` per stored `thread-` unit that has the `owner_last_ts` key. A thread read of a root listed there, for a hit or a reread, passes `oldest` = `last_ts` minus the reread margin on both transports (`slack_read_thread` and `conversations.replies`), so the record holds the root and the replies after `oldest`; a response with the parent block and `No thread messsages` keeps the root only. Any other thread is read whole. A `known_threads` key written in the config is ignored.
- Failed entries: a conversation the token cannot read is a failed entry keyed by its channel id (`channel_not_found`, `is_archived`, `not_in_channel`), a missing thread one keyed `<channel>:<root ts>`, a cut search one keyed `search:<name>`, and a reactions read that failed one keyed `reactions:<channel>:<ts>`. The unit of a failed conversation or thread is dropped; the other reads go on. Only a call cap, an unreadable page or a token error makes the source not read.
- Reactions: with `reactions: true`, each unit reads the reactions (`slack_get_reactions` with `channel_id` and `message_ts` / `reactions.get`) of the messages from someone other than the owner after the owner's last message, the newest 3 at most, oldest first. A message of a unit the owner never wrote in counts as after. Only the reacting user ids are read: `owner_reacted` is true when the owner is one of them. A message whose reactions were not read, or whose read failed, has no `owner_reacted` key. The connector's answer is `{"result": "<text>"}` and counts only when the text is `No reactions found on this message.` or starts with `Reactions on message:`; any other text is a failed entry with the reason `unreadable reactions response`. Each line after the header reads `:<emoji>: x <N> <separator> Name (U123), Name (U456)`, and the ids are those in parentheses before a comma or the end of the line after the separator, so a display name holding an id is not counted. Over the api, `message_not_found` is a failed entry; any other error makes the source not read.
- Unit record, the same on both transports: `{"channel": <id>, "name": <"DM", "group DM" or "#name">, "participants": [{"id", "name"}], "messages": [{"user", "name", "bot", "ts", "root_ts", "mentions", "group_mentions", "text", "owner_reacted"?}]}`. `participants` is set for a direct or group conversation only: the connector's `Participants` line, or over the api `conversations.info` (the other user, then the owner) for a direct conversation and `conversations.members` for a group one; it is empty for a thread or a single message. The messages ascend by ts. `bot` is true for an author marked `[BOT]` (in a search result's `From` line or after the id in a read header; over the api, a message with a `bot_id`); the author stays the user id, and the features step decides exclusions. `root_ts` is the thread's root ts, null outside a thread. `mentions` (sorted, deduplicated user ids of every `<@U...>` or `<@U...|name>`) and `group_mentions` (ids of every `<!subteam^S...>` or `<!subteam^S...|label>`) are read from the raw text before it is cleaned and cut, the same on both transports; a bare id in plain text is no mention. `text` is cleaned like the other labels (`<`, `>` and `@` become spaces, so the mention markup is blanked) and cut at 300 characters. Over the connector, names come from the tool's text; over the api, every name comes from `users.info` (one call per user id, cached for the run; `user_not_found` gives an empty name, any other error makes the source not read), except a bot's, which is the message's `username`. No permalink is kept. The cursor of a source with no `channels` stays as stored.
- Call budget: `call_cap` counts search pages, unit reads, participants reads, reactions reads and name lookups together, on both transports; reaching it makes the source not read (`partial: call cap`). A recap routine raises it; the connector transport counts the relayed calls.
- Rate limits: the api transport retries a 429 or 5xx answer once after the `Retry-After` delay (30 seconds at most); a second failure makes the source not read.

### Credentials

| Credential | Header | Holds |
| --- | --- | --- |
| `token` | `Authorization: Bearer` | a bot or user token limited to the read-only scopes below |

`providers.<name>.api.credentials` in `config.json` maps the credential to an environment variable. The variable name is a config choice:

```json
{
  "providers": {
    "chat": {
      "adapter": "slack",
      "api": {
        "base_url": "https://slack.com",
        "credentials": {"token": "CHAT_TOKEN"}
      }
    }
  }
}
```

### Read-only scope

Create an app token with these scopes only:

| Scope | Reads |
| --- | --- |
| `channels:history` | messages and thread replies of public channels |
| `groups:history` | messages and thread replies of private channels |
| `search:read` | the search of `searches` |
| `im:history` | the owner's direct conversations |
| `mpim:history` | the owner's group conversations |
| `reactions:read` | the reactions of `reactions: true` |
| `im:read` | the other user of a direct conversation (`conversations.info`) |
| `mpim:read` | the members of a group conversation (`conversations.members`) |
| `users:read` | the display names of the authors and participants of a unit (`users.info`) |

A bot token reads only the channels the app belongs to: invite the app to each channel listed in `channels`. A source with `searches` over the `api` transport needs a user token with the scopes above: a bot token cannot search or read the owner's direct conversations.

### Hosts

- The cloud environment allows `slack.com`, the host of `base_url`.
- Record links are `<base>/archives/<channel>/p<ts without the dot>`. The base is `links_base` when set, else `base_url`, else `https://slack.com` for a provider read only through a connector. The collector builds these links and never requests them.

### Where each place reads the variables

| Place | Variables come from |
| --- | --- |
| `local` | the shell that runs `collect.py` |
| `cloud` | the environment's variables, set in the cloud environment settings at claude.ai |
